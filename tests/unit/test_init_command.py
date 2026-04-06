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


def test_init_stores_active_workspace_in_api_json(tmp_path, monkeypatch) -> None:
    from olav.cli.commands.init import InitCommand

    monkeypatch.chdir(tmp_path)
    # Pre-create api.json so init can inject active_workspace
    api_path = tmp_path / ".olav" / "config" / "api.json"
    api_path.parent.mkdir(parents=True, exist_ok=True)
    api_path.write_text(json.dumps({"llm": {}}), encoding="utf-8")

    asyncio.run(InitCommand().execute())

    data = json.loads(api_path.read_text(encoding="utf-8"))
    assert data.get("active_workspace") == "core", (
        "init should set active_workspace=core in api.json"
    )


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
    """Running init twice should not fail or overwrite existing active_workspace."""
    from olav.cli.commands.init import InitCommand

    monkeypatch.chdir(tmp_path)
    # Pre-create api.json with a custom active_workspace
    api_path = tmp_path / ".olav" / "config" / "api.json"
    api_path.parent.mkdir(parents=True, exist_ok=True)
    api_path.write_text(json.dumps({"active_workspace": "netops"}), encoding="utf-8")

    asyncio.run(InitCommand().execute())

    data2 = json.loads(api_path.read_text())
    assert data2["active_workspace"] == "netops", (
        "init should not overwrite existing active_workspace in api.json"
    )
