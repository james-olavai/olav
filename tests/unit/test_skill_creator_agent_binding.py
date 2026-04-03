"""Unit tests for create_skill_workspace agent binding (ISSUE-P2-SKILL-CREATOR-NO-AGENT-BINDING).

Tests both registration modes:
- top-level: creates .olav/workspace/<name>/, registers in PLATFORM.md
- subskill:  creates .olav/workspace/<parent>/<name>/, registers in parent AGENT.md
"""

import sys
import textwrap
from pathlib import Path

import pytest
import yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_tool(tmp_path: Path):
    """Import create_skill_workspace from the tool file, patching cwd to tmp_path."""
    import importlib.util, os

    tool_path = Path(__file__).parents[2] / ".olav/workspace/config/creator/tools/create_skill_workspace.py"
    spec = importlib.util.spec_from_file_location("create_skill_workspace_mod", tool_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.create_skill_workspace


def _invoke(fn, tmp_path: Path, **kwargs):
    """Call the LangChain @tool function from a temp dir."""
    import os
    orig = os.getcwd()
    os.chdir(tmp_path)
    try:
        # @tool wraps function — call via .invoke() dict or direct call
        try:
            return fn.invoke(kwargs)
        except AttributeError:
            return fn(**kwargs)
    finally:
        os.chdir(orig)


def _make_parent_workspace(tmp_path: Path, agent_name: str, existing_subagents: list[str] | None = None):
    """Create a minimal parent agent workspace with AGENT.md."""
    ws = tmp_path / ".olav/workspace" / agent_name
    ws.mkdir(parents=True)
    subagents_yaml = ""
    if existing_subagents:
        entries = "\n".join(f"  - path: ./{s}/SKILL.md" for s in existing_subagents)
        subagents_yaml = f"subagents:\n{entries}\n"
    agent_md = f"---\nname: {agent_name}\ndescription: \"Test agent\"\n{subagents_yaml}---\n\n# {agent_name}\n"
    (ws / "AGENT.md").write_text(agent_md)
    return ws


def _make_platform_md(tmp_path: Path, agents: list[str]):
    """Create minimal PLATFORM.md."""
    ws_root = tmp_path / ".olav/workspace"
    ws_root.mkdir(parents=True, exist_ok=True)
    fm = yaml.dump({"active": agents[0] if agents else "quick", "agents": agents})
    (ws_root / "PLATFORM.md").write_text(f"---\n{fm.rstrip()}\n---\n\n# Platform\n")


# ---------------------------------------------------------------------------
# Tests: top-level agent mode
# ---------------------------------------------------------------------------

class TestTopLevelRegistration:
    def test_creates_workspace_at_root_level(self, tmp_path):
        fn = _load_tool(tmp_path)
        _make_platform_md(tmp_path, ["quick"])
        (tmp_path / ".olav/workspace/ops/tools/_generated").mkdir(parents=True)
        tool_file = tmp_path / ".olav/workspace/ops/tools/_generated/fake_tool.py"
        tool_file.write_text("def fake(): pass")

        result = _invoke(fn, tmp_path,
            workspace_name="my-service",
            description="My service integration",
            tool_file_paths=[str(tool_file.relative_to(tmp_path))],
            manifest_keywords=["my-service", "widget"],
            system_prompt="You are the my-service agent.",
        )

        assert result["status"] == "ok"
        assert result["registration_mode"] == "top-level"
        ws_dir = tmp_path / ".olav/workspace/my-service"
        assert ws_dir.exists(), "workspace created at root level"

    def test_registers_in_platform_md(self, tmp_path):
        fn = _load_tool(tmp_path)
        _make_platform_md(tmp_path, ["quick"])

        result = _invoke(fn, tmp_path,
            workspace_name="new-agent",
            description="New agent",
            tool_file_paths=[],
            manifest_keywords=["new"],
        )

        platform = (tmp_path / ".olav/workspace/PLATFORM.md").read_text()
        assert "new-agent" in platform
        assert result["registered_in_platform"] is True
        assert result["registered_as_subskill_of"] == ""

    def test_creates_manifest_yaml(self, tmp_path):
        fn = _load_tool(tmp_path)
        _make_platform_md(tmp_path, ["quick"])

        _invoke(fn, tmp_path,
            workspace_name="routable-agent",
            description="Routable",
            tool_file_paths=[],
            manifest_keywords=["routable", "api"],
        )

        manifest = tmp_path / ".olav/workspace/routable-agent/MANIFEST.yaml"
        assert manifest.exists()
        data = yaml.safe_load(manifest.read_text())
        assert "routable" in data["route_keywords"]

    def test_not_registered_in_platform_if_already_present(self, tmp_path):
        fn = _load_tool(tmp_path)
        _make_platform_md(tmp_path, ["quick", "existing-agent"])

        result = _invoke(fn, tmp_path,
            workspace_name="existing-agent",
            description="Already exists",
            tool_file_paths=[],
            manifest_keywords=["existing"],
        )

        # Should not duplicate entry
        platform = (tmp_path / ".olav/workspace/PLATFORM.md").read_text()
        assert platform.count("existing-agent") == 1
        assert result["registered_in_platform"] is False


# ---------------------------------------------------------------------------
# Tests: subskill mode
# ---------------------------------------------------------------------------

class TestSubskillRegistration:
    def test_creates_workspace_inside_parent_directory(self, tmp_path):
        fn = _load_tool(tmp_path)
        _make_parent_workspace(tmp_path, "ops")

        result = _invoke(fn, tmp_path,
            workspace_name="my-probe",
            description="Custom probe subskill",
            tool_file_paths=[],
            parent_agent="ops",
        )

        assert result["status"] == "ok"
        assert result["registration_mode"] == "subskill"
        ws_dir = tmp_path / ".olav/workspace/ops/my-probe"
        assert ws_dir.exists(), "workspace created inside parent agent dir"

    def test_registers_in_parent_agent_md(self, tmp_path):
        fn = _load_tool(tmp_path)
        _make_parent_workspace(tmp_path, "ops", existing_subagents=["topology"])

        result = _invoke(fn, tmp_path,
            workspace_name="new-probe",
            description="New probe",
            tool_file_paths=[],
            parent_agent="ops",
        )

        agent_md = (tmp_path / ".olav/workspace/ops/AGENT.md").read_text()
        assert "./new-probe/SKILL.md" in agent_md
        assert result["registered_as_subskill_of"] == "ops"
        assert result["registered_in_platform"] is False

    def test_preserves_existing_subagents_in_parent(self, tmp_path):
        fn = _load_tool(tmp_path)
        _make_parent_workspace(tmp_path, "ops", existing_subagents=["topology", "sim"])

        _invoke(fn, tmp_path,
            workspace_name="diff2",
            description="diff v2",
            tool_file_paths=[],
            parent_agent="ops",
        )

        agent_md = (tmp_path / ".olav/workspace/ops/AGENT.md").read_text()
        fm_match = __import__("re").match(r"^---\n(.*?)\n---", agent_md, __import__("re").DOTALL)
        fm = yaml.safe_load(fm_match.group(1))
        paths = [s["path"] for s in fm["subagents"]]
        assert "./topology/SKILL.md" in paths
        assert "./sim/SKILL.md" in paths
        assert "./diff2/SKILL.md" in paths

    def test_does_not_create_manifest_for_subskill(self, tmp_path):
        fn = _load_tool(tmp_path)
        _make_parent_workspace(tmp_path, "audit")

        _invoke(fn, tmp_path,
            workspace_name="custom-check",
            description="Custom audit check",
            tool_file_paths=[],
            manifest_keywords=["audit", "compliance"],  # should be ignored
            parent_agent="audit",
        )

        manifest = tmp_path / ".olav/workspace/audit/custom-check/MANIFEST.yaml"
        assert not manifest.exists(), "subskills must NOT have MANIFEST.yaml"

    def test_does_not_register_in_platform_md(self, tmp_path):
        fn = _load_tool(tmp_path)
        _make_platform_md(tmp_path, ["quick"])
        _make_parent_workspace(tmp_path, "ops")

        _invoke(fn, tmp_path,
            workspace_name="my-subskill",
            description="Subskill",
            tool_file_paths=[],
            parent_agent="ops",
        )

        platform = (tmp_path / ".olav/workspace/PLATFORM.md").read_text()
        assert "my-subskill" not in platform

    def test_skill_md_created_for_subskill(self, tmp_path):
        fn = _load_tool(tmp_path)
        _make_parent_workspace(tmp_path, "ops")

        _invoke(fn, tmp_path,
            workspace_name="my-skill",
            description="My subskill",
            tool_file_paths=[],
            parent_agent="ops",
            system_prompt="You are my-skill.",
        )

        skill_md = tmp_path / ".olav/workspace/ops/my-skill/SKILL.md"
        assert skill_md.exists()
        content = skill_md.read_text()
        assert "my-skill" in content

    def test_no_duplicate_subagent_registration(self, tmp_path):
        fn = _load_tool(tmp_path)
        _make_parent_workspace(tmp_path, "ops", existing_subagents=["already-there"])

        # Register same subskill twice
        for _ in range(2):
            _invoke(fn, tmp_path,
                workspace_name="already-there",
                description="Already there",
                tool_file_paths=[],
                parent_agent="ops",
            )

        agent_md = (tmp_path / ".olav/workspace/ops/AGENT.md").read_text()
        assert agent_md.count("./already-there/SKILL.md") == 1


# ---------------------------------------------------------------------------
# Tests: return value shape
# ---------------------------------------------------------------------------

class TestReturnValueShape:
    def test_top_level_result_fields(self, tmp_path):
        fn = _load_tool(tmp_path)
        _make_platform_md(tmp_path, ["quick"])
        result = _invoke(fn, tmp_path,
            workspace_name="svc",
            description="svc",
            tool_file_paths=[],
            manifest_keywords=["svc"],
        )
        assert "registration_mode" in result
        assert "registered_as_subskill_of" in result
        assert result["registration_mode"] == "top-level"

    def test_subskill_result_fields(self, tmp_path):
        fn = _load_tool(tmp_path)
        _make_parent_workspace(tmp_path, "config")
        result = _invoke(fn, tmp_path,
            workspace_name="my-sub",
            description="sub",
            tool_file_paths=[],
            parent_agent="config",
        )
        assert result["registration_mode"] == "subskill"
        assert result["registered_as_subskill_of"] == "config"
        assert result["registered_in_platform"] is False
        assert result["has_manifest"] is False
