"""Round 38 — progressive-disclosure batch:

* ARCH-17 close: ``load_reference(name, section=)`` slices by ``##`` header
* ARCH-19 #C: ``tool_help(name, detail=)`` tier-aware; brief drops full_docstring

Both tools live under ``.olav/workspace/admin/editor/tools/`` (v0.11.0:
core/admin dissolved; previously ``.olav/workspace/core/admin/tools/``) and
are loaded the same way :mod:`olav.core.tool_discovery` does —
``importlib.util.spec_from_file_location`` so they don't collide with
the packaged fixtures.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LOAD_REFERENCE_PY = REPO / ".olav" / "workspace" / "admin" / "editor" / "scripts" / "load_reference.py"
TOOL_HELP_PY = REPO / ".olav" / "workspace" / "admin" / "editor" / "scripts" / "tool_help.py"
REFS_DIR = REPO / ".olav" / "workspace" / "core" / "references"


def _load(py: Path, alias: str):
    spec = importlib.util.spec_from_file_location(alias, py)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _invoke(tool_obj, **kwargs):
    if hasattr(tool_obj, "invoke"):
        return tool_obj.invoke(kwargs)
    return tool_obj(**kwargs)


# ── load_reference section slicing ──────────────────────────────────────


def test_load_reference_file_exists():
    assert LOAD_REFERENCE_PY.exists()


def _param_names(fn):
    """Return parameter names for @tool (args_schema) or plain function (inspect)."""
    import inspect as _ins
    schema = getattr(fn, "args_schema", None)
    if schema is not None:
        fields = getattr(schema, "model_fields", None) or getattr(schema, "__fields__", {})
        return set(fields)
    return set(_ins.signature(fn).parameters)


def test_load_reference_has_section_param():
    """The function signature must expose the new ``section`` kwarg."""
    mod = _load(LOAD_REFERENCE_PY, "load_reference_u1")
    params = _param_names(mod.load_reference)
    assert "section" in params, (
        f"load_reference missing 'section' kwarg; found: {sorted(params)}"
    )


def test_load_reference_no_section_returns_full_file():
    mod = _load(LOAD_REFERENCE_PY, "load_reference_u2")
    result = _invoke(mod.load_reference, name="schema")
    # The full file contains all H2 headings.
    assert "## 🗄️ netops.* Tables (the data plane)" in result
    assert "## 💡 Verified SQL Examples" in result
    assert "## ⛔ Common SQL mistakes (and the right form)" in result


def test_load_reference_section_slices_one_header():
    mod = _load(LOAD_REFERENCE_PY, "load_reference_u3")
    result = _invoke(mod.load_reference, name="schema", section="common sql mistakes")
    assert "Common SQL mistakes" in result
    # Must NOT include the neighbouring sections.
    assert "Core Table & View Schema" not in result
    assert "Verified SQL Examples" not in result


def test_load_reference_section_question_mark_lists_sections():
    mod = _load(LOAD_REFERENCE_PY, "load_reference_u4")
    result = _invoke(mod.load_reference, name="schema", section="?")
    assert "Available sections in 'schema'" in result
    assert "netops.* Tables (the data plane)" in result
    assert "Verified SQL Examples" in result


def test_load_reference_unknown_section_lists_available():
    mod = _load(LOAD_REFERENCE_PY, "load_reference_u5")
    result = _invoke(
        mod.load_reference, name="schema", section="nonexistent_section_xyz"
    )
    assert "not found" in result.lower()
    assert "Available sections" in result
    assert "netops.* Tables (the data plane)" in result


def test_load_reference_unknown_name_still_clean():
    mod = _load(LOAD_REFERENCE_PY, "load_reference_u6")
    result = _invoke(mod.load_reference, name="definitely_not_a_ref")
    assert "not found" in result.lower()
    # available list enumerates the 7 valid refs.
    for key in ("mermaid", "schema", "skill_dev"):
        assert key in result


def test_load_reference_section_matches_case_insensitive():
    mod = _load(LOAD_REFERENCE_PY, "load_reference_u7")
    a = _invoke(mod.load_reference, name="schema", section="NETOPS TABLES")
    b = _invoke(mod.load_reference, name="schema", section="netops tables")
    # Both must hit the same section.
    assert "netops.* Tables (the data plane)" in a
    assert "netops.* Tables (the data plane)" in b


# ── tool_help tier-aware detail ────────────────────────────────────────


def test_tool_help_has_detail_param():
    mod = _load(TOOL_HELP_PY, "tool_help_u1")
    params = _param_names(mod.tool_help)
    assert "detail" in params, (
        f"tool_help missing 'detail' kwarg; found: {sorted(params)}"
    )


def test_tool_help_brief_drops_full_docstring():
    mod = _load(TOOL_HELP_PY, "tool_help_u2")
    result = _invoke(mod.tool_help, name="tool_help", detail="brief")
    assert result.get("name") == "tool_help"
    assert "full_docstring" not in result, (
        "brief mode must not include full_docstring (defeats the ARCH-19 #C "
        "token-saving purpose)"
    )
    assert result.get("_detail") == "brief"


def test_tool_help_full_keeps_full_docstring():
    mod = _load(TOOL_HELP_PY, "tool_help_u3")
    result = _invoke(mod.tool_help, name="tool_help", detail="full")
    assert "full_docstring" in result
    assert result["full_docstring"], "full_docstring must be populated in full mode"
    assert result.get("_detail") == "full"


def test_tool_help_invalid_detail_falls_back_to_auto():
    """Bogus ``detail`` values must not raise — fall back to tier resolution."""
    mod = _load(TOOL_HELP_PY, "tool_help_u4")
    result = _invoke(mod.tool_help, name="tool_help", detail="bogus_value")
    assert result.get("_detail") in {"brief", "full"}


def test_tool_help_default_still_tier_driven():
    """Omitting ``detail`` must resolve to one of the two valid modes — we
    don't care which (depends on deployment tier), only that it's present
    and one of the documented levels."""
    mod = _load(TOOL_HELP_PY, "tool_help_u5")
    result = _invoke(mod.tool_help, name="tool_help")
    assert result.get("_detail") in {"brief", "full"}


def test_tool_help_resolve_detail_helper_exists():
    """Pin the internal helper name so the switchboard stays discoverable."""
    mod = _load(TOOL_HELP_PY, "tool_help_u6")
    assert hasattr(mod, "_resolve_detail")
    assert hasattr(mod, "_VALID_DETAIL")
    assert mod._VALID_DETAIL == frozenset({"brief", "full"})
