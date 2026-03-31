import asyncio
from pathlib import Path


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
) -> None:
    """Write a minimal MANIFEST.yaml into agent_dir."""
    import yaml

    data = {"kind": kind, "name": name, "version": version, "route_keywords": route_keywords or []}
    if requires:
        data["requires"] = requires
    (agent_dir / "MANIFEST.yaml").write_text(
        yaml.dump(data, default_flow_style=False), encoding="utf-8"
    )


def test_workspace_status_reports_agent_state(tmp_path, monkeypatch) -> None:
    from olav.cli.commands.workspace import WorkspaceCommand

    monkeypatch.chdir(tmp_path)
    workspace_root = tmp_path / ".olav" / "workspace"
    managed_agent = _make_agent(workspace_root, "quick", managed=True)
    (managed_agent / ".disabled").write_text("disabled\n", encoding="utf-8")
    _make_agent(workspace_root, "audit", managed=False)

    result = asyncio.run(WorkspaceCommand().execute("status"))

    assert "quick" in result
    assert "managed" in result
    assert "disabled" in result
    assert "audit" in result
    assert "user" in result


# ── MANIFEST-aware status tests ───────────────────────────────────────────────


def test_workspace_status_shows_manifest_kind(tmp_path, monkeypatch) -> None:
    """status should show kind (Agent/Skill) from MANIFEST.yaml."""
    from olav.cli.commands.workspace import WorkspaceCommand

    monkeypatch.chdir(tmp_path)
    workspace_root = tmp_path / ".olav" / "workspace"
    agent_dir = _make_agent(workspace_root, "ops")
    _make_manifest(agent_dir, "ops", kind="Agent")

    result = asyncio.run(WorkspaceCommand().execute("status"))

    assert "ops" in result
    assert "Agent" in result


def test_workspace_status_shows_manifest_version(tmp_path, monkeypatch) -> None:
    """status should show version from MANIFEST.yaml."""
    from olav.cli.commands.workspace import WorkspaceCommand

    monkeypatch.chdir(tmp_path)
    workspace_root = tmp_path / ".olav" / "workspace"
    agent_dir = _make_agent(workspace_root, "audit")
    _make_manifest(agent_dir, "audit", version="0.12.0")

    result = asyncio.run(WorkspaceCommand().execute("status"))

    assert "0.12.0" in result


def test_workspace_status_shows_route_keywords_count(tmp_path, monkeypatch) -> None:
    """status should show the number of route_keywords."""
    from olav.cli.commands.workspace import WorkspaceCommand

    monkeypatch.chdir(tmp_path)
    workspace_root = tmp_path / ".olav" / "workspace"
    agent_dir = _make_agent(workspace_root, "ops")
    _make_manifest(agent_dir, "ops", route_keywords=["troubleshoot", "probe", "diff"])

    result = asyncio.run(WorkspaceCommand().execute("status"))

    assert "3" in result  # 3 route_keywords


def test_workspace_status_disabled_shown_with_manifest(tmp_path, monkeypatch) -> None:
    """MANIFEST-aware status must still reflect disabled flag."""
    from olav.cli.commands.workspace import WorkspaceCommand

    monkeypatch.chdir(tmp_path)
    workspace_root = tmp_path / ".olav" / "workspace"
    agent_dir = _make_agent(workspace_root, "ops")
    _make_manifest(agent_dir, "ops", kind="Agent")
    (agent_dir / ".disabled").write_text("disabled\n", encoding="utf-8")

    result = asyncio.run(WorkspaceCommand().execute("status"))

    assert "disabled" in result


def test_workspace_status_no_manifest_falls_back(tmp_path, monkeypatch) -> None:
    """Agents without MANIFEST.yaml still appear in status (no crash)."""
    from olav.cli.commands.workspace import WorkspaceCommand

    monkeypatch.chdir(tmp_path)
    workspace_root = tmp_path / ".olav" / "workspace"
    _make_agent(workspace_root, "legacy", managed=False)  # no MANIFEST.yaml

    result = asyncio.run(WorkspaceCommand().execute("status"))

    assert "legacy" in result


def test_workspace_status_shows_requires_source(tmp_path, monkeypatch) -> None:
    """status shows the first package in requires as 'source'."""
    from olav.cli.commands.workspace import WorkspaceCommand

    monkeypatch.chdir(tmp_path)
    workspace_root = tmp_path / ".olav" / "workspace"
    agent_dir = _make_agent(workspace_root, "ops")
    _make_manifest(agent_dir, "ops", requires=["olav-netops>=0.11"])

    result = asyncio.run(WorkspaceCommand().execute("status"))

    assert "olav-netops" in result


def test_workspace_disable_marks_agent_disabled(tmp_path, monkeypatch) -> None:
    from olav.cli.commands.workspace import WorkspaceCommand

    monkeypatch.chdir(tmp_path)
    workspace_root = tmp_path / ".olav" / "workspace"
    agent_dir = _make_agent(workspace_root, "quick", managed=True)

    result = asyncio.run(WorkspaceCommand().execute("disable quick"))

    assert "disabled" in result
    assert (agent_dir / ".disabled").exists()


def test_workspace_upgrade_updates_managed_version(tmp_path, monkeypatch) -> None:
    from olav.cli.commands.workspace import WorkspaceCommand

    monkeypatch.chdir(tmp_path)
    workspace_root = tmp_path / ".olav" / "workspace"
    agent_dir = _make_agent(workspace_root, "quick", managed=True)
    (agent_dir / ".upstream-version").write_text("0.2.0\n", encoding="utf-8")

    result = asyncio.run(WorkspaceCommand().execute("upgrade quick"))

    assert "0.2.0" in result
    assert (agent_dir / ".version").read_text(encoding="utf-8").strip() == "0.2.0"


def test_workspace_remove_only_allows_managed_agents(tmp_path, monkeypatch) -> None:
    from olav.cli.commands.workspace import WorkspaceCommand

    monkeypatch.chdir(tmp_path)
    workspace_root = tmp_path / ".olav" / "workspace"
    _make_agent(workspace_root, "quick", managed=True)
    _make_agent(workspace_root, "audit", managed=False)
    cmd = WorkspaceCommand()

    remove_result = asyncio.run(cmd.execute("remove quick"))
    assert "removed" in remove_result
    assert not (workspace_root / "quick").exists()

    denied_result = asyncio.run(cmd.execute("remove audit"))
    assert "refusing" in denied_result
    assert (workspace_root / "audit").exists()


def test_workspace_rollback_restores_from_archive(tmp_path, monkeypatch) -> None:
    from olav.cli.commands.workspace import WorkspaceCommand

    monkeypatch.chdir(tmp_path)
    archive_root = tmp_path / "archive"
    archived_agent = _make_agent(archive_root, "quick", managed=True)
    (archived_agent / "SKILL.md").write_text("skill\n", encoding="utf-8")

    result = asyncio.run(WorkspaceCommand().execute(f"rollback quick --from {archive_root}"))

    restored_agent = tmp_path / ".olav" / "workspace" / "quick"
    assert "restored" in result
    assert (restored_agent / "AGENT.md").exists()
    assert (restored_agent / "SKILL.md").exists()


def test_workspace_install_denied_for_user_role(tmp_path, monkeypatch) -> None:
    from olav.cli.commands.workspace import WorkspaceCommand

    monkeypatch.chdir(tmp_path)
    source_dir = tmp_path / "pkg"
    source_dir.mkdir()
    (source_dir / "MANIFEST.yaml").write_text(
        "kind: Skill\nname: pkg\nversion: '0.1.0'\n", encoding="utf-8"
    )

    result = asyncio.run(WorkspaceCommand().execute(f"install {source_dir}", role="user"))
    assert "denied" in result


def test_workspace_install_denied_for_readonly_role(tmp_path, monkeypatch) -> None:
    from olav.cli.commands.workspace import WorkspaceCommand

    monkeypatch.chdir(tmp_path)
    source_dir = tmp_path / "pkg"
    source_dir.mkdir()
    (source_dir / "MANIFEST.yaml").write_text(
        "kind: Skill\nname: pkg\nversion: '0.1.0'\n", encoding="utf-8"
    )

    result = asyncio.run(WorkspaceCommand().execute(f"install {source_dir}", role="readonly"))
    assert "denied" in result


def test_workspace_install_allowed_for_admin_role(tmp_path, monkeypatch) -> None:
    from olav.cli.commands.workspace import WorkspaceCommand

    monkeypatch.chdir(tmp_path)
    source_dir = tmp_path / "pkg"
    source_dir.mkdir()
    (source_dir / "MANIFEST.yaml").write_text(
        "kind: Skill\nname: pkg\nversion: '0.1.0'\n", encoding="utf-8"
    )

    result = asyncio.run(WorkspaceCommand().execute(f"install {source_dir}", role="admin"))
    assert "denied" not in result
    assert "installed" in result


def test_workspace_upgrade_denied_for_user_role(tmp_path, monkeypatch) -> None:
    from olav.cli.commands.workspace import WorkspaceCommand

    monkeypatch.chdir(tmp_path)
    workspace_root = tmp_path / ".olav" / "workspace"
    agent_dir = _make_agent(workspace_root, "quick", managed=True)
    (agent_dir / ".upstream-version").write_text("0.2.0\n", encoding="utf-8")

    result = asyncio.run(WorkspaceCommand().execute("upgrade quick", role="user"))
    assert "denied" in result


def test_workspace_remove_denied_for_user_role(tmp_path, monkeypatch) -> None:
    from olav.cli.commands.workspace import WorkspaceCommand

    monkeypatch.chdir(tmp_path)
    workspace_root = tmp_path / ".olav" / "workspace"
    _make_agent(workspace_root, "quick", managed=True)

    result = asyncio.run(WorkspaceCommand().execute("remove quick", role="user"))
    assert "denied" in result
    assert (workspace_root / "quick").exists()


def test_workspace_rollback_denied_for_readonly_role(tmp_path, monkeypatch) -> None:
    from olav.cli.commands.workspace import WorkspaceCommand

    monkeypatch.chdir(tmp_path)
    archive_root = tmp_path / "archive"
    _make_agent(archive_root, "quick", managed=True)

    result = asyncio.run(
        WorkspaceCommand().execute(f"rollback quick --from {archive_root}", role="readonly")
    )
    assert "denied" in result


def test_workspace_status_allowed_for_readonly(tmp_path, monkeypatch) -> None:
    from olav.cli.commands.workspace import WorkspaceCommand

    monkeypatch.chdir(tmp_path)
    workspace_root = tmp_path / ".olav" / "workspace"
    _make_agent(workspace_root, "quick", managed=True)

    result = asyncio.run(WorkspaceCommand().execute("status", role="readonly"))
    assert "denied" not in result
    assert "quick" in result
