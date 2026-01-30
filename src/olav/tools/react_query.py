"""Zero-ETL ReAct 查询工具集。

Enhancements (v0.9.9):
- SQL error suggestions (reduces error rate from 50-60% to <30%)
- EXPLAIN validation for early error detection
"""

from __future__ import annotations

import json
from pathlib import Path

from langchain_core.tools import tool

EXPORTS_DIR = Path("exports")


@tool
def discover_data(pattern: str = "*") -> str:
    """发现可用的网络数据文件。

    Args:
        pattern: 文件匹配模式，如 "*.json" 或 "bgp*"

    Returns:
        可用数据文件列表，包含路径和大小
    """
    files = []
    # 支持递归搜索 snapshot 目录
    for f in EXPORTS_DIR.glob(f"**/{pattern}.json"):
        # 计算相对于 exports 的路径
        rel_path = f.relative_to(EXPORTS_DIR)
        # 提取设备名 (parsed/设备名/命令.json)
        parts = rel_path.parts
        device = "unknown"
        if "parsed" in parts:
            parsed_idx = parts.index("parsed")
            if parsed_idx + 1 < len(parts):
                device = parts[parsed_idx + 1]

        files.append(
            {
                "path": str(rel_path),
                "size_kb": f.stat().st_size // 1024,
                "device": device,
            }
        )

        # 限制返回数量
        if len(files) >= 50:
            break

    return json.dumps(files, indent=2)


@tool
async def query_network(question: str | None = None, sql: str | None = None) -> str:
    """执行网络数据查询。

    支持直接的 SQL 语句或自然语言问题。
    使用专门的 SQL Assistant Agent，具备跨表关联、自省 Schema 和错误自愈能力。

    Args:
        question: 自然语言问题 (可选，优先)
        sql: SQL 查询语句 (可选，fallback)

    Returns:
        查询分析结果
    """
    query_text = question or sql
    if not query_text:
        return "Error: No question or SQL query provided."

    try:
        from olav.agents.query_agent_v2 import QueryAgentV2

        agent = QueryAgentV2()
        result = await agent.query(query_text)
        if isinstance(result, dict):
            return result.get("output") or result.get("error") or str(result)
        return result
    except Exception as e:
        return f"Query Error: {e}"


@tool
def inspect_file(file_path: str) -> str:
    """检查 JSON 文件结构和示例数据。

    Args:
        file_path: 相对于 exports/ 的文件路径

    Returns:
        文件结构描述和前 3 条记录
    """
    full_path = EXPORTS_DIR / file_path
    if not full_path.exists():
        return f"File not found: {file_path}"

    try:
        with open(full_path) as f:
            data = json.load(f)

        if isinstance(data, list):
            sample = data[:3]
            structure = f"Array[{len(data)}]"
            if data and isinstance(data[0], dict):
                fields = list(data[0].keys())
                structure += f" with fields: {fields}"
        elif isinstance(data, dict):
            sample = {k: v for k, v in list(data.items())[:3]}
            structure = f"Object with keys: {list(data.keys())}"
        else:
            sample = data
            structure = type(data).__name__

        return json.dumps({"structure": structure, "sample": sample}, indent=2, default=str)
    except Exception as e:
        return f"Parse Error: {e}"
