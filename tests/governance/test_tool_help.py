"""ARCH-19 #C: ``tool_help`` returns full docs for a named tool.

This is a small-model aid — the system prompt carries one-line
descriptions and agents look up full schemas on demand. The tool is
workspace-vendored, so we load it the same way the discovery pipeline
does instead of importing via a package path.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
# v0.11.0: tool_help.py moved from core/admin/tools/ to admin/developer/tools/
# post-R-AGENT-HIERARCHY: admin/developer/ split into admin/installer/ + admin/editor/
# scripts-化: moved from tools/ to scripts/
TOOL_PY = REPO / ".olav" / "workspace" / "admin" / "editor" / "scripts" / "tool_help.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("tool_help_under_test", TOOL_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _invoke(mod, name: str) -> dict:
    # LangChain wraps the callable; invoke via its .invoke API when present,
    # otherwise call the underlying function directly.
    tool_obj = mod.tool_help
    if hasattr(tool_obj, "invoke"):
        return tool_obj.invoke({"name": name})
    return tool_obj(name)


def test_tool_file_exists():
    assert TOOL_PY.exists(), f"tool_help.py missing at {TOOL_PY}"


def test_tool_help_describes_itself():
    mod = _load_module()
    result = _invoke(mod, "tool_help")
    assert result.get("name") == "tool_help"
    assert "description" in result and result["description"]
    assert isinstance(result.get("args"), list)
    # The single `name` arg must be present and marked required.
    arg_names = {a["name"] for a in result["args"]}
    assert "name" in arg_names
    name_arg = next(a for a in result["args"] if a["name"] == "name")
    assert name_arg["required"] is True


def test_tool_help_unknown_returns_error_with_available_list():
    mod = _load_module()
    result = _invoke(mod, "definitely_not_a_real_tool_xyz")
    assert "error" in result
    # The error payload must list what *is* discoverable so the caller can
    # self-correct without a second round-trip.
    assert isinstance(result.get("available"), list)
    assert "tool_help" in result["available"], (
        f"tool_help should self-register in the available list: {result['available'][:10]}"
    )


def test_tool_help_rejects_empty_name():
    mod = _load_module()
    assert "error" in _invoke(mod, "")
