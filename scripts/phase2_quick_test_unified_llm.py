#!/usr/bin/env python3
"""Phase 2: Quick Test - Unified LLM System Integration

- Verify LLMFactory embeddings work with .env configuration
- Test PDF reading first
- Then test embedding with just 2 pages
- Show configuration being used
"""

import logging
import sys
from pathlib import Path

from config.paths import AGENT_DIR
from config.settings import settings
from src.olav.core.llm import LLMFactory
from src.olav.lib.kb_manager import KnowledgeBaseManager

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s"
)
logger = logging.getLogger(__name__)


def test_unified_llm():
    """Quick test of unified LLM system"""
    
    logger.info("=" * 70)
    logger.info("PHASE 2: Quick Test - Unified LLM Integration")
    logger.info("=" * 70)
    
    # Step 1: Show configuration
    logger.info("\n[Step 1/5] Current LLM Configuration:")
    logger.info(f"  Provider: {settings.llm_provider}")
    logger.info(f"  Model: {settings.llm_model_name}")
    logger.info(f"  API Key: {'✅ Configured' if settings.llm_api_key else '❌ Missing'}")
    logger.info(f"  Base URL: {settings.llm_base_url or 'Default'}")
    
    # Step 2: Verify embeddings factory
    logger.info("\n[Step 2/5] Testing LLMFactory Embeddings...")
    try:
        embeddings = LLMFactory.get_embeddings()
        logger.info(f"✅ Embeddings initialized successfully")
        logger.info(f"   Type: {type(embeddings).__name__}")
    except Exception as e:
        logger.error(f"❌ Embeddings initialization failed: {e}")
        return False
    
    # Step 3: Test simple embedding
    logger.info("\n[Step 3/5] Testing single embedding (quick)...")
    try:
        test_embedding = embeddings.embed_query("BGP configuration")
        logger.info(f"✅ Embedding successful")
        logger.info(f"   Dimension: {len(test_embedding)}")
        logger.info(f"   Sample values: {test_embedding[:3]}")
    except Exception as e:
        logger.error(f"❌ Embedding test failed: {e}")
        return False
    
    # Step 4: Test KnowledgeBaseManager with unified LLM
    logger.info("\n[Step 4/5] Testing KnowledgeBaseManager...")
    try:
        manager = KnowledgeBaseManager()
        logger.info(f"✅ Manager initialized with unified LLM")
        
        # Test generate_embedding
        embedding = manager.generate_embedding("OSPF troubleshooting")
        logger.info(f"   Generated embedding: {len(embedding)} dimensions")
    except Exception as e:
        logger.error(f"❌ Manager initialization failed: {e}")
        logger.info(f"   Error: {e}")
        return False
    
    # Step 5: Verify PDF reading (no embedding)
    logger.info("\n[Step 5/5] Testing PDF reading (no embedding)...")
    knowledge_dir = AGENT_DIR / "knowledge"
    pdf_files = [f for f in knowledge_dir.glob("*.pdf")]
    
    if not pdf_files:
        logger.warning(f"⚠️  No PDF files found in {knowledge_dir}")
        return True
    
    try:
        pdf_file = pdf_files[0]
        text = manager.read_pdf(pdf_file)
        logger.info(f"✅ PDF reading successful")
        logger.info(f"   File: {pdf_file.name}")
        logger.info(f"   Text length: {len(text)} characters")
        
        # Try splitting
        chunks = manager.split_text(text[:3000], pdf_file.name)  # Just first chunk
        logger.info(f"   Split into {len(chunks)} chunks (sample)")
    except Exception as e:
        logger.error(f"❌ PDF reading failed: {e}")
        return False
    
    # Summary
    logger.info("\n" + "=" * 70)
    logger.info("✅ All Quick Tests Passed!")
    logger.info("=" * 70)
    logger.info("\n✨ Findings:")
    logger.info("  ✓ OLAV unified LLM system is working")
    logger.info("  ✓ LLMFactory correctly provides embeddings")
    logger.info("  ✓ KnowledgeBaseManager integrated with unified system")
    logger.info("  ✓ PDF reading functional")
    logger.info("\n📋 Next: Full indexing when ready")
    logger.info("   All 392 pages will be indexed and embedded")
    
    return True


if __name__ == "__main__":
    success = test_unified_llm()
    sys.exit(0 if success else 1)
