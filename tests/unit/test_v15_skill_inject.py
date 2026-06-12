"""v0.15.0 skill injection tests (C-V15-09~12).

Tests for inject_into_core feature — workspace.yaml declares tools/references
to be symlinked into core workspace on skill install.

C-V15-09 — workspace.yaml parses inject_into_core field
C-V15-10 — after install, core/tools/ has symlinks
C-V15-11 — after install, core/SKILL.md lists injected tools
C-V15-12 — uninstall cleans symlinks + SKILL.md entries

Always-run (no LLM required).
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from textwrap import dedent

import yaml
import pytest


def _make_skill_dir(base: Path, name: str, inject_tools: list[str] | None = None) -> Path:
    """Create a minimal skill directory with workspace.yaml and a tool."""
    skill_dir = base / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    agent_dir = skill_dir / name
    agent_dir.mkdir(exist_ok=True)
    (agent_dir / "AGENT.md").write_text(f"---\nname: {name}\n---\n", encoding="utf-8")

    # Create a dummy tool file
    tool_file = skill_dir / "tools" / "mytool.py"
    tool_file.parent.mkdir(exist_ok=True)
    tool_file.write_text('"""dummy tool"""\n', encoding="utf-8")

    workspace_yaml: dict = {
        "name": name,
        "version": "0.1.0",
        "description": f"{name} test skill",
        "source": f".olav/workspace/{name}",
    }
    if inject_tools:
        workspace_yaml["inject_into_core"] = {
            "tools": inject_tools,
        }
    (skill_dir / "workspace.yaml").write_text(yaml.dump(workspace_yaml), encoding="utf-8")
    return skill_dir


def _make_core_workspace(ws_root: Path) -> Path:
    """Create a minimal core workspace with SKILL.md."""
    core_dir = ws_root / "core"
    core_dir.mkdir(parents=True, exist_ok=True)
    core_tools = core_dir / "tools"
    core_tools.mkdir(exist_ok=True)

    # Write initial SKILL.md
    skill_md_content = dedent("""\
        ---
        name: core
        description: "Core platform tools"
        tools:
          - execute_sql
          - run_python_code
        metadata:
          version: 3.0.0
        ---

        # Core Workspace
    """)
    (core_dir / "SKILL.md").write_text(skill_md_content, encoding="utf-8")
    return core_dir


# ---------------------------------------------------------------------------
# C-V15-09 — workspace.yaml parses inject_into_core
# ---------------------------------------------------------------------------

class TestWorkspaceYamlInjectIntoCore:
    """C-V15-09: WorkspaceDeclaration.from_yaml() parses inject_into_core field."""

    def test_inject_into_core_tools_parsed(self, tmp_path):
        ws_yaml = tmp_path / "workspace.yaml"
        ws_yaml.write_text(dedent("""\
            name: myskill
            version: "0.1.0"
            description: "test skill"
            inject_into_core:
              tools:
                - tools/execute_cli.py
                - tools/search_commands.py
        """), encoding="utf-8")

        from olav.core.workspace import WorkspaceDeclaration
        decl = WorkspaceDeclaration.from_yaml(ws_yaml)
        assert hasattr(decl, "inject_into_core"), "WorkspaceDeclaration should have inject_into_core field"
        assert decl.inject_into_core is not None
        assert "tools/execute_cli.py" in decl.inject_into_core.tools
        assert "tools/search_commands.py" in decl.inject_into_core.tools

    def test_inject_into_core_optional(self, tmp_path):
        """inject_into_core is optional — absence means no injection."""
        ws_yaml = tmp_path / "workspace.yaml"
        ws_yaml.write_text(dedent("""\
            name: simpleskill
            version: "0.1.0"
        """), encoding="utf-8")

        from olav.core.workspace import WorkspaceDeclaration
        decl = WorkspaceDeclaration.from_yaml(ws_yaml)
        assert decl.inject_into_core is None

    def test_inject_into_core_with_references(self, tmp_path):
        ws_yaml = tmp_path / "workspace.yaml"
        ws_yaml.write_text(dedent("""\
            name: myskill
            version: "0.1.0"
            inject_into_core:
              tools:
                - tools/execute_cli.py
              references:
                - references/SCHEMA_REFERENCE.md
        """), encoding="utf-8")

        from olav.core.workspace import WorkspaceDeclaration
        decl = WorkspaceDeclaration.from_yaml(ws_yaml)
        assert decl.inject_into_core is not None
        assert "references/SCHEMA_REFERENCE.md" in decl.inject_into_core.references


# ---------------------------------------------------------------------------
# C-V15-10 — after install, core/tools/ has symlinks
# ---------------------------------------------------------------------------

class TestCoreToolsSymlinksAfterInstall:
    """C-V15-10: after skill install, core/tools/ contains symlinks to injected tools."""

    def test_symlink_created_on_install(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ws_root = tmp_path / ".olav" / "workspace"
        core_dir = _make_core_workspace(ws_root)

        # Create skill with inject_into_core
        skill_src = tmp_path / "myskill_src"
        tool_file = skill_src / "tools" / "mytool.py"
        tool_file.parent.mkdir(parents=True, exist_ok=True)
        tool_file.write_text('"""mytool"""\n', encoding="utf-8")
        (skill_src / "workspace.yaml").write_text(dedent("""\
            name: myskill
            version: "0.1.0"
            description: "test"
            source: .olav/workspace/myskill
            inject_into_core:
              tools:
                - tools/mytool.py
        """), encoding="utf-8")
        # Create source workspace dir (where install copies to)
        skill_ws = ws_root / "myskill"
        skill_ws_tools = skill_ws / "tools"
        skill_ws_tools.mkdir(parents=True, exist_ok=True)
        (skill_ws_tools / "mytool.py").write_text('"""mytool"""\n', encoding="utf-8")
        # Write lock file to simulate already-installed
        import yaml as _yaml
        (skill_ws / "workspace.lock.yaml").write_text(
            _yaml.dump({"name": "myskill", "version": "0.1.0"}), encoding="utf-8"
        )

        from olav.core.workspace import WorkspaceDeclaration
        from olav.cli.commands.skill import inject_tools_into_core

        decl = WorkspaceDeclaration.from_yaml(skill_src / "workspace.yaml")
        inject_tools_into_core(decl, skill_ws, ws_root)

        # Symlink should exist in core/tools/
        symlink = core_dir / "tools" / "mytool.py"
        assert symlink.exists(), f"Symlink should exist at {symlink}"
        assert symlink.is_symlink() or symlink.is_file(), "Tool should be reachable via core/tools/"

    def test_no_symlinks_when_no_inject(self, tmp_path, monkeypatch):
        """Skills without inject_into_core don't create symlinks in core."""
        monkeypatch.chdir(tmp_path)
        ws_root = tmp_path / ".olav" / "workspace"
        _make_core_workspace(ws_root)

        skill_ws = ws_root / "simpleskill"
        skill_ws.mkdir()

        from olav.core.workspace import WorkspaceDeclaration
        from olav.cli.commands.skill import inject_tools_into_core

        ws_yaml = tmp_path / "workspace.yaml"
        ws_yaml.write_text("name: simpleskill\nversion: '0.1.0'\n", encoding="utf-8")
        decl = WorkspaceDeclaration.from_yaml(ws_yaml)
        # Should not raise — just a no-op
        inject_tools_into_core(decl, skill_ws, ws_root)


# ---------------------------------------------------------------------------
# C-V15-11 — after install, SKILL.md lists injected tools
# ---------------------------------------------------------------------------

class TestCoreSkillMdUpdatedAfterInstall:
    """C-V15-11: after inject, core/SKILL.md lists the injected tools."""

    def test_skill_md_updated_with_tool(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ws_root = tmp_path / ".olav" / "workspace"
        core_dir = _make_core_workspace(ws_root)

        skill_ws = ws_root / "myskill"
        skill_ws_tools = skill_ws / "tools"
        skill_ws_tools.mkdir(parents=True, exist_ok=True)
        (skill_ws_tools / "newtool.py").write_text('"""newtool"""\n', encoding="utf-8")
        import yaml as _yaml
        (skill_ws / "workspace.lock.yaml").write_text(
            _yaml.dump({"name": "myskill", "version": "0.1.0"}), encoding="utf-8"
        )

        from olav.core.workspace import WorkspaceDeclaration
        from olav.cli.commands.skill import inject_tools_into_core

        ws_yaml = tmp_path / "ws.yaml"
        ws_yaml.write_text(dedent("""\
            name: myskill
            version: "0.1.0"
            inject_into_core:
              tools:
                - tools/newtool.py
        """), encoding="utf-8")
        decl = WorkspaceDeclaration.from_yaml(ws_yaml)
        inject_tools_into_core(decl, skill_ws, ws_root)

        skill_md_content = (core_dir / "SKILL.md").read_text(encoding="utf-8")
        assert "newtool" in skill_md_content, (
            f"core/SKILL.md should list 'newtool' after injection, got:\n{skill_md_content}"
        )

    def test_skill_md_not_duplicated(self, tmp_path, monkeypatch):
        """Calling inject twice doesn't duplicate the tool entry."""
        monkeypatch.chdir(tmp_path)
        ws_root = tmp_path / ".olav" / "workspace"
        core_dir = _make_core_workspace(ws_root)

        skill_ws = ws_root / "myskill"
        skill_ws_tools = skill_ws / "tools"
        skill_ws_tools.mkdir(parents=True, exist_ok=True)
        (skill_ws_tools / "newtool.py").write_text('"""newtool"""\n', encoding="utf-8")
        import yaml as _yaml
        (skill_ws / "workspace.lock.yaml").write_text(
            _yaml.dump({"name": "myskill", "version": "0.1.0"}), encoding="utf-8"
        )

        from olav.core.workspace import WorkspaceDeclaration
        from olav.cli.commands.skill import inject_tools_into_core

        ws_yaml = tmp_path / "ws.yaml"
        ws_yaml.write_text(dedent("""\
            name: myskill
            version: "0.1.0"
            inject_into_core:
              tools:
                - tools/newtool.py
        """), encoding="utf-8")
        decl = WorkspaceDeclaration.from_yaml(ws_yaml)

        # Call inject twice — should be idempotent
        inject_tools_into_core(decl, skill_ws, ws_root)
        inject_tools_into_core(decl, skill_ws, ws_root)

        skill_md_content = (core_dir / "SKILL.md").read_text(encoding="utf-8")
        count = skill_md_content.count("newtool")
        assert count == 1, f"'newtool' should appear only once in SKILL.md, found {count} times"


# ---------------------------------------------------------------------------
# C-V15-12 — uninstall cleans symlinks + SKILL.md entries
# ---------------------------------------------------------------------------

class TestUninstallCleansInjectedTools:
    """C-V15-12: uninstalling a skill removes its injected tools from core."""

    def test_symlink_removed_on_uninstall(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ws_root = tmp_path / ".olav" / "workspace"
        core_dir = _make_core_workspace(ws_root)

        # Setup: create and inject
        skill_ws = ws_root / "myskill"
        skill_ws_tools = skill_ws / "tools"
        skill_ws_tools.mkdir(parents=True, exist_ok=True)
        (skill_ws_tools / "injectedtool.py").write_text('"""injectedtool"""\n', encoding="utf-8")
        import yaml as _yaml
        (skill_ws / "workspace.lock.yaml").write_text(
            _yaml.dump({"name": "myskill", "version": "0.1.0", "inject_into_core": {"tools": ["tools/injectedtool.py"]}}), encoding="utf-8"
        )

        # Create symlink manually to simulate a prior injection
        symlink = core_dir / "tools" / "injectedtool.py"
        symlink.symlink_to(skill_ws_tools / "injectedtool.py")

        # Add tool to SKILL.md
        skill_md = core_dir / "SKILL.md"
        skill_md.write_text(
            skill_md.read_text() + "\n  - injectedtool              # injected by myskill\n",
            encoding="utf-8",
        )

        from olav.cli.commands.skill import remove_injected_tools_from_core
        remove_injected_tools_from_core("myskill", ws_root)

        assert not symlink.exists(), "Injected symlink should be removed after uninstall"

    def test_skill_md_entry_removed_on_uninstall(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ws_root = tmp_path / ".olav" / "workspace"
        core_dir = _make_core_workspace(ws_root)

        # Add injected entry to SKILL.md
        skill_md = core_dir / "SKILL.md"
        skill_md.write_text(
            skill_md.read_text() + "\n  - injectedtool              # injected by myskill\n",
            encoding="utf-8",
        )

        skill_ws = ws_root / "myskill"
        skill_ws.mkdir()

        from olav.cli.commands.skill import remove_injected_tools_from_core
        remove_injected_tools_from_core("myskill", ws_root)

        content = skill_md.read_text(encoding="utf-8")
        assert "injectedtool" not in content, (
            "Injected tool entry should be removed from core/SKILL.md on uninstall"
        )
