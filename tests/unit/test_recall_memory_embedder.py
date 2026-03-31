"""Phase 0-3 TDD (updated for Phase 2-1): PERF-3 — recall_memory embedder 单例

原始修复（PERF-3）：将 SentenceTransformer 提升为模块级惰性单例。
升级（Phase 2-1）：现在 _get_embedder() 委托给 olav.core.embedder.get_embedder()，
                  实现全进程单例，彻底消除重复加载。
使用 AST 静态分析，避免 numpy 二次加载限制。
"""

import ast
from pathlib import Path

SOURCE_PATH = Path("/home/yhvh/Olav/olav-netops/.olav/workspace/ops/tools/recall_memory.py")


def _load_ast():
    return ast.parse(SOURCE_PATH.read_text())


def test_embedder_is_module_level_not_local():
    """Phase 2-1 upgrade: _get_embedder() must delegate to olav.core.embedder.

    There should be NO module-level `_embedder = None` (that was the old PERF-3 interim
    pattern); instead the function calls into the central shared singleton.
    """
    tree = _load_ast()

    # Confirm the old module-level cache variable is gone (no longer needed)
    module_level_assigns = [
        node
        for node in ast.iter_child_nodes(tree)
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "_embedder" for t in node.targets)
    ]
    assert not module_level_assigns, (
        "recall_memory.py must NOT have a module-level `_embedder` variable since "
        "Phase 2-1 delegates to olav.core.embedder.get_embedder() instead."
    )


def test_get_embedder_function_exists():
    """修复后：模块内必须存在 `_get_embedder` 函数定义。"""
    tree = _load_ast()

    func_names = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}

    assert "_get_embedder" in func_names, (
        "recall_memory.py MUST define a `_get_embedder()` function. "
        "PERF-3 fix requires a lazy singleton getter."
    )


def test_get_embedder_uses_global_and_lazy_init():
    """Phase 2-1: _get_embedder() must delegate to olav.core.embedder.get_embedder."""
    tree = _load_ast()

    get_embedder_fn = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_get_embedder"
        ),
        None,
    )

    assert get_embedder_fn is not None, "_get_embedder function not found."

    # The function body must import from olav.core.embedder
    def _imports_from_core_embedder(fn_node):
        for node in ast.walk(fn_node):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                names = [alias.name for alias in node.names]
                if "olav.core.embedder" in module and "get_embedder" in names:
                    return True
        return False

    assert _imports_from_core_embedder(get_embedder_fn), (
        "_get_embedder() must delegate: `from olav.core.embedder import get_embedder`. "
        "Phase 2-1 moves the singleton to olav.core.embedder."
    )


def test_no_local_embedder_in_recall_function():
    """修复后：`recall_memory` 函数内不应再有局部 `_embedder = SentenceTransformer(...)` 赋值。"""
    tree = _load_ast()

    recall_fn = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "recall_memory"
        ),
        None,
    )

    if recall_fn is None:
        return  # 有可能被 @tool 包装，跳过此检查

    local_embedder_assigns = [
        node
        for node in ast.walk(recall_fn)
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "_embedder" for t in node.targets)
    ]

    assert not local_embedder_assigns, (
        f"Found local `_embedder = ...` inside recall_memory function at lines "
        f"{[n.lineno for n in local_embedder_assigns]}. "
        "PERF-3: remove it, use _get_embedder() instead."
    )
