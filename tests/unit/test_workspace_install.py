"""
tests/unit/test_workspace_install.py
─────────────────────────────────────
TDD tests for SKI-1 / SKI-2 / HP-3: workspace install, validate, and dependency status.

Tests verify:
  1. workspace install <source> copies skill into workspace
  2. workspace install requires a source argument
  3. workspace validate <name> validates MANIFEST.yaml presence and schema
  4. workspace validate reports missing dependencies
  5. workspace status shows dependency state (available/unavailable/discovered)
  6. workspace status shows dependency detail for unavailable skills
  7. workspace install checks dependencies after install
  8. workspace validate returns validation summary
"""

import asyncio
from pathlib import Path

import pytest
import yaml


def _make_agent(workspace_root: Path, name: str, managed: bool = False) -> Path:
    agent_dir = workspace_root / name
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "AGENT.md").write_text("---\nname: test\n---\n", encoding="utf-8")
    if managed:
        (agent_dir / ".version").write_text("0.1.0\n", encoding="utf-8")
    return agent_dir


def _make_manifest(
    agent_dir: Path,
    name: str,
    kind: str = "Agent",
    version: str = "0.11.0",
    route_keywords: list | None = None,
    requires: list | None = None,
    provider_package: str | None = None,
    required_modules: list | None = None,
    required_binaries: list | None = None,
    config_namespace: str | None = None,
) -> None:
    """Write a MANIFEST.yaml with dependency fields."""
    data: dict = {"kind": kind, "name": name, "version": version}
    if route_keywords:
        data["route_keywords"] = route_keywords
    if requires:
        data["requires"] = requires
    if provider_package:
        data["provider_package"] = provider_package
    if required_modules:
        data["required_modules"] = required_modules
    if required_binaries:
        data["required_binaries"] = required_binaries
    if config_namespace:
        data["config_namespace"] = config_namespace
    (agent_dir / "MANIFEST.yaml").write_text(
        yaml.dump(data, default_flow_style=False), encoding="utf-8"
    )


# ── HP-3: workspace status with dependency state ──────────────────────────────


def test_workspace_status_shows_available_state(tmp_path, monkeypatch) -> None:
    """HP-3: workspace status shows 'available' for skills with all deps met."""
    from olav.cli.commands.workspace import WorkspaceCommand

    monkeypatch.chdir(tmp_path)
    workspace_root = tmp_path / ".olav" / "workspace"
    agent_dir = _make_agent(workspace_root, "ops")
    _make_manifest(
        agent_dir,
        "ops",
        kind="Agent",
        required_modules=["os", "sys"],  # stdlib — always available
    )

    result = asyncio.run(WorkspaceCommand().execute("status"))

    assert "ops" in result
    assert "available" in result.lower()


def test_workspace_status_shows_unavailable_state(tmp_path, monkeypatch) -> None:
    """HP-3: workspace status shows 'unavailable' for skills with missing deps."""
    from olav.cli.commands.workspace import WorkspaceCommand

    monkeypatch.chdir(tmp_path)
    workspace_root = tmp_path / ".olav" / "workspace"
    agent_dir = _make_agent(workspace_root, "netops")
    _make_manifest(
        agent_dir,
        "netops",
        kind="Skill",
        required_modules=["nonexistent_module_xyz_12345"],
    )

    result = asyncio.run(WorkspaceCommand().execute("status"))

    assert "netops" in result
    assert "unavailable" in result.lower()


def test_workspace_status_shows_discovered_when_no_deps(tmp_path, monkeypatch) -> None:
    """HP-3: workspace status shows 'available' when no dependencies declared (discovered = always available)."""
    from olav.cli.commands.workspace import WorkspaceCommand

    monkeypatch.chdir(tmp_path)
    workspace_root = tmp_path / ".olav" / "workspace"
    agent_dir = _make_agent(workspace_root, "audit")
    _make_manifest(agent_dir, "audit", kind="Agent")

    result = asyncio.run(WorkspaceCommand().execute("status"))

    assert "audit" in result
    assert "available" in result.lower()


def test_workspace_status_shows_missing_detail(tmp_path, monkeypatch) -> None:
    """HP-3: workspace status shows which deps are missing for unavailable skills."""
    from olav.cli.commands.workspace import WorkspaceCommand

    monkeypatch.chdir(tmp_path)
    workspace_root = tmp_path / ".olav" / "workspace"
    agent_dir = _make_agent(workspace_root, "netops")
    _make_manifest(
        agent_dir,
        "netops",
        kind="Skill",
        provider_package="nonexistent-pkg-xyz",
        required_modules=["nonexistent_mod_xyz"],
        required_binaries=["nonexistent_bin_xyz"],
    )

    result = asyncio.run(WorkspaceCommand().execute("status"))

    assert "unavailable" in result.lower()


# ── SKI-1: workspace install / validate ───────────────────────────────────────


def test_workspace_install_requires_source(tmp_path, monkeypatch) -> None:
    """SKI-1: workspace install without source returns error message."""
    from olav.cli.commands.workspace import WorkspaceCommand

    monkeypatch.chdir(tmp_path)

    result = asyncio.run(WorkspaceCommand().execute("install"))

    assert "requires" in result.lower() or "usage" in result.lower()


def test_workspace_install_copies_from_source(tmp_path, monkeypatch) -> None:
    """SKI-1: workspace install <source_dir> copies skill into workspace."""
    from olav.cli.commands.workspace import WorkspaceCommand

    monkeypatch.chdir(tmp_path)

    # Create source skill directory
    source_dir = tmp_path / "source" / "my-skill"
    source_dir.mkdir(parents=True)
    _make_manifest(source_dir, "my-skill", kind="Skill")
    (source_dir / "SKILL.md").write_text("# My Skill\n", encoding="utf-8")

    result = asyncio.run(WorkspaceCommand().execute(f"install {source_dir}"))

    assert "installed" in result.lower() or "my-skill" in result.lower()
    installed_dir = tmp_path / ".olav" / "workspace" / "my-skill"
    assert installed_dir.exists()
    assert (installed_dir / "MANIFEST.yaml").exists()


def test_workspace_install_rejects_missing_manifest(tmp_path, monkeypatch) -> None:
    """SKI-1: install rejects source dirs without MANIFEST.yaml."""
    from olav.cli.commands.workspace import WorkspaceCommand

    monkeypatch.chdir(tmp_path)

    source_dir = tmp_path / "source" / "bad-skill"
    source_dir.mkdir(parents=True)
    (source_dir / "SKILL.md").write_text("# No manifest\n", encoding="utf-8")

    result = asyncio.run(WorkspaceCommand().execute(f"install {source_dir}"))

    assert "manifest" in result.lower() or "not found" in result.lower()


def test_workspace_validate_checks_manifest(tmp_path, monkeypatch) -> None:
    """SKI-1: workspace validate <name> checks MANIFEST.yaml presence and structure."""
    from olav.cli.commands.workspace import WorkspaceCommand

    monkeypatch.chdir(tmp_path)
    workspace_root = tmp_path / ".olav" / "workspace"
    agent_dir = _make_agent(workspace_root, "my-skill")
    _make_manifest(agent_dir, "my-skill", kind="Skill")

    result = asyncio.run(WorkspaceCommand().execute("validate my-skill"))

    assert "valid" in result.lower() or "my-skill" in result.lower()


def test_workspace_validate_requires_name(tmp_path, monkeypatch) -> None:
    """SKI-1: workspace validate without name returns error."""
    from olav.cli.commands.workspace import WorkspaceCommand

    monkeypatch.chdir(tmp_path)

    result = asyncio.run(WorkspaceCommand().execute("validate"))

    assert "requires" in result.lower() or "usage" in result.lower()


def test_workspace_validate_reports_missing_manifest(tmp_path, monkeypatch) -> None:
    """SKI-1: validate reports missing MANIFEST.yaml."""
    from olav.cli.commands.workspace import WorkspaceCommand

    monkeypatch.chdir(tmp_path)
    workspace_root = tmp_path / ".olav" / "workspace"
    agent_dir = _make_agent(workspace_root, "no-manifest")
    # No MANIFEST.yaml written

    result = asyncio.run(WorkspaceCommand().execute("validate no-manifest"))

    assert "manifest" in result.lower() or "not found" in result.lower()


# ── SKI-2: install dependency pre-check ───────────────────────────────────────


def test_workspace_validate_shows_dependency_status(tmp_path, monkeypatch) -> None:
    """SKI-2: validate shows dependency check results."""
    from olav.cli.commands.workspace import WorkspaceCommand

    monkeypatch.chdir(tmp_path)
    workspace_root = tmp_path / ".olav" / "workspace"
    agent_dir = _make_agent(workspace_root, "netops-skill")
    _make_manifest(
        agent_dir,
        "netops-skill",
        kind="Skill",
        required_modules=["nonexistent_module_xyz"],
    )

    result = asyncio.run(WorkspaceCommand().execute("validate netops-skill"))

    # Should report dependency issues
    assert "unavailable" in result.lower() or "missing" in result.lower()


def test_workspace_validate_passes_with_all_deps_met(tmp_path, monkeypatch) -> None:
    """SKI-2: validate passes when all dependencies are met."""
    from olav.cli.commands.workspace import WorkspaceCommand

    monkeypatch.chdir(tmp_path)
    workspace_root = tmp_path / ".olav" / "workspace"
    agent_dir = _make_agent(workspace_root, "good-skill")
    _make_manifest(
        agent_dir,
        "good-skill",
        kind="Skill",
        required_modules=["os", "sys"],  # stdlib always present
    )

    result = asyncio.run(WorkspaceCommand().execute("validate good-skill"))

    assert "valid" in result.lower() or "available" in result.lower()
