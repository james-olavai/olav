"""Round 45 — ``olav explain`` CLI (ARCH-11 last mile).

Builds on Round 44's ``parse_src_token`` helper: operators paste a
``[src: ...]`` citation from an audit report; the CLI parses it and
fetches the underlying DuckDB row so they can verify the finding
without writing SQL.

Pins:

* command registered on the root subparser
* dispatch wired in main.py
* ``_fetch_source_rows`` is read-only (no DuckDB write surface)
* handler returns non-zero exit code on unparseable token / missing table
* handler prints resolved table + token fields before rows
"""

from __future__ import annotations

import argparse
import importlib.util
import io
import sys
from pathlib import Path
from contextlib import redirect_stdout, redirect_stderr

REPO = Path(__file__).resolve().parents[2]
EXPLAIN_PY = REPO / "src" / "olav" / "cli" / "commands" / "explain.py"
CLI_MAIN = REPO / "src" / "olav" / "cli" / "main.py"


def _load_explain():
    spec = importlib.util.spec_from_file_location("_olav_explain_r45", EXPLAIN_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── CLI registration pins ────────────────────────────────────────────────


def test_explain_module_exists():
    assert EXPLAIN_PY.is_file()


def test_explain_exports_builder_and_handler():
    mod = _load_explain()
    assert callable(getattr(mod, "build_explain_parser", None))
    assert callable(getattr(mod, "handle_explain_command", None))


def test_main_registers_explain_subparser():
    src = CLI_MAIN.read_text(encoding="utf-8")
    assert "build_explain_parser(subparsers)" in src, (
        "cli/main.py no longer registers the explain subparser"
    )


def test_main_dispatches_explain():
    src = CLI_MAIN.read_text(encoding="utf-8")
    assert 'args.command == "explain"' in src
    assert "handle_explain_command(args)" in src


def test_build_explain_parser_adds_token_positional():
    mod = _load_explain()
    root = argparse.ArgumentParser()
    subs = root.add_subparsers(dest="command")
    p = mod.build_explain_parser(subs)
    # Argparse doesn't expose a friendly field list — format_help is the
    # cheapest way to confirm the positional argument landed.
    assert "token" in p.format_help()
    assert "--limit" in p.format_help()


# ── Handler behaviour pins (no DB needed — uses unparseable input) ──────


def test_handler_rejects_empty_token():
    mod = _load_explain()
    ns = argparse.Namespace(token="", limit=3)
    buf_err = io.StringIO()
    with redirect_stderr(buf_err):
        rc = mod.handle_explain_command(ns)
    assert rc == 1
    assert "no [src:" in buf_err.getvalue() or "not recognised" in buf_err.getvalue()


def test_handler_rejects_unparseable_token():
    mod = _load_explain()
    ns = argparse.Namespace(token="totally not a token", limit=3)
    buf_err = io.StringIO()
    with redirect_stderr(buf_err):
        rc = mod.handle_explain_command(ns)
    assert rc == 1


# ── Read-only posture pins ───────────────────────────────────────────────


def test_fetch_source_rows_opens_db_read_only():
    """Safety: the explain CLI must not be able to mutate the DB — pin the
    ``read_only=True`` flag on the duckdb.connect call."""
    src = EXPLAIN_PY.read_text(encoding="utf-8")
    assert "read_only=True" in src, (
        "explain CLI must open DuckDB in read-only mode — verification tool, "
        "not a write surface."
    )


def test_explain_does_not_import_write_helpers():
    """Structural: the module should not import any known write helper so a
    future refactor can't silently add a write path."""
    src = EXPLAIN_PY.read_text(encoding="utf-8")
    banned = ["ingest_manager", "write_workspace_file", "run_shell"]
    for name in banned:
        assert name not in src, (
            f"explain CLI picked up a write-ish dependency ({name!r}); "
            f"keep it read-only."
        )


# ── parse_src_token loader pins ──────────────────────────────────────────


def test_loader_finds_parse_src_token():
    mod = _load_explain()
    fn = mod._load_parse_src_token()
    assert callable(fn), (
        "explain CLI can't locate render_report.parse_src_token — Round 44 "
        "groundwork dependency broken."
    )
    # The parser should work on a known-good tag.
    assert fn("[src: tab#snap; device=R1; row=4]") == {
        "table": "tab",
        "snapshot_id": "snap",
        "device": "R1",
        "row_index": 4,
    }


# ── Formatting pin ───────────────────────────────────────────────────────


def test_format_row_truncates_long_fields():
    mod = _load_explain()
    row = {"short": "ok", "long": "x" * 1000}
    out = mod._format_row(row, max_field_chars=100)
    assert "short: ok" in out
    # Long field must be truncated with ellipsis.
    assert "x" * 100 + "…" in out
    assert "x" * 1000 not in out
