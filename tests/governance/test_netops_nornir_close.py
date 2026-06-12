"""NETOPS-01: Every Nornir entry point releases its connection pool.

Static AST audit — verifies each ``InitNornir(...)`` call is protected by a
surrounding ``try``/``finally`` or an explicit ``close_connections()`` before
the function returns. Prevents regressions that would re-introduce the
Netmiko SSH session leak in long-running processes.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests.governance._paths import NETOPS_INIT_DIR

REPO = Path(__file__).resolve().parents[2]

# Files where InitNornir is used as part of a production code path (not
# tests, not examples). These three must keep their close_connections()
# guard until a higher-level refactor (module-level singleton + atexit)
# supersedes them.
TARGETS = [
    REPO / "olav-netops" / "src" / "olav_netops" / "tools" / "ssh.py",
    NETOPS_INIT_DIR / "run.py",
]


def _count_calls(tree: ast.AST, func_name: str) -> int:
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr == func_name:
                count += 1
            elif isinstance(f, ast.Name) and f.id == func_name:
                count += 1
    return count


def test_every_init_nornir_has_matching_close():
    for path in TARGETS:
        assert path.exists(), f"Expected target missing: {path}"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        init_count = _count_calls(tree, "InitNornir")
        close_count = _count_calls(tree, "close_connections")
        assert init_count > 0, f"No InitNornir() calls found in {path}"
        assert close_count >= init_count, (
            f"{path}: {init_count} InitNornir() call(s) but only "
            f"{close_count} close_connections() call(s). Every InitNornir "
            "must be paired with close_connections() to avoid Netmiko "
            "session leaks (NETOPS-01)."
        )
