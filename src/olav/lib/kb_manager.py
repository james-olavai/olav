"""Knowledge Base Manager - Document Processing and Indexing

Handles:
- PDF/Markdown file reading and chunking
- Text splitting optimization
- Embedding generation via unified OLAV LLM system
- Batch storage with error recovery
- Incremental & differential updates (skip unchanged files)
"""

import hashlib
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import PyPDF2
from langchain_text_splitters import RecursiveCharacterTextSplitter

from config.paths import AGENT_DIR
from config.settings import settings
from src.olav.core.llm import LLMFactory
from src.olav.lib.knowledge_gateway import KnowledgeGateway

logger = logging.getLogger(__name__)


class KnowledgeBaseManager:
    """Manages knowledge base lifecycle: ingest, index, update, delete.
    
    Features:
    - Full indexing: reindex all files
    - Incremental: skip unchanged files (based on file hash)
    - Differential: detect and reindex only modified files
    """

    def __init__(
        self,
        knowledge_dir: Path | str | None = None,
        gateway: KnowledgeGateway | None = None
    ):
        """Initialize knowledge base manager using OLAV unified LLM system.
        
        Args:
            knowledge_dir: Path to .olav/knowledge/ (default: auto)
            gateway: KnowledgeGateway instance (default: auto)
        
        Raises:
            ValueError: If LLM_API_KEY not configured in settings/environment
        """
        self.knowledge_dir = Path(knowledge_dir or AGENT_DIR / "knowledge")
        self.gateway = gateway or KnowledgeGateway()
        
        # Use OLAV unified LLM system for embeddings
        # Supports all configured LLM providers
        try:
            self.embeddings = LLMFactory.get_embeddings()
            logger.info("Using OLAV unified LLM system for embeddings")
        except ValueError as e:
            logger.error(f"Embeddings initialization failed: {e}")
            raise
        
        # Text splitter config
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.knowledge.chunk_size,        # From config, not hardcoded
            chunk_overlap=settings.knowledge.chunk_overlap,  # From config, not hardcoded
            separators=["\n\n", "\n", " ", ""]
        )
        
        # Embedding metadata
        self.embedding_mode = settings.embedding_mode
        self.embedding_model = settings.embedding_local_model if self.embedding_mode == "local" else settings.embedding_model
        
        # Get embedding dimension
        try:
            test_embedding = self.embeddings.embed_query("test")
            self.embedding_dim = len(test_embedding)
            logger.info(f"Detected embedding dimension: {self.embedding_dim}")
        except Exception as e:
            logger.error(f"Could not determine embedding dimension: {e}")
            self.embedding_dim = settings.knowledge.embedding_fallback_dim  # From config
            logger.warning(f"Using fallback embedding dimension: {self.embedding_dim}")
    
    def calculate_file_hash(self, file_path: Path) -> str:
        """Calculate SHA256 hash of file content for differential detection.
        
        Args:
            file_path: Path to file
        
        Returns:
            Hex digest hash
        """
        hash_func = hashlib.sha256()
        try:
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    hash_func.update(chunk)
            return hash_func.hexdigest()
        except Exception as e:
            logger.error(f"Failed to calculate hash for {file_path}: {e}")
            return "error"
    
    def check_if_indexed(self, file_path: Path) -> dict[str, Any]:
        """Check if file is already indexed and unchanged.
        
        Args:
            file_path: Path to file
        
        Returns:
            Dict with keys:
            - needs_reindex: bool
            - current_hash: str (calculated)
            - stored_hash: str or None
            - reason: str (why it needs reindex)
        """
        try:
            import duckdb
            from config.paths import MAIN_DB_PATH
            
            current_hash = self.calculate_file_hash(file_path)
            file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
            
            conn = duckdb.connect(str(MAIN_DB_PATH), read_only=True)
            
            # Check if file is in indexed_files
            result = conn.execute("""
                SELECT file_hash, file_mtime, chunk_count, status
                FROM indexed_files
                WHERE file_path = ?
            """, [str(file_path)]).fetchone()
            
            conn.close()
            
            if result:
                stored_hash, stored_mtime, chunk_count, status = result
                
                # File unchanged if hash matches
                if current_hash == stored_hash:
                    return {
                        "needs_reindex": False,
                        "current_hash": current_hash,
                        "stored_hash": stored_hash,
                        "reason": "File unchanged (hash match)",
                        "existing_chunks": chunk_count
                    }
                else:
                    return {
                        "needs_reindex": True,
                        "current_hash": current_hash,
                        "stored_hash": stored_hash,
                        "reason": f"File modified (hash mismatch: {stored_hash[:8]} → {current_hash[:8]})",
                        "existing_chunks": chunk_count
                    }
            else:
                # File not yet indexed
                return {
                    "needs_reindex": True,
                    "current_hash": current_hash,
                    "stored_hash": None,
                    "reason": "New file (not in index)",
                    "existing_chunks": 0
                }
        
        except Exception as e:
            # If error checking, assume needs reindex
            logger.warning(f"Error checking if indexed: {e}")
            return {
                "needs_reindex": True,
                "current_hash": "unknown",
                "stored_hash": None,
                "reason": f"Error checking status: {e}",
                "existing_chunks": 0
            }
    
    def record_indexing(self, file_path: Path, chunk_count: int, status: str = "indexed"):
        """Record file indexing in indexed_files table.
        
        Args:
            file_path: Path to file
            chunk_count: Number of chunks created
            status: Status (indexed, error, partial)
        """
        try:
            import duckdb
            from config.paths import MAIN_DB_PATH
            
            file_hash = self.calculate_file_hash(file_path)
            file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
            
            conn = duckdb.connect(str(MAIN_DB_PATH))
            
            conn.execute("""
                INSERT INTO indexed_files
                (file_path, file_name, file_hash, file_mtime, chunk_count,
                 embedding_mode, embedding_model, embedding_dim, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (file_path) DO UPDATE SET
                    file_hash = excluded.file_hash,
                    file_mtime = excluded.file_mtime,
                    chunk_count = excluded.chunk_count,
                    embedding_model = excluded.embedding_model,
                    embedding_dim = excluded.embedding_dim,
                    status = excluded.status,
                    indexed_at = now()
            """, [
                str(file_path),
                file_path.name,
                file_hash,
                file_mtime,
                chunk_count,
                self.embedding_mode,
                self.embedding_model,
                self.embedding_dim,
                status
            ])
            
            conn.close()
            logger.debug(f"Recorded {file_path.name}: {chunk_count} chunks, status={status}")
        
        except Exception as e:
            logger.warning(f"Failed to record indexing: {e}")
    
    def read_pdf(self, pdf_path: Path) -> str:
        """Extract text from PDF file.
        
        Args:
            pdf_path: Path to PDF file
        
        Returns:
            Extracted text
        """
        try:
            text = ""
            with open(pdf_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                
                for page_num, page in enumerate(reader.pages, 1):
                    try:
                        page_text = page.extract_text()
                        # Add page marker for metadata tracking
                        text += f"\n\n=== PAGE {page_num} ===\n{page_text}"
                    except Exception as e:
                        logger.warning(f"Failed to extract page {page_num}: {e}")
            
            logger.info(f"✅ Extracted {len(reader.pages)} pages from {pdf_path.name}")
            return text
        except Exception as e:
            logger.error(f"Failed to read PDF {pdf_path}: {e}")
            raise
    
    def read_markdown(self, md_path: Path) -> str:
        """Read markdown file.
        
        Args:
            md_path: Path to markdown file
        
        Returns:
            File content
        """
        try:
            content = md_path.read_text(encoding='utf-8')
            logger.info(f"✅ Read markdown file: {md_path.name}")
            return content
        except Exception as e:
            logger.error(f"Failed to read markdown {md_path}: {e}")
            raise
    
    def split_text(self, text: str, source_file: str) -> list[dict[str, Any]]:
        """Split text into chunks and generate metadata.
        
        Args:
            text: Raw text content
            source_file: Source filename
        
        Returns:
            List of chunk dicts ready for embedding
        """
        chunks = self.splitter.split_text(text)
        
        chunk_dicts = []
        for chunk_idx, chunk_content in enumerate(chunks, 1):
            # Extract page number from content if available
            page_match = re.search(r'=== PAGE (\d+) ===', chunk_content)
            page_num = int(page_match.group(1)) if page_match else None
            
            # Clean page markers from chunk
            clean_content = re.sub(r'=== PAGE \d+ ===', '', chunk_content).strip()
            
            chunk_dict = {
                'chunk_id': f"{Path(source_file).stem}_{chunk_idx:03d}",
                'content': clean_content,
                'source_file': source_file,
                'file_path': str(self.knowledge_dir / source_file),
                'metadata': {
                    'chunk_index': chunk_idx,
                    'total_chunks': len(chunks),
                    'page_number': page_num,
                    'char_count': len(clean_content)
                }
            }
            chunk_dicts.append(chunk_dict)
        
        logger.info(f"Split {source_file} into {len(chunks)} chunks")
        return chunk_dicts
    
    def generate_embedding(self, text: str) -> list[float]:
        """Generate OpenAI embedding for text.
        
        Args:
            text: Text to embed
        
        Returns:
            1536-dimensional embedding vector
        """
        try:
            # Use LangChain embeddings interface (works with OpenAI, Ollama, etc.)
            embedding = self.embeddings.embed_query(text)
            return embedding
        except Exception as e:
            logger.error(f"Embedding generation failed: {e}")
            raise
    
    def index_file(self, file_path: Path, force_reindex: bool = False, incremental: bool = False) -> int:
        """Index a single file and store chunks.
        
        Args:
            file_path: Path to file (.pdf or .md)
            force_reindex: Whether to delete existing chunks first
            incremental: If True, skip if file hash unchanged (differential update)
        
        Returns:
            Number of chunks indexed (0 if skipped due to incremental mode)
        """
        if not file_path.exists():
            logger.error(f"File not found: {file_path}")
            return 0
        
        source_file = file_path.name
        
        # INCREMENTAL MODE: Check if file changed
        if incremental:
            index_check = self.check_if_indexed(file_path)
            
            if not index_check["needs_reindex"]:
                logger.info(f"⊙ SKIPPED: {source_file}")
                logger.info(f"   └─ {index_check['reason']}")
                logger.info(f"   └─ ({index_check['existing_chunks']} chunks in DB)")
                return 0
            else:
                logger.info(f"↻ MODIFIED: {source_file}")
                logger.info(f"   └─ {index_check['reason']}")
                
                # Delete old chunks if file was modified
                if index_check["existing_chunks"] > 0:
                    logger.info(f"   └─ Deleting {index_check['existing_chunks']} old chunks...")
                    self.gateway.delete_source(source_file)
        else:
            # FULL REINDEX MODE: Delete old chunks if rebuilding
            if force_reindex:
                self.gateway.delete_source(source_file)
        
        # Read file
        try:
            if file_path.suffix.lower() == '.pdf':
                text = self.read_pdf(file_path)
            elif file_path.suffix.lower() in ['.md', '.markdown']:
                text = self.read_markdown(file_path)
            else:
                logger.error(f"Unsupported file type: {file_path.suffix}")
                return 0
        except Exception as e:
            logger.error(f"Failed to read {source_file}: {e}")
            self.record_indexing(file_path, 0, status="error")
            return 0
        
        # Split into chunks
        chunks = self.split_text(text, source_file)
        
        # Generate embeddings for each chunk
        logger.info(f"Generating embeddings for {len(chunks)} chunks...")
        for i, chunk in enumerate(chunks):
            try:
                embedding = self.generate_embedding(chunk['content'])
                chunk['embedding'] = embedding
                
                if (i + 1) % 10 == 0:
                    logger.info(f"  Embedded {i + 1}/{len(chunks)} chunks")
            except Exception as e:
                logger.warning(f"Skipping chunk {chunk['chunk_id']}: {e}")
                continue
        
        # Batch insert
        logger.info(f"Inserting {len(chunks)} chunks into database...")
        inserted = self.gateway.insert_batch(chunks, batch_size=50)
        
        # Record in indexed_files
        self.record_indexing(file_path, inserted, status="indexed")
        
        logger.info(f"✅ Indexed {inserted}/{len(chunks)} chunks from {source_file}")
        return inserted
    
    def index_knowledge_dir(self, force_reindex: bool = False, incremental: bool = False) -> dict[str, Any]:
        """Index all files in knowledge directory.
        
        Args:
            force_reindex: Whether to delete and reindex all
            incremental: If True, skip unchanged files (differential update)
        
        Returns:
            Dict with stats: {
                'total_indexed': total chunks indexed,
                'files_processed': number of files checked,
                'files_skipped': files skipped in incremental mode,
                'files_new': new files indexed,
                'files_modified': modified files reindexed
            }
        """
        if not self.knowledge_dir.exists():
            logger.error(f"Knowledge directory not found: {self.knowledge_dir}")
            return {'total_indexed': 0}
        
        supported_extensions = {'.pdf', '.md', '.markdown'}
        files = [
            f for f in self.knowledge_dir.glob('*')
            if f.is_file() and f.suffix.lower() in supported_extensions
        ]
        
        if not files:
            logger.warning(f"No supported files found in {self.knowledge_dir}")
            return {'total_indexed': 0}
        
        mode = "INCREMENTAL" if incremental else ("REBUILD" if force_reindex else "FULL")
        logger.info(f"Indexing mode: {mode}")
        logger.info(f"Found {len(files)} files to process\n")
        
        stats = {
            'total_indexed': 0,
            'files_processed': len(files),
            'files_skipped': 0,
            'files_new': 0,
            'files_modified': 0,
            'files_failed': 0
        }
        
        for idx, file_path in enumerate(files, 1):
            try:
                logger.info(f"\n[{idx}/{len(files)}] {file_path.name}")
                
                indexed = self.index_file(
                    file_path,
                    force_reindex=force_reindex,
                    incremental=incremental
                )
                
                stats['total_indexed'] += indexed
                
                if indexed == 0 and incremental:
                    stats['files_skipped'] += 1
                elif indexed > 0:
                    # Check if new or modified
                    check = self.check_if_indexed(file_path)
                    if check['stored_hash'] is None:
                        stats['files_new'] += 1
                    else:
                        stats['files_modified'] += 1
                
            except Exception as e:
                logger.error(f"Failed to index {file_path.name}: {e}")
                stats['files_failed'] += 1
                continue
        
        # Print summary
        logger.info("\n" + "=" * 70)
        logger.info("✅ INDEXING COMPLETE")
        logger.info("=" * 70)
        logger.info(f"Total chunks indexed:     {stats['total_indexed']}")
        logger.info(f"Files processed:          {stats['files_processed']}")
        
        if incremental:
            logger.info(f"  • Skipped (unchanged):  {stats['files_skipped']}")
            logger.info(f"  • New:                  {stats['files_new']}")
            logger.info(f"  • Modified:             {stats['files_modified']}")
        
        if stats['files_failed'] > 0:
            logger.info(f"Files failed:             {stats['files_failed']}")
        
        logger.info("=" * 70)
        
        return stats
    
    def get_status(self) -> dict[str, Any]:
        """Get current knowledge base status.
        
        Returns:
            Status dict with file count, chunk count, stats
        """
        # Get DB statistics
        db_stats = self.gateway.get_statistics()
        
        # Count files in knowledge dir
        supported_extensions = {'.pdf', '.md', '.markdown'}
        file_count = len([
            f for f in self.knowledge_dir.glob('*')
            if f.is_file() and f.suffix.lower() in supported_extensions
        ])
        
        return {
            'timestamp': datetime.now().isoformat(),
            'knowledge_dir': str(self.knowledge_dir),
            'file_count': file_count,
            'total_chunks': db_stats.get('total_chunks', 0),
            'indexed_chunks': db_stats.get('indexed_chunks', 0),
            'indexed_percentage': db_stats.get('indexed_percentage', 0),
            'sources': db_stats.get('sources', [])
        }


def reload_knowledge_base(force: bool = False, incremental: bool = True) -> dict[str, Any]:
    """CLI wrapper for knowledge base reload.
    
    Args:
        force: Force complete reindex of all files (ignores incremental)
        incremental: If True (default), skip unchanged files for faster updates
    
    Returns:
        Operation result with stats
    """
    try:
        logger.info("Initializing knowledge base manager...")
        manager = KnowledgeBaseManager()
        
        logger.info(f"Indexing knowledge directory: {manager.knowledge_dir}")
        
        # If force is True, disable incremental
        mode_incremental = incremental and not force
        
        stats = manager.index_knowledge_dir(
            force_reindex=force,
            incremental=mode_incremental
        )
        
        status = manager.get_status()
        
        return {
            'success': True,
            'stats': stats,
            'status': status
        }
    except Exception as e:
        logger.error(f"Knowledge base reload failed: {e}")
        return {
            'success': False,
            'error': str(e)
        }
