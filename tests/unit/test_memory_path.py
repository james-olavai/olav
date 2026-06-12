"""Phase 0-1 TDD: BUG-1 — LanceDB 路径双轨隔离

预期：修复前 Red（路径不一致），修复后 Green。
"""
from pathlib import Path

from olav.core.memory import DEFAULT_MEMORY_DB


def test_lancedb_path_consistent(tmp_path):
    """LangGraphLanceDBStore 使用的路径必须与 DEFAULT_MEMORY_DB 格式一致。

    具体规则：两者结尾的数据库目录名必须相同（均为 memory.lance）。
    """
    from olav.core.memory.langgraph_adapter import LangGraphLanceDBStore

    db_path = tmp_path / "databases" / "memory.lance"
    store = LangGraphLanceDBStore(db_path=str(db_path))

    # DEFAULT_MEMORY_DB 的目录名
    default_db_name = Path(DEFAULT_MEMORY_DB).name  # "memory.lance"
    # store 实际使用的路径目录名
    actual_db_name = Path(store._store.db_path).name

    assert actual_db_name == default_db_name, (
        f"Path mismatch: store uses '{actual_db_name}', "
        f"DEFAULT_MEMORY_DB expects '{default_db_name}'. "
        "Fix: align agents/agent.py L199 to use 'memory.lance'."
    )


def test_agent_uses_default_memory_db_name(tmp_path, monkeypatch):
    """OLAVAgent 初始化时，LanceDB 路径的目录名与 DEFAULT_MEMORY_DB 一致。"""
    # 只测路径名对齐，不真实初始化整个 agent（避免需要 LLM）
    # 直接检查 agent.py 的构造逻辑中硬编码的字符串
    import ast
    import inspect

    from olav.agents import agent as agent_module

    source = inspect.getsource(agent_module)
    tree = ast.parse(source)

    # 查找 "memory.lancedb" 字符串常量（旧的错误路径）
    bad_paths = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if "memory.lancedb" in node.value:
                bad_paths.append(node.value)

    assert not bad_paths, (
        f"Found 'memory.lancedb' (wrong path) in agent.py: {bad_paths}. "
        "Should be 'memory.lance' to match DEFAULT_MEMORY_DB."
    )
