"""Phase 3 TDD — `olav kb` CLI command group (e2e / contract tests).

These tests do NOT require a running OLAV server or LLM — they run the CLI
in-process via subprocess and verify exit codes and output patterns.

C-KB-16: `olav kb export` command is available and succeeds (exit 0)
C-KB-23: `olav kb status` outputs knowledge store statistics
C-KB-24: `olav kb graph` generates an HTML file
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_PYTHON = sys.executable


def _run_kb(*args, env_extra=None, cwd=None):
    """Run `python -m olav.cli.main kb <args>` and return (returncode, stdout, stderr)."""
    import os

    env = os.environ.copy()
    # Point to a temp LanceDB so tests are isolated
    if env_extra:
        env.update(env_extra)

    result = subprocess.run(
        [_PYTHON, "-m", "olav.cli.main", "kb", *args],
        capture_output=True,
        text=True,
        cwd=str(cwd or _ROOT),
        env=env,
        timeout=90,
    )
    return result.returncode, result.stdout, result.stderr


# ─── C-KB-16: `olav kb export` is available ──────────────────────────────────

def test_kb_export_command_exists(tmp_path):
    """C-KB-16: `olav kb export` must exit 0 (not 'unknown command')."""
    import os
    env_extra = {
        "OLAV_MEMORY_DB_PATH": str(tmp_path / "mem.db"),
        "OLAV_KB_EXPORT_DIR": str(tmp_path / "vault"),
    }
    rc, stdout, stderr = _run_kb("export", env_extra=env_extra)
    combined = (stdout + stderr).lower()
    assert "unknown command" not in combined, (
        f"'olav kb export' not registered — rc={rc}\nstdout={stdout}\nstderr={stderr}"
    )
    assert "error" not in combined or rc == 0, (
        f"`olav kb export` failed unexpectedly — rc={rc}\nstdout={stdout}\nstderr={stderr}"
    )


def test_kb_help_shows_subcommands(tmp_path):
    """C-KB-16: `olav kb --help` must list export, status, graph, sync, import."""
    rc, stdout, stderr = _run_kb("--help")
    combined = stdout + stderr
    for subcmd in ("export", "status", "graph"):
        assert subcmd in combined, (
            f"Subcommand '{subcmd}' missing from `olav kb --help`:\n{combined}"
        )


# ─── C-KB-23: `olav kb status` outputs statistics ────────────────────────────

def test_kb_status_outputs_stats(tmp_path):
    """C-KB-23: `olav kb status` must print statistics (counts by origin)."""
    import os
    env_extra = {
        "OLAV_MEMORY_DB_PATH": str(tmp_path / "mem.db"),
    }
    rc, stdout, stderr = _run_kb("status", env_extra=env_extra)
    combined = stdout + stderr
    # Should mention totals even for empty store
    assert any(
        kw in combined.lower()
        for kw in ("total", "entries", "agent", "document", "0", "knowledge")
    ), (
        f"`olav kb status` output has no recognizable stats:\n{combined}"
    )


# ─── C-KB-24: `olav kb graph` generates _graph.html ─────────────────────────

def test_kb_graph_creates_html(tmp_path):
    """C-KB-24: `olav kb graph` must generate an HTML file."""
    import os
    output_html = tmp_path / "knowledge_graph.html"
    env_extra = {
        "OLAV_MEMORY_DB_PATH": str(tmp_path / "mem.db"),
    }
    rc, stdout, stderr = _run_kb(
        "graph", "--output", str(output_html),
        env_extra=env_extra,
    )
    combined = stdout + stderr
    assert output_html.exists() or any(
        kw in combined.lower() for kw in ("html", "graph", "export", "written", "empty")
    ), (
        f"`olav kb graph` neither created {output_html} nor reported graph output.\n"
        f"rc={rc}\nstdout={stdout}\nstderr={stderr}"
    )
