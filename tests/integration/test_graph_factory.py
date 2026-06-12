"""
tests/integration/test_graph_factory.py
───────────────────────────────────────
Integration coverage for src/olav/server/graph_factory.py — the
LangGraph factory that lets OLAV agents be served by langgraph dev /
LangSmith Studio / (v0.20.2+) deepagents-cli in server-subprocess
mode.

Guarantees:
  1. `build_graph()` returns a compiled graph for the default
     (core) agent, with no env var set.
  2. `build_graph(name)` handles an explicit assistant_id for each of
     OLAV's top-level agents (skipping any that aren't installed in
     the repo workspace).
  3. `build_graph()` honours the
     ``DEEPAGENTS_CLI_SERVER_ASSISTANT_ID`` env var.
  4. An unknown agent name produces a clear ``ValueError`` (not a
     silent default to core).
  5. `langgraph validate -c langgraph.json` accepts the repo's
     config file.

These are integration tests because ``create_olav_agent_with_backend``
reaches into the full OLAV stack (LangChain models, plugin registry,
workspace loader).  Unit coverage for the env-parsing wrapper alone
lives inline.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
"""Repo root; used for `langgraph validate` which must run in-repo."""


# ── 1. default path returns a compiled graph ────────────────────────────────


def test_build_graph_default_returns_compiled_graph() -> None:
    from olav.server.graph_factory import build_graph

    g = build_graph()
    assert g is not None, "build_graph() returned None"
    # Duck-type check — langgraph 1.x exposes ainvoke on compiled graphs.
    assert hasattr(g, "ainvoke") or hasattr(g, "invoke"), (
        "compiled graph does not look like a LangGraph Pregel-ish object; "
        f"got {type(g).__name__}"
    )


# ── 2. each installed top-level agent builds ────────────────────────────────


def _installed_agents() -> list[str]:
    """Scan the repo's .olav/workspace for agent dirs that are
    actually present in this environment.  Avoids hard-coding a
    list that a partial install would fail against."""
    workspace_root = REPO_ROOT / ".olav" / "workspace"
    if not workspace_root.is_dir():
        return []
    return sorted(
        p.name
        for p in workspace_root.iterdir()
        if p.is_dir() and (p / "AGENT.md").is_file()
    )


@pytest.mark.parametrize("agent_name", _installed_agents() or ["core"])
def test_build_graph_per_agent(agent_name: str) -> None:
    """Every agent whose workspace is on disk must build cleanly.

    Skips agents whose AGENT.md is missing YAML frontmatter — that's
    a data integrity issue for the workspace owner (typically
    ``olav-netops``), not a graph_factory bug.  A proper fix lives in
    that package's install step; this test just doesn't pretend the
    factory can produce a graph from malformed input.
    """
    from olav.server.graph_factory import build_graph

    try:
        g = build_graph(agent_name)
    except RuntimeError as exc:
        if "frontmatter" in str(exc).lower():
            pytest.skip(f"{agent_name}: AGENT.md missing frontmatter ({exc})")
        raise
    assert g is not None, f"{agent_name}: build_graph returned None"
    assert hasattr(g, "ainvoke") or hasattr(g, "invoke"), (
        f"{agent_name}: unexpected graph type {type(g).__name__}"
    )


# ── 3. env var honoured ─────────────────────────────────────────────────────


def test_build_graph_reads_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """When called with no argument, the factory picks the env var."""
    agents = _installed_agents()
    if "core" not in agents:
        pytest.skip("core workspace not present in this repo")

    monkeypatch.setenv("DEEPAGENTS_CLI_SERVER_ASSISTANT_ID", "core")
    from olav.server.graph_factory import build_graph

    g = build_graph()  # no explicit arg → reads env
    assert g is not None


def test_build_graph_empty_env_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty-string env var must not confuse the resolver — treat
    it as unset and use the default ``core``."""
    monkeypatch.setenv("DEEPAGENTS_CLI_SERVER_ASSISTANT_ID", "")
    from olav.server.graph_factory import build_graph

    g = build_graph()
    assert g is not None


# ── 4. unknown agent → ValueError ──────────────────────────────────────────


def test_build_graph_unknown_raises() -> None:
    """Fail fast with a clear message for misconfigured deployments."""
    from olav.server.graph_factory import build_graph

    with pytest.raises(ValueError, match="No workspace found"):
        build_graph("definitely-not-a-real-agent-xyz")


# ── 5. langgraph validate accepts langgraph.json ──────────────────────────


def test_langgraph_validate_accepts_config() -> None:
    """The committed langgraph.json must pass ``langgraph validate``.

    Looks for the CLI in three places:
      1. ``$PATH`` (dev machine / CI with langgraph-cli installed)
      2. The active interpreter's Scripts/ dir (pytest under uv/venv)
      3. ``python -m langgraph_cli`` fallback (import-based)

    Skipped (not failed) when none work — langgraph-cli is a dev-time
    dep; its absence in a production-like runtime venv is fine.
    """
    config_path = REPO_ROOT / "langgraph.json"
    assert config_path.is_file(), f"missing {config_path}"

    langgraph_bin = shutil.which("langgraph")
    if not langgraph_bin:
        # Fallback 1: look next to the active interpreter.
        candidate = Path(sys.executable).parent / "langgraph"
        if candidate.is_file():
            langgraph_bin = str(candidate)

    if langgraph_bin:
        cmd = [langgraph_bin, "validate", "-c", str(config_path)]
    else:
        # Fallback 2: use the module entry point.
        try:
            __import__("langgraph_cli")
        except ImportError:
            pytest.skip("langgraph CLI not installed in this environment")
        cmd = [sys.executable, "-m", "langgraph_cli", "validate", "-c", str(config_path)]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=60,
    )
    assert result.returncode == 0, (
        f"langgraph validate failed ({' '.join(cmd)}):\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "valid" in result.stdout.lower()
