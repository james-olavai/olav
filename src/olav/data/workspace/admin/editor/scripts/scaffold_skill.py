#!/usr/bin/env python3
"""scaffold_skill.py — Generate a SKILL.md + script file skeleton from a description.

Given a skill name, description, and list of script names, writes:
  .olav/workspace/<parent_agent>/<skill_name>/SKILL.md   (body = system prompt)
  .olav/workspace/<parent_agent>/<skill_name>/scripts/<script>.py  (one per script)

System prompt is written directly into the SKILL.md body — no prompts/ directory.
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


def _script_skeleton(script_name: str, description: str) -> str:
    return f'''"""
{script_name}.py — {description}
"""

from __future__ import annotations


def {script_name}() -> str:
    """TODO: implement {script_name}.

    Returns:
        str: result description
    """
    raise NotImplementedError("{script_name} not yet implemented")


if __name__ == "__main__":
    import json as _json, sys as _sys
    _args = _json.loads(_sys.stdin.read() or "{{}}")
    result = {script_name}(**_args)
    print(_json.dumps(result, default=str))
'''


def _skill_md(name: str, description: str, script_names: list[str]) -> str:
    scripts_block = "\n".join(
        f"  - name: {s}\n    description: 'TODO: describe {s}'\n    file: {s}.py"
        for s in script_names
    )
    scripts_table = "\n".join(f"| `{s}(...)` | TODO |" for s in script_names)
    return f"""---
name: {name}
description: "{description}"
agent_type: api
tools:
  - execute_skill_script
scripts:
{scripts_block}
---

# {name.capitalize()} — System Prompt

You are the **{name}** sub-agent. {description}

## Scripts

| Script | Purpose |
|---|---|
{scripts_table}

## Hard rules

- Use `execute_skill_script` to call scripts declared above.
- After each script call, interpret the result before calling the next.
- Return a complete, structured response when done.
"""


def scaffold_skill(
    skill_name: str,
    parent_agent: str,
    description: str,
    script_names: Optional[list[str]] = None,
    overwrite: bool = False,
) -> str:
    """Generate a SKILL.md scaffold + script stubs for a new sub-agent.

    The system prompt is written directly into the SKILL.md body — no prompts/ directory.

    Args:
        skill_name: Directory name for the new skill (e.g. "my_checker").
        parent_agent: Parent agent directory under .olav/workspace/ (e.g. "admin").
        description: One-line description of what the skill does.
        script_names: List of script function names to scaffold (e.g. ["check_x", "report_x"]).
        overwrite: If False (default), refuse to overwrite an existing skill directory.

    Returns:
        Summary of files written, or an error message if the directory already exists.
    """
    if script_names is None:
        script_names = []

    skill_dir = _WORKSPACE / parent_agent / skill_name
    if skill_dir.exists() and not overwrite:
        return (
            f"Error: {skill_dir.relative_to(_PROJECT_ROOT)} already exists. "
            f"Pass overwrite=True to replace it."
        )

    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)

    written: list[str] = []

    # SKILL.md (body contains system prompt)
    skill_md_path = skill_dir / "SKILL.md"
    skill_md_path.write_text(_skill_md(skill_name, description, script_names))
    written.append(str(skill_md_path.relative_to(_PROJECT_ROOT)))

    # script stubs
    for s in script_names:
        sp = scripts_dir / f"{s}.py"
        sp.write_text(_script_skeleton(s, f"TODO: {s}"))
        written.append(str(sp.relative_to(_PROJECT_ROOT)))

    return "Scaffolded:\n" + "\n".join(f"  {w}" for w in written)


if __name__ == "__main__":
    import json as _json, sys as _sys
    _args = _json.loads(_sys.stdin.read() or "{}")
    result = scaffold_skill(**_args)
    print(_json.dumps(result, default=str))
