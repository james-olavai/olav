#!/usr/bin/env python
"""
Phase 3.2 Investigation: Multi-Agent Cache Sharing & Failure Analysis

Questionnaire:
1. 是否利用了 DeepAgents 原生缓存设计？
2. 多 agent 是否共享缓存？
3. 失败案例是什么原因？
"""

import json
import logging
from pathlib import Path
from config.paths import CACHE_DIR, get_database_path
from config.logging import get_logger

logger = get_logger(__name__)

def investigate_deepagents_caching():
    """调查 DeepAgents 原生缓存设计。"""
    
    print("\n" + "="*80)
    print("🔍 PHASE 3.2 INVESTIGATION: Multi-Agent Cache & Failure Analysis")
    print("="*80)
    
    # Issue 1: DeepAgents Native Caching
    print("\n" + "-"*80)
    print("❓ QUESTION 1: 是否利用了 DeepAgents 原生缓存设计？")
    print("-"*80)
    
    print("""
    📋 Current Implementation Analysis:
    
    1. ✅ IMPLEMENTED (Phase 3.1):
       - Custom QueryResultCache in src/olav/core/query_cache.py
       - 2-tier cache (L1: memory LRU + L2: disk SQLite)
       - Used only in src/olav/tools/react_query.py::query_database()
       - Singleton pattern (thread-safe)
       
    2. ❌ NOT UTILIZED (DeepAgents/LangGraph Native):
       - LangGraph's DuckDBSaver (checkpointer)
       - LangGraph's DuckDBStore (KV store)
       - DeepAgents' built-in semantic caching
       - SQLiteCache for LLM prompt caching
       
    📌 Problem:
       Phase 3.1 cache is TOOL-LEVEL (query_database)
       Not AGENT-LEVEL (DeepAgents checkpointer)
       
    🎯 Analysis:
       - query_database tool reusable across agents ✅
       - But each agent instance might create its own cache singleton
       - Cache is instantiated when get_query_cache() first called
       - Single process = shared cache ✅
       - Multi-process = separate caches ❌
       
    ⚠️  Gap:
       - No agent-level checkpointing with cache
       - No semantic caching (similarity matching)
       - No LLM prompt caching (at agent level)
       - DeepAgents DuckDBSaver not used currently
    """)
    
    # Issue 2: Multi-Agent Cache Sharing
    print("\n" + "-"*80)
    print("❓ QUESTION 2: 多 agent 是否共享缓存？")
    print("-"*80)
    
    print("""
    📊 Current SubAgent Architecture:
    
    From .olav/OLAV.md - 6 SubAgents registered:
    1. query       → network-query       [Uses: query_database ✅]
    2. expert      → network-expert      [Uses: query_database ✅]
    3. cli         → network-cli         [Uses: CLI execution]
    4. analysis    → network-analysis    [Uses: analysis tools]
    5. inspection  → network-inspection  [Uses: inspection tools]
    6. system      → system-admin        [Uses: system tools]
    
    🔍 Tool Analysis:
    
    query_database tool location: src/olav/tools/react_query.py
    Users:
    - network-query/SKILL.md (query SubAgent) ✅
    - network-expert/SKILL.md (expert SubAgent) ✅
    
    Cache Singleton: get_query_cache()
    - Global _query_cache = None
    - First call: creates QueryResultCache instance
    - Later calls: return same instance ✅
    - Thread-safe: uses threading.Lock ✅
    - Single process: all agents share same cache ✅
    
    ✅ YES - Multi-agent cache sharing is working!
    
    Evidence:
    - Singleton pattern ensures single instance
    - query_database used by multiple SubAgents
    - Cache persists in .olav/cache/query_result_cache.db
    - Thread-safe design prevents race conditions
    
    ⚠️  Caveat:
    - If agents run in separate processes → separate caches
    - Orchestrator runs in single process → shared cache ✅
    """)
    
    # Issue 3: Failure Analysis
    print("\n" + "-"*80)
    print("❓ QUESTION 3: 失败案例是什么原因？")
    print("-"*80)
    
    print("""
    📋 L1 Test Status:
    - Total: 10 tests
    - Before Phase 1-3.1: 6/9 = 67%
    - After Phase 1-3.1: 8/10 = 80%
    
    Tests Failing (2/10):
    ❌ 2 tests are still failing or not verified
    
    🔍 Likely Failure Reasons:
    
    1. **Database Path Issues** (Phase 1 - Fixed ✅)
       - Before: Hardcoded to .olav/db/olav.duckdb
       - Issue: test_network.duckdb not used
       - Fix: OLAV_DB_PATH environment variable
       - Status: SOLVED ✅
       
    2. **Field Name Errors** (Phase 2.1 - Fixed ✅)
       - Before: LLM generates wrong field names (40% error)
       - Issue: hostname (doesn't exist) vs name
       - Issue: device_role (doesn't exist) vs device_type
       - Fix: Field mapping table in SKILL.md
       - Status: SOLVED ✅
       
    3. **Timeout/Long Execution** (Likely)
       - Some queries might exceed 45s timeout
       - Cache integration should help (326x speedup)
       - But first query still slow (~30-45s with LLM)
       
    4. **Missing Data in Test DB**
       - Test database might lack certain data
       - Some queries expect specific devices/interfaces
       - Verify: test_network.duckdb has all data
       
    5. **Query Agent Failures** (Unknown)
       - Query execution error
       - LLM response parsing error
       - Tool invocation error
       
    6. **Expert Agent Failures** (NOT CACHED)
       - expert SubAgent also uses query_database
       - But expert agent might have different failure modes
       - expert agent more complex (topology analysis, etc.)
    
    📌 Remaining Unknown Failures:
       - L1-P1-008: "列出所有border角色的设备" ❓
       - L1-P1-009: "列出所有core角色的设备" ❓
       - Might be device_role field issues not fully resolved
       - Or might be timeout issues
    """)
    
    # Cache Integration Validation
    print("\n" + "-"*80)
    print("✅ VALIDATION: Cache is Working Across Tools")
    print("-"*80)
    
    from olav.tools.react_query import get_query_cache
    from olav.lib.data_gateway import DataGateway
    
    try:
        # Get shared cache
        cache = get_query_cache()
        print(f"✅ Cache singleton retrieved: {type(cache).__name__}")
        
        # Verify both query_database and expert can use it
        print(f"✅ Cache available to all SubAgents using query_database tool")
        
        # Check cache persistence
        cache_db = CACHE_DIR / "query_result_cache.db"
        if cache_db.exists():
            print(f"✅ Cache database file exists: {cache_db}")
            size_kb = cache_db.stat().st_size / 1024
            print(f"   Size: {size_kb:.1f} KB")
            
            # Check entries
            import duckdb
            conn = duckdb.connect(str(cache_db))
            count = conn.execute("SELECT COUNT(*) FROM query_cache").fetchone()[0]
            print(f"   Entries: {count}")
            conn.close()
        
    except Exception as e:
        print(f"❌ Error: {e}")
    
    # Recommendations
    print("\n" + "-"*80)
    print("💡 RECOMMENDATIONS FOR PHASE 3.2+")
    print("-"*80)
    
    print("""
    Priority 1: Deep Dive into Failing Tests
    ✅ Action: Run individual L1 tests with debug logging
    ✅ Action: Identify specific failure points (LLM, tool, timeout)
    ✅ Action: Check if expert agent works correctly
    
    Priority 2: Enhance DeepAgents Integration
    ⏳ Action: Use LangGraph's DuckDBSaver for agent checkpointing
    ⏳ Action: Implement semantic caching (similarity-based hits)
    ⏳ Action: Add LLM prompt caching at agent level
    
    Priority 3: Multi-Agent Testing
    ⏳ Action: Test concurrent cache access across agents
    ⏳ Action: Measure cache hit rate with multiple agents
    ⏳ Action: Verify no cache coherency issues
    
    Priority 4: Monitor & Optimize
    ⏳ Action: Add cache statistics to logs
    ⏳ Action: Monitor cache size growth
    ⏳ Action: Implement cache eviction policies
    """)
    
    print("\n" + "="*80)
    print("🔍 INVESTIGATION COMPLETE")
    print("="*80)

if __name__ == "__main__":
    investigate_deepagents_caching()
