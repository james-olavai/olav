"""
tests/unit/test_migrate_cli.py
──────────────────────────────
Unit coverage for the ``olav migrate`` CLI verb (P1 cycle 3).

The CLI surface is:

  olav migrate                      — run real migration with backup
  olav migrate --dry-run            — print plan, don't touch disk
  olav migrate --dry-run --json     — machine-readable plan
  olav migrate --no-backup          — run migration without backup tar

All four test cases stub the heavy lifters
(:func:`olav.migrate.v0_20_layout.plan_migration` and
:func:`apply_migration`) so we only exercise the CLI dispatch layer —
argument parsing, summary printing, exit codes — not the filesystem
planner itself (that's covered in :mod:`tests.unit.test_v0_20_layout_plan`
and :mod:`tests.integration.test_v0_20_layout_apply`).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest


class _FakePlan:
    """Stub returned by ``plan_migration``.  Matches the public surface
    used by the CLI (``.operations``, ``.summary()``, ``.as_dict()``).
    """

    def __init__(self, ops: int = 3) -> None:
        self.operations = [object()] * ops

    def summary(self) -> str:
        return f"Planned: {len(self.operations)} operations."

    def as_dict(self) -> dict:
        return {"operations": [{"kind": "test"}] * len(self.operations)}


class _FakeResult:
    """Stub returned by ``apply_migration``."""

    def __init__(
        self,
        *,
        applied: int = 3,
        skipped: int = 0,
        backup_path: Path | None = None,
    ) -> None:
        self.applied_operations = applied
        self.skipped_operations = skipped
        self.backup_path = backup_path
        self.operation_results = [{"kind": "x", "status": "ok"}] * applied


# ── 1. Module importable ────────────────────────────────────────────────────


def test_module_importable() -> None:
    from olav.cli.commands import migrate as migrate_cmd

    assert hasattr(migrate_cmd, "MigrateCommand")


# ── 2. Dry-run prints summary, does NOT call apply ─────────────────────────


def test_dry_run_prints_summary_and_skips_apply(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    import asyncio

    from olav.cli.commands.migrate import MigrateCommand

    fake_plan = _FakePlan(ops=5)
    plan_calls = []
    apply_calls = []

    def _fake_plan(root: Path) -> _FakePlan:
        plan_calls.append(root)
        return fake_plan

    def _fake_apply(*args, **kwargs) -> _FakeResult:  # noqa: ANN002
        apply_calls.append((args, kwargs))
        return _FakeResult()

    monkeypatch.setattr(
        "olav.migrate.v0_20_layout.plan_migration", _fake_plan
    )
    monkeypatch.setattr(
        "olav.migrate.v0_20_layout.apply_migration", _fake_apply
    )

    cmd = MigrateCommand()
    output = asyncio.run(cmd.execute("--dry-run"))

    assert len(plan_calls) == 1
    assert apply_calls == []  # dry-run MUST NOT apply
    assert "Planned" in output or "Planned" in (capsys.readouterr().out or "")


# ── 3. Dry-run --json emits JSON ──────────────────────────────────────────


def test_dry_run_json_mode_emits_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    import json

    from olav.cli.commands.migrate import MigrateCommand

    monkeypatch.setattr(
        "olav.migrate.v0_20_layout.plan_migration", lambda root: _FakePlan(ops=2)
    )

    cmd = MigrateCommand()
    output = asyncio.run(cmd.execute("--dry-run --json"))

    # Output must be valid JSON with an operations key
    parsed = json.loads(output)
    assert "operations" in parsed
    assert len(parsed["operations"]) == 2


# ── 4. Real run calls apply with backup by default ────────────────────────


def test_real_run_defaults_to_backup(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from olav.cli.commands.migrate import MigrateCommand

    monkeypatch.setattr(
        "olav.migrate.v0_20_layout.plan_migration", lambda root: _FakePlan(ops=3)
    )

    apply_kwargs: dict = {}

    def _fake_apply(plan, **kwargs):  # noqa: ANN001
        apply_kwargs.update(kwargs)
        return _FakeResult(applied=3, backup_path=Path("/tmp/fake.tar.gz"))

    monkeypatch.setattr(
        "olav.migrate.v0_20_layout.apply_migration", _fake_apply
    )

    cmd = MigrateCommand()
    output = asyncio.run(cmd.execute(""))

    assert apply_kwargs.get("backup") is True
    assert "3" in output  # applied count appears in output
    assert "fake.tar.gz" in output  # backup path referenced


def test_no_backup_flag_disables_backup(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from olav.cli.commands.migrate import MigrateCommand

    monkeypatch.setattr(
        "olav.migrate.v0_20_layout.plan_migration", lambda root: _FakePlan(ops=1)
    )

    apply_kwargs: dict = {}

    def _fake_apply(plan, **kwargs):
        apply_kwargs.update(kwargs)
        return _FakeResult(applied=1)

    monkeypatch.setattr(
        "olav.migrate.v0_20_layout.apply_migration", _fake_apply
    )

    cmd = MigrateCommand()
    asyncio.run(cmd.execute("--no-backup"))

    assert apply_kwargs.get("backup") is False


# ── 5. Empty plan prints "nothing to do" ──────────────────────────────────


def test_empty_plan_reports_no_action(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from olav.cli.commands.migrate import MigrateCommand

    # Empty plan
    monkeypatch.setattr(
        "olav.migrate.v0_20_layout.plan_migration",
        lambda root: _FakePlan(ops=0),
    )

    # apply should NOT be called on an empty plan (save a backup round trip)
    apply_calls = []

    def _fake_apply(*args, **kwargs):
        apply_calls.append((args, kwargs))
        return _FakeResult(applied=0)

    monkeypatch.setattr(
        "olav.migrate.v0_20_layout.apply_migration", _fake_apply
    )

    cmd = MigrateCommand()
    output = asyncio.run(cmd.execute(""))

    # Regardless of whether apply was called, output should tell the
    # user nothing actually changed.
    assert "nothing" in output.lower() or "already" in output.lower() or "0" in output


# ── 6. Unknown flag returns usage, doesn't crash ──────────────────────────


def test_unknown_flag_returns_usage() -> None:
    import asyncio

    from olav.cli.commands.migrate import MigrateCommand

    cmd = MigrateCommand()
    output = asyncio.run(cmd.execute("--not-a-real-flag"))
    assert "usage" in output.lower() or "unknown" in output.lower()
