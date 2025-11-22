"""Test if suzieq_parquet_tool is loaded in simple_agent."""

import asyncio
import sys

# Windows ProactorEventLoop fix for psycopg async
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from olav.agents.simple_agent import create_simple_agent


async def test():
    agent, checkpointer_ctx = await create_simple_agent()
    
    print("=" * 60)
    print("Agent Tools:")
    print("=" * 60)
    for i, tool in enumerate(agent.tools, 1):
        print(f"{i}. {tool.name}")
        print(f"   Description: {tool.description[:100]}...")
        print()
    
    print("=" * 60)
    print(f"Total tools: {len(agent.tools)}")
    print("=" * 60)
    
    # Cleanup
    await checkpointer_ctx.__aexit__(None, None, None)


if __name__ == "__main__":
    asyncio.run(test())
