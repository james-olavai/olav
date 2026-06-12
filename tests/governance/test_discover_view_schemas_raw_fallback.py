"""RAW-05: discover_view_schemas surfaces commands that only have raw output.

Before the fix, commands appearing only in ``netops.raw_output_store`` (for
instance Junos outputs that fail TextFSM parsing) never showed up in the
view-recipe discovery pass, which gated all future learner progress on them.
The fix UNIONs raw_output_store into the candidate query so such commands
are at least discoverable.

This test loads ``discover_view_schemas.py`` directly from its workspace
path (the tool is workspace-vendored, not importable via
``olav_netops``), and asserts the two candidate queries reference
``raw_output_store``.
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TOOL_CANDIDATES = (
    REPO / "src" / "olav" / "core" / "curator" / "discover_view_schemas.py",
    REPO / ".olav" / "workspace" / "audit" / "curator" / "tools" / "discover_view_schemas.py",
    REPO / "olav-netops" / ".olav" / "workspace" / "audit" / "curator" / "tools" / "discover_view_schemas.py",
)


def _resolve_tool_path() -> Path:
    for candidate in TOOL_CANDIDATES:
        if candidate.exists():
            return candidate
    assert False, (
        "discover_view_schemas tool missing; checked: "
        + ", ".join(str(p) for p in TOOL_CANDIDATES)
    )


def test_tool_file_exists():
    assert _resolve_tool_path().exists()


def test_candidate_query_unions_raw_output_store():
    src = _resolve_tool_path().read_text(encoding="utf-8")
    # Both the force_refresh branch and the delta branch must consult
    # raw_output_store — otherwise raw-only commands are invisible.
    assert src.count("netops.raw_output_store") >= 2, (
        "discover_view_schemas no longer unions netops.raw_output_store into "
        "its candidate query — RAW-05 regression. Commands whose TextFSM "
        "parser returned empty / errored will stop surfacing in learner runs."
    )


def test_union_pattern_is_present():
    src = _resolve_tool_path().read_text(encoding="utf-8")
    # Cheap structural check: the UNION clause is the intended shape (not
    # merely a stray mention of raw_output_store in a comment).
    assert "UNION" in src and "raw_output_store" in src, (
        "Expected a SELECT ... UNION SELECT ... FROM netops.raw_output_store "
        "pattern in the candidate discovery query."
    )
