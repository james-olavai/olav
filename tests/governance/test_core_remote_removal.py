"""Governance — core/remote/ removal and docker_compose migration.

These tests are RED before the implementation:
- core/remote/ must be removed (run_shell + remote_execute security risks)
- docker_compose tool must land in devops/services/tools/
- core SKILL.md must be updated to remove core/remote references

No LLM required — purely structural / file-system assertions.
"""
from __future__ import annotations

from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[2]


def _parse_front_matter(md_path: Path) -> dict:
    text = md_path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}
    parts = text.split("---\n", 2)
    if len(parts) < 3:
        return {}
    return yaml.safe_load(parts[1]) or {}


# ---------------------------------------------------------------------------
# TestCoreRemoteRemoved — core/remote/ must not exist
# ---------------------------------------------------------------------------


class TestCoreRemoteRemoved:
    """core/remote/ directory and its tools must be absent after removal."""

    def test_core_remote_dir_absent(self):
        remote_dir = _ROOT / ".olav" / "workspace" / "core" / "remote"
        assert not remote_dir.is_dir(), (
            f"core/remote/ still exists at {remote_dir}; "
            "this directory must be removed as part of the security remediation"
        )

    def test_core_agent_md_no_remote_subagent(self):
        agent_md = _ROOT / ".olav" / "workspace" / "core" / "SKILL.md"
        fm = _parse_front_matter(agent_md)
        subagent_paths = [s["path"] for s in fm.get("subagents", []) if isinstance(s, dict)]
        assert "./remote/SKILL.md" not in subagent_paths, (
            f"core SKILL.md still lists './remote/SKILL.md' as a subagent; "
            f"current subagents: {subagent_paths}"
        )

    def test_run_shell_py_absent(self):
        run_shell = _ROOT / ".olav" / "workspace" / "core" / "remote" / "tools" / "run_shell.py"
        assert not run_shell.exists(), (
            f"run_shell.py still present at {run_shell}; "
            "must be removed — blocklist-only approach with shell=True is a security risk"
        )

    def test_remote_execute_py_absent(self):
        remote_execute = (
            _ROOT / ".olav" / "workspace" / "core" / "remote" / "tools" / "remote_execute.py"
        )
        assert not remote_execute.exists(), (
            f"remote_execute.py still present at {remote_execute}; "
            "must be removed — zero filtering, any host any command is a security risk"
        )


# ---------------------------------------------------------------------------
# TestDockerComposeMigrated — docker_compose must land in devops/services/
# ---------------------------------------------------------------------------


class TestDockerComposeMigrated:
    """docker_compose tool must exist in the services agent with correct declarations.

    ADR-0014: services moved from a devops sub-agent to a platform top-level
    agent — docker_compose now lives at .olav/workspace/services/scripts/.
    """

    def test_docker_compose_tool_exists(self):
        tool_path = (
            _ROOT / ".olav" / "workspace" / "services" / "scripts" / "docker_compose.py"
        )
        assert tool_path.is_file(), (
            f"docker_compose.py missing at {tool_path}; "
            "this is the replacement for core/remote/ tools (ADR-0014: in services/)"
        )

    def test_devops_services_skill_declares_docker_compose(self):
        skill_md = _ROOT / ".olav" / "workspace" / "services" / "SKILL.md"
        text = skill_md.read_text(encoding="utf-8")
        assert "docker_compose" in text, (
            "services/SKILL.md does not mention 'docker_compose'; "
            "the new tool must be declared in the skill"
        )

    def test_core_agent_escalation_hint_updated(self):
        agent_md = _ROOT / ".olav" / "workspace" / "core" / "SKILL.md"
        text = agent_md.read_text(encoding="utf-8")
        assert "core/remote" not in text, (
            "core/SKILL.md still references 'core/remote' in escalation hints; "
            "all references to the removed sub-agent must be purged"
        )
