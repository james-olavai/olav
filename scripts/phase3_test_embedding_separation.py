#!/usr/bin/env python3
"""Test: Independent Embedding Provider Configuration
========================================================

Tests that embedding provider can be separated from LLM provider.

Configuration from .env:
  LLM_PROVIDER=openai
  LLM_MODEL_NAME=x-ai/grok-4.1-fast
  EMBEDDING_PROVIDER=openai
  EMBEDDING_MODEL=qwen/qwen3-embedding-8b
  EMBEDDING_BASE_URL=https://openrouter.ai/api/v1
  
This allows using different models for LLM and embeddings.
"""

import sys
import os
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import settings
from src.olav.core.llm import LLMFactory
from src.olav.lib.kb_manager import KnowledgeBaseManager
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def display_config():
    """Display current configuration."""
    print("\n" + "=" * 70)
    print("[Step 1/4] Current Configuration from .env")
    print("=" * 70)
    
    print("\n📋 LLM Configuration:")
    print(f"  LLM_PROVIDER: {settings.llm_provider}")
    print(f"  LLM_MODEL_NAME: {settings.llm_model_name}")
    print(f"  LLM_BASE_URL: {settings.llm_base_url or '(default)'}")
    print(f"  LLM_API_KEY: {'✅ Set' if settings.llm_api_key else '❌ Not set'}")
    
    print("\n🔌 Embedding Configuration (Independent):")
    print(f"  EMBEDDING_PROVIDER: {settings.embedding_provider or '(uses LLM_PROVIDER)'}")
    print(f"  EMBEDDING_MODEL: {settings.embedding_model or '(default: text-embedding-3-small)'}")
    print(f"  EMBEDDING_BASE_URL: {settings.embedding_base_url or '(uses LLM_BASE_URL)'}")
    print(f"  EMBEDDING_API_KEY: {'✅ Set' if settings.embedding_api_key else '❌ Using LLM_API_KEY'}")


def test_llm_provider():
    """Test LLM provider configuration."""
    print("\n" + "=" * 70)
    print("[Step 2/4] Testing LLM Chat Model")
    print("=" * 70)
    
    try:
        chat_model = LLMFactory.get_chat_model()
        print(f"  ✅ LLM Chat Model initialized: {type(chat_model).__name__}")
        print(f"     Model: {settings.llm_model_name}")
        return True
    except Exception as e:
        print(f"  ❌ LLM Chat Model initialization failed: {e}")
        return False


def test_embedding_separation():
    """Test independent embedding provider configuration."""
    print("\n" + "=" * 70)
    print("[Step 3/4] Testing Independent Embedding Provider")
    print("=" * 70)
    
    try:
        embeddings = LLMFactory.get_embeddings()
        print(f"  ✅ Embeddings initialized: {type(embeddings).__name__}")
        
        # Show effective configuration
        effective_provider = settings.embedding_provider or settings.llm_provider
        effective_model = settings.embedding_model or "text-embedding-3-small"
        effective_base_url = settings.embedding_base_url or settings.llm_base_url
        
        print(f"\n  📊 Effective Configuration:")
        print(f"     Provider: {effective_provider}")
        print(f"     Model: {effective_model}")
        print(f"     Base URL: {effective_base_url or '(default OpenAI)'}")
        
        # Generate a test embedding
        print(f"\n  🧪 Testing embedding generation...")
        test_text = "BGP routing protocol for ISP networks"
        embedding = embeddings.embed_query(test_text)
        
        print(f"  ✅ Embedding generated successfully")
        print(f"     Dimension: {len(embedding)}")
        print(f"     Sample values: [{embedding[0]:.4f}, {embedding[1]:.4f}, {embedding[2]:.4f}...]")
        
        return True
    except Exception as e:
        print(f"  ❌ Embedding test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_kb_manager_integration():
    """Test KnowledgeBaseManager with independent embeddings."""
    print("\n" + "=" * 70)
    print("[Step 4/4] Testing KnowledgeBaseManager Integration")
    print("=" * 70)
    
    try:
        manager = KnowledgeBaseManager()
        print(f"  ✅ KnowledgeBaseManager initialized with unified LLM system")
        
        # Test generating description embedding
        test_desc = "This is a BGP configuration example for enterprise networks"
        embedding = manager.generate_embedding(test_desc)
        
        print(f"  ✅ Generated description embedding")
        print(f"     Length: {len(embedding)} dimensions")
        
        return True
    except Exception as e:
        print(f"  ❌ KnowledgeBaseManager test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    print("\n" + "=" * 70)
    print("Testing: Independent Embedding Provider Separation")
    print("=" * 70)
    
    # Step 1: Display configuration
    display_config()
    
    # Step 2: Test LLM provider
    llm_ok = test_llm_provider()
    
    # Step 3: Test independent embeddings
    embedding_ok = test_embedding_separation()
    
    # Step 4: Test KBManager integration
    kb_ok = test_kb_manager_integration()
    
    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    
    results = {
        "✓ LLM Provider": llm_ok,
        "✓ Independent Embeddings": embedding_ok,
        "✓ KBManager Integration": kb_ok,
    }
    
    for test, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {test}: {status}")
    
    all_passed = all(results.values())
    
    print("\n" + "=" * 70)
    if all_passed:
        print("✅ ALL TESTS PASSED - Embedding separation configured correctly!")
        print("\nConfiguration Summary:")
        print(f"  • LLM: {settings.llm_provider}/{settings.llm_model_name}")
        print(f"  • Embeddings: {settings.embedding_provider or settings.llm_provider}/{settings.embedding_model or 'text-embedding-3-small'}")
        print(f"  • Endpoint: {settings.embedding_base_url or settings.llm_base_url}")
    else:
        print("❌ SOME TESTS FAILED")
        sys.exit(1)
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
