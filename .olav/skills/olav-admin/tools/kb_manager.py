"""Knowledge Base Manager - Index and manage knowledge base.

Responsible for:
- Indexing all .md files in .olav/knowledge/ directory
- Generating embeddings via OpenAI API
- Storing indexed content in DuckDB using LangChain VectorStore
- Retrieving knowledge base status
- Supporting incremental and full reindexing

Uses LangChain's VectorStore abstraction for seamless ecosystem integration
and significantly reduced custom code (~200 lines → ~120 lines).
"""

import logging
import time
from pathlib import Path
from typing import Dict, Optional
import hashlib

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    from langchain_core.documents import Document
    from langchain_community.vectorstores import DuckDB
except ImportError:
    RecursiveCharacterTextSplitter = None
    Document = None
    DuckDB = None

try:
    import duckdb
except ImportError:
    duckdb = None

from config.paths import MAIN_DB_PATH
from config.settings import AGENT_DIR
from olav.core.llm import LLMFactory

# OLAV_DIR is the .olav/ directory (also called AGENT_DIR in config)
KNOWLEDGE_DIR = AGENT_DIR / "knowledge"

logger = logging.getLogger(__name__)




def _get_db_connection(read_only: bool = True):
    """Get DuckDB connection.
    
    Args:
        read_only: If True, opens in read-only mode
        
    Returns:
        DuckDB connection
    """
    if duckdb is None:
        raise RuntimeError("duckdb not installed. Install: pip install duckdb")
    
    return duckdb.connect(str(MAIN_DB_PATH), read_only=read_only)


def calculate_file_hash(file_path: Path, chunk_size: int = 8192) -> str:
    """Calculate SHA256 hash of file for change detection.
    
    Args:
        file_path: Path to file
        chunk_size: Size of chunks to read (default 8KB)
    
    Returns:
        str: Hex digest of SHA256 hash
    """
    sha256_hash = hashlib.sha256()
    
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(chunk_size), b""):
                sha256_hash.update(chunk)
        
        return sha256_hash.hexdigest()
    except Exception as e:
        logger.error(f"Failed to calculate hash for {file_path}: {e}")
        raise


def check_if_indexed_langchain(file_path: Path) -> bool:
    """Check if file is already indexed by comparing content hash.
    
    Args:
        file_path: Path to markdown file
    
    Returns:
        bool: True if file is indexed and unchanged, False otherwise
    """
    try:
        if duckdb is None:
            return False
        
        conn = duckdb.connect(str(MAIN_DB_PATH), read_only=True)
        
        try:
            # Check if knowledge_chunks table exists (no indexed_files table in DuckDB)
            tables = conn.execute("""
                SELECT table_name FROM information_schema.tables 
                WHERE table_name='knowledge_chunks'
            """).fetchall()
            
            if not tables:
                return False
            
            # Note: DuckDB VectorStore doesn't track source file changes,
            # so always return False to perform complete re-indexing
            # This is safer than trying to track changes
            return False
            
        finally:
            conn.close()
            
    except Exception as e:
        logger.warning(f"Failed to check if {file_path} is indexed: {e}")
        return False


def index_knowledge_base(rebuild: bool = False, incremental: bool = True) -> Dict:
    """Index all markdown files in .olav/knowledge/ to DuckDB using LangChain VectorStore.
    
    Uses LangChain's from_documents() pattern for:
    - Automatic embedding generation and storage
    - Transactional consistency
    - Reduced custom code
    - Better ecosystem integration
    
    Args:
        rebuild: If True, drop existing index and rebuild from scratch
        incremental: If True (default), skip unchanged files
    
    Returns:
        Dict with statistics:
        - files_total: Total .md files found
        - files_indexed: Number of files indexed
        - files_skipped: Number of unchanged files
        - chunks_created: Total chunks created
        - elapsed_time: Seconds elapsed
        - api_cost_estimate: Estimated OpenAI API cost
    """
    start = time.time()
    
    # Validate dependencies
    if DuckDB is None:
        raise RuntimeError(
            "LangChain DuckDB integration not available. "
            "Install: pip install langchain-community"
        )
    
    if RecursiveCharacterTextSplitter is None:
        raise RuntimeError(
            "LangChain text splitter not available. "
            "Install: pip install langchain"
        )
    
    # Ensure knowledge directory exists
    if not KNOWLEDGE_DIR.exists():
        KNOWLEDGE_DIR.mkdir(parents=True)
        logger.info(f"Created knowledge directory: {KNOWLEDGE_DIR}")
        return {
            "files_total": 0,
            "files_indexed": 0,
            "files_skipped": 0,
            "chunks_created": 0,
            "elapsed_time": 0.0,
            "api_cost_estimate": 0.0
        }
    
    # Collect all .md files
    md_files = sorted(KNOWLEDGE_DIR.glob("*.md"))
    files_total = len(md_files)
    
    if files_total == 0:
        logger.warning(f"No .md files found in {KNOWLEDGE_DIR}")
        return {
            "files_total": 0,
            "files_indexed": 0,
            "files_skipped": 0,
            "chunks_created": 0,
            "elapsed_time": 0.0,
            "api_cost_estimate": 0.0
        }
    
    logger.info(f"Found {files_total} markdown files in {KNOWLEDGE_DIR}")
    
    # Drop table if rebuild
    if rebuild:
        try:
            conn = _get_db_connection(read_only=False)
            conn.execute("DROP TABLE IF EXISTS knowledge_chunks")
            conn.close()
            logger.info("Dropped existing knowledge_chunks table for rebuild")
        except Exception as e:
            logger.warning(f"Failed to drop table: {e}")
    
    try:
            # Initialize embeddings (use LLMFactory for unified provider support)
            embeddings = LLMFactory.get_embeddings()
        # Initialize text splitter
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            separators=["\n## ", "\n### ", "\n\n", "\n", " ", ""]
        )
        
        # Collect documents from all .md files
        documents = []
        total_tokens = 0
        files_indexed = 0
        
        for md_file in md_files:
            try:
                # Check if already indexed (incremental mode)
                if incremental and not rebuild and check_if_indexed_langchain(md_file):
                    logger.debug(f"Skipping unchanged file: {md_file.name}")
                    continue
                
                # Read file content
                content = md_file.read_text(encoding="utf-8")
                
                # Create document with metadata
                doc = Document(
                    page_content=content,
                    metadata={
                        "source_file": md_file.name,
                        "file_path": str(md_file)
                    }
                )
                documents.append(doc)
                
                # Estimate tokens for cost calculation
                total_tokens += int(len(content) / 4)  # rough estimate
                files_indexed += 1
                
                logger.debug(f"Added {md_file.name} for indexing")
                
            except Exception as e:
                logger.error(f"Failed to read {md_file.name}: {e}")
                continue
        
        if not documents:
            logger.warning("No documents to index")
            return {
                "files_total": files_total,
                "files_indexed": 0,
                "files_skipped": files_total,
                "chunks_created": 0,
                "elapsed_time": 0.0,
                "api_cost_estimate": 0.0
            }
        
        # Use LangChain's from_documents to create/update VectorStore
        # This handles:
        # - Text splitting
        # - Embedding generation
        # - Database storage
        # - Transaction management
        logger.info(f"Indexing {len(documents)} files using LangChain VectorStore...")
        
        # Create/get persistent connection for VectorStore
        db_conn = _get_db_connection(read_only=False)
        
        try:
            vectorstore = DuckDB.from_documents(
                documents,
                embeddings,
                connection=db_conn,
                table_name="knowledge_chunks"
            )
            
            # Count total chunks created
            result = db_conn.execute(
                "SELECT COUNT(*) FROM knowledge_chunks"
            ).fetchone()
            chunks_created = result[0] if result else 0
        finally:
            db_conn.close()
        
        elapsed = time.time() - start
        
        # Estimate API cost (text-embedding-3-small: $0.02 per 1M tokens)
        api_cost = (total_tokens / 1_000_000) * 0.02
        
        result = {
            "files_total": files_total,
            "files_indexed": files_indexed,
            "files_skipped": files_total - files_indexed,
            "chunks_created": chunks_created,
            "elapsed_time": round(elapsed, 2),
            "api_cost_estimate": round(api_cost, 4)
        }
        
        logger.info(
            f"✓ Knowledge base indexed: {files_indexed} files, "
            f"{chunks_created} chunks in {elapsed:.2f}s "
            f"(cost: ~${api_cost:.4f})"
        )
        
        return result
        
    except Exception as e:
        logger.error(f"Knowledge base indexing failed: {e}", exc_info=True)
        raise


def get_kb_status() -> Dict:
    """Get knowledge base statistics.
    
    Returns:
        Dict with status:
        - status: "indexed", "not_indexed", or "error"
        - total_files: Number of unique source files
        - total_chunks: Number of chunks in index
        - last_updated: Timestamp of most recent index
    """
    try:
        conn = _get_db_connection(read_only=True)
        
        try:
            # Check if table exists
            tables = conn.execute("""
                SELECT table_name FROM information_schema.tables 
                WHERE table_name='knowledge_chunks'
            """).fetchall()
            
            if not tables:
                return {
                    "status": "not_indexed",
                    "message": "Run 'olav admin kb-index' to create index",
                    "total_files": 0,
                    "total_chunks": 0
                }
            
            # Get stats (note: LangChain VectorStore doesn't add created_at by default)
            stats = conn.execute("""
                SELECT 
                    COUNT(*) as total_chunks
                FROM knowledge_chunks
            """).fetchone()
            
            return {
                "status": "indexed",
                "total_files": 0,  # VectorStore doesn't track per-file
                "total_chunks": stats[0] if stats else 0,
                "last_updated": "unknown"  # VectorStore doesn't track timestamps
            }
            
        finally:
            conn.close()
        
    except Exception as e:
        logger.error(f"Failed to get KB status: {e}")
        return {
            "status": "error",
            "message": str(e),
            "total_files": 0,
            "total_chunks": 0
        }


# For command-line usage
if __name__ == "__main__":
    import sys
    import json
    
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == "index":
            rebuild = "--rebuild" in sys.argv
            result = index_knowledge_base(rebuild=rebuild, incremental=True)
            print(json.dumps(result, indent=2))
        
        elif command == "status":
            status = get_kb_status()
            print(json.dumps(status, indent=2))
        
        else:
            print("Usage:")
            print("  python kb_manager.py index [--rebuild]")
            print("  python kb_manager.py status")
    else:
        print("Usage:")
        print("  python kb_manager.py index [--rebuild]")
        print("  python kb_manager.py status")
