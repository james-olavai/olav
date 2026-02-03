
import time
import sys
import os
from pathlib import Path

# Add src to path
sys.path.append(os.path.join(os.getcwd(), "src"))

def profile(name, func):
    start = time.time()
    print(f"Starting {name}...", end="", flush=True)
    res = func()
    end = time.time()
    print(f" Done. ({end - start:.4f}s)")
    return res

def test_imports():
    print("\n--- 1. Import Overhead ---")
    
    def import_duckdb():
        import duckdb
        return duckdb
    profile("import duckdb", import_duckdb)

    def import_langchain():
        import langchain
        return langchain
    profile("import langchain", import_langchain)
    
    def import_sentence_transformers():
        # This is usually the heavy one
        from olav.core.llm import LLMFactory
        return LLMFactory
    profile("import olav.core.llm", import_sentence_transformers)

def test_components():
    print("\n--- 2. Component Initialization ---")

    def init_udb():
        from olav.core.unified_database import UnifiedDatabase
        return UnifiedDatabase()
    udb = profile("UnifiedDatabase Init (Connection + Attach)", init_udb)
    udb.close()

    def init_router():
        from olav.core.query_router import QueryRouter
        return QueryRouter(Path(".olav/config/routing_rules.yaml"))
    
    router = profile("QueryRouter Init (Config Load)", init_router)
    
    def load_embeddings():
        # Trigger lazy load
        from olav.core.embeddings import get_embedder
        return get_embedder()
    
    embedder = profile("Embeddings Load (Model Load)", load_embeddings)
    
    def embed_query():
        return embedder.embed_query("Test query")
    
    profile("Embedding 1st inference", embed_query)
    profile("Embedding 2nd inference", embed_query)
    
    print("\n--- 3. Agent Overhead Analysis ---")
    def init_agent():
        from olav.agents.query_agent_v2 import QueryAgentV2
        return QueryAgentV2() # This calls _inject_metadata internally
        
    agent = profile("QueryAgentV2 Init (Total)", init_agent)
    
    # Measure specific internal method if possible (mock DB?)
    # For now total init time should reveal if it's slow.

if __name__ == "__main__":
    try:
        test_imports()
        test_components()
    except Exception as e:
        print(f"\n❌ Error: {e}")
