from __future__ import annotations

import json

import pytest

# ADR-0014 (2026-06-02): `workspace_health` is an ADMIN platform-management
# tool, not a `services` tool — the maintainer kept admin separate and scoped
# `services` to service lifecycle only. This test encodes the abandoned
# "services absorbs admin tools" design and imports a module that does not
# exist on branch 0.20.0 (workspace_health currently lives only in an
# unrelated worktree). Re-enable + repoint to admin once admin ships
# workspace_health. See dev_docs/92. SERVICES_PLATFORM_MIGRATION.md.
pytest.skip(
    "ADR-0014: workspace_health belongs to admin, not services; "
    "not present on this branch (see dev_docs/92).",
    allow_module_level=True,
)

import olav.data.workspace.services.tools.workspace_health as wh  # noqa: E402


def _call_workspace_health(agent_dir: str = ""):
    if hasattr(wh.workspace_health, "invoke"):
        return wh.workspace_health.invoke({"agent_dir": agent_dir})
    return wh.workspace_health(agent_dir=agent_dir)


def test_workspace_health_tool_reports_clean_workspace(monkeypatch, tmp_path):
    project_root = tmp_path / "repo"
    workspace_dir = project_root / ".olav" / "workspace" / "core"
    tools_dir = workspace_dir / "tools"
    prompts_dir = workspace_dir / "prompts"
    tools_dir.mkdir(parents=True)
    prompts_dir.mkdir(parents=True)

    (workspace_dir / "SKILL.md").write_text(
        "---\nname: core\ntools:\n  - healthy_tool\n---\n",
        encoding="utf-8",
    )
    (prompts_dir / "system.md").write_text("system prompt", encoding="utf-8")
    (tools_dir / "healthy_tool.py").write_text(
        "from langchain_core.tools import tool\n@tool\ndef healthy_tool() -> str:\n    return 'ok'\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(wh, "_PROJECT_ROOT", project_root)
    monkeypatch.setattr(wh, "_WORKSPACE_DIR", project_root / ".olav" / "workspace")
    monkeypatch.setattr(wh, "_check_platform_md_stale", lambda: None)

    out = json.loads(_call_workspace_health(""))
    assert out["summary"]["scanned"] == 1
    assert out["summary"]["errors"] == 0
    assert out["summary"]["warnings"] == 0
    assert out["summary"]["status"] == "clean"
