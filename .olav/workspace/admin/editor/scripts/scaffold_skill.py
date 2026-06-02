#!/usr/bin/env python3
"""scaffold_skill.py — Generate a SKILL.md + tool file skeleton from a description.

Given a skill name, description, and list of tool names, writes:
  .olav/workspace/<parent_agent>/<skill_name>/SKILL.md
  .olav/workspace/<parent_agent>/<skill_name>/tools/<tool>.py  (one per tool)
  .olav/workspace/<parent_agent>/<skill_name>/prompts/system.md
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


def _find_project_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


_PROJECT_ROOT = _find_project_root()
_WORKSPACE = _PROJECT_ROOT / ".olav" / "workspace"


def _tool_skeleton(tool_name: str, description: str) -> str:
    return f'''"""
{tool_name}.py — {description}
"""

from __future__ import annotations

from langchain_core.tools import tool


@tool
def {tool_name}() -> str:
    """TODO: implement {tool_name}.

    Returns:
        str: result description
    """
    raise NotImplementedError("{tool_name} not yet implemented")
'''


def _skill_md(name: str, description: str, tool_names: list[str]) -> str:
    tool_lines = "\n".join(f"  - {t}" for t in tool_names)
    return f"""---
name: {name}
description: "{description}"
agent_type: api
tools:
{tool_lines}
system_prompt_file: prompts/system.md
---

## {name.capitalize()}

{description}

### Tools

| Tool | Purpose |
|---|---|
""" + "\n".join(f"| `{t}(...)` | TODO |" for t in tool_names) + "\n"


def _system_md(name: str, description: str) -> str:
    return f"""# {name.capitalize()} — system prompt

You are the **{name}** sub-agent. {description}

## Hard rules

- Call only the tools declared in your SKILL.md.
- After each tool call, interpret the result before calling the next.
- Return a complete, structured response when done.
"""


def scaffold_skill(
    skill_name: str,
    parent_agent: str,
    description: str,
    tool_names: list[str],
    overwrite: bool = False,
) -> str:
    """Generate a SKILL.md scaffold + tool stubs for a new sub-agent.

    Args:
        skill_name: Directory name for the new skill (e.g. "my_checker").
        parent_agent: Parent agent directory under .olav/workspace/ (e.g. "admin").
        description: One-line description of what the skill does.
        tool_names: List of tool function names to scaffold (e.g. ["check_x", "report_x"]).
        overwrite: If False (default), refuse to overwrite an existing skill directory.

    Returns:
        Summary of files written, or an error message if the directory already exists.
    """
    skill_dir = _WORKSPACE / parent_agent / skill_name
    if skill_dir.exists() and not overwrite:
        return (
            f"Error: {skill_dir.relative_to(_PROJECT_ROOT)} already exists. "
            f"Pass overwrite=True to replace it."
        )

    tools_dir = skill_dir / "tools"
    prompts_dir = skill_dir / "prompts"
    tools_dir.mkdir(parents=True, exist_ok=True)
    prompts_dir.mkdir(parents=True, exist_ok=True)

    written: list[str] = []

    # SKILL.md
    skill_md_path = skill_dir / "SKILL.md"
    skill_md_path.write_text(_skill_md(skill_name, description, tool_names))
    written.append(str(skill_md_path.relative_to(_PROJECT_ROOT)))

    # prompts/system.md
    system_md_path = prompts_dir / "system.md"
    system_md_path.write_text(_system_md(skill_name, description))
    written.append(str(system_md_path.relative_to(_PROJECT_ROOT)))

    # tool stubs
    for t in tool_names:
        tp = tools_dir / f"{t}.py"
        tp.write_text(_tool_skeleton(t, f"TODO: {t}"))
        written.append(str(tp.relative_to(_PROJECT_ROOT)))

    return "Scaffolded:\n" + "\n".join(f"  {w}" for w in written)


if __name__ == "__main__":
    import json as _json, sys as _sys
    _args = _json.loads(_sys.stdin.read() or "{}")
    result = scaffold_skill(**_args)
    print(_json.dumps(result, default=str))
