#!/usr/bin/env python3
"""
Schema Migration: Add incremental indexing support

目的：
1. 添加索引元数据表 (indexed_files)
2. 为 knowledge_chunks 添加源文件hash和修改时间
3. 支持增量和差量更新

运行: uv run python scripts/migrate_kb_to_incremental.py
"""

import hashlib
import logging
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import duckdb
from config.paths import MAIN_DB_PATH

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def migrate_kb_schema():
    """Add incremental indexing support to knowledge base"""
    
    conn = duckdb.connect(str(MAIN_DB_PATH))
    
    try:
        # Step 1: Create indexed_files metadata table if not exists
        logger.info("Creating indexed_files metadata table...")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS indexed_files (
                file_path VARCHAR PRIMARY KEY,
                file_name VARCHAR NOT NULL,
                file_hash VARCHAR NOT NULL,              -- SHA256 hash of file content
                file_mtime TIMESTAMP NOT NULL,           -- Last modified time
                chunk_count INT DEFAULT 0,               -- Number of chunks created
                indexed_at TIMESTAMP DEFAULT now(),      -- When indexed
                embedding_mode VARCHAR DEFAULT 'local',  -- local or openai
                embedding_model VARCHAR DEFAULT '',      -- Which model used
                embedding_dim INT DEFAULT 512,           -- Vector dimension
                status VARCHAR DEFAULT 'indexed'         -- indexed, error, partial
            );
            
            CREATE INDEX IF NOT EXISTS idx_indexed_files_hash 
            ON indexed_files (file_hash);
            
            CREATE INDEX IF NOT EXISTS idx_indexed_files_mtime 
            ON indexed_files (file_mtime DESC);
        """)
        logger.info("✓ indexed_files table created/verified")
        
        # Step 2: Verify knowledge_chunks has required columns
        logger.info("Verifying knowledge_chunks schema...")
        
        try:
            # Check if columns exist
            result = conn.execute("""
                SELECT column_name FROM information_schema.columns 
                WHERE table_name = 'knowledge_chunks'
            """).fetchall()
            
            existing_cols = {row[0].lower() for row in result}
            
            # Add source_file_hash if missing
            if 'source_file_hash' not in existing_cols:
                logger.info("Adding source_file_hash column...")
                conn.execute("""
                    ALTER TABLE knowledge_chunks 
                    ADD COLUMN source_file_hash VARCHAR DEFAULT NULL
                """)
            
            # Add source_file_mtime if missing  
            if 'source_file_mtime' not in existing_cols:
                logger.info("Adding source_file_mtime column...")
                conn.execute("""
                    ALTER TABLE knowledge_chunks 
                    ADD COLUMN source_file_mtime TIMESTAMP DEFAULT NULL
                """)
            
            # Add embedding_model if missing
            if 'embedding_model' not in existing_cols:
                logger.info("Adding embedding_model column...")
                conn.execute("""
                    ALTER TABLE knowledge_chunks 
                    ADD COLUMN embedding_model VARCHAR DEFAULT ''
                """)
            
            # Add embedding_dim if missing
            if 'embedding_dim' not in existing_cols:
                logger.info("Adding embedding_dim column...")
                conn.execute("""
                    ALTER TABLE knowledge_chunks 
                    ADD COLUMN embedding_dim INT DEFAULT 512
                """)
            
            logger.info("✓ knowledge_chunks schema verified/updated")
            
        except Exception as e:
            logger.warning(f"Could not verify knowledge_chunks columns: {e}")
        
        # Step 3: Create index on source_file_hash for faster lookups
        logger.info("Creating indexes for incremental operations...")
        try:
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_kb_source_hash 
                ON knowledge_chunks (source_file_hash)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_kb_source_file 
                ON knowledge_chunks (source_file)
            """)
            logger.info("✓ Indexes created")
        except Exception as e:
            logger.warning(f"Index creation warning: {e}")
        
        # Step 4: Populate indexed_files from existing knowledge_chunks
        logger.info("Populating indexed_files from existing chunks...")
        
        try:
            # Get unique source files from knowledge_chunks
            result = conn.execute("""
                SELECT DISTINCT source_file, file_path, COUNT(*) as chunk_count
                FROM knowledge_chunks
                GROUP BY source_file, file_path
            """).fetchall()
            
            if result:
                logger.info(f"Found {len(result)} unique source files in knowledge_chunks")
                
                for source_file, file_path, chunk_count in result:
                    if file_path:
                        try:
                            # Calculate hash from file (if exists)
                            file_obj = Path(file_path)
                            if file_obj.exists():
                                file_hash = calculate_file_hash(file_obj)
                                file_mtime = datetime.fromtimestamp(
                                    file_obj.stat().st_mtime
                                )
                            else:
                                # File no longer exists, use placeholder hash
                                file_hash = "unknown"
                                file_mtime = datetime.now()
                            
                            # Upsert into indexed_files
                            conn.execute("""
                                INSERT INTO indexed_files 
                                (file_path, file_name, file_hash, file_mtime, chunk_count)
                                VALUES (?, ?, ?, ?, ?)
                                ON CONFLICT (file_path) DO UPDATE SET
                                    file_hash = excluded.file_hash,
                                    file_mtime = excluded.file_mtime,
                                    chunk_count = excluded.chunk_count,
                                    indexed_at = now()
                            """, [file_path, source_file, file_hash, file_mtime, chunk_count])
                        except Exception as e:
                            logger.warning(f"Could not index {file_path}: {e}")
                
                logger.info("✓ Populated indexed_files from knowledge_chunks")
            else:
                logger.info("No existing chunks found (clean database)")
        
        except Exception as e:
            logger.warning(f"Could not populate indexed_files: {e}")
        
        logger.info("\n" + "=" * 60)
        logger.info("✅ SCHEMA MIGRATION COMPLETE")
        logger.info("=" * 60)
        logger.info("\nNew tables/features available:")
        logger.info("  • indexed_files - tracks all indexed files")
        logger.info("  • Incremental indexing - skip unchanged files")
        logger.info("  • Differential updates - only reindex modified files")
        logger.info("  • Embedding metadata - track which model was used")
        logger.info("\nUsage:")
        logger.info("  # Incremental (skip unchanged):")
        logger.info("  uv run python scripts/index_with_local_embeddings.py --incremental")
        logger.info("\n  # Complete reindex (delete all, start fresh):")
        logger.info("  uv run python scripts/index_with_local_embeddings.py --rebuild")
        logger.info("\n" + "=" * 60 + "\n")
        
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        raise
    finally:
        conn.close()


def calculate_file_hash(file_path: Path, algorithm: str = 'sha256') -> str:
    """Calculate SHA256 hash of file content
    
    Args:
        file_path: Path to file
        algorithm: Hash algorithm (default: sha256)
    
    Returns:
        Hex digest hash
    """
    hash_func = hashlib.sha256()
    
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            hash_func.update(chunk)
    
    return hash_func.hexdigest()


if __name__ == "__main__":
    try:
        migrate_kb_schema()
    except Exception as e:
        logger.error(f"✗ Migration failed: {e}")
        sys.exit(1)
