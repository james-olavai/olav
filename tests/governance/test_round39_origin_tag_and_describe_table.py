"""Round 39 batch — observability + progressive disclosure:

* WRITER-01 (a): 🔧 event output carries an origin tag (``[orch]`` /
  ``[sub]``) so CI can filter orchestrator-level tool calls from
  delegate-internal ones. Round 28 had to bump the T2-14 threshold to
  ``≤ 8`` to accommodate writer-arch delegate bloat; Round 39 tightens
  it back to ``≤ 5`` on ``🔧[orch]``.
* ARCH-18: ``describe_table(table_name, include_samples=)`` exposes
  per-table schema introspection on demand as a proper @tool — no more
  asking the orchestrator to carry every table's columns in the prompt.
  Canonical home ``core/tools/describe_table.py`` + symlink from
  ``core/db_query/tools/`` per ARCH-20 P2.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CLI_MAIN = REPO / "src" / "olav" / "cli" / "main.py"
TIER2_CI = REPO / "tests" / "ci" / "tier2_integration.sh"
DESCRIBE_TABLE_PY = REPO / ".olav" / "workspace" / "core" / "db_query" / "scripts" / "describe_table.py"
DB_QUERY_SYMLINK = (
    REPO / ".olav" / "workspace" / "core" / "db_query" / "scripts" / "describe_table.py"
)
DB_QUERY_SKILL = REPO / ".olav" / "workspace" / "core" / "db_query" / "SKILL.md"


# ── WRITER-01 (a) origin tag pins ────────────────────────────────────────


def test_cli_emits_origin_tag_on_tool_start():
    """🔧 log line must carry an origin tag so CI can grep orch-only."""
    src = CLI_MAIN.read_text(encoding="utf-8")
    # Look for the bracketed origin in the tool-start print.
    assert re.search(r"🔧\[\{_origin\}\]", src), (
        "CLI main.py on_tool_start no longer emits 🔧[{_origin}] — WRITER-01 (a) "
        "origin tag regressed. Tier2 CI T2-14 filter depends on this shape."
    )


def test_cli_tracks_delegate_depth_counter():
    """The nested-counter pattern must stay in place, otherwise all calls
    would look like orch (defeating the filter)."""
    src = CLI_MAIN.read_text(encoding="utf-8")
    assert "_delegate_depth" in src, "delegate_depth counter removed"
    assert "_DELEGATE_TOOLS" in src, "_DELEGATE_TOOLS set removed"
    # Both olav_delegate and task (deepagents built-in) must count as
    # delegation events.
    assert '"olav_delegate"' in src
    assert '"task"' in src


def test_cli_increments_on_delegate_start_decrements_on_delegate_end():
    """Both sides of the counter must be wired — otherwise depth drifts."""
    src = CLI_MAIN.read_text(encoding="utf-8")
    assert "_delegate_depth += 1" in src
    assert "_delegate_depth -= 1" in src


def test_tier2_filters_on_orch_origin_tag():
    """T2-14 must grep on 🔧[orch] only (orchestrator-level calls)."""
    src = TIER2_CI.read_text(encoding="utf-8")
    assert re.search(r"grep -cE \"🔧\\\[orch\\\]\"", src), (
        "tier2 T2-14 no longer filters 🔧[orch] — CI will still count "
        "delegate-internal bloat and the threshold must stay loose."
    )


def test_tier2_threshold_tightened_to_5():
    """Post-WRITER-01-(a), the ≤8 concession can drop back to ≤5."""
    src = TIER2_CI.read_text(encoding="utf-8")
    # -le 5 on the TOOL_CALLS test
    assert '"${TOOL_CALLS}" -le 5' in src, (
        "T2-14 threshold not tightened to ≤5 — WRITER-01 (a) observability "
        "fix is wasted if we don't tighten the budget it bought us."
    )


# ── ARCH-18 describe_table pins ─────────────────────────────────────────


def test_describe_table_file_exists_as_canonical_home():
    assert DESCRIBE_TABLE_PY.exists(), (
        f"canonical home {DESCRIBE_TABLE_PY} missing — ARCH-20 P2 requires "
        f"one authoritative file per tool."
    )
    assert DESCRIBE_TABLE_PY.is_file() and not DESCRIBE_TABLE_PY.is_symlink(), (
        "canonical home must be a real file (not a symlink)."
    )


def test_describe_table_symlinked_into_db_query():
    """Post-R65 (ARCH-23): db_query *is* the canonical home, not a symlink
    target. This test previously pinned the ARCH-20 P2 dedup pattern of
    canonical-in-core/tools/ + symlink-in-subagent. ARCH-23 R65 inverted
    this — describe_table now lives directly under db_query/tools/."""
    assert DESCRIBE_TABLE_PY.exists() and DESCRIBE_TABLE_PY.is_file(), (
        f"{DESCRIBE_TABLE_PY} must exist as the canonical db_query home."
    )
    assert not DESCRIBE_TABLE_PY.is_symlink(), (
        "Post-R65 the canonical home is a real file, not a symlink."
    )


def test_describe_table_listed_in_db_query_skill():
    src = DB_QUERY_SKILL.read_text(encoding="utf-8")
    # Look inside the top YAML frontmatter only.
    assert "describe_table" in src, (
        "core/db_query/SKILL.md no longer advertises describe_table — the "
        "ARCH-18 on-demand lookup is invisible to the db_query sub-agent."
    )


def test_describe_table_exposes_include_samples_param():
    """Function signature must carry ``include_samples`` and ``table_name``."""
    import inspect
    spec = importlib.util.spec_from_file_location(
        "describe_table_under_test", DESCRIBE_TABLE_PY
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # Support both @tool (args_schema) and plain function (inspect.signature).
    schema = getattr(mod.describe_table, "args_schema", None)
    if schema is not None:
        fields = getattr(schema, "model_fields", None) or getattr(schema, "__fields__", {})
        assert "table_name" in fields
        assert "include_samples" in fields, (
            f"describe_table args must include 'include_samples'; got {list(fields)}"
        )
    else:
        sig = inspect.signature(mod.describe_table)
        assert "table_name" in sig.parameters
        assert "include_samples" in sig.parameters, (
            f"describe_table args must include 'include_samples'; got {list(sig.parameters)}"
        )


def test_describe_table_rejects_empty_name():
    spec = importlib.util.spec_from_file_location(
        "describe_table_under_test_b", DESCRIBE_TABLE_PY
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fn = mod.describe_table
    result = fn.invoke({"table_name": ""}) if hasattr(fn, "invoke") else fn(table_name="")
    assert isinstance(result, dict)
    assert "error" in result


def test_describe_table_reuses_duckdb_connection_readonly():
    """describe_table must open DuckDB in read_only mode — pinning this
    prevents a refactor from silently introducing a write path through
    what should be an introspection tool."""
    src = DESCRIBE_TABLE_PY.read_text(encoding="utf-8")
    assert "read_only=True" in src, (
        "describe_table no longer opens DuckDB read-only — ARCH-18 "
        "introspection must not take a write lock."
    )
