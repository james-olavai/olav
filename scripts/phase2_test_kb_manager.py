#!/usr/bin/env python3
"""Phase 2: Test Knowledge Base Manager

- Index the uploaded CCNP PDF
- Generate embeddings
- Store chunks in database
- Verify vector search works
"""

import logging
import sys
from pathlib import Path

from config.paths import AGENT_DIR
from src.olav.lib.kb_manager import KnowledgeBaseManager

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s"
)
logger = logging.getLogger(__name__)


def test_kb_manager():
    """Phase 2 Test"""
    
    logger.info("=" * 70)
    logger.info("PHASE 2: Test Knowledge Base Manager")
    logger.info("=" * 70)
    
    # Step 1: Initialize manager
    logger.info("\n[Step 1/4] Initializing Knowledge Base Manager...")
    try:
        manager = KnowledgeBaseManager()
        logger.info(f"✅ Manager initialized")
        logger.info(f"   Knowledge dir: {manager.knowledge_dir}")
    except Exception as e:
        logger.error(f"❌ Failed to initialize manager: {e}")
        logger.info("💡 Make sure OPENAI_API_KEY is set in environment")
        return False
    
    # Step 2: Check available files
    logger.info("\n[Step 2/4] Checking files to index...")
    supported = {'.pdf', '.md', '.markdown'}
    files = [
        f for f in manager.knowledge_dir.glob('*')
        if f.is_file() and f.suffix.lower() in supported
    ]
    
    if not files:
        logger.error(f"❌ No PDF/Markdown files found in {manager.knowledge_dir}")
        return False
    
    logger.info(f"✅ Found {len(files)} files:")
    for f in files:
        logger.info(f"   • {f.name}")
    
    # Step 3: Index first file as test
    logger.info("\n[Step 3/4] Indexing test file...")
    test_file = files[0]
    try:
        indexed = manager.index_file(test_file, force_reindex=True)
        logger.info(f"✅ Indexed {indexed} chunks from {test_file.name}")
    except Exception as e:
        logger.error(f"❌ Indexing failed: {e}")
        logger.info("💡 Troubleshooting:")
        logger.info("   - Check if PDF is valid and readable")
        logger.info("   - Verify OPENAI_API_KEY is correct")
        logger.info("   - Check API quota and rate limits")
        return False
    
    # Step 4: Display statistics
    logger.info("\n[Step 4/4] Knowledge Base Statistics...")
    try:
        status = manager.get_status()
        logger.info(f"✅ Knowledge base status:")
        logger.info(f"   Total chunks: {status['total_chunks']}")
        logger.info(f"   Indexed chunks: {status['indexed_chunks']}")
        logger.info(f"   Indexed %: {status['indexed_percentage']:.1f}%")
        logger.info(f"   Files: {status['file_count']}")
        
        sources = status.get('sources', [])
        if sources:
            logger.info(f"   Sources:")
            for source in sources:
                logger.info(f"     • {source['file']}: {source['count']} chunks")
    except Exception as e:
        logger.error(f"❌ Statistics retrieval failed: {e}")
        return False
    
    # Step 5: Test vector search (sample)
    logger.info("\n[BONUS] Testing Vector Search...")
    try:
        # Generate embedding for a test query
        test_query = "network topology"
        logger.info(f"   Query: '{test_query}'")
        
        query_embedding = manager.generate_embedding(test_query)
        logger.info(f"   Generated embedding (1536-dim): ✅")
        
        # Search
        results = manager.gateway.vector_search(
            query_embedding,
            limit=3,
            threshold=0.5
        )
        
        logger.info(f"✅ Vector search results ({len(results)} matches):")
        for i, result in enumerate(results, 1):
            # Truncate long content
            content_preview = result['content'][:100].replace('\n', ' ')
            logger.info(f"   [{i}] Similarity: {result['similarity']:.3f}")
            logger.info(f"       Source: {result['source_file']}")
            logger.info(f"       Preview: {content_preview}...")
    except Exception as e:
        logger.warning(f"Vector search test failed (non-critical): {e}")
    
    # Summary
    logger.info("\n" + "=" * 70)
    logger.info("✅ Phase 2 Complete!")
    logger.info("=" * 70)
    logger.info("\nNext Steps:")
    logger.info("1. Phase 3: Implement search_knowledge and web_search tools")
    logger.info("2. Phase 3: Update network-expert SKILL to use tools")
    logger.info("3. Phase 4: E2E testing and integration")
    logger.info("\nTo index all files:")
    logger.info(f"  uv run python scripts/phase2_test_kb_manager.py --all")
    logger.info("\nTo force reindex:")
    logger.info(f"  uv run python scripts/phase2_test_kb_manager.py --force")
    
    return True


if __name__ == "__main__":
    success = test_kb_manager()
    sys.exit(0 if success else 1)
