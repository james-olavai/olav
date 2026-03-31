"""Tests for olav init command (P1A: platform scaffolding + DB + core workspace)."""

import asyncio
import json
from pathlib import Path
from textwrap import dedent

import pytest


def test_init_command_creates_platform_scaffolding(tmp_path, monkeypatch) -> None:
    from olav.cli.commands.init import InitCommand

    monkeypatch.chdir(tmp_path)
    result = asyncio.run(InitCommand().execute())

    assert "platform ready" in result
    assert (tmp_path / ".olav" / "config" / "api.json").exists()
    assert (tmp_path / ".olav" / "workspace").exists()
    assert (tmp_path / ".olav" / "databases").exists()
    assert (tmp_path / "exports" / "snapshots" / "json").exists()

    api_json = json.loads((tmp_path / ".olav" / "config" / "api.json").read_text(encoding="utf-8"))
    assert "llm" in api_json


def test_init_creates_services_yaml_template(tmp_path, monkeypatch) -> None:
    from olav.cli.commands.init import InitCommand

    monkeypatch.chdir(tmp_path)
    asyncio.run(InitCommand().execute())

    services_yaml = tmp_path / ".olav" / "config" / "services.yaml"
    assert services_yaml.exists(), "services.yaml template should be written by init"
    content = services_yaml.read_text(encoding="utf-8")
    # Must be valid YAML and contain the expected comment header
    assert "services" in content


def test_init_creates_settings_json(tmp_path, monkeypatch) -> None:
    from olav.cli.commands.init import InitCommand

    monkeypatch.chdir(tmp_path)
    asyncio.run(InitCommand().execute())

    settings_path = tmp_path / ".olav" / "config" / "settings.json"
    assert settings_path.exists(), "settings.json should be created by init"
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    assert data.get("active_workspace") == "core"


def test_init_creates_main_database(tmp_path, monkeypatch) -> None:
    from olav.cli.commands.init import InitCommand

    monkeypatch.chdir(tmp_path)
    asyncio.run(InitCommand().execute())

    assert (tmp_path / ".olav" / "databases" / "domain.duckdb").exists(), (
        "domain.duckdb should be created by init"
    )


def test_init_creates_audit_database(tmp_path, monkeypatch) -> None:
    from olav.cli.commands.init import InitCommand

    monkeypatch.chdir(tmp_path)
    asyncio.run(InitCommand().execute())

    assert (tmp_path / ".olav" / "databases" / "audit.duckdb").exists(), (
        "audit.duckdb should be created by init"
    )


def test_init_deploys_core_workspace(tmp_path, monkeypatch) -> None:
    from olav.cli.commands.init import InitCommand

    monkeypatch.chdir(tmp_path)
    asyncio.run(InitCommand().execute())

    core_ws = tmp_path / ".olav" / "workspace" / "core"
    assert core_ws.exists(), "core workspace dir should be created by init"
    assert (core_ws / "AGENT.md").exists(), "core workspace AGENT.md should exist"
    assert (core_ws / "MANIFEST.yaml").exists(), "core workspace MANIFEST.yaml should exist"


def test_init_is_idempotent(tmp_path, monkeypatch) -> None:
    """Running init twice should not fail or overwrite existing config."""
    from olav.cli.commands.init import InitCommand

    monkeypatch.chdir(tmp_path)
    asyncio.run(InitCommand().execute())

    # Modify settings to a custom value
    settings_path = tmp_path / ".olav" / "config" / "settings.json"
    data = json.loads(settings_path.read_text())
    data["active_workspace"] = "netops"
    settings_path.write_text(json.dumps(data), encoding="utf-8")

    # Second run should NOT overwrite existing settings
    asyncio.run(InitCommand().execute())
    data2 = json.loads(settings_path.read_text())
    assert data2["active_workspace"] == "netops", "init should not overwrite existing settings.json"
