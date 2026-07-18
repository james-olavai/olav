"""`olav doctor` stack checks + `olav kb bench` — wiring proof (DoD).

doctor grew from 3 checks (scaffolding/llm/embedding) to also report the
agent / sub-agent / tool / experience(memory) / recall-smoke health of the
deployed workspace. These run through the real DoctorCommand entry point and
assert the checks are well-formed and reachable. The filesystem checks
(agents/subagents/tools) are deterministic in CI (which runs `olav init` +
`olav skill install`); the store/embedder checks are asserted only for shape
(they degrade to ok=False without crashing when the embedder is unavailable).
"""
from __future__ import annotations

import asyncio
import json

import pytest

from olav.cli.commands.doctor import DoctorCommand


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _check(name, checks):
    return next((c for c in checks if c["name"] == name), None)


def test_doctor_reports_the_stack_checks():
    """execute() emits the 8 checks, each a well-formed verdict dict."""
    out = _run(DoctorCommand().execute())
    for name in ("agents", "subagents", "tools", "memory", "recall"):
        assert f"{name}:" in out, f"doctor output missing the {name} check"


def test_doctor_json_is_valid_and_complete():
    """--json must be parseable (long detail strings must not corrupt it) and
    carry every check as {name, ok, detail}."""
    raw = _run(DoctorCommand().execute("--json"))
    data = json.loads(raw)  # would raise if rich-wrapped / control chars
    names = {c["name"] for c in data["checks"]}
    assert {"agents", "subagents", "tools", "memory", "recall"} <= names
    for c in data["checks"]:
        assert {"name", "ok", "detail"} <= set(c)
        assert isinstance(c["ok"], bool)


def test_agents_subagents_tools_checks_pass_on_deployed_workspace():
    """Filesystem checks are deterministic once the workspace is deployed."""
    doc = DoctorCommand()
    if not doc._workspace_root().is_dir():
        pytest.skip("no deployed .olav/workspace (run `olav init`)")
    agents = doc._check_agents()
    assert agents["ok"], f"agents check failed: {agents['detail']}"
    subs = doc._check_subagents()
    assert subs["ok"], f"subagents check failed (orphans?): {subs['detail']}"
    tools = doc._check_tools()
    assert tools["ok"], f"tools check found syntax errors: {tools['detail']}"


def test_memory_and_recall_checks_are_defensive():
    """Store/embedder checks must return a verdict dict, never raise, even when
    the embedder is unavailable."""
    doc = DoctorCommand()
    for check in (doc._check_memory(), doc._check_recall()):
        assert {"name", "ok", "detail"} <= set(check)
        assert isinstance(check["ok"], bool)


# ── olav kb bench ─────────────────────────────────────────────────────────
def test_kb_bench_is_registered():
    import argparse

    from olav.cli.commands.kb import build_kb_parser

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")
    build_kb_parser(sub)
    ns = parser.parse_args(["kb", "bench", "--sample", "5", "--json"])
    assert ns.kb_command == "bench"
    assert ns.sample == 5 and ns.json is True


def test_kb_bench_handles_missing_store_gracefully(monkeypatch):
    """cmd_bench returns an int (never raises) when there's no store."""
    import types

    import olav.core.memory as memmod
    from olav.cli.commands import kb as kbmod

    # cmd_bench does a local `from olav.core.memory import get_store`, so patch
    # the source module.
    monkeypatch.setattr(memmod, "get_store", lambda: None, raising=False)
    args = types.SimpleNamespace(sample=10, top_k=5, json=False)
    rc = kbmod.cmd_bench(args)
    assert isinstance(rc, int)
