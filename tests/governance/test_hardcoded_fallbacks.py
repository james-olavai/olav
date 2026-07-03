"""Pin hardcoded fallback constants that sit outside TIER_DEFAULTS.

These constants are intentional: they fire only when config is completely
unavailable (import failure, missing api.json). The values are documented
choices, not accidents — this test catches accidental drift.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

GUARDRAILS_PY = REPO / "src" / "olav" / "core" / "memory" / "guardrails.py"
API_REQUEST_CORE = (
    REPO / "src" / "olav" / "data" / "workspace" / "core" / "api-query" / "scripts" / "api_request.py"
)
API_REQUEST_SERVICES = (
    REPO / "src" / "olav" / "data" / "workspace" / "services" / "scripts" / "api_request.py"
)
RECALL_SCRIPT = (
    REPO / "src" / "olav" / "data" / "workspace" / "core" / "scripts" / "olav_recall_memory.py"
)
RECALL_TOOL = (
    REPO / "src" / "olav" / "data" / "workspace" / "core" / "tools" / "olav_recall_memory.py"
)


def _load(py: Path, alias: str):
    spec = importlib.util.spec_from_file_location(alias, py)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── GUARDRAIL_TOP_K ────────────────────────────────────────────────────────


def test_guardrail_top_k_pinned():
    """GUARDRAIL_TOP_K = 5 — max constraints injected per invocation.

    This is a fixed policy limit, not tier-driven. Raising it without review
    would bloat every model call with constraint tokens.
    """
    mod = _load(GUARDRAILS_PY, "guardrails_fb")
    assert getattr(mod, "GUARDRAIL_TOP_K", None) == 5, (
        "GUARDRAIL_TOP_K drifted from pinned value of 5"
    )


# ── recall_top_k docstring correctness ────────────────────────────────────


def test_recall_script_docstring_large_tier_is_13():
    """olav_recall_memory (script) docstring must say large=13, not large=3."""
    src = RECALL_SCRIPT.read_text(encoding="utf-8")
    assert "large=13" in src, (
        "recall script docstring says wrong large-tier recall_top_k "
        "(should be 13 per TIER_DEFAULTS, not 3)"
    )
    assert "large=3" not in src, (
        "recall script docstring still contains stale 'large=3'"
    )


def test_recall_tool_docstring_large_tier_is_13():
    """olav_recall_memory (@tool) docstring must say large=13, not large=3."""
    src = RECALL_TOOL.read_text(encoding="utf-8")
    assert "large=13" in src, (
        "recall tool docstring says wrong large-tier recall_top_k "
        "(should be 13 per TIER_DEFAULTS, not 3)"
    )
    assert "large=3" not in src, (
        "recall tool docstring still contains stale 'large=3'"
    )


# ── api_request dual-copy consistency ─────────────────────────────────────


def test_api_request_module_docstring_says_script_not_tool():
    """Both api_request.py copies must identify as 'script', not 'tool'.

    The services copy was historically labelled 'tool' (copy-paste from the
    @tool era). Keeping both as 'script' makes grep and code review reliable.
    """
    for path in (API_REQUEST_CORE, API_REQUEST_SERVICES):
        src = path.read_text(encoding="utf-8")
        first_line = src.split("\n")[1]  # line 2 is the module docstring body
        assert "script" in first_line, (
            f"{path.relative_to(REPO)}: module docstring should say 'script', got: {first_line!r}"
        )
        assert "tool" not in first_line, (
            f"{path.relative_to(REPO)}: module docstring still says 'tool': {first_line!r}"
        )


def test_api_request_both_copies_have_tool_help_pointer():
    """Both api_request copies must advertise tool_help() in the function docstring."""
    for path in (API_REQUEST_CORE, API_REQUEST_SERVICES):
        src = path.read_text(encoding="utf-8")
        assert 'tool_help("api_request")' in src, (
            f"{path.relative_to(REPO)}: missing tool_help() pointer in docstring"
        )


def test_api_request_compact_cap_identical():
    """_COMPACT_LIST_CAP must be the same value in both api_request copies."""
    core_mod = _load(API_REQUEST_CORE, "api_req_core_fb")
    svc_mod = _load(API_REQUEST_SERVICES, "api_req_svc_fb")
    assert core_mod._COMPACT_LIST_CAP == svc_mod._COMPACT_LIST_CAP, (
        f"_COMPACT_LIST_CAP mismatch: core={core_mod._COMPACT_LIST_CAP} "
        f"services={svc_mod._COMPACT_LIST_CAP}"
    )
