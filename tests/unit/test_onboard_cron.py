"""TDD tests for _register_trace_learner_cron() in netops_init.py.

Contracts:

1. Returns dict with status/message

2. Writes expected cron line to an injectable crontab file (dry_run=False)

3. Idempotent: running twice does NOT duplicate the line

4. dry_run=True: returns what would be written, touches nothing

5. Existing crontab preserved; only one line appended

"""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Import helper — netops_init.py is a script (not a package module)
# ---------------------------------------------------------------------------

def _load_onboard():
    import importlib.util
    path = Path(__file__).resolve().parents[2] / "olav-netops" / "scripts" / "netops_init.py"
    spec = importlib.util.spec_from_file_location("netops_init", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_register_cron_function_exists():
    """_register_trace_learner_cron must be importable from netops_init.py."""
    mod = _load_onboard()
    assert hasattr(mod, "_register_trace_learner_cron"), (
        "_register_trace_learner_cron not found in netops_init.py"
    )


def test_register_cron_dry_run_returns_cron_line(tmp_path: Path):
    """dry_run=True must return the cron line without writing anything."""
    mod = _load_onboard()
    result = mod._register_trace_learner_cron(project_root=tmp_path, dry_run=True)

    assert result["status"] == "dry_run"
    assert "cron_line" in result
    assert "trace_learner" in result["cron_line"]
    # No side effects
    assert not (tmp_path / ".olav" / "cron.tab").exists()


def test_register_cron_writes_to_cron_tab_file(tmp_path: Path):
    """Writes cron line to ~/.olav/cron.tab equivalent (injectable path)."""
    mod = _load_onboard()

    cron_file = tmp_path / "cron.tab"
    result = mod._register_trace_learner_cron(
        project_root=tmp_path, cron_file=cron_file, dry_run=False
    )

    assert result["status"] == "registered"
    assert cron_file.exists()
    content = cron_file.read_text()
    assert "trace_learner" in content
    assert "0 3 * * *" in content


def test_register_cron_idempotent(tmp_path: Path):
    """Calling twice must NOT duplicate the cron entry."""
    mod = _load_onboard()
    cron_file = tmp_path / "cron.tab"

    mod._register_trace_learner_cron(project_root=tmp_path, cron_file=cron_file, dry_run=False)
    mod._register_trace_learner_cron(project_root=tmp_path, cron_file=cron_file, dry_run=False)

    lines = [l for l in cron_file.read_text().splitlines()
             if "trace_learner" in l and not l.startswith("#")]
    assert len(lines) == 1, f"Expected exactly 1 cron entry, got {len(lines)}: {lines}"


def test_register_cron_preserves_existing_entries(tmp_path: Path):
    """Existing crontab content is preserved when appending."""
    mod = _load_onboard()
    cron_file = tmp_path / "cron.tab"
    cron_file.write_text("# existing job\n30 6 * * * echo hello\n")

    mod._register_trace_learner_cron(project_root=tmp_path, cron_file=cron_file, dry_run=False)

    content = cron_file.read_text()
    assert "echo hello" in content
    assert "trace_learner" in content


def test_register_cron_already_registered_returns_skipped(tmp_path: Path):
    """If cron line already present, returns status='already_registered'."""
    mod = _load_onboard()
    cron_file = tmp_path / "cron.tab"

    mod._register_trace_learner_cron(project_root=tmp_path, cron_file=cron_file, dry_run=False)
    result2 = mod._register_trace_learner_cron(
        project_root=tmp_path, cron_file=cron_file, dry_run=False
    )

    assert result2["status"] == "already_registered"
