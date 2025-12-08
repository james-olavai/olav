"""直接测试 SuzieQ Parquet 工具."""

import asyncio

from olav.tools.suzieq_parquet_tool import suzieq_query, suzieq_schema_search


async def test():
    print("=" * 60)
    print("测试 1: suzieq_schema_search")
    print("=" * 60)
    result = await suzieq_schema_search.ainvoke({"query": "接口"})
    print(f"Result: {result}\n")

    print("=" * 60)
    print("测试 2: suzieq_query (interfaces, summarize)")
    print("=" * 60)
    result = await suzieq_query.ainvoke({"table": "interfaces", "method": "summarize", "hostname": "R1"})
    print(f"Result: {result}\n")

    print("=" * 60)
    print("测试 3: suzieq_query (interfaces, get)")
    print("=" * 60)
    result = await suzieq_query.ainvoke({"table": "interfaces", "method": "get", "hostname": "R1"})
    print(f"Result: {result}\n")


if __name__ == "__main__":
    asyncio.run(test())
