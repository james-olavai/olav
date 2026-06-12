"""Round 47 — ARCH-13 ``olav diff`` CLI + ARCH-16/17/18/19 reconciliation.

ARCH-13 last-mile: wraps the workspace-vendored ``diff_snapshots``
aggregator (``.olav/workspace/ops/tools/diff_snapshots.py``) so operators
can diff two snapshots with one command instead of invoking the tool via
the agent shell.

Reconciliation pins: ARCH-16 / 17 / 18 are all effectively closed — every
matrix row is ✅ by Round 42. Round 47 flips the section status headers
to match and pins them so they can't drift back.
"""

from __future__ import annotations

import argparse
import importlib.util
import io
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DIFF_PY = REPO / "src" / "olav" / "cli" / "commands" / "diff.py"
CLI_MAIN = REPO / "src" / "olav" / "cli" / "main.py"
ISSUES_MD = REPO / "dev_docs" / "00. issues.md"


def _load_diff_cli():
    spec = importlib.util.spec_from_file_location("_olav_diff_cli_r47", DIFF_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── ARCH-13 CLI pins ────────────────────────────────────────────────────


def test_diff_module_exists():
    assert DIFF_PY.is_file()


def test_diff_exports_builder_and_handler():
    mod = _load_diff_cli()
    assert callable(getattr(mod, "build_diff_parser", None))
    assert callable(getattr(mod, "handle_diff_command", None))


def test_main_registers_diff_subparser():
    src = CLI_MAIN.read_text(encoding="utf-8")
    assert "build_diff_parser(subparsers)" in src, (
        "cli/main.py no longer registers the diff subparser"
    )


def test_main_dispatches_diff():
    src = CLI_MAIN.read_text(encoding="utf-8")
    assert 'args.command == "diff"' in src
    assert "handle_diff_command(args)" in src


def test_parser_accepts_two_snapshot_args_and_flags():
    mod = _load_diff_cli()
    root = argparse.ArgumentParser()
    subs = root.add_subparsers(dest="command")
    p = mod.build_diff_parser(subs)
    help_text = p.format_help()
    # The positional args + optional flags must all be declared.
    for needed in (
        "snapshot_id_1",
        "snapshot_id_2",
        "--table",
        "--device",
        "--max-rows",
        "--json",
    ):
        assert needed in help_text, (
            f"olav diff parser dropped {needed!r}: {help_text!r}"
        )


def test_handler_rejects_missing_snapshot_args():
    mod = _load_diff_cli()
    # Build a Namespace without snapshot ids — simulates `olav diff` with no args.
    ns = argparse.Namespace(
        snapshot_id_1=None,
        snapshot_id_2=None,
        table=None,
        device=None,
        max_rows=5,
        json=False,
    )
    err = io.StringIO()
    with redirect_stderr(err):
        rc = mod.handle_diff_command(ns)
    assert rc == 1
    assert "snapshot" in err.getvalue().lower()


def test_loader_finds_diff_snapshots():
    mod = _load_diff_cli()
    fn = mod._load_diff_snapshots()
    if fn is None:
        from importlib.metadata import entry_points
        eps = list(entry_points(group="olav.cli_tools"))
        if not any(ep.name == "diff_snapshots" for ep in eps):
            pytest.skip("diff_snapshots entry-point not registered in this environment")
    assert fn is not None, (
        "diff CLI can't locate diff_snapshots despite registered entry-point"
    )


def test_format_diff_renders_totals_and_per_table():
    mod = _load_diff_cli()
    sample = {
        "status": "success",
        "snapshot_id_1": "snap_a",
        "snapshot_id_2": "snap_b",
        "total_added": 2,
        "total_removed": 1,
        "tables": {
            "parsed_outputs": {
                "added": [{"device_name": "R1", "command": "show bgp"}],
                "removed": [],
                "added_count": 1,
                "removed_count": 0,
            },
            "topology_links": {
                "added": [],
                "removed": [],
                "added_count": 0,
                "removed_count": 0,
            },
        },
    }
    out = mod._format_diff(sample, max_rows=5)
    assert "snap_a" in out
    assert "snap_b" in out
    assert "+2" in out and "-1" in out
    assert "[parsed_outputs]" in out
    assert "[topology_links] unchanged" in out


def test_format_diff_truncates_to_max_rows():
    mod = _load_diff_cli()
    sample = {
        "status": "success",
        "snapshot_id_1": "a",
        "snapshot_id_2": "b",
        "total_added": 10,
        "total_removed": 0,
        "tables": {
            "parsed_outputs": {
                "added": [{"idx": i} for i in range(10)],
                "removed": [],
                "added_count": 10,
                "removed_count": 0,
            },
        },
    }
    out = mod._format_diff(sample, max_rows=3)
    # Only 3 rows shown, plus an indicator that 7 remain.
    assert '"idx": 0' in out and '"idx": 2' in out
    assert '"idx": 3' not in out
    assert "7 more" in out


# ── Reconciliation pins ────────────────────────────────────────────────


def _section(md: str, header: str) -> str:
    idx = md.find(header)
    if idx < 0:
        return ""
    return md[idx : idx + 500]


def test_arch13_status_reflects_closed():
    md = ISSUES_MD.read_text(encoding="utf-8")
    s = _section(md, "### ISSUE-ARCH-13:")
    assert "Closed" in s and "Round 47" in s


def test_arch16_status_reflects_closed():
    md = ISSUES_MD.read_text(encoding="utf-8")
    s = _section(md, "### ISSUE-ARCH-16:")
    # tool-LIMITs 3-of-3 landed in Rounds 40-41; reconcile in 47.
    assert "Closed" in s and "Round 47" in s


def test_arch17_status_reflects_closed():
    md = ISSUES_MD.read_text(encoding="utf-8")
    s = _section(md, "### ISSUE-ARCH-17:")
    assert "Closed" in s and "Round 47" in s


def test_arch18_status_reflects_closed():
    md = ISSUES_MD.read_text(encoding="utf-8")
    s = _section(md, "### ISSUE-ARCH-18:")
    assert "Closed" in s and "Round 47" in s


def test_arch19_status_reflects_core_closed():
    md = ISSUES_MD.read_text(encoding="utf-8")
    s = _section(md, "### ISSUE-ARCH-19:")
    # ARCH-19 was marked Core Closed in R47 (SummarizationMiddleware
    # landed) with two residuals (local LLM cache, SKILL.md field). R49
    # shipped the SKILL.md field so we now accept plain "Closed" too —
    # the guard just needs to prevent drift back to 🟡 Partially.
    assert "Closed" in s, (
        f"ARCH-19 status drifted; must stay Closed (or Core Closed). "
        f"Section head: {s[:200]!r}"
    )
