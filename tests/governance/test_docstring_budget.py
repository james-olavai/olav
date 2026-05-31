"""ARCH-18 #1: @tool docstrings stay lean (≤ 15 lines).

Pairs with ``tool_help`` (ARCH-19 #C): the prompt only carries a
one-liner per tool, full usage lives behind ``tool_help('<name>')``.
This guard prevents regressions where someone pastes a 40-line
docstring back into the source and blows the small-model context.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests.governance._paths import NETOPS_TOOLS

REPO = Path(__file__).resolve().parents[2]

# Tools we've explicitly trimmed in round 8. New @tool decorated functions
# outside this set should also land ≤ the budget when added.
#
# Budget set at 20 lines (headroom over the typical trimmed-tool docstring
# of 15-17 lines). The original unmaintained state was 28-43 lines per
# tool — this guard catches gradual bloat without demanding pixel-perfect
# trim on every edit.
_BUDGET_LINES = 20

_TOOL_FILES = [
    REPO / ".olav" / "workspace" / "core" / "tools" / "execute_sql.py",
    REPO / ".olav" / "workspace" / "core" / "tools" / "recall_memory.py",
    REPO / ".olav" / "workspace" / "core" / "tools" / "format_and_export.py",
    REPO / ".olav" / "workspace" / "core" / "api_query" / "scripts" / "api_request.py",
    NETOPS_TOOLS / "diff_configs.py",
    NETOPS_TOOLS / "take_snapshot.py",
    NETOPS_TOOLS / "execute_cli_parallel.py",
]


def _tool_docstrings(path: Path) -> dict[str, int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: dict[str, int] = {}
    stem = path.stem
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        # Accept @tool-decorated functions OR the stem-named/main plain function.
        # Scripts (post tools→scripts migration) use plain functions without
        # @tool; tools/ versions use @tool decorator.
        has_tool = any(
            (isinstance(d, ast.Name) and d.id == "tool")
            or (isinstance(d, ast.Attribute) and d.attr == "tool")
            for d in node.decorator_list
        )
        is_plain_entry = not node.decorator_list and node.name in (stem, "main")
        if not (has_tool or is_plain_entry):
            continue
        doc = ast.get_docstring(node) or ""
        out[node.name] = len(doc.splitlines())
    return out


def test_every_tool_docstring_within_budget():
    over_budget: list[str] = []
    for path in _TOOL_FILES:
        docstrings = _tool_docstrings(path)
        assert docstrings, f"No @tool functions found in {path} — wrong file?"
        for name, lines in docstrings.items():
            if lines > _BUDGET_LINES:
                over_budget.append(
                    f"{path.relative_to(REPO)}::{name} — {lines} lines (budget {_BUDGET_LINES})"
                )
    assert not over_budget, (
        "One or more @tool docstrings exceed the small-model budget. "
        "Move detail to `tool_help('<name>')`:\n" + "\n".join(over_budget)
    )


def test_each_tool_advertises_tool_help_pointer():
    """Every trimmed docstring should hand readers off to tool_help()."""
    missing: list[str] = []
    for path in _TOOL_FILES:
        if path.name == "diff_configs.py":
            # Wrapper module delegates to shared netops core implementation.
            continue
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        stem = path.stem
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            has_tool = any(
                (isinstance(d, ast.Name) and d.id == "tool")
                or (isinstance(d, ast.Attribute) and d.attr == "tool")
                for d in node.decorator_list
            )
            # Scripts (post migration) use a stem-named plain function as
            # the entry point; @tool versions use the decorator.
            # Exclude `main` helper dispatchers from the tool_help requirement
            # since those are internal subprocess wrappers, not LLM-facing tools.
            is_plain_entry = not node.decorator_list and node.name == stem
            if not (has_tool or is_plain_entry):
                continue
            doc = ast.get_docstring(node) or ""
            if "tool_help" not in doc:
                missing.append(f"{path.relative_to(REPO)}::{node.name}")
    assert not missing, (
        "Trimmed docstrings must reference tool_help so the LLM knows where "
        "to fetch full docs:\n" + "\n".join(missing)
    )
