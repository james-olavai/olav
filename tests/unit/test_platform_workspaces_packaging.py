"""Governance tests for platform workspace packaging.

ISSUE-SERVICES-AGENT-NOT-PACKAGED: a fresh wheel install must include
every platform agent workspace under ``src/olav/data/workspace/`` so
``olav init`` can deploy them. Without this guard, future agents added
to ``src/olav/data/workspace/<name>/`` could silently fall out of the
wheel and demo runsheet steps would mysteriously fail.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_SRC = REPO_ROOT / "src" / "olav" / "data" / "workspace"


def _expected_platform_agents() -> set[str]:
    """Top-level dirs under ``src/olav/data/workspace/`` are the platform
    agents that must ship in the wheel. Skip dunder / hidden entries."""
    if not WORKSPACE_SRC.is_dir():
        pytest.skip(f"workspace source not found at {WORKSPACE_SRC}")
    return {
        p.name for p in WORKSPACE_SRC.iterdir()
        if p.is_dir() and not p.name.startswith((".", "_"))
    }


def _wheel_path() -> Path | None:
    """Find the most recent olav-*.whl under dist/."""
    dist = REPO_ROOT / "dist"
    if not dist.is_dir():
        return None
    wheels = sorted(dist.glob("olav-*-py3-none-any.whl"))
    return wheels[-1] if wheels else None


def test_platform_workspaces_source_includes_services():
    """services/ must be in the packaging source. Catches the original
    bug: services lived only in ``.olav/workspace/services/`` (dev runtime)
    and never made it into the wheel."""
    agents = _expected_platform_agents()
    assert "services" in agents, (
        "services/ must exist in src/olav/data/workspace/ to ship in wheel"
    )


def test_platform_workspaces_source_includes_core():
    """Always-required platform agent."""
    agents = _expected_platform_agents()
    assert "core" in agents


def test_wheel_contains_all_platform_workspace_agents():
    """If a wheel exists in dist/, every src-tree agent must appear in it.
    Skipped when no wheel built."""
    wheel = _wheel_path()
    if wheel is None:
        pytest.skip("no wheel in dist/ — run `uv build` first")
    expected = _expected_platform_agents()
    assert expected, "no platform agents in src — packaging source empty?"

    with zipfile.ZipFile(wheel) as z:
        names = z.namelist()
    in_wheel = set()
    for n in names:
        # olav/data/workspace/<agent>/...
        parts = n.split("/")
        if len(parts) >= 4 and parts[:3] == ["olav", "data", "workspace"]:
            agent = parts[3]
            if agent and not agent.startswith((".", "_")):
                in_wheel.add(agent)

    missing = expected - in_wheel
    assert not missing, (
        f"wheel {wheel.name} is missing platform agents from src tree: "
        f"{sorted(missing)}. The hatch build excludes them — check "
        f"`tool.hatch.build.targets.wheel.packages` and ensure each "
        f"`src/olav/data/workspace/<agent>/` is reachable."
    )


def test_each_agent_workspace_has_agent_md():
    """Every shipped platform agent dir must have SKILL.md or AGENT.md so
    the registry can find it. Catches an empty / partial copy."""
    agents = _expected_platform_agents()
    for name in agents:
        skill_md = WORKSPACE_SRC / name / "SKILL.md"
        agent_md = WORKSPACE_SRC / name / "AGENT.md"
        assert skill_md.is_file() or agent_md.is_file(), (
            f"src/olav/data/workspace/{name}/ ships in wheel but is "
            f"missing SKILL.md/AGENT.md — agent registry will not detect it"
        )
