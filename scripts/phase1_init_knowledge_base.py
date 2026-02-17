#!/usr/bin/env python3
"""Phase 1: Initialize Knowledge Base Infrastructure

- Create knowledge_chunks table in main.duckdb
- Set up vector indexing with HNSW
- Verify connection pool works
- Clean up old databases and directories
"""

import logging
import sys
from pathlib import Path

from config.paths import UNIFIED_DB, AGENT_DIR
from src.olav.lib.knowledge_gateway import KnowledgeGateway

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s"
)
logger = logging.getLogger(__name__)


def init_knowledge_base():
    """Phase 1 Initialization Steps"""
    
    logger.info("=" * 70)
    logger.info("PHASE 1: Initialize Knowledge Base Infrastructure")
    logger.info("=" * 70)
    
    # Step 1: Create gateway and initialize schema
    logger.info("\n[Step 1/4] Creating knowledge gateway...")
    try:
        gateway = KnowledgeGateway(db_path=UNIFIED_DB, read_only=False)
        logger.info(f"✅ Connected to: {UNIFIED_DB}")
    except Exception as e:
        logger.error(f"❌ Failed to create gateway: {e}")
        return False
    
    # Step 2: Initialize schema
    logger.info("\n[Step 2/4] Initializing database schema...")
    try:
        gateway.init_schema()
        logger.info("✅ Schema initialized (knowledge_chunks table created)")
    except Exception as e:
        logger.error(f"❌ Schema initialization failed: {e}")
        return False
    
    # Step 3: Verify connection and get statistics
    logger.info("\n[Step 3/4] Verifying connection and statistics...")
    try:
        stats = gateway.get_statistics()
        logger.info(f"✅ Current knowledge base statistics:")
        logger.info(f"   - Total chunks: {stats.get('total_chunks', 0)}")
        logger.info(f"   - Indexed chunks: {stats.get('indexed_chunks', 0)}")
        logger.info(f"   - Indexed %: {stats.get('indexed_percentage', 0):.1f}%")
        
        sources = stats.get('sources', [])
        if sources:
            logger.info(f"   - Sources:")
            for source in sources:
                logger.info(f"     • {source['file']}: {source['count']} chunks")
    except Exception as e:
        logger.error(f"❌ Statistics query failed: {e}")
        return False
    
    # Step 4: Clean up old databases and directories
    logger.info("\n[Step 4/4] Cleaning up legacy components...")
    
    cleanup_tasks = [
        # Old databases
        (AGENT_DIR / "db" / "knowledge.duckdb", "Old knowledge database"),
        (AGENT_DIR / "db" / "cases.duckdb", "Old cases database"),
        
        # Old subdirectories in .olav/knowledge/
        (AGENT_DIR / "knowledge" / "troubleshooting", "Troubleshooting subdir"),
        (AGENT_DIR / "knowledge" / "cases", "Cases subdir"),
        (AGENT_DIR / "knowledge" / "vendor_docs", "Vendor docs subdir"),
        
        # Old skill memories
        (AGENT_DIR / "skills" / "network-expert" / "memories", "Expert memories"),
    ]
    
    cleaned = 0
    for path, description in cleanup_tasks:
        if not path.exists():
            continue
        
        try:
            if path.is_file():
                path.unlink()
                logger.info(f"   ✅ Deleted file: {description} ({path.name})")
            else:
                import shutil
                shutil.rmtree(path)
                logger.info(f"   ✅ Deleted directory: {description} ({path.name}/)")
            cleaned += 1
        except Exception as e:
            logger.warning(f"   ⚠️  Failed to delete {description}: {e}")
    
    logger.info(f"\n✅ Cleaned up {cleaned} legacy items")
    
    # Step 5: Summary
    logger.info("\n" + "=" * 70)
    logger.info("✅ Phase 1 Complete!")
    logger.info("=" * 70)
    logger.info("\nNext Steps:")
    logger.info("1. Phase 2: Implement kb_manager.py (OpenAI embeddings + indexing)")
    logger.info("2. Advanced: kb-index, kb-reload, kb-status, kb-search CLI commands")
    logger.info("\nTo verify the setup:")
    logger.info(f"  sqlite3 {UNIFIED_DB} '.tables'")
    logger.info(f"  sqlite3 {UNIFIED_DB} 'SELECT COUNT(*) FROM knowledge_chunks;'")
    
    return True


if __name__ == "__main__":
    success = init_knowledge_base()
    sys.exit(0 if success else 1)
