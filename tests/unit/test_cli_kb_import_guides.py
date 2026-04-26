"""Platform CLI — `olav kb import-guides <dir>` — TDD red bar.

Pin the contract for the new CLI subcommand added in
``src/olav/cli/commands/kb.py``.  See dev_docs/62 § "Platform-KB
refactor".

The CLI scans a directory for ``*.guide.yaml`` files and primes them
into LanceDB via ``olav.core.memory.guide_kb.prime_guides_from_dir``.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest


DIM = 32


VALID_GUIDE_YAML = """
schema_version: 1
intent: topology_visualization
agent: ops
keywords: [topology, mermaid]
body: |
  Pull L2 links, build Mermaid graph, delegate to writer.
"""


def _embed_stub(text: str) -> list[float]:
    return [float(len(text) % 100) / 100.0] * DIM


def _write_guide(workspace_root: Path) -> Path:
    p = workspace_root / "ops" / "guides" / "topology_viz.guide.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(VALID_GUIDE_YAML, encoding="utf-8")
    return p


def _isolate_store(monkeypatch, tmp_path):
    """Point ``_get_store`` at a tmp LanceDB path so the test doesn't
    touch the user's real memory store."""
    db_path = tmp_path / "memory.db"
    monkeypatch.setenv("OLAV_MEMORY_DB_PATH", str(db_path))


# ── argparse wiring ────────────────────────────────────────────────


def test_kb_import_guides_subparser_registered():
    """``olav kb import-guides`` is a known subcommand."""
    import argparse

    from olav.cli.commands.kb import build_kb_parser

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")
    build_kb_parser(sub)

    args = parser.parse_args(["kb", "import-guides", "/tmp/ws"])
    assert args.kb_command == "import-guides"
    assert args.dir == "/tmp/ws"


# ── command handler ────────────────────────────────────────────────


def test_kb_import_guides_runs(tmp_path, monkeypatch, capsys):
    """``cmd_import_guides`` returns 0 + prints count when guides are present."""
    _isolate_store(monkeypatch, tmp_path)
    workspace_root = tmp_path / "workspace"
    _write_guide(workspace_root)

    from olav.cli.commands.kb import cmd_import_guides

    args = type("Args", (), {"dir": str(workspace_root)})()
    with patch("olav.core.memory.guide_kb._embed", side_effect=_embed_stub):
        rc = cmd_import_guides(args)

    assert rc == 0
    out = capsys.readouterr().out
    assert "1" in out  # count appears
    assert "guide" in out.lower()


def test_kb_import_guides_missing_dir(tmp_path, monkeypatch, capsys):
    """Missing dir → exit code 1 + stderr/stdout error message."""
    _isolate_store(monkeypatch, tmp_path)

    from olav.cli.commands.kb import cmd_import_guides

    args = type("Args", (), {"dir": str(tmp_path / "does-not-exist")})()
    rc = cmd_import_guides(args)
    assert rc == 1


def test_kb_import_guides_handle_dispatches(tmp_path, monkeypatch):
    """``handle_kb_command`` routes 'import-guides' to cmd_import_guides."""
    _isolate_store(monkeypatch, tmp_path)
    workspace_root = tmp_path / "workspace"
    _write_guide(workspace_root)

    from olav.cli.commands import kb as kb_mod

    args = type("Args", (), {
        "kb_command": "import-guides",
        "dir": str(workspace_root),
    })()
    with patch("olav.core.memory.guide_kb._embed", side_effect=_embed_stub):
        rc = kb_mod.handle_kb_command(args)

    assert rc == 0
