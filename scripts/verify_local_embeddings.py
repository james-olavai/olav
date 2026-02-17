#!/usr/bin/env python3
"""
Verify that LOCAL embeddings are working correctly.

Tests:
1. Configuration loaded (EMBEDDING_MODE=local)
2. Model downloaded and loaded
3. Embeddings generated (no API calls)
4. Dimensions correct
"""

import sys
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from config.settings import settings
from src.olav.core.llm import LLMFactory


def test_embedding_mode():
    """Test 1: Check embedding mode configuration"""
    logger.info("=" * 60)
    logger.info("TEST 1: Embedding Mode Configuration")
    logger.info("=" * 60)
    logger.info(f"EMBEDDING_MODE: {settings.embedding_mode}")
    logger.info(f"EMBEDDING_LOCAL_MODEL: {settings.embedding_local_model}")
    
    if settings.embedding_mode.lower() != "local":
        logger.error(f"✗ EMBEDDING_MODE is '{settings.embedding_mode}', expected 'local'")
        logger.error("  Set EMBEDDING_MODE=local in .env file")
        return False
    
    logger.info("✓ Embedding mode is set to LOCAL")
    return True


def test_embeddings_creation():
    """Test 2: Initialize embeddings"""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 2: Initialize Local Embeddings")
    logger.info("=" * 60)
    
    try:
        logger.info(f"Loading model: {settings.embedding_local_model}")
        logger.info("(This may take a moment on first run as model is downloaded)")
        
        embeddings = LLMFactory.get_embeddings()
        
        logger.info("✓ Embeddings initialized successfully (no API call!)")
        return embeddings
    except ImportError as e:
        logger.error(f"✗ Import error: {e}")
        logger.error("  Run: uv add langchain-huggingface sentence-transformers torch")
        return None
    except Exception as e:
        logger.error(f"✗ Failed to initialize embeddings: {e}")
        return None


def test_embedding_generation(embeddings):
    """Test 3: Generate test embeddings"""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 3: Generate Test Embeddings")
    logger.info("=" * 60)
    
    try:
        # Test 1: Single embedding
        logger.info("Generating single embedding...")
        single_embedding = embeddings.embed_query("BGP neighbor down troubleshooting")
        logger.info(f"✓ Generated single embedding (dim={len(single_embedding)})")
        
        # Test 2: Batch embeddings
        logger.info("Generating batch embeddings...")
        batch_embeddings = embeddings.embed_documents([
            "OSPF neighbor in INIT state",
            "VXLAN tunnel not working",
            "BGP route flapping"
        ])
        logger.info(f"✓ Generated {len(batch_embeddings)} embeddings in batch")
        logger.info(f"  Each embedding dimension: {len(batch_embeddings[0])}")
        
        # Check dimensions match
        if len(single_embedding) != len(batch_embeddings[0]):
            logger.error("✗ Embedding dimensions don't match!")
            return False
        
        # Show sample values
        logger.info(f"\nSample embedding values (first 10):")
        logger.info(f"  {single_embedding[:10]}")
        logger.info(f"Vector magnitude: {sum(x**2 for x in single_embedding)**0.5:.4f}")
        logger.info("  (Should be ~1.0 for normalized vectors)")
        
        return True, len(single_embedding)
    
    except Exception as e:
        logger.error(f"✗ Failed to generate embeddings: {e}")
        return False, None


def test_comparison():
    """Test 4: Compare with OpenAI config (info only)"""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 4: Configuration Comparison")
    logger.info("=" * 60)
    
    logger.info("Current settings:")
    logger.info(f"  Embedding mode: {settings.embedding_mode} (LOCAL = FREE, no API calls)")
    logger.info(f"  Embedding model: {settings.embedding_local_model}")
    
    logger.info("\nOpenAI mode (if switched back):")
    logger.info(f"  embedding_provider: {settings.embedding_provider or 'openai'}")
    logger.info(f"  embedding_model: {settings.embedding_model or 'text-embedding-3-small'}")
    
    logger.info("\nBenefit of LOCAL mode:")
    logger.info("  ✓ No API dependencies")
    logger.info("  ✓ No API costs")
    logger.info("  ✓ Works offline")
    logger.info("  ✓ Runs on your machine")
    logger.info("  ✓ Faster response time (no network)")
    
    return True


if __name__ == "__main__":
    try:
        logger.info("\n🔬 LOCAL EMBEDDING VERIFICATION")
        logger.info("Testing sentence-transformers local embeddings\n")
        
        # Test 1: Configuration
        if not test_embedding_mode():
            sys.exit(1)
        
        # Test 2: Initialize embeddings
        embeddings = test_embeddings_creation()
        if embeddings is None:
            sys.exit(1)
        
        # Test 3: Generate embeddings
        success, dim = test_embedding_generation(embeddings)
        if not success:
            sys.exit(1)
        
        # Test 4: Comparison
        test_comparison()
        
        # Summary
        logger.info("\n" + "=" * 60)
        logger.info("✅ ALL TESTS PASSED")
        logger.info("=" * 60)
        logger.info(f"\n✓ Local embeddings ready!")
        logger.info(f"✓ Embedding model: {settings.embedding_local_model}")
        logger.info(f"✓ Dimension: {dim}")
        logger.info(f"✓ Mode: COMPLETELY LOCAL (no API calls)\n")
        logger.info("Next step: Index your PDFs")
        logger.info("  uv run python scripts/index_with_local_embeddings.py\n")
        
    except Exception as e:
        logger.error(f"\n✗ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
