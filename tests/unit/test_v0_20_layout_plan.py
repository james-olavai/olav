"""
tests/unit/test_v0_20_layout_plan.py
────────────────────────────────────
Unit coverage for :mod:`olav.migrate.v0_20_layout` — the pure-read
migration planner.

Phase B (v0.20.2) cycle 1: plan_migration() scans a workspace root
and returns a declarative description of what would change.  Zero
side effects; dry-run is the primary use case.

Guarantees:
  1. Accepts a fresh (v0.19.x) layout and produces an ordered plan
     (``AGENT.md`` → ``AGENTS.md`` moves; subagent dir → single md
     flattening; workspace dir → .deepagents/agents/ path shift).
  2. Detects already-migrated installs and returns an empty plan
     (idempotence — running twice is safe).
  3. Produces a human-readable summary + machine-readable operations
     list (tests assert on both).
  4. Declines gracefully when the root doesn't look like an OLAV
     workspace at all (bail out with clear error rather than
     touching unrelated dirs).
"""

from __future__ import annotations

from pathlib import Path

import pytest


# ── 1. Module importable ────────────────────────────────────────────────────


def test_module_importable() -> None:
    from olav.migrate import v0_20_layout

    assert hasattr(v0_20_layout, "plan_migration")
    assert hasattr(v0_20_layout, "already_migrated")


# ── 2. Fresh v0.19 layout → detailed plan ──────────────────────────────────


def _make_legacy_workspace(root: Path, *, with_subagent: bool = True) -> None:
    """Create a minimal v0.19.x workspace tree under *root*."""
    ws = root / ".olav" / "workspace"
    for agent in ("core", "ops"):
        d = ws / agent
        d.mkdir(parents=True, exist_ok=True)
        (d / "AGENT.md").write_text(
            f"---\nname: {agent}\n---\n{agent} body\n", encoding="utf-8"
        )
        (d / "MANIFEST.yaml").write_text(
            f"kind: Agent\nname: {agent}\n", encoding="utf-8"
        )
        (d / "tools").mkdir()
        (d / "tools" / "noop.py").write_text("# tool\n", encoding="utf-8")
    # One subagent under core
    if with_subagent:
        sub = ws / "core" / "writer"
        sub.mkdir(parents=True, exist_ok=True)
        (sub / "AGENT.md").write_text(
            "---\nname: writer\ndescription: writes reports\n---\n"
            "Writer body\n",
            encoding="utf-8",
        )


def test_plan_migration_detects_legacy_layout(tmp_path: Path) -> None:
    from olav.migrate.v0_20_layout import plan_migration

    _make_legacy_workspace(tmp_path)
    plan = plan_migration(tmp_path)

    assert plan is not None
    assert len(plan.operations) > 0
    # Expect at least: 2 agents × 1 AGENT.md→AGENTS.md move each,
    # plus 1 subagent flatten.  Tests don't assert exact count
    # because the planner may emit extra "create parent dir" ops.
    kinds = {op.kind for op in plan.operations}
    assert "rename_agent_md" in kinds
    assert "flatten_subagent" in kinds


def test_plan_agent_moves_are_well_formed(tmp_path: Path) -> None:
    from olav.migrate.v0_20_layout import plan_migration

    _make_legacy_workspace(tmp_path, with_subagent=False)
    plan = plan_migration(tmp_path)

    rename_ops = [op for op in plan.operations if op.kind == "rename_agent_md"]
    assert len(rename_ops) == 2  # core + ops

    for op in rename_ops:
        # Source exists (validated pre-flight)
        assert op.source.name == "AGENT.md"
        assert op.source.exists()
        # Target is in the new tree under .deepagents/agents/<n>/
        assert ".deepagents" in op.target.parts
        assert op.target.name == "AGENTS.md"
        # Target parent matches expected structure
        assert op.target.parent.parent.name == "agents"


def test_plan_subagent_flatten(tmp_path: Path) -> None:
    from olav.migrate.v0_20_layout import plan_migration

    _make_legacy_workspace(tmp_path)
    plan = plan_migration(tmp_path)

    flatten_ops = [op for op in plan.operations if op.kind == "flatten_subagent"]
    # writer is the only subagent
    assert len(flatten_ops) == 1
    op = flatten_ops[0]
    # .olav/workspace/core/writer/AGENT.md → .deepagents/agents/core/agents/writer.md
    assert op.source.parts[-2] == "writer"
    assert op.source.name == "AGENT.md"
    assert op.target.parts[-2] == "agents"
    assert op.target.name == "writer.md"


# ── 3. Already-migrated → empty plan ────────────────────────────────────────


def test_plan_already_migrated_returns_empty(tmp_path: Path) -> None:
    """An install that's already on the new layout should produce
    no operations — idempotent safety."""
    from olav.migrate.v0_20_layout import already_migrated, plan_migration

    # Create the new-layout tree directly
    new = tmp_path / ".deepagents" / "agents" / "core"
    new.mkdir(parents=True, exist_ok=True)
    (new / "AGENTS.md").write_text("---\nname: core\n---\nbody\n", encoding="utf-8")

    assert already_migrated(tmp_path) is True
    plan = plan_migration(tmp_path)
    assert plan.operations == []


def test_plan_both_layouts_present_prefers_idempotent(tmp_path: Path) -> None:
    """If both old + new layouts coexist (partial migration from a
    prior crash), plan_migration must not double-rename.  Treats
    new layout as authoritative."""
    from olav.migrate.v0_20_layout import plan_migration

    _make_legacy_workspace(tmp_path, with_subagent=False)
    # Also create new layout
    new = tmp_path / ".deepagents" / "agents" / "core"
    new.mkdir(parents=True, exist_ok=True)
    (new / "AGENTS.md").write_text("---\n", encoding="utf-8")

    plan = plan_migration(tmp_path)

    # Should NOT emit rename for core (already in new layout)
    rename_ops = [
        op
        for op in plan.operations
        if op.kind == "rename_agent_md" and op.source.parts[-2] == "core"
    ]
    assert rename_ops == []


# ── 4. Missing workspace → clean error ─────────────────────────────────────


def test_plan_missing_workspace_returns_empty_plan(tmp_path: Path) -> None:
    """Directory that isn't an OLAV install → return empty plan
    rather than raising — CLI layer can decide whether to warn."""
    from olav.migrate.v0_20_layout import plan_migration

    plan = plan_migration(tmp_path)
    assert plan.operations == []


# ── 5. Summary is human-readable ───────────────────────────────────────────


def test_plan_summary_mentions_change_counts(tmp_path: Path) -> None:
    from olav.migrate.v0_20_layout import plan_migration

    _make_legacy_workspace(tmp_path)
    plan = plan_migration(tmp_path)

    summary = plan.summary()
    assert isinstance(summary, str)
    # Must mention the number of agents touched + subagents flattened
    assert "agent" in summary.lower()
    # Non-empty
    assert len(summary.strip()) > 0


def test_plan_is_jsonable(tmp_path: Path) -> None:
    """The plan must serialise to JSON so CLI --dry-run can print it
    machine-readably."""
    import json

    from olav.migrate.v0_20_layout import plan_migration

    _make_legacy_workspace(tmp_path)
    plan = plan_migration(tmp_path)

    as_dict = plan.as_dict()
    # Must round-trip through JSON without crashing
    encoded = json.dumps(as_dict, default=str)
    decoded = json.loads(encoded)
    assert "operations" in decoded
    assert isinstance(decoded["operations"], list)
