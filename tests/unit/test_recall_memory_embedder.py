"""Phase 0-3 TDD (updated rev 100): olav_recall_memory embedder function

Original fix (PERF-3): SentenceTransformer lazy singleton.
Phase 2-1: _get_embedder() delegated to olav.core.embedder.get_embedder().
Rev 98: renamed to _embed_query() — calls embed_text() (OpenAI API, same as kb_import).
Uses AST static analysis to avoid numpy secondary-load restrictions.
"""

import ast
from pathlib import Path

SOURCE_PATH = Path(__file__).resolve().parents[2] / "src/olav/data/workspace/core/tools/olav_recall_memory.py"


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
        "olav_recall_memory.py must NOT have a module-level `_embedder` variable since "
        "Phase 2-1 delegates to olav.core.embedder.get_embedder() instead."
    )


def test_embed_query_function_exists():
    """Rev 98: module must define `_embed_query` (renamed from _get_embedder)."""
    tree = _load_ast()

    func_names = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}

    assert "_embed_query" in func_names, (
        "olav_recall_memory.py MUST define a `_embed_query()` function. "
        "Rev 98 renamed _get_embedder → _embed_query to call embed_text() (OpenAI API)."
    )


def test_embed_query_calls_embed_text():
    """Rev 98: _embed_query() must call embed_text from olav.core.embedder (not get_embedder)."""
    tree = _load_ast()

    embed_query_fn = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_embed_query"
        ),
        None,
    )

    assert embed_query_fn is not None, "_embed_query function not found."

    # The function body must import embed_text from olav.core.embedder
    def _imports_embed_text(fn_node):
        for node in ast.walk(fn_node):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                names = [alias.name for alias in node.names]
                if "olav.core.embedder" in module and "embed_text" in names:
                    return True
        return False

    assert _imports_embed_text(embed_query_fn), (
        "_embed_query() must call: `from olav.core.embedder import embed_text`. "
        "Rev 98 uses embed_text() (OpenAI API) instead of get_embedder() (SentenceTransformer)."
    )


def test_no_local_embedder_in_recall_function():
    """修复后：`olav_recall_memory` 函数内不应再有局部 `_embedder = SentenceTransformer(...)` 赋值。"""
    tree = _load_ast()

    recall_fn = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "olav_recall_memory"
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
        f"Found local `_embedder = ...` inside olav_recall_memory function at lines "
        f"{[n.lineno for n in local_embedder_assigns]}. "
        "PERF-3: remove it, use _get_embedder() instead."
    )
