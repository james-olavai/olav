"""Tests for olav.core.skill_runner.execute_skill_script.

Per ADR-0008 — controlled subprocess execution of skill scripts.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from olav.core.skill_runner import execute_skill_script


def _make_skill(tmp_path: Path, skill_name: str, script_name: str, body: str) -> Path:
    """Create ``<tmp_path>/<skill_name>/{SKILL.md, scripts/<script>.py}``."""
    skill_dir = tmp_path / skill_name
    (skill_dir / "scripts").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {skill_name}\ndescription: Test skill\n---\n",
        encoding="utf-8",
    )
    (skill_dir / "scripts" / script_name).write_text(body, encoding="utf-8")
    return skill_dir


# --- happy path -------------------------------------------------------------


def test_runs_script_and_captures_json_stdout(tmp_path):
    _make_skill(
        tmp_path,
        "demo-skill",
        "echo.py",
        "import json, sys\n"
        "args = json.loads(sys.stdin.read() or '{}')\n"
        "print(json.dumps({'echo': args}))\n",
    )
    out = execute_skill_script(
        skill_name="demo-skill",
        script_name="echo.py",
        args={"hello": "world"},
        workspace_root=tmp_path,
    )
    assert out["status"] == "ok"
    assert out["returncode"] == 0
    assert out["stdout"] == {"echo": {"hello": "world"}}


def test_finds_skill_one_level_deep(tmp_path):
    """Skill nested under a parent (e.g. ops/lab) is discoverable."""
    _make_skill(
        tmp_path / "ops",
        "lab",
        "trivial.py",
        "import json; print(json.dumps({'ok': True}))\n",
    )
    out = execute_skill_script(
        skill_name="lab",
        script_name="trivial.py",
        workspace_root=tmp_path,
    )
    assert out["status"] == "ok"
    assert out["stdout"] == {"ok": True}


def test_non_zero_exit_returned_as_error(tmp_path):
    _make_skill(
        tmp_path,
        "demo-skill",
        "fail.py",
        "import sys; sys.exit(7)\n",
    )
    out = execute_skill_script(
        skill_name="demo-skill",
        script_name="fail.py",
        workspace_root=tmp_path,
    )
    assert out["status"] == "error"
    assert out["returncode"] == 7


def test_stderr_captured(tmp_path):
    _make_skill(
        tmp_path,
        "demo-skill",
        "stderr.py",
        "import sys; sys.stderr.write('something went wrong\\n')\n"
        "print('{}')\n",
    )
    out = execute_skill_script(
        skill_name="demo-skill",
        script_name="stderr.py",
        workspace_root=tmp_path,
    )
    assert out["status"] == "ok"
    assert "something went wrong" in out["stderr"]


def test_stdout_falls_back_to_string_when_not_json(tmp_path):
    _make_skill(
        tmp_path,
        "demo-skill",
        "plain.py",
        "print('not-json text output')\n",
    )
    out = execute_skill_script(
        skill_name="demo-skill",
        script_name="plain.py",
        workspace_root=tmp_path,
    )
    assert out["status"] == "ok"
    assert "not-json" in out["stdout"]


# --- security / validation --------------------------------------------------


def test_unknown_skill_errors(tmp_path):
    out = execute_skill_script(
        skill_name="missing",
        script_name="anything.py",
        workspace_root=tmp_path,
    )
    assert out["status"] == "error"
    assert "not found" in out["error"].lower()


def test_missing_script_errors(tmp_path):
    _make_skill(tmp_path, "demo-skill", "exists.py", "print('{}')\n")
    out = execute_skill_script(
        skill_name="demo-skill",
        script_name="missing.py",
        workspace_root=tmp_path,
    )
    assert out["status"] == "error"
    assert "not found" in out["error"].lower()


def test_path_traversal_blocked(tmp_path):
    _make_skill(tmp_path, "demo-skill", "ok.py", "print('{}')\n")
    out = execute_skill_script(
        skill_name="demo-skill",
        script_name="../../../etc/hosts.py",
        workspace_root=tmp_path,
    )
    assert out["status"] == "error"
    assert "bare filename" in out["error"].lower() or "path component" in out["error"].lower()


def test_non_py_extension_blocked(tmp_path):
    _make_skill(tmp_path, "demo-skill", "ok.py", "print('{}')\n")
    out = execute_skill_script(
        skill_name="demo-skill",
        script_name="ok.sh",
        workspace_root=tmp_path,
    )
    assert out["status"] == "error"
    assert ".py" in out["error"]


def test_symlink_escape_blocked(tmp_path):
    """Symlink inside scripts/ pointing outside is rejected."""
    skill_dir = _make_skill(tmp_path, "demo-skill", "ok.py", "print('{}')\n")
    target = tmp_path / "outside.py"
    target.write_text("print('escape')\n")
    link = skill_dir / "scripts" / "escape.py"
    link.symlink_to(target)

    out = execute_skill_script(
        skill_name="demo-skill",
        script_name="escape.py",
        workspace_root=tmp_path,
    )
    assert out["status"] == "error"
    assert "escapes" in out["error"].lower()


# --- timeout ----------------------------------------------------------------


def test_timeout_enforced(tmp_path):
    _make_skill(
        tmp_path,
        "demo-skill",
        "slow.py",
        "import time; time.sleep(5)\n",
    )
    out = execute_skill_script(
        skill_name="demo-skill",
        script_name="slow.py",
        timeout=1,
        workspace_root=tmp_path,
    )
    assert out["status"] == "error"
    assert "timed out" in out["error"].lower()


# --- argv mode (third-party / argparse-compatible scripts) ------------------


def _make_skill_argv(tmp_path: Path, skill_name: str, script_name: str, body: str) -> Path:
    """Like _make_skill but declares ``argv: true`` in the scripts entry."""
    skill_dir = tmp_path / skill_name
    (skill_dir / "scripts").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {skill_name}\ndescription: Test argv skill\n"
        f"scripts:\n  - name: run\n    file: {script_name}\n    argv: true\n---\n",
        encoding="utf-8",
    )
    (skill_dir / "scripts" / script_name).write_text(body, encoding="utf-8")
    return skill_dir


def test_argv_mode_passes_args_as_cli_flags(tmp_path):
    """argv: true → args arrive as --key value pairs in sys.argv."""
    _make_skill_argv(
        tmp_path,
        "third-party",
        "greet.py",
        "import argparse, json\n"
        "p = argparse.ArgumentParser()\n"
        "p.add_argument('--name'); p.add_argument('--count')\n"
        "a = p.parse_args()\n"
        "print(json.dumps({'name': a.name, 'count': a.count}))\n",
    )
    out = execute_skill_script(
        skill_name="third-party",
        script_name="greet.py",
        args={"name": "OLAV", "count": "3"},
        workspace_root=tmp_path,
    )
    assert out["status"] == "ok"
    assert out["stdout"] == {"name": "OLAV", "count": "3"}


def test_argv_mode_complex_value_json_serialised(tmp_path):
    """List/dict values in argv mode are passed as JSON strings."""
    _make_skill_argv(
        tmp_path,
        "third-party",
        "listarg.py",
        "import argparse, json\n"
        "p = argparse.ArgumentParser()\n"
        "p.add_argument('--items')\n"
        "a = p.parse_args()\n"
        "print(json.dumps({'items': json.loads(a.items)}))\n",
    )
    out = execute_skill_script(
        skill_name="third-party",
        script_name="listarg.py",
        args={"items": ["a", "b", "c"]},
        workspace_root=tmp_path,
    )
    assert out["status"] == "ok"
    assert out["stdout"] == {"items": ["a", "b", "c"]}


def test_argv_mode_no_args_script_still_runs(tmp_path):
    """Script that ignores all args works fine in argv mode."""
    _make_skill_argv(
        tmp_path,
        "third-party",
        "noargs.py",
        "import json; print(json.dumps({'status': 'ok'}))\n",
    )
    out = execute_skill_script(
        skill_name="third-party",
        script_name="noargs.py",
        args={"ignored": "value"},
        workspace_root=tmp_path,
    )
    assert out["status"] == "ok"
    assert out["stdout"]["status"] == "ok"


def test_default_mode_unchanged_when_argv_false_explicit(tmp_path):
    """Explicit argv: false falls back to JSON stdin (OLAV native)."""
    skill_dir = tmp_path / "native-skill"
    (skill_dir / "scripts").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: native-skill\ndescription: native\n"
        "scripts:\n  - name: run\n    file: echo.py\n    argv: false\n---\n",
        encoding="utf-8",
    )
    (skill_dir / "scripts" / "echo.py").write_text(
        "import json, sys\n"
        "args = json.loads(sys.stdin.read() or '{}')\n"
        "print(json.dumps({'got': args}))\n",
        encoding="utf-8",
    )
    out = execute_skill_script(
        skill_name="native-skill",
        script_name="echo.py",
        args={"key": "val"},
        workspace_root=tmp_path,
    )
    assert out["status"] == "ok"
    assert out["stdout"] == {"got": {"key": "val"}}
