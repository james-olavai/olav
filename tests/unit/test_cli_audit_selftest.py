"""Tests for ``olav audit selftest`` CLI command (#7, 2026-05-12).

Verified contracts:
  * profile name resolves to default workspace path
  * explicit .md path passes through unchanged
  * missing profile → exit 1 + error to stderr
  * schema_error in any job → exit 2 + each failure listed
  * --json flag emits parseable JSON instead of human text
  * usage shown when no subcommand is given
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from olav.cli.commands.audit import (
    _print_result,
    _resolve_profile_path,
    handle_audit_command,
)


# ── path resolution ─────────────────────────────────────────────────────


def test_resolve_profile_path_bare_name(tmp_path, monkeypatch):
    """Bare names resolve against .olav/workspace/audit/profiles/<name>.md
    when that file exists."""
    profiles_dir = tmp_path / ".olav" / "workspace" / "audit" / "profiles"
    profiles_dir.mkdir(parents=True)
    (profiles_dir / "bgp_health.md").write_text("---\nname: bgp_health\n---\n")
    monkeypatch.chdir(tmp_path)
    resolved = _resolve_profile_path("bgp_health")
    assert resolved.endswith(".olav/workspace/audit/profiles/bgp_health.md")


def test_resolve_profile_path_explicit_path_passes_through():
    """Explicit .md paths are returned verbatim — no implicit lookup."""
    assert _resolve_profile_path("/tmp/x.md") == "/tmp/x.md"
    assert _resolve_profile_path("relative/path/x.md") == "relative/path/x.md"


def test_resolve_profile_path_bare_name_no_workspace_returns_arg(tmp_path, monkeypatch):
    """No workspace + bare name → return the arg unchanged (caller will
    surface the not-found error)."""
    monkeypatch.chdir(tmp_path)
    assert _resolve_profile_path("nonexistent") == "nonexistent"


# ── handler return codes ────────────────────────────────────────────────


def test_handle_audit_command_no_subcommand(capsys):
    args = argparse.Namespace(audit_command=None)
    assert handle_audit_command(args) == 1
    err = capsys.readouterr().err
    assert "usage: olav audit <subcommand>" in err


def test_handle_audit_command_unknown_subcommand(capsys):
    args = argparse.Namespace(audit_command="bogus")
    assert handle_audit_command(args) == 1
    err = capsys.readouterr().err
    assert "unknown subcommand: bogus" in err


def test_handle_selftest_missing_profile(capsys, monkeypatch):
    monkeypatch.setattr(
        "olav.cli.commands.audit._load_selftest_profile",
        lambda: (lambda p: {"ok": True, "profile": "x", "profile_path": p, "jobs": []}),
    )
    args = argparse.Namespace(audit_command="selftest", profile=None, json=False)
    assert handle_audit_command(args) == 1
    err = capsys.readouterr().err
    assert "missing required argument: profile" in err


def test_handle_selftest_profile_file_not_found(capsys, monkeypatch):
    monkeypatch.setattr(
        "olav.cli.commands.audit._load_selftest_profile",
        lambda: (lambda p: {"ok": True, "profile_path": p, "jobs": []}),
    )
    args = argparse.Namespace(
        audit_command="selftest", profile="/tmp/no_such_profile.md", json=False,
    )
    assert handle_audit_command(args) == 1
    err = capsys.readouterr().err
    assert "profile not found" in err


def test_handle_selftest_all_jobs_pass_exit_0(tmp_path, capsys, monkeypatch):
    profile = tmp_path / "p.md"
    profile.write_text("---\nname: p\n---\n")
    monkeypatch.setattr(
        "olav.cli.commands.audit._load_selftest_profile",
        lambda: (lambda p: {
            "ok": True, "profile": "p", "profile_path": p,
            "jobs": [{"name": "j1", "status": "ok", "error": None, "table": "t"}],
        }),
    )
    args = argparse.Namespace(
        audit_command="selftest", profile=str(profile), json=False,
    )
    assert handle_audit_command(args) == 0
    out = capsys.readouterr().out
    assert "✅ all jobs pass" in out


def test_handle_selftest_failure_exit_2(tmp_path, capsys, monkeypatch):
    profile = tmp_path / "p.md"
    profile.write_text("---\nname: p\n---\n")
    monkeypatch.setattr(
        "olav.cli.commands.audit._load_selftest_profile",
        lambda: (lambda p: {
            "ok": False, "profile": "p", "profile_path": p,
            "jobs": [
                {"name": "j1", "status": "ok", "error": None, "table": "t"},
                {"name": "j2", "status": "schema_error",
                 "error": "Binder Error: column missing", "table": "t"},
            ],
        }),
    )
    args = argparse.Namespace(
        audit_command="selftest", profile=str(profile), json=False,
    )
    assert handle_audit_command(args) == 2
    out = capsys.readouterr().out
    assert "🔴 1 of 2 job(s) failed" in out
    assert "j2" in out and "column missing" in out


def test_handle_selftest_loader_missing_exit_2(tmp_path, capsys, monkeypatch):
    """If the entry-point doesn't resolve AND the fallback walk fails,
    the CLI must exit 2 with a clear error — not crash."""
    profile = tmp_path / "p.md"
    profile.write_text("---\nname: p\n---\n")
    monkeypatch.setattr(
        "olav.cli.commands.audit._load_selftest_profile",
        lambda: None,
    )
    args = argparse.Namespace(
        audit_command="selftest", profile=str(profile), json=False,
    )
    assert handle_audit_command(args) == 2
    err = capsys.readouterr().err
    assert "could not load map_engine.selftest_profile" in err


# ── JSON output ─────────────────────────────────────────────────────────


def test_handle_selftest_json_emits_parseable_output(tmp_path, capsys, monkeypatch):
    profile = tmp_path / "p.md"
    profile.write_text("---\nname: p\n---\n")
    fake_result = {
        "ok": False, "profile": "p", "profile_path": str(profile),
        "jobs": [{"name": "j1", "status": "schema_error",
                  "error": "missing column", "table": "t"}],
    }
    monkeypatch.setattr(
        "olav.cli.commands.audit._load_selftest_profile",
        lambda: (lambda p: fake_result),
    )
    args = argparse.Namespace(
        audit_command="selftest", profile=str(profile), json=True,
    )
    assert handle_audit_command(args) == 2
    out = capsys.readouterr().out
    # MUST be parseable JSON for CI consumption
    parsed = json.loads(out)
    assert parsed["ok"] is False
    assert parsed["jobs"][0]["status"] == "schema_error"
