"""No duplicate class/function names within a test module.

Python shadowing: a second ``class X`` (or ``def test_x``) in the same
module silently replaces the first binding, so pytest only collects
the LAST definition — the earlier tests never run and never fail.
Batch-4 of tests/00_e2e_acceptance_test.py re-declared 6 claim classes
this way; 13 original tests silently did not run for weeks (fixed in
2c8e946c). This gate scans every test module's top level.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _top_level_duplicates(tree: ast.Module) -> list[str]:
    class_names = [n.name for n in tree.body if isinstance(n, ast.ClassDef)]
    func_names = [
        n.name
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name.startswith("test_")
    ]
    dups = {n for n in class_names if class_names.count(n) > 1}
    dups |= {n for n in func_names if func_names.count(n) > 1}
    return sorted(dups)


def test_no_shadowed_test_definitions():
    offenders: dict[str, list[str]] = {}
    for path in sorted((REPO / "tests").rglob("test_*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue  # other gates own syntax validity
        dups = _top_level_duplicates(tree)
        if dups:
            offenders[str(path.relative_to(REPO))] = dups

    assert not offenders, (
        "duplicate top-level test definitions — the earlier copy is shadowed "
        f"and silently never runs: {offenders}"
    )
