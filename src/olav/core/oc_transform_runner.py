"""OC Transform Sandbox — execute LLM-generated transform functions safely.

LLM generates a Python function ``transform(records: list[dict]) -> dict``
that converts flat TextFSM records into an OpenConfig JSON dict.  This module
validates the code via AST inspection and executes it in a restricted namespace.

Public API:
    validate_ast(code)           — raise ValueError if unsafe constructs found
    run_transform(code, records) — execute safely, return OC dict
"""
from __future__ import annotations

import ast
import concurrent.futures
import re as _re
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Allowed and blocked names in generated code
# ---------------------------------------------------------------------------

_BLOCKED_CALLS: frozenset[str] = frozenset({
    "exec", "eval", "open", "__import__", "compile",
    "globals", "locals", "vars", "getattr", "setattr", "delattr",
    "breakpoint", "input",
})

_SAFE_BUILTINS: dict[str, Any] = {
    name: getattr(__builtins__, name, None) or __builtins__.get(name)  # type: ignore[union-attr]
    for name in (
        "len", "int", "str", "float", "bool",
        "list", "dict", "tuple", "set", "frozenset",
        "isinstance", "issubclass",
        "enumerate", "zip", "range",
        "sorted", "reversed", "map", "filter",
        "min", "max", "sum", "any", "all",
        "abs", "round", "divmod",
        "repr", "type",
        "print",  # useful for LLM debugging; harmless in sandbox
        "ValueError", "TypeError", "KeyError", "IndexError", "Exception",
    )
    if (getattr(__builtins__, name, None) or
        (isinstance(__builtins__, dict) and name in __builtins__))
}

# Resolve builtins regardless of whether __builtins__ is a dict or module
import builtins as _builtins_mod
_SAFE_BUILTINS = {name: getattr(_builtins_mod, name) for name in (
    "len", "int", "str", "float", "bool",
    "list", "dict", "tuple", "set", "frozenset",
    "isinstance", "issubclass",
    "enumerate", "zip", "range",
    "sorted", "reversed", "map", "filter",
    "min", "max", "sum", "any", "all",
    "abs", "round", "divmod",
    "repr", "type",
    "print",
    "ValueError", "TypeError", "KeyError", "IndexError", "Exception",
) if hasattr(_builtins_mod, name)}


# ---------------------------------------------------------------------------
# AST validation
# ---------------------------------------------------------------------------

def validate_ast(code: str) -> None:
    """Parse and walk the AST; raise ValueError on unsafe constructs.

    Blocked:
    - ``import`` / ``from X import`` statements
    - Calls to dangerous builtins (exec, eval, open, etc.)
    - ``__dunder__`` attribute access
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise ValueError(f"syntax error in generated code: {exc}") from exc

    for node in ast.walk(tree):
        # No imports
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise ValueError("import statements are not allowed in transform code")

        # No blocked builtin calls
        if isinstance(node, ast.Call):
            func = node.func
            name = None
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            if name and name in _BLOCKED_CALLS:
                raise ValueError(f"call to '{name}' is not allowed in transform code")

        # No dunder attribute access
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("__") and node.attr.endswith("__"):
                raise ValueError(
                    f"dunder attribute access '{node.attr}' is not allowed"
                )


# ---------------------------------------------------------------------------
# Sandbox executor
# ---------------------------------------------------------------------------

def run_transform(
    code: str,
    records: list[dict[str, Any]],
    timeout_secs: int = 5,
) -> dict[str, Any]:
    """Execute a sandboxed transform function.

    Args:
        code:         Python source defining ``transform(records) -> dict``.
        records:      Flat TextFSM dicts from parsed_outputs.
        timeout_secs: Hard timeout; raises TimeoutError if exceeded.

    Returns:
        OC JSON dict produced by the transform function.

    Raises:
        ValueError:   AST validation failure or function not defined.
        TimeoutError: Function exceeded timeout_secs.
        RuntimeError: Function raised an exception during execution.
    """
    validate_ast(code)

    namespace: dict[str, Any] = {
        "__builtins__": _SAFE_BUILTINS,
        "re": _re,
    }

    try:
        exec(code, namespace)  # noqa: S102 — intentional sandboxed exec
    except Exception as exc:
        raise RuntimeError(f"code failed during exec: {exc}") from exc

    transform_fn = namespace.get("transform")
    if not callable(transform_fn):
        raise ValueError("generated code must define a callable 'transform(records)' function")

    def _call() -> dict[str, Any]:
        try:
            return transform_fn(records)
        except Exception as exc:
            raise RuntimeError(f"transform raised: {exc}") from exc

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(_call)
    try:
        result = future.result(timeout=timeout_secs)
    except concurrent.futures.TimeoutError:
        # Do NOT wait for the stuck thread — let it die as a daemon
        executor.shutdown(wait=False, cancel_futures=True)
        raise TimeoutError(
            f"transform function exceeded {timeout_secs}s timeout"
        )
    finally:
        executor.shutdown(wait=False)

    if not isinstance(result, dict):
        raise ValueError(
            f"transform must return dict, got {type(result).__name__}"
        )

    return result
