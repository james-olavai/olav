"""
tests/integration/test_v0_20_layout_apply.py
────────────────────────────────────────────
Integration coverage for :func:`olav.migrate.v0_20_layout.apply_migration`
(P1 cycle 2).

This is the first filesystem-mutating step in Phase B.  Every test
operates on a ``tmp_path`` tree so no real OLAV install is ever
touched.  Guarantees:

1. A plan produced by :func:`plan_migration` can be applied and
   results in the expected new-layout files.
2. ``backup=True`` (default) produces a tarball at ``.olav.bak/`` so
   users can roll back a bad migration.
3. ``backup=False`` skips backup (CI / deliberate).
4. The original legacy tree is left intact — we *copy*, not move, so
   ``OLAV_V0_20_LAYOUT=legacy`` keeps working until the user runs a
   separate cleanup.
5. Running ``apply_migration`` twice is a no-op (idempotent).
6. Applying an empty plan does nothing and returns a clean result.
"""

from __future__ import annotations

import tarfile
from pathlib import Path

import pytest


def _make_legacy_workspace(root: Path) -> None:
    """Minimal legacy workspace fixture."""
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
    # One subagent under core
    sub = ws / "core" / "writer"
    sub.mkdir(parents=True, exist_ok=True)
    (sub / "AGENT.md").write_text(
        "---\nname: writer\n---\nwriter body\n", encoding="utf-8"
    )


# ── 1. Happy path with backup ──────────────────────────────────────────────


def test_apply_migration_happy_path_with_backup(tmp_path: Path) -> None:
    from olav.migrate.v0_20_layout import apply_migration, plan_migration

    _make_legacy_workspace(tmp_path)

    plan = plan_migration(tmp_path)
    result = apply_migration(plan, backup=True)

    assert result.applied_operations > 0
    assert result.backup_path is not None
    assert result.backup_path.exists()
    assert result.backup_path.suffix in {".tar", ".gz"}  # tar or tar.gz both OK

    # New layout files exist
    assert (tmp_path / ".deepagents" / "agents" / "core" / "AGENTS.md").is_file()
    assert (tmp_path / ".deepagents" / "agents" / "ops" / "AGENTS.md").is_file()
    # Subagent flattened
    assert (
        tmp_path / ".deepagents" / "agents" / "core" / "agents" / "writer.md"
    ).is_file()

    # Content preserved on rename
    new_core = (tmp_path / ".deepagents" / "agents" / "core" / "AGENTS.md").read_text(
        encoding="utf-8"
    )
    assert "core body" in new_core

    # Original legacy tree STILL EXISTS (we copy, we don't move)
    assert (tmp_path / ".olav" / "workspace" / "core" / "AGENT.md").is_file()


def test_backup_tar_contains_legacy_tree(tmp_path: Path) -> None:
    from olav.migrate.v0_20_layout import apply_migration, plan_migration

    _make_legacy_workspace(tmp_path)
    plan = plan_migration(tmp_path)
    result = apply_migration(plan, backup=True)

    assert result.backup_path is not None
    with tarfile.open(result.backup_path, mode="r:*") as tar:
        members = tar.getnames()

    # The backup should contain every file under .olav/workspace/
    assert any(".olav/workspace/core/AGENT.md" in m for m in members)
    assert any(".olav/workspace/core/writer/AGENT.md" in m for m in members)
    assert any(".olav/workspace/ops/AGENT.md" in m for m in members)


# ── 2. Skip backup ─────────────────────────────────────────────────────────


def test_apply_migration_skips_backup_when_disabled(tmp_path: Path) -> None:
    from olav.migrate.v0_20_layout import apply_migration, plan_migration

    _make_legacy_workspace(tmp_path)
    plan = plan_migration(tmp_path)
    result = apply_migration(plan, backup=False)

    assert result.backup_path is None
    # Migration still happened
    assert (tmp_path / ".deepagents" / "agents" / "core" / "AGENTS.md").is_file()
    # No backup dir created
    assert not (tmp_path / ".olav.bak").is_dir()


# ── 3. Idempotence ────────────────────────────────────────────────────────


def test_apply_migration_is_idempotent(tmp_path: Path) -> None:
    """Running the migration twice must not corrupt or duplicate."""
    from olav.migrate.v0_20_layout import (
        already_migrated,
        apply_migration,
        plan_migration,
    )

    _make_legacy_workspace(tmp_path)

    plan1 = plan_migration(tmp_path)
    result1 = apply_migration(plan1, backup=False)
    assert result1.applied_operations > 0
    assert already_migrated(tmp_path)

    # Second run: plan is empty (already migrated)
    plan2 = plan_migration(tmp_path)
    assert plan2.operations == []
    result2 = apply_migration(plan2, backup=False)
    assert result2.applied_operations == 0

    # Original new-layout files unchanged
    content = (tmp_path / ".deepagents" / "agents" / "core" / "AGENTS.md").read_text(
        encoding="utf-8"
    )
    assert "core body" in content


# ── 4. Empty plan → no-op ──────────────────────────────────────────────────


def test_empty_plan_no_op(tmp_path: Path) -> None:
    from olav.migrate.v0_20_layout import MigrationPlan, apply_migration

    plan = MigrationPlan(root=tmp_path, operations=[])
    result = apply_migration(plan, backup=False)
    assert result.applied_operations == 0
    assert result.backup_path is None
    # No directories created
    assert not (tmp_path / ".deepagents").exists()


# ── 5. Result shape ────────────────────────────────────────────────────────


def test_result_reports_per_operation_status(tmp_path: Path) -> None:
    from olav.migrate.v0_20_layout import apply_migration, plan_migration

    _make_legacy_workspace(tmp_path)
    plan = plan_migration(tmp_path)
    result = apply_migration(plan, backup=False)

    # At least one entry per op executed; each has kind + status
    assert len(result.operation_results) == result.applied_operations
    for op_result in result.operation_results:
        assert "kind" in op_result
        assert "status" in op_result
        assert op_result["status"] in ("ok", "skipped")
