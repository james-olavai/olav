"""workspace upgrade real source integration tests.

The upgrade command should resolve the upstream version from real package
metadata (importlib.metadata / pip) when no .upstream-version file exists,
and fall back gracefully if no package provides the agent.

Real source priority:
1. .upstream-version file (explicit override — highest priority)
2. importlib.metadata for "olav-workspace-{agent}" or "olav" package
3. pyproject.toml / installed olav package version (platform fallback)
4. Warn + no-op if nothing found
"""

import asyncio
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_service(tmp_path: Path, agent_name: str, version: str = "1.0.0") -> Path:
    """Create a minimal managed agent workspace entry."""
    agent_dir = tmp_path / "workspace" / agent_name
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "AGENT.md").write_text("---\nname: test\n---\n", encoding="utf-8")
    (agent_dir / ".version").write_text(f"{version}\n", encoding="utf-8")
    return agent_dir


def _run_upgrade(tmp_path: Path, agent_name: str) -> str:
    from olav.cli.commands.workspace import WorkspaceCommand
    cmd = WorkspaceCommand()
    cmd.workspace_root = tmp_path / "workspace"
    return asyncio.run(cmd.execute(f"upgrade {agent_name}"))


# ---------------------------------------------------------------------------
# .upstream-version file still takes highest priority
# ---------------------------------------------------------------------------

def test_upgrade_uses_upstream_version_file_when_present(tmp_path: Path) -> None:
    agent_dir = _make_service(tmp_path, "quick", "1.0.0")
    (agent_dir / ".upstream-version").write_text("1.1.0\n", encoding="utf-8")

    result = _run_upgrade(tmp_path, "quick")

    assert "1.0.0" in result
    assert "1.1.0" in result
    assert (agent_dir / ".version").read_text().strip() == "1.1.0"


# ---------------------------------------------------------------------------
# No .upstream-version → resolve from package metadata
# ---------------------------------------------------------------------------

def test_upgrade_resolves_from_package_metadata(tmp_path: Path, monkeypatch) -> None:
    """When no .upstream-version file, fetch version from importlib.metadata."""
    agent_dir = _make_service(tmp_path, "ops", "0.9.0")

    # Patch importlib.metadata.version to return a known version
    import importlib.metadata as meta
    monkeypatch.setattr(meta, "version", lambda pkg: "2.0.0" if pkg == "olav" else (_ for _ in ()).throw(meta.PackageNotFoundError(pkg)))

    result = _run_upgrade(tmp_path, "ops")

    assert "2.0.0" in result
    assert (agent_dir / ".version").read_text().strip() == "2.0.0"


def test_upgrade_checks_agent_specific_package_first(tmp_path: Path, monkeypatch) -> None:
    """Check for olav-workspace-{agent} package before falling back to olav."""
    agent_dir = _make_service(tmp_path, "audit", "1.0.0")

    import importlib.metadata as meta
    def _mock_version(pkg: str) -> str:
        if pkg == "olav-workspace-audit":
            return "3.0.0"
        if pkg == "olav":
            return "2.0.0"
        raise meta.PackageNotFoundError(pkg)
    monkeypatch.setattr(meta, "version", _mock_version)

    result = _run_upgrade(tmp_path, "audit")

    assert "3.0.0" in result


# ---------------------------------------------------------------------------
# Graceful handling when package not found
# ---------------------------------------------------------------------------

def test_upgrade_warns_gracefully_when_no_package_found(tmp_path: Path, monkeypatch) -> None:
    """No .upstream-version and no installed package → warn, do not change version."""
    agent_dir = _make_service(tmp_path, "myagent", "1.0.0")

    import importlib.metadata as meta
    monkeypatch.setattr(meta, "version", lambda pkg: (_ for _ in ()).throw(meta.PackageNotFoundError(pkg)))

    result = _run_upgrade(tmp_path, "myagent")

    # Version unchanged
    assert (agent_dir / ".version").read_text().strip() == "1.0.0"
    # Human-readable warning in result
    assert any(word in result.lower() for word in ("no upstream", "not found", "warn", "up-to-date", "already")), (
        f"Expected graceful message, got: {result!r}"
    )


# ---------------------------------------------------------------------------
# WorkspaceCommand has _resolve_upstream_version() method
# ---------------------------------------------------------------------------

def test_workspace_command_has_resolve_upstream_version(tmp_path: Path) -> None:
    from olav.cli.commands.workspace import WorkspaceCommand
    cmd = WorkspaceCommand()
    assert hasattr(cmd, "_resolve_upstream_version"), (
        "WorkspaceCommand must have a _resolve_upstream_version(agent_name) method"
    )
