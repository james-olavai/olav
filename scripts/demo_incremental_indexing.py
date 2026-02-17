#!/usr/bin/env python3
"""
演示脚本: 展示增量索引相比完全重新索引的时间节省

运行: uv run python scripts/demo_incremental_indexing.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.olav.lib.kb_manager import KnowledgeBaseManager


def format_time(seconds: float) -> str:
    """Format seconds to readable time"""
    if seconds < 60:
        return f"{seconds:.1f}s"
    else:
        min = int(seconds // 60)
        sec = int(seconds % 60)
        return f"{min}m {sec}s"


def demo():
    """Run indexing demonstration"""
    
    print("\n" + "=" * 70)
    print("🎬 INCREMENTAL INDEXING DEMONSTRATION")
    print("=" * 70)
    
    manager = KnowledgeBaseManager()
    
    # Check current status
    status = manager.get_status()
    print(f"\nCurrent knowledge base status:")
    print(f"  Files in directory: {status['file_count']}")
    print(f"  Chunks in database: {status['total_chunks']}")
    
    if status['file_count'] == 0:
        print("\n⚠ No files found in knowledge directory!")
        print(f"   {manager.knowledge_dir}")
        print("\nAdd some PDF or markdown files first.")
        return
    
    # Scenario 1: First run (full index)
    print("\n" + "-" * 70)
    print("📍 SCENARIO 1: First Run (Full Index)")
    print("-" * 70)
    print("\nWhat to expect:")
    print("  • Process all files (first time)")
    print("  • Generate embeddings for all chunks")
    print("  • Populate indexed_files metadata")
    
    input("\nPress Enter to start first run... ")
    
    start_time = time.time()
    stats = manager.index_knowledge_dir(force_reindex=False, incremental=False)
    first_run_time = time.time() - start_time
    
    print(f"\n✅ First run complete!")
    print(f"   Time: {format_time(first_run_time)}")
    print(f"   Total chunks: {stats['total_indexed']}")
    
    # Scenario 2: Second run without changes (incremental)
    print("\n" + "-" * 70)
    print("📍 SCENARIO 2: Second Run (No Changes)")
    print("-" * 70)
    print("\nWhat to expect:")
    print("  • Check file hashes (very fast)")
    print("  • Skip all unchanged files")
    print("  • Complete in < 1 second")
    
    input("\nPress Enter to run incremental update... ")
    
    start_time = time.time()
    stats = manager.index_knowledge_dir(force_reindex=False, incremental=True)
    incremental_time = time.time() - start_time
    
    print(f"\n✅ Incremental run complete!")
    print(f"   Time: {format_time(incremental_time)}")
    
    # Calculate speedup
    if incremental_time > 0:
        speedup = first_run_time / incremental_time
        print(f"   Speedup: {speedup:.0f}x faster! ⚡")
    
    # Scenario 3: Modify a file
    print("\n" + "-" * 70)
    print("📍 SCENARIO 3: File Modified")
    print("-" * 70)
    print("\nWhat to expect:")
    print("  • Detect file hash mismatch")
    print("  • Delete old chunks for modified file")
    print("  • Re-index only the modified file")
    
    # For demo, we could create a test file or just show logic
    print("\n💡 Tip: To test this scenario:")
    print("   1. Edit a markdown file in .olav/knowledge/")
    print("   2. Run again: uv run python scripts/index_with_local_embeddings.py")
    print("   3. Watch it detect and reindex only that file")
    
    # Show file status
    print("\n" + "-" * 70)
    print("📊 Current File Status")
    print("-" * 70)
    
    # Get status from indexed_files table
    try:
        import duckdb
        from config.paths import MAIN_DB_PATH
        
        conn = duckdb.connect(str(MAIN_DB_PATH), read_only=True)
        
        result = conn.execute("""
            SELECT 
                file_name,
                chunk_count,
                status,
                file_hash
            FROM indexed_files
            ORDER BY file_name
        """).fetchall()
        
        if result:
            print("\nIndexed files:")
            for file_name, chunk_count, status, file_hash in result:
                print(f"  ✓ {file_name:40} ({chunk_count:4} chunks)  {status:8}  {file_hash[:8]}...")
        
        conn.close()
    except Exception as e:
        print(f"Could not get indexed_files: {e}")
    
    # Summary
    print("\n" + "=" * 70)
    print("📈 PERFORMANCE SUMMARY")
    print("=" * 70)
    print(f"\nFirst run (full index):      {format_time(first_run_time)}")
    print(f"Second run (incremental):    {format_time(incremental_time)}")
    
    if incremental_time > 0 and first_run_time > 0:
        seconds_saved = first_run_time - incremental_time
        percentage_saved = (seconds_saved / first_run_time) * 100
        print(f"Time saved per update:       {format_time(seconds_saved)} ({percentage_saved:.0f}%)")
    
    print("\n💡 Key Insights:")
    print("  • First run: Must process all files (baseline)")
    print("  • Subsequent runs: Only process changed files")
    print("  • Incremental mode detects changes via file hash (SHA256)")
    print("  • Perfect for: Daily updates, adding docs, quick iteration")
    
    print("\n🚀 Usage Tips:")
    print("  Full rebuild (when needed):")
    print("    uv run python scripts/index_with_local_embeddings.py --rebuild")
    print("\n  Incremental (recommended, default):")
    print("    uv run python scripts/index_with_local_embeddings.py --incremental")
    print("\n  Auto (tries incremental, works offline):")
    print("    uv run python scripts/index_with_local_embeddings.py")
    
    print("\n" + "=" * 70 + "\n")


if __name__ == "__main__":
    try:
        demo()
    except Exception as e:
        print(f"\n✗ Demo failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
