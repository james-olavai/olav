"""Create a skill workspace directory and register it in PLATFORM.md."""

from langchain_core.tools import tool


@tool
def create_skill_workspace(
    workspace_name: str,
    description: str,
    tool_file_paths: list,
    skill_name: str = "",
    static_context_paths: list | None = None,
    agent_description: str = "",
) -> dict:
    """Create a workspace under .olav/workspace/<workspace_name>/ with SKILL.md
    pointing to the specified generated tool files, then register the workspace
    in PLATFORM.md so it becomes immediately available to the platform.

    The workspace follows SKILL.md v5 format (frontmatter + markdown body).
    Tool paths are stored as relative references — they are NOT copied, just
    referenced. The actual tool code lives in the _generated/ directory.

    Args:
        workspace_name:      Directory name under .olav/workspace/ (e.g. 'netbox-circuits')
        description:         One-line description shown in PLATFORM.md agent table
        tool_file_paths:     List of paths to generated tool files
                             (relative to project root, e.g.
                              ['.olav/workspace/ops/tools/_generated/netbox_circuits.py'])
        skill_name:          SKILL.md 'name' field (defaults to workspace_name)
        static_context_paths: Optional list of reference file paths to embed as context
        agent_description:   Longer description for AGENT.md (defaults to description)

    Returns:
        dict with status and paths of created files
    """
    from pathlib import Path

    import yaml as _yaml

    workspace_root = Path(".olav/workspace")
    ws_dir = workspace_root / workspace_name
    ws_dir.mkdir(parents=True, exist_ok=True)

    _skill_name = skill_name or workspace_name
    _agent_desc = agent_description or description
    files_created: list[str] = []

    # --- SKILL.md (v5 frontmatter format) ---
    tool_refs = [{"path": p} for p in (tool_file_paths or [])]
    ctx_refs = [{"path": p} for p in (static_context_paths or [])]

    frontmatter: dict = {
        "name": _skill_name,
        "description": description,
        "tools": tool_refs,
    }
    if ctx_refs:
        frontmatter["static_context"] = ctx_refs

    skill_md_content = (
        "---\n"
        + _yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True).rstrip()
        + "\n---\n\n"
        f"# {_skill_name.replace('-', ' ').title()}\n\n"
        f"{description}\n\n"
        "## Tools\n\n"
        + "".join(
            f"- `{Path(p).stem}` — from `{p}`\n" for p in (tool_file_paths or [])
        )
    )

    skill_md_path = ws_dir / "SKILL.md"
    skill_md_path.write_text(skill_md_content)
    files_created.append(str(skill_md_path))

    # --- AGENT.md (minimal, no subagents) ---
    agent_md_content = (
        "---\n"
        f"name: {_skill_name}\n"
        f"description: \"{_agent_desc}\"\n"
        "---\n\n"
        f"# {_skill_name.replace('-', ' ').title()}\n\n"
        f"{_agent_desc}\n"
    )
    agent_md_path = ws_dir / "AGENT.md"
    agent_md_path.write_text(agent_md_content)
    files_created.append(str(agent_md_path))

    # --- Register in PLATFORM.md ---
    platform_md_path = workspace_root / "PLATFORM.md"
    registered_in_platform = False

    if platform_md_path.exists():
        platform_content = platform_md_path.read_text()

        # Check if already registered
        if workspace_name not in platform_content:
            # Inject into frontmatter agents list
            try:
                import re
                # Find frontmatter block
                fm_match = re.match(r"^---\n(.*?)\n---", platform_content, re.DOTALL)
                if fm_match:
                    fm_text = fm_match.group(1)
                    fm_data = _yaml.safe_load(fm_text) or {}
                    agents_list: list = fm_data.get("agents", [])
                    if workspace_name not in agents_list:
                        agents_list.append(workspace_name)
                        fm_data["agents"] = agents_list
                        new_fm = _yaml.dump(fm_data, default_flow_style=False, allow_unicode=True).rstrip()
                        new_content = f"---\n{new_fm}\n---" + platform_content[fm_match.end():]
                        platform_md_path.write_text(new_content)
                        registered_in_platform = True
            except Exception:
                # Non-fatal: workspace created, platform registration skipped
                pass

    return {
        "status": "ok",
        "workspace_name": workspace_name,
        "workspace_path": str(ws_dir),
        "files_created": files_created,
        "registered_in_platform": registered_in_platform,
        "skill_name": _skill_name,
        "tools_referenced": len(tool_file_paths or []),
        "next_step": (
            f"Workspace '{workspace_name}' is ready. "
            "Verify with: read_file('.olav/workspace/"
            + workspace_name + "/SKILL.md')"
        ),
    }
