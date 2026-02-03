
import asyncio
import time
import os
import sys
from pathlib import Path

# Add src to path
sys.path.append(os.path.join(os.getcwd(), "src"))

from olav.agents.query_agent_v2 import QueryAgentV2
from olav.core.unified_database import UnifiedDatabase

QUERY = "List all devices version info"

async def benchmark():
    print(f"Benchmarking Semantic Cache for query: '{QUERY}'")
    
    # Setup
    sys.path.append(os.path.join(os.getcwd(), "src"))
    from olav.core.query_router import QueryRouter
    from olav.agents.query_agent_v2 import QueryAgentV2
    from pathlib import Path
    
    # 0. Clean slate
    print("🧹 Clearing previous cache entries...")
    with UnifiedDatabase() as db:
        db.conn.execute("DELETE FROM commands.main.semantic_cache WHERE query_text = ?", [QUERY])
    
    # Initialize components
    router = QueryRouter(Path(".olav/config/routing_rules.yaml"))
    agent = QueryAgentV2()

    async def execute_query(query_text):
        # Emulate cli_main.py logic
        decision = router.route(query_text)
        
        # Check for Semantic Cache Hit (Fast Path)
        if decision.expert == "database" and decision.tool and decision.params:
            # print(f"  ⚡ Fast Path Hit: {decision.tool} (SQL: {decision.params.get('sql', '')[:20]}...)")
            # Execute SQL directly (simulated tool execution)
            if decision.tool == "query_database":
                with UnifiedDatabase() as db:
                    return db.query(decision.params["sql"])
            return "Simulated Fast Path Result"
            
        # Fallback to Agent
        # print("  🤖 Agent Fallback")
        return await agent.query(query_text)

    # 1. First Run (Cold Cache - should miss router and go to agent)
    print("\n🚀 Run 1: Cold Cache (Agent Execution)")
    start_time = time.time()
    await execute_query(QUERY)
    duration1 = time.time() - start_time
    print(f"⏱️  Duration: {duration1:.4f}s")

    # 2. Second Run (Warm Cache - should hit router)
    print("\n🚀 Run 2: Warm Cache (Semantic Routing)")
    start_time = time.time()
    await execute_query(QUERY)
    duration2 = time.time() - start_time
    print(f"⏱️  Duration: {duration2:.4f}s")

    # Analysis
    print("\n📊 Analysis:")
    if duration2 < duration1:
        speedup = duration1 / duration2
        print(f"✅ Speedup: {speedup:.2f}x faster")
    else:
        print(f"❌ No speedup detected")
        
    # Verify DB Hit Count
    with UnifiedDatabase() as db:
        count = db.conn.execute("SELECT count(*) FROM commands.main.semantic_cache WHERE query_text = ?", [QUERY]).fetchone()[0]
        print(f"Cache entries: {count}")

if __name__ == "__main__":
    asyncio.run(benchmark())
