#!/usr/bin/env python3
"""Index CCNP PDF and Test Knowledge Base Search
==============================================

Complete workflow to:
1. Index CCNP TSHOOT PDF file
2. Verify chunks stored in database
3. Test search functionality
"""

import sys
from pathlib import Path
import time

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import settings
from src.olav.lib.kb_manager import KnowledgeBaseManager
from src.olav.lib.knowledge_gateway import KnowledgeGateway
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def main():
    """Index PDF and test complete workflow."""
    
    print("\n" + "=" * 70)
    print("CCNP PDF Indexing & Knowledge Base Search Test")
    print("=" * 70)
    
    # Step 1: Initialize
    print("\n[Step 1/5] Initializing Knowledge Base Manager...")
    try:
        manager = KnowledgeBaseManager()
        gateway = KnowledgeGateway()
        print("  ✅ Initialized")
        print(f"  Knowledge dir: {manager.knowledge_dir}")
    except Exception as e:
        print(f"  ❌ Failed: {e}")
        return False
    
    # Step 2: Find PDFs
    print("\n[Step 2/5] Finding PDF files...")
    knowledge_dir = Path(".olav/knowledge")
    pdfs = list(knowledge_dir.glob("*.pdf"))
    
    if not pdfs:
        print(f"  ⚠️  No PDFs found in {knowledge_dir}")
        return False
    
    print(f"  Found {len(pdfs)} PDF(s):")
    for pdf in pdfs:
        size_mb = pdf.stat().st_size / (1024 * 1024)
        print(f"    - {pdf.name} ({size_mb:.1f} MB)")
    
    # Step 3: Index each PDF
    print("\n[Step 3/5] Indexing PDFs...")
    total_chunks = 0
    
    for pdf_path in pdfs:
        print(f"\n  📄 Indexing: {pdf_path.name}")
        
        start_time = time.time()
        try:
            indexed = manager.index_file(pdf_path, force_reindex=False)
            elapsed = time.time() - start_time
            
            print(f"     ✅ Indexed {indexed} chunks in {elapsed:.1f}s")
            total_chunks += indexed
        except Exception as e:
            print(f"     ❌ Failed: {e}")
            import traceback
            traceback.print_exc()
    
    # Step 4: Verify indexing
    print("\n[Step 4/5] Verifying database...")
    try:
        conn = gateway._get_connection()
        result = conn.execute("""
            SELECT COUNT(*) as chunk_count, 
                   COUNT(DISTINCT source_file) as file_count,
                   AVG(LENGTH(content)) as avg_chunk_size
            FROM knowledge_chunks
        """).fetchall()
        
        chunk_count, file_count, avg_size = result[0]
        print(f"  ✅ Database verified:")
        print(f"     Total chunks: {chunk_count}")
        print(f"     Files indexed: {file_count}")
        print(f"     Avg chunk size: {avg_size:.0f} chars")
        
        if chunk_count > 0:
            # Show breakdown by file
            stats = conn.execute("""
                SELECT source_file, COUNT(*) as chunks,
                       AVG(LENGTH(content)) as avg_size,
                       SUM(LENGTH(content)) as total_chars
                FROM knowledge_chunks
                GROUP BY source_file
                ORDER BY chunks DESC
            """).fetchall()
            
            print(f"\n     Breakdown:")
            for file, count, avg, total in stats:
                print(f"       - {file}")
                print(f"         Chunks: {count}, Total: {total/1024:.1f}KB")
    except Exception as e:
        print(f"  ❌ Verification failed: {e}")
        return False
    
    # Step 5: Test search
    print("\n[Step 5/5] Testing vector search...")
    
    test_queries = [
        "BGP routing protocol troubleshooting",
        "OSPF neighbor relationship problems",
        "network device configuration",
        "routing protocol convergence",
        "network troubleshooting best practices"
    ]
    
    try:
        for query in test_queries:
            print(f"\n  🔍 Query: '{query}'")
            
            # Generate embedding for query
            query_embedding = manager.embeddings.embed_query(query)
            print(f"     Query embedding: {len(query_embedding)}-dim vector")
            
            # Search
            conn = gateway._get_connection()
            results = conn.execute("""
                SELECT 
                    substr(content, 1, 100) as preview,
                    source_file,
                    LENGTH(content) as content_length
                FROM knowledge_chunks
                ORDER BY array_cosine_similarity(embedding, ?) DESC
                LIMIT 2
            """, [query_embedding]).fetchall()
            
            if results:
                print(f"     ✅ Found {len(results)} results:")
                for i, (preview, file, length) in enumerate(results, 1):
                    print(f"        [{i}] {file} ({length} chars)")
                    print(f"            Preview: {preview}...")
            else:
                print(f"     ⚠️  No results found")
    
    except Exception as e:
        print(f"  ❌ Search test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Summary
    print("\n" + "=" * 70)
    print("✅ INDEXING & SEARCH TEST COMPLETE")
    print("=" * 70)
    print(f"\n📊 Summary:")
    print(f"  • PDF files indexed: {len(pdfs)}")
    print(f"  • Total chunks: {total_chunks}")
    print(f"  • Embedding model: {settings.embedding_model or 'text-embedding-3-small'}")
    print(f"  • Search tested: {len(test_queries)} queries")
    print(f"\n✨ Knowledge base is ready for use!")
    print(f"   Try: uv run olav ask 'How to troubleshoot BGP?'")
    print()
    
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
