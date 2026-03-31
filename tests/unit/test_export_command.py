import asyncio
import json
from pathlib import Path

import yaml


def _make_agent(workspace_root: Path, name: str) -> Path:
    agent_dir = workspace_root / name
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "AGENT.md").write_text("---\nname: quick\n---\n", encoding="utf-8")
    (agent_dir / "SKILL.md").write_text("# skill\n", encoding="utf-8")
    return agent_dir


def _add_manifest(agent_dir: Path, name: str, kind: str = "Agent",
                  route_keywords: list | None = None, requires: list | None = None) -> None:
    data = {"kind": kind, "name": name, "version": "0.11.0",
            "route_keywords": route_keywords or []}
    if requires:
        data["requires"] = requires
    (agent_dir / "MANIFEST.yaml").write_text(
        yaml.dump(data, default_flow_style=False), encoding="utf-8"
    )


def test_export_claude_skills_copies_skill_file(tmp_path, monkeypatch) -> None:
    from olav.cli.commands.export import ExportCommand

    monkeypatch.chdir(tmp_path)
    workspace_root = tmp_path / ".olav" / "workspace"
    _make_agent(workspace_root, "quick")
    output_dir = tmp_path / "dist"

    result = asyncio.run(
        ExportCommand().execute(f"claude-skills --agent quick --output {output_dir}")
    )

    exported = output_dir / "skills" / "quick" / "SKILL.md"
    assert "exported" in result
    assert exported.exists()


def test_export_claude_plugin_creates_plugin_layout(tmp_path, monkeypatch) -> None:
    from olav.cli.commands.export import ExportCommand

    monkeypatch.chdir(tmp_path)
    workspace_root = tmp_path / ".olav" / "workspace"
    _make_agent(workspace_root, "quick")
    output_dir = tmp_path / "plugin-dist"

    result = asyncio.run(
        ExportCommand().execute(f"claude-plugin --agent quick --output {output_dir}")
    )

    plugin_json = output_dir / ".claude-plugin" / "plugin.json"
    exported_agent = output_dir / "agents" / "quick.md"
    exported_skill = output_dir / "skills" / "quick" / "SKILL.md"

    assert "exported" in result
    assert plugin_json.exists()
    assert exported_agent.exists()
    assert exported_skill.exists()

    payload = json.loads(plugin_json.read_text(encoding="utf-8"))
    # name now comes from AGENT.md frontmatter (name: quick)
    assert payload["name"] == "quick"


# ── MANIFEST enrichment tests ─────────────────────────────────────────────────

def test_export_claude_plugin_includes_route_keywords_from_manifest(tmp_path, monkeypatch) -> None:
    """plugin.json should include route_keywords from MANIFEST.yaml."""
    from olav.cli.commands.export import ExportCommand

    monkeypatch.chdir(tmp_path)
    workspace_root = tmp_path / ".olav" / "workspace"
    agent_dir = _make_agent(workspace_root, "ops")
    _add_manifest(agent_dir, "ops", kind="Agent",
                  route_keywords=["troubleshoot", "probe", "diff config"])
    output_dir = tmp_path / "plugin-dist"

    asyncio.run(ExportCommand().execute(f"claude-plugin --agent ops --output {output_dir}"))

    payload = json.loads((output_dir / ".claude-plugin" / "plugin.json").read_text())
    assert "route_keywords" in payload
    assert "troubleshoot" in payload["route_keywords"]
    assert "probe" in payload["route_keywords"]


def test_export_claude_plugin_includes_kind_from_manifest(tmp_path, monkeypatch) -> None:
    """plugin.json should include 'kind' field from MANIFEST.yaml."""
    from olav.cli.commands.export import ExportCommand

    monkeypatch.chdir(tmp_path)
    workspace_root = tmp_path / ".olav" / "workspace"
    agent_dir = _make_agent(workspace_root, "audit")
    _add_manifest(agent_dir, "audit", kind="Agent")
    output_dir = tmp_path / "plugin-dist"

    asyncio.run(ExportCommand().execute(f"claude-plugin --agent audit --output {output_dir}"))

    payload = json.loads((output_dir / ".claude-plugin" / "plugin.json").read_text())
    assert payload.get("kind") == "Agent"


def test_export_claude_plugin_no_manifest_still_works(tmp_path, monkeypatch) -> None:
    """claude-plugin export must not crash when no MANIFEST.yaml exists."""
    from olav.cli.commands.export import ExportCommand

    monkeypatch.chdir(tmp_path)
    workspace_root = tmp_path / ".olav" / "workspace"
    _make_agent(workspace_root, "quick")  # no MANIFEST.yaml
    output_dir = tmp_path / "plugin-dist"

    result = asyncio.run(
        ExportCommand().execute(f"claude-plugin --agent quick --output {output_dir}")
    )

    assert "exported" in result
    plugin_json = output_dir / ".claude-plugin" / "plugin.json"
    assert plugin_json.exists()
    payload = json.loads(plugin_json.read_text())
    # route_keywords absent or empty list when no MANIFEST
    assert payload.get("route_keywords", []) == []


def test_export_claude_plugin_manifest_version_in_plugin_json(tmp_path, monkeypatch) -> None:
    """plugin.json version should reflect MANIFEST.yaml version."""
    from olav.cli.commands.export import ExportCommand

    monkeypatch.chdir(tmp_path)
    workspace_root = tmp_path / ".olav" / "workspace"
    agent_dir = _make_agent(workspace_root, "ops")
    # Write MANIFEST with specific version
    (agent_dir / "MANIFEST.yaml").write_text(
        "kind: Agent\nname: ops\nversion: \"0.12.5\"\nroute_keywords: []\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "plugin-dist"

    asyncio.run(ExportCommand().execute(f"claude-plugin --agent ops --output {output_dir}"))

    payload = json.loads((output_dir / ".claude-plugin" / "plugin.json").read_text())
    assert payload["version"] == "0.12.5"
