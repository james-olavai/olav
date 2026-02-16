"""Knowledge Base Gateway - Vector Search with DuckDB

Single-writer, multi-reader architecture for knowledge base management.
Handles embedding storage, vector indexing, and semantic search.
"""

import json
import logging
import threading
from pathlib import Path
from typing import Any

import duckdb

from config.paths import UNIFIED_DB
from config.settings import settings

logger = logging.getLogger(__name__)


class KnowledgeGateway:
    """Thread-safe knowledge base gateway with connection pooling.
    
    Architecture:
    - Single DuckDB file (main.duckdb) for unified storage
    - Connection pool per thread (read-only for non-writers)
    - HNSW vector indexing for similarity search
    - Batch writes to minimize locking
    """

    def __init__(self, db_path: str | Path | None = None, read_only: bool = False):
        """Initialize knowledge gateway.
        
        Args:
            db_path: Path to DuckDB database file (default: UNIFIED_DB)
            read_only: Whether to open in read-only mode
        """
        if db_path is None:
            db_path = UNIFIED_DB

        self.db_path = Path(db_path)
        self.read_only = read_only
        
        # Thread-local connection pool (SWMR pattern)
        self._local = threading.local()
    
    def _get_connection(self) -> duckdb.DuckDBPyConnection:
        """Get or create thread-local connection.
        
        DuckDB Single-Writer Multi-Reader (SWMR) pattern:
        - Read-only connections never block writers
        - Write connection must be exclusive
        """
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            try:
                self._local.conn = duckdb.connect(
                    str(self.db_path),
                    read_only=self.read_only
                )
                # Enable HNSW support (if available)
                try:
                    self._local.conn.execute("SELECT 1;")  # Test connection
                except Exception as e:
                    logger.warning(f"Connection test failed: {e}")
            except Exception as e:
                logger.error(f"Failed to create connection: {e}")
                raise
        
        return self._local.conn
    
    def init_schema(self) -> None:
        """Create knowledge_chunks table with vector index.
        
        Schema:
        - id: Unique identifier
        - content: Plain text (source for embeddings)
        - embedding: Variable-dimensional float vector (512 for local, 1536 for OpenAI)
        - source_file: Markdown/PDF filename
        - file_path: Full file path in .olav/knowledge/
        - metadata: JSON with chunk_id, page, section, etc.
        - created_at: Timestamp
        - updated_at: Last modification time
        """
        if self.read_only:
            logger.warning("Cannot initialize schema in read-only mode")
            return
        
        conn = self._get_connection()
        
        # Create table if not exists
        conn.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_chunks (
                id VARCHAR PRIMARY KEY,
                content TEXT NOT NULL,
                embedding FLOAT[],
                source_file VARCHAR,
                file_path VARCHAR,
                metadata JSON,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create indexes for efficient querying
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_knowledge_source 
            ON knowledge_chunks(source_file)
        """)
        
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_knowledge_created 
            ON knowledge_chunks(created_at)
        """)
        
        # Create indexed_files table for tracking file changes (incremental updates)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS indexed_files (
                file_path VARCHAR PRIMARY KEY,
                file_name VARCHAR NOT NULL,
                file_hash VARCHAR NOT NULL,
                file_mtime TIMESTAMP NOT NULL,
                chunk_count INTEGER DEFAULT 0,
                embedding_mode VARCHAR,
                embedding_model VARCHAR,
                embedding_dim INTEGER,
                status VARCHAR DEFAULT 'indexed',
                indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_indexed_files_hash 
            ON indexed_files(file_hash)
        """)
        
        # Note: DuckDB vector similarity is computed at query time
        # using distance operator (<=>) which finds nearest neighbors
        # by computing distances between query vector and stored vectors.
        # Native HNSW indexing may be available in newer DuckDB versions.
        # For now, vector search relies on DuckDB's efficient <=> operator.
        logger.info("Vector search will use DuckDB's <=> operator (brute force + quick <=> calculation)")
        
        logger.info(f"Knowledge schema initialized at {self.db_path}")
    
    def insert_chunk(
        self,
        chunk_id: str,
        content: str,
        embedding: list[float],
        source_file: str,
        file_path: str,
        metadata: dict[str, Any] | None = None
    ) -> bool:
        """Insert a single knowledge chunk.
        
        Args:
            chunk_id: Unique identifier (e.g., "pdf_page_001_para_02")
            content: Chunk text
            embedding: 1536-dimensional embedding vector
            source_file: Source filename (e.g., "CCNP TSHOOT.pdf")
            file_path: Full file path
            metadata: Optional JSON metadata (page, section, etc.)
        
        Returns:
            True if inserted successfully
        """
        if self.read_only:
            logger.error("Cannot insert in read-only mode")
            return False
        
        try:
            conn = self._get_connection()
            
            # DuckDB auto-converts Python list[float] to FLOAT[] array
            metadata_str = json.dumps(metadata) if metadata else None
            
            conn.execute("""
                INSERT INTO knowledge_chunks
                (id, content, embedding, source_file, file_path, metadata, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT (id) DO UPDATE SET
                    content = excluded.content,
                    embedding = excluded.embedding,
                    source_file = excluded.source_file,
                    file_path = excluded.file_path,
                    metadata = excluded.metadata,
                    updated_at = excluded.updated_at
            """, [chunk_id, content, embedding, source_file, file_path, metadata_str])
            
            return True
        except Exception as e:
            logger.error(f"Failed to insert chunk {chunk_id}: {e}")
            return False
    
    def insert_batch(
        self,
        chunks: list[dict[str, Any]],
        batch_size: int | None = None
    ) -> int:
        """Insert multiple chunks in batches.
        
        Args:
            chunks: List of chunk dicts with keys:
                - chunk_id, content, embedding, source_file, file_path, metadata
            batch_size: Rows per transaction (default from settings)
        
        Returns:
            Number of successfully inserted chunks
        """
        if batch_size is None:
            batch_size = settings.knowledge.batch_size  # Use config default
        
        if self.read_only:
            logger.error("Cannot insert in read-only mode")
            return 0
        
        conn = self._get_connection()
        inserted = 0
        
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            try:
                for chunk in batch:
                    # DuckDB auto-converts Python list[float] to FLOAT[] array
                    metadata_str = json.dumps(chunk.get('metadata')) if chunk.get('metadata') else None
                    
                    conn.execute("""
                        INSERT INTO knowledge_chunks
                        (id, content, embedding, source_file, file_path, metadata, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                        ON CONFLICT (id) DO UPDATE SET
                            content = excluded.content,
                            embedding = excluded.embedding,
                            source_file = excluded.source_file,
                            file_path = excluded.file_path,
                            metadata = excluded.metadata,
                            updated_at = excluded.updated_at
                    """, [
                        chunk['chunk_id'],
                        chunk['content'],
                        chunk.get('embedding'),
                        chunk.get('source_file', ''),
                        chunk.get('file_path', ''),
                        metadata_str
                    ])
                
                inserted += len(batch)
                logger.info(f"Inserted batch {i//batch_size + 1}: {len(batch)} chunks")
            except Exception as e:
                logger.error(f"Batch insert failed at index {i}: {e}")
                continue
        
        return inserted
    
    def vector_search(
        self,
        query_embedding: list[float],
        limit: int | None = None,
        threshold: float | None = None
    ) -> list[dict[str, Any]]:
        """Search knowledge base by vector similarity.
        
        Args:
            query_embedding: Variable-dimensional embedding
            limit: Max results to return (default from settings)
            threshold: Minimum similarity score (default from settings)
        
        Returns:
            List of relevant chunks with similarity scores
        """
        # Use config defaults if not provided
        if limit is None:
            limit = settings.knowledge.max_results
        if threshold is None:
            threshold = settings.knowledge.similarity_threshold
        try:
            conn = self._get_connection()
            
            # DuckDB vector search using parameterized query
            # 使用参数化查询而非 f-string，避免 SQL 注入
            results = conn.execute("""
                SELECT
                    id,
                    content,
                    source_file,
                    file_path,
                    metadata,
                    list_cosine_similarity(embedding, ?) as similarity
                FROM knowledge_chunks
                WHERE embedding IS NOT NULL
                ORDER BY similarity DESC
                LIMIT ?
            """, [query_embedding, limit]).fetchall()
            
            # Convert to list of dicts
            output = []
            for row in results:
                similarity = row[5]
                if similarity >= threshold:
                    output.append({
                        'id': row[0],
                        'content': row[1],
                        'source_file': row[2],
                        'file_path': row[3],
                        'metadata': json.loads(row[4]) if row[4] else {},
                        'similarity': similarity
                    })
            
            return output
        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            return []
    
    def delete_source(self, source_file: str) -> int:
        """Delete all chunks from a source file.
        
        Args:
            source_file: Source filename to delete
        
        Returns:
            Number of deleted chunks
        """
        if self.read_only:
            logger.error("Cannot delete in read-only mode")
            return 0
        
        try:
            conn = self._get_connection()
            
            result = conn.execute(
                "DELETE FROM knowledge_chunks WHERE source_file = ?",
                [source_file]
            )
            
            deleted = result.rowcount
            logger.info(f"Deleted {deleted} chunks from {source_file}")
            return deleted
        except Exception as e:
            logger.error(f"Delete failed for {source_file}: {e}")
            return 0
    
    def get_statistics(self) -> dict[str, Any]:
        """Get knowledge base statistics.
        
        Returns:
            Dict with chunk count, sources, etc.
        """
        try:
            conn = self._get_connection()
            
            total_chunks = conn.execute(
                "SELECT COUNT(*) FROM knowledge_chunks"
            ).fetchone()[0]
            
            sources = conn.execute("""
                SELECT source_file, COUNT(*) as count
                FROM knowledge_chunks
                GROUP BY source_file
                ORDER BY count DESC
            """).fetchall()
            
            indexed_chunks = conn.execute(
                "SELECT COUNT(*) FROM knowledge_chunks WHERE embedding IS NOT NULL"
            ).fetchone()[0]
            
            return {
                'total_chunks': total_chunks,
                'indexed_chunks': indexed_chunks,
                'sources': [{'file': s[0], 'count': s[1]} for s in sources],
                'indexed_percentage': (indexed_chunks / total_chunks * 100) if total_chunks > 0 else 0
            }
        except Exception as e:
            logger.error(f"Failed to get statistics: {e}")
            return {}
    
    def close(self) -> None:
        """Close thread-local connection."""
        if hasattr(self._local, 'conn') and self._local.conn is not None:
            try:
                self._local.conn.close()
                self._local.conn = None
            except Exception as e:
                logger.error(f"Error closing connection: {e}")


# Global instance (lazy loaded)
_gateway: KnowledgeGateway | None = None


def get_knowledge_gateway(read_only: bool = False) -> KnowledgeGateway:
    """Get or create global knowledge gateway instance.
    
    Args:
        read_only: Whether to open in read-only mode
    
    Returns:
        KnowledgeGateway instance
    """
    global _gateway
    
    if _gateway is None:
        _gateway = KnowledgeGateway(read_only=read_only)
    
    return _gateway
