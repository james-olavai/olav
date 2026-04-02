"""TDD — GAP-10: Skill-level Python venv isolation.

skill install reads requires_packages from SKILL.md and creates a
per-workspace .venv. run_python_code uses that venv when present.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import yaml


def _make_skill_with_packages(root: Path, name: str, packages: list[str]) -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "MANIFEST.yaml").write_text(yaml.dump({
        "kind": "Agent", "name": name, "version": "1.0.0",
        "description": f"{name} skill", "route_keywords": [name],
    }))
    (d / "AGENT.md").write_text(f"---\nname: {name}\n---\n")
    (d / "SKILL.md").write_text(
        "---\n"
        f"name: {name}\n"
        "tools: []\n"
        f"requires_packages:\n"
        + "".join(f"  - {p}\n" for p in packages)
        + "---\n"
    )
    return d


def _make_skill_no_packages(root: Path, name: str) -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "MANIFEST.yaml").write_text(yaml.dump({
        "kind": "Agent", "name": name, "version": "1.0.0",
        "description": name, "route_keywords": [name],
    }))
    (d / "AGENT.md").write_text(f"---\nname: {name}\n---\n")
    (d / "SKILL.md").write_text(f"---\nname: {name}\ntools: []\n---\n")
    return d


# ── SKILL.md requires_packages parsing ───────────────────────────────────────


class TestSkillMdRequiresPackages:
    def test_parse_requires_packages_from_skill_md(self, tmp_path):
        """requires_packages in SKILL.md frontmatter is parsed correctly."""
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text(
            "---\nname: netbox\ntools: []\nrequires_packages:\n  - pynetbox>=7.0\n  - requests\n---\n"
        )
        from olav.cli.commands.skill import _read_requires_packages
        pkgs = _read_requires_packages(skill_md)
        assert "pynetbox>=7.0" in pkgs
        assert "requests" in pkgs

    def test_parse_returns_empty_when_no_requires_packages(self, tmp_path):
        """Missing requires_packages returns empty list (not error)."""
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("---\nname: myskill\ntools: []\n---\n")
        from olav.cli.commands.skill import _read_requires_packages
        pkgs = _read_requires_packages(skill_md)
        assert pkgs == []

    def test_parse_returns_empty_when_skill_md_missing(self, tmp_path):
        """Missing SKILL.md returns empty list gracefully."""
        from olav.cli.commands.skill import _read_requires_packages
        pkgs = _read_requires_packages(tmp_path / "nonexistent.md")
        assert pkgs == []


# ── skill install creates venv ────────────────────────────────────────────────


class TestSkillInstallCreatesVenv:
    def test_install_creates_venv_when_requires_packages_declared(self, tmp_path, monkeypatch):
        """install calls venv creation when SKILL.md has requires_packages."""
        monkeypatch.chdir(tmp_path)
        skill_dir = _make_skill_with_packages(tmp_path / "skills", "netbox", ["pynetbox>=7.0"])

        with patch("olav.cli.commands.skill._create_skill_venv") as mock_venv:
            mock_venv.return_value = {"status": "ok", "venv": str(tmp_path / ".venv")}
            from olav.cli.commands.skill import SkillCommand
            asyncio.run(SkillCommand().execute(f"install {skill_dir}"))

        mock_venv.assert_called_once()
        call_args = mock_venv.call_args
        assert "pynetbox>=7.0" in call_args[0][1]  # packages arg

    def test_install_skips_venv_when_no_requires_packages(self, tmp_path, monkeypatch):
        """install does NOT call venv creation when no requires_packages."""
        monkeypatch.chdir(tmp_path)
        skill_dir = _make_skill_no_packages(tmp_path / "skills", "myskill")

        with patch("olav.cli.commands.skill._create_skill_venv") as mock_venv:
            from olav.cli.commands.skill import SkillCommand
            asyncio.run(SkillCommand().execute(f"install {skill_dir}"))

        mock_venv.assert_not_called()

    def test_create_skill_venv_runs_uv_venv_and_install(self, tmp_path):
        """_create_skill_venv runs 'uv venv' then 'uv pip install' in workspace dir."""
        from olav.cli.commands.skill import _create_skill_venv

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = _create_skill_venv(tmp_path, ["pynetbox>=7.0", "requests"])

        calls = mock_run.call_args_list
        cmds = [" ".join(c[0][0]) for c in calls]
        assert any("uv" in c and "venv" in c for c in cmds), f"No uv venv call: {cmds}"
        assert any("install" in c and "pynetbox" in c for c in cmds), f"No pip install: {cmds}"
        assert result["status"] == "ok"

    def test_create_skill_venv_returns_error_on_failure(self, tmp_path):
        """_create_skill_venv returns error dict when venv creation fails."""
        from olav.cli.commands.skill import _create_skill_venv

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="uv not found")
            result = _create_skill_venv(tmp_path, ["pynetbox"])

        assert result["status"] == "error"

    def test_install_result_mentions_venv_created(self, tmp_path, monkeypatch):
        """install output mentions venv when packages are installed."""
        monkeypatch.chdir(tmp_path)
        skill_dir = _make_skill_with_packages(tmp_path / "skills", "netbox", ["pynetbox"])

        with patch("olav.cli.commands.skill._create_skill_venv") as mock_venv:
            mock_venv.return_value = {"status": "ok", "venv": ".olav/workspace/netbox/.venv"}
            from olav.cli.commands.skill import SkillCommand
            result = asyncio.run(SkillCommand().execute(f"install {skill_dir}"))

        assert "venv" in result.lower() or "pynetbox" in result.lower()


# ── run_python_code uses workspace venv ───────────────────────────────────────


class TestRunPythonCodeVenvSelection:
    def test_uses_workspace_venv_python_when_present(self, tmp_path, monkeypatch):
        """run_python_code uses .olav/workspace/<active>/.venv/bin/python when it exists."""
        monkeypatch.chdir(tmp_path)

        # Simulate a workspace venv
        venv_python = tmp_path / ".olav" / "workspace" / "netbox" / ".venv" / "bin" / "python"
        venv_python.parent.mkdir(parents=True)
        venv_python.write_text("#!/bin/sh\nexec python3 \"$@\"\n")
        venv_python.chmod(0o755)

        with patch("olav.core.workspace.get_active_workspace", return_value="netbox"):
            from olav.platform.sandbox import resolve_sandbox_python
            python_exe = resolve_sandbox_python()

        assert str(venv_python) in python_exe or "netbox" in python_exe

    def test_falls_back_to_sys_executable_when_no_venv(self, tmp_path, monkeypatch):
        """run_python_code falls back to sys.executable when no workspace venv."""
        monkeypatch.chdir(tmp_path)

        with patch("olav.core.workspace.get_active_workspace", return_value="quick"):
            from olav.platform.sandbox import resolve_sandbox_python
            python_exe = resolve_sandbox_python()

        assert python_exe == sys.executable

    def test_run_python_code_uses_resolved_python(self, tmp_path, monkeypatch):
        """_execute_code uses resolve_sandbox_python() not sys.executable directly."""
        monkeypatch.chdir(tmp_path)

        captured = {}

        def fake_run(cmd, **kwargs):
            captured["python"] = cmd[0]
            return MagicMock(returncode=0, stdout="__OLAV_RESULT__:null", stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            with patch("olav.platform.sandbox.resolve_sandbox_python", return_value="/fake/venv/python"):
                from olav.platform.sandbox import execute_in_sandbox
                execute_in_sandbox("_result = 1", timeout=5)

        assert captured.get("python") == "/fake/venv/python"
