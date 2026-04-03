"""Create a skill workspace directory and register it in PLATFORM.md or as a subskill."""

from langchain_core.tools import tool


@tool
def create_skill_workspace(
    workspace_name: str,
    description: str,
    tool_file_paths: list,
    skill_name: str = "",
    static_context_paths: list | None = None,
    agent_description: str = "",
    schema_ref_path: str = "",
    manifest_keywords: list | None = None,
    system_prompt: str = "",
    parent_agent: str = "",
) -> dict:
    """Create a workspace under .olav/workspace/ with SKILL.md pointing to the
    specified generated tool files, then register the workspace either as a
    top-level agent in PLATFORM.md OR as a subskill under an existing agent.

    Registration mode is controlled by `parent_agent`:
    - parent_agent="" (default): workspace created at .olav/workspace/<workspace_name>/
      and registered in PLATFORM.md as an independent top-level agent.
    - parent_agent="ops" (example): workspace created at .olav/workspace/ops/<workspace_name>/
      and the parent's AGENT.md subagents list is updated with the new SKILL.md path.
      PLATFORM.md is NOT modified. MANIFEST.yaml is NOT created (subskills are not
      independently routed — they are invoked via their parent agent).

    The workspace follows SKILL.md v5 format (frontmatter + markdown body).
    Tool paths are stored as relative references — they are NOT copied, just
    referenced. The actual tool code lives in the _generated/ directory.

    Args:
        workspace_name:      Directory name for the workspace (e.g. 'netbox-circuits')
                             Top-level mode: .olav/workspace/<workspace_name>/
                             Subskill mode:  .olav/workspace/<parent_agent>/<workspace_name>/
        description:         One-line description shown in PLATFORM.md or parent AGENT.md
        tool_file_paths:     List of paths to generated tool files
                             (relative to project root, e.g.
                              ['.olav/workspace/ops/tools/_generated/netbox_circuits.py'])
        skill_name:          SKILL.md 'name' field (defaults to workspace_name)
        static_context_paths: Optional list of reference file paths to embed as context.
                              Prefer using schema_ref_path for schema references.
        agent_description:   Longer description for AGENT.md (defaults to description)
        schema_ref_path:     Path to schema_reference.json from extract_schema_reference().
                             If provided, automatically added to static_context so the
                             agent loads API schema awareness at startup.
        manifest_keywords:   List of routing keywords for MANIFEST.yaml. Only used in
                             top-level mode. In subskill mode this is ignored — the parent
                             agent handles routing.
        system_prompt:       Optional system prompt text written to prompts/system.md.
        parent_agent:        Name of an existing agent workspace to register this skill
                             under (e.g. "ops", "audit"). When set, the skill is created
                             as a subskill and registered in the parent's AGENT.md instead
                             of PLATFORM.md. Leave empty for a top-level agent.

    Returns:
        dict with status, paths of created files, and registration mode
    """
    from pathlib import Path

    import yaml as _yaml

    workspace_root = Path(".olav/workspace")
    # Subskill mode: nest under parent agent directory
    is_subskill = bool(parent_agent)
    if is_subskill:
        ws_dir = workspace_root / parent_agent / workspace_name
    else:
        ws_dir = workspace_root / workspace_name
    ws_dir.mkdir(parents=True, exist_ok=True)

    _skill_name = skill_name or workspace_name
    _agent_desc = agent_description or description
    files_created: list[str] = []

    # Merge schema_ref_path into static_context_paths
    all_ctx_paths = list(static_context_paths or [])
    if schema_ref_path and schema_ref_path not in all_ctx_paths:
        all_ctx_paths.append(schema_ref_path)

    # --- SKILL.md (v5 frontmatter format) ---
    tool_refs = [{"path": p} for p in (tool_file_paths or [])]
    ctx_refs = [{"path": p} for p in all_ctx_paths]

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

    # --- MANIFEST.yaml (top-level agents only — subskills are routed via parent) ---
    if manifest_keywords and not is_subskill:
        manifest_data = {
            "name": _skill_name,
            "kind": "Agent",
            "description": description,
            "version": "1.0.0",
            "route_keywords": list(manifest_keywords),
        }
        manifest_path = ws_dir / "MANIFEST.yaml"
        manifest_path.write_text(
            _yaml.dump(manifest_data, default_flow_style=False, allow_unicode=True)
        )
        files_created.append(str(manifest_path))

    # --- prompts/system.md (optional agent context) ---
    if system_prompt:
        prompts_dir = ws_dir / "prompts"
        prompts_dir.mkdir(exist_ok=True)
        system_md_path = prompts_dir / "system.md"
        system_md_path.write_text(system_prompt)
        files_created.append(str(system_md_path))

        # Register system_prompt_file in AGENT.md
        agent_md_path.write_text(
            "---\n"
            f"name: {_skill_name}\n"
            f"description: \"{_agent_desc}\"\n"
            f"system_prompt_file: prompts/system.md\n"
            "---\n\n"
            f"# {_skill_name.replace('-', ' ').title()}\n\n"
            f"{_agent_desc}\n"
        )

    # --- Registration: PLATFORM.md (top-level) or parent AGENT.md (subskill) ---
    registered_in_platform = False
    registered_as_subskill_of = ""

    if is_subskill:
        # Register as subagent in parent agent's AGENT.md
        parent_agent_md = workspace_root / parent_agent / "AGENT.md"
        if parent_agent_md.exists():
            try:
                import re
                content = parent_agent_md.read_text()
                fm_match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
                if fm_match:
                    fm_text = fm_match.group(1)
                    fm_data = _yaml.safe_load(fm_text) or {}
                    subagents: list = fm_data.get("subagents", [])
                    # Relative path from parent workspace dir to new SKILL.md
                    new_path = f"./{workspace_name}/SKILL.md"
                    existing_paths = [s.get("path", "") for s in subagents if isinstance(s, dict)]
                    if new_path not in existing_paths:
                        subagents.append({"path": new_path})
                        fm_data["subagents"] = subagents
                        new_fm = _yaml.dump(
                            fm_data, default_flow_style=False, allow_unicode=True
                        ).rstrip()
                        new_content = f"---\n{new_fm}\n---" + content[fm_match.end():]
                        parent_agent_md.write_text(new_content)
                        registered_as_subskill_of = parent_agent
            except Exception:
                pass  # Non-fatal
    else:
        # Register as top-level agent in PLATFORM.md
        platform_md_path = workspace_root / "PLATFORM.md"
        if platform_md_path.exists():
            platform_content = platform_md_path.read_text()
            if workspace_name not in platform_content:
                try:
                    import re
                    fm_match = re.match(r"^---\n(.*?)\n---", platform_content, re.DOTALL)
                    if fm_match:
                        fm_text = fm_match.group(1)
                        fm_data = _yaml.safe_load(fm_text) or {}
                        agents_list: list = fm_data.get("agents", [])
                        if workspace_name not in agents_list:
                            agents_list.append(workspace_name)
                            fm_data["agents"] = agents_list
                            new_fm = _yaml.dump(
                                fm_data, default_flow_style=False, allow_unicode=True
                            ).rstrip()
                            new_content = f"---\n{new_fm}\n---" + platform_content[fm_match.end():]
                            platform_md_path.write_text(new_content)
                            registered_in_platform = True
                except Exception:
                    pass  # Non-fatal

    # Build result summary
    if is_subskill:
        next_step = (
            f"Subskill '{workspace_name}' created under '{parent_agent}' agent"
            + (" (schema-aware ✓)" if all_ctx_paths else " ⚠ not schema-aware — run extract_schema_reference")
            + (f" (registered in {parent_agent}/AGENT.md ✓)" if registered_as_subskill_of else " ⚠ parent AGENT.md not updated — check parent_agent name")
            + f". Verify with: read_file('.olav/workspace/{parent_agent}/{workspace_name}/SKILL.md')"
        )
    else:
        next_step = (
            f"Agent '{workspace_name}' is ready"
            + (" (schema-aware ✓)" if all_ctx_paths else " ⚠ not schema-aware — run extract_schema_reference")
            + (" (manifest ✓)" if manifest_keywords else " ⚠ no MANIFEST — router cannot discover this agent")
            + f". Verify with: read_file('.olav/workspace/{workspace_name}/SKILL.md')"
        )

    return {
        "status": "ok",
        "workspace_name": workspace_name,
        "workspace_path": str(ws_dir),
        "files_created": files_created,
        "registration_mode": "subskill" if is_subskill else "top-level",
        "registered_in_platform": registered_in_platform,
        "registered_as_subskill_of": registered_as_subskill_of,
        "skill_name": _skill_name,
        "tools_referenced": len(tool_file_paths or []),
        "schema_aware": bool(all_ctx_paths),
        "has_manifest": bool(manifest_keywords) and not is_subskill,
        "has_system_prompt": bool(system_prompt),
        "static_context_files": all_ctx_paths,
        "next_step": next_step,
    }
