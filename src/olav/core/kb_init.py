#!/usr/bin/env python3
"""Initialize Knowledge Base table structure in main.duckdb.

This script creates the knowledge_chunks table and HNSW index for vector search.
"""

import logging
import sys
from pathlib import Path

import duckdb

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Import from config
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config.paths import MAIN_DB_PATH


def init_kb_schema() -> bool:
    """Create knowledge_chunks table and indexes.
    
    Returns:
        True if successful, False otherwise
    """
    try:
        # Connect to main database
        conn = duckdb.connect(str(MAIN_DB_PATH))
        logger.info(f"Connected to {MAIN_DB_PATH}")
        
        # Drop table if it exists (for clean rebuild)
        try:
            conn.execute("DROP TABLE IF EXISTS knowledge_chunks CASCADE")
            logger.info("Dropped existing knowledge_chunks table")
        except:
            pass
        
        # Create knowledge_chunks table (vector-ready)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_chunks (
                id VARCHAR PRIMARY KEY,
                content TEXT NOT NULL,
                embedding FLOAT[1536],
                source_file VARCHAR NOT NULL,
                file_path VARCHAR NOT NULL,
                created_at TIMESTAMP DEFAULT now(),
                updated_at TIMESTAMP DEFAULT now(),
                metadata JSON
            )
        """)
        logger.info("✅ Created knowledge_chunks table")
        
        # Create basic indexes (DuckDB native)
        conn.execute("""
            CREATE INDEX idx_knowledge_source 
            ON knowledge_chunks (source_file, created_at)
        """)
        logger.info("✅ Created source file index")
        
        conn.execute("""
            CREATE INDEX idx_knowledge_created 
            ON knowledge_chunks (created_at DESC)
        """)
        logger.info("✅ Created creation time index")
        
        # Verify table structure
        result = conn.execute("""
            SELECT COUNT(*) as total_chunks
            FROM knowledge_chunks
        """).fetchone()
        
        total_chunks = result[0]
        logger.info(f"✅ knowledge_chunks table ready ({total_chunks} rows)")
        
        # Show table info
        schema = conn.execute("""
            PRAGMA table_info('knowledge_chunks')
        """).fetchall()
        
        logger.info("\n📋 Table Schema:")
        for col_info in schema:
            col_name, col_type = col_info[1], col_info[2]
            logger.info(f"   {col_name:20s} {col_type:20s}")
        
        conn.close()
        logger.info("\n✅ Database initialization successful!")
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to initialize KB schema: {e}", exc_info=True)
        return False


def verify_kb_schema() -> bool:
    """Verify knowledge_chunks table exists and is properly configured.
    
    Returns:
        True if schema is valid, False otherwise
    """
    try:
        conn = duckdb.connect(str(MAIN_DB_PATH), read_only=True)
        
        # Check if table exists
        result = conn.execute("""
            SELECT COUNT(*) as cnt
            FROM information_schema.tables 
            WHERE table_name = 'knowledge_chunks'
        """).fetchone()
        
        if result[0] == 0:
            logger.error("❌ knowledge_chunks table not found")
            return False
        
        # Check column count
        columns = conn.execute("""
            SELECT COUNT(*) as cnt
            FROM information_schema.columns 
            WHERE table_name = 'knowledge_chunks'
        """).fetchone()
        
        if columns[0] < 6:  # Minimum 6 columns
            logger.error(f"❌ Table has only {columns[0]} columns (expected >= 6)")
            return False
        
        # Test query
        result = conn.execute("""
            SELECT COUNT(*) as chunks, COUNT(DISTINCT source_file) as files
            FROM knowledge_chunks
        """).fetchone()
        
        logger.info(f"✅ Knowledge base verification passed:")
        logger.info(f"   Total chunks: {result[0]}")
        logger.info(f"   Source files: {result[1]}")
        
        conn.close()
        return True
        
    except Exception as e:
        logger.error(f"❌ Verification failed: {e}")
        return False
        
        # Check if table exists
        result = conn.execute("""
            SELECT COUNT(*) as cnt
            FROM information_schema.tables 
            WHERE table_name = 'knowledge_chunks'
        """).fetchone()
        
        if result[0] == 0:
            logger.error("❌ knowledge_chunks table not found")
            return False
        
        # Check column count
        columns = conn.execute("""
            SELECT COUNT(*) as cnt
            FROM information_schema.columns 
            WHERE table_name = 'knowledge_chunks'
        """).fetchone()
        
        if columns[0] < 6:  # Minimum 6 columns
            logger.error(f"❌ Table has only {columns[0]} columns (expected >= 6)")
            return False
        
        # Test query
        result = conn.execute("""
            SELECT COUNT(*) as chunks, COUNT(DISTINCT source_file) as files
            FROM knowledge_chunks
        """).fetchone()
        
        logger.info(f"✅ Knowledge base verification passed:")
        logger.info(f"   Total chunks: {result[0]}")
        logger.info(f"   Source files: {result[1]}")
        
        conn.close()
        return True
        
    except Exception as e:
        logger.error(f"❌ Verification failed: {e}")
        return False


if __name__ == "__main__":
    logger.info("═" * 60)
    logger.info("Knowledge Base Schema Initialization")
    logger.info("═" * 60)
    
    # Initialize schema
    if not init_kb_schema():
        sys.exit(1)
    
    logger.info("")
    
    # Verify schema
    if not verify_kb_schema():
        logger.warning("⚠️  Some verification checks failed, but table may still be usable")
    
    logger.info("")
    logger.info("✨ Knowledge Base initialization complete!")
    logger.info("\nNext steps:")
    logger.info("  1. olav admin kb-index       (Index knowledge base)")
    logger.info("  2. olav admin kb-status      (Verify indexing)")
    logger.info("  3. olav admin kb-search 'query'  (Test search)")
