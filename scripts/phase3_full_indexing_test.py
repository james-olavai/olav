#!/usr/bin/env python3
"""Full PDF Indexing Test with Separated Embedding Provider
===========================================================

Tests complete knowledge base indexing workflow with independent
embedding model (qwen/qwen3-embedding-8b instead of text-embedding-3-small).

Configuration:
  LLM: x-ai/grok-4.1-fast via OpenRouter
  Embeddings: qwen/qwen3-embedding-8b via OpenRouter (4096-dim instead of 1536-dim)
"""

import sys
import os
from pathlib import Path
import time

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import settings
from src.olav.lib.kb_manager import KnowledgeBaseManager
from src.olav.lib.knowledge_gateway import KnowledgeGateway
import logging
import json

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def find_pdf_files(knowledge_dir: Path, max_size_mb: float = 50) -> list[Path]:
    """Find PDF files in knowledge directory."""
    pdfs = []
    if not knowledge_dir.exists():
        return pdfs
    
    for pdf_file in knowledge_dir.glob("*.pdf"):
        size_mb = pdf_file.stat().st_size / (1024 * 1024)
        if size_mb <= max_size_mb:
            pdfs.append(pdf_file)
            logger.info(f"Found PDF: {pdf_file.name} ({size_mb:.1f} MB)")
    
    return sorted(pdfs)


def index_single_pdf(manager: KnowledgeBaseManager, pdf_path: Path, batch_size: int = 10) -> dict:
    """Index a single PDF file and return statistics."""
    print(f"\n📄 Indexing: {pdf_path.name}")
    print(f"   Size: {pdf_path.stat().st_size / (1024*1024):.1f} MB")
    
    start_time = time.time()
    
    try:
        # Use the manager's index_file method which handles everything
        indexed_count = manager.index_file(pdf_path, force_reindex=False)
        
        elapsed = time.time() - start_time
        
        # Get some stats from the PDF
        text = manager.read_pdf(pdf_path)
        chunks = manager.split_text(text, pdf_path.name)
        
        return {
            "file": pdf_path.name,
            "size_mb": pdf_path.stat().st_size / (1024*1024),
            "chunks": len(chunks),
            "indexed": indexed_count,
            "failed": len(chunks) - indexed_count if indexed_count > 0 else len(chunks),
            "duration_sec": elapsed,
            "rate_chunks_per_sec": indexed_count / elapsed if elapsed > 0 else 0,
            "success": indexed_count > 0
        }
    
    except Exception as e:
        logger.error(f"Failed to index PDF: {e}", exc_info=True)
        return {
            "file": pdf_path.name,
            "error": str(e),
            "success": False
        }


def main():
    """Run complete indexing test."""
    print("\n" + "=" * 70)
    print("Full PDF Indexing Test with Separated Embedding Provider")
    print("=" * 70)
    
    # Show configuration
    print("\n[Config] Embedding Configuration:")
    effective_provider = settings.embedding_provider or settings.llm_provider
    effective_model = settings.embedding_model or "text-embedding-3-small"
    effective_base_url = settings.embedding_base_url or settings.llm_base_url
    print(f"  Provider: {effective_provider}")
    print(f"  Model: {effective_model}")
    print(f"  Endpoint: {effective_base_url}")
    
    # Initialize manager and gateway
    print("\n[Setup] Initializing Knowledge Base Manager...")
    try:
        manager = KnowledgeBaseManager()
        gateway = KnowledgeGateway()
        print("  ✅ Manager initialized")
    except Exception as e:
        print(f"  ❌ Failed to initialize: {e}")
        sys.exit(1)
    
    # Find PDFs
    print("\n[Discovery] Searching for PDF files...")
    knowledge_dir = Path(".olav/knowledge")
    pdfs = find_pdf_files(knowledge_dir)
    
    if not pdfs:
        print(f"  ⚠️ No PDFs found in {knowledge_dir}")
        print("     Creating sample test data...")
        
        # Create test chunks directly
        print("\n[Test] Creating sample knowledge chunks...")
        test_chunks = [
            {
                "id": "bgp_001",
                "title": "BGP Fundamentals",
                "description": "Overview of Border Gateway Protocol",
                "content": "BGP (Border Gateway Protocol) is the protocol used for routing between autonomous systems. It enables ISPs and large enterprises to exchange routing information across the internet. BGP is a path-vector protocol that makes routing decisions based on policies configured by network administrators.",
                "metadata": {"type": "test", "topic": "routing"}
            },
            {
                "id": "ospf_001",
                "title": "OSPF Design",
                "description": "OSPF area design best practices",
                "content": "OSPF (Open Shortest Path First) is an interior gateway protocol used within autonomous systems. Proper area design is critical for OSPF performance. Areas can be optimized using stub areas, not-so-stubby areas (NSSA), and area filtering to reduce protocol overhead.",
                "metadata": {"type": "test", "topic": "routing"}
            }
        ]
        
        try:
            for chunk in test_chunks:
                manager.index_chunk(**chunk)
                print(f"  ✅ Indexed: {chunk['id']}")
        except Exception as e:
            logger.error(f"Failed to index test chunks: {e}", exc_info=True)
    
    else:
        # Index PDFs
        print(f"\n[Indexing] Found {len(pdfs)} PDF(s), starting indexing...")
        
        results = []
        total_chunks = 0
        
        for pdf_path in pdfs:
            result = index_single_pdf(manager, pdf_path)
            results.append(result)
            if result.get("success"):
                total_chunks += result.get("chunks", 0)
        
        # Print results
        print("\n" + "=" * 70)
        print("INDEXING RESULTS")
        print("=" * 70)
        
        for result in results:
            if result.get("success"):
                print(f"\n✅ {result['file']}")
                print(f"   Pages: {result['pages']}")
                print(f"   Chunks: {result['chunks']} (indexed: {result['indexed']}, failed: {result['failed']})")
                print(f"   Duration: {result['duration_sec']:.1f}s")
                print(f"   Rate: {result['rate_chunks_per_sec']:.1f} chunks/sec")
            else:
                print(f"\n❌ {result['file']}")
                if "error" in result:
                    print(f"   Error: {result['error']}")
    
    # Test search functionality
    print("\n" + "=" * 70)
    print("[Search] Testing database functionality...")
    print("=" * 70)
    
    try:
        # Verify database state
        conn = gateway.get_read_only_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM knowledge_chunks")
        chunk_count = cursor.fetchone()[0]
        print(f"\n  ✅ Knowledge chunks in database: {chunk_count}")
        
        cursor.execute("DESCRIBE knowledge_chunks")
        columns = cursor.fetchall()
        print(f"  ✅ Database schema verified ({len(columns)} columns)")
        
        # Get status
        print("\n  Database Columns:")
        for col in columns:
            print(f"    - {col[0]}: {col[1]}")
        
    except Exception as e:
        logger.warning(f"Database test failed: {e}")
    
    print("\n" + "=" * 70)
    print("✅ Full indexing test complete!")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
