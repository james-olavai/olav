#!/usr/bin/env python3
"""analyze_skill.py — Inspect an installed skill for OLAV compatibility issues.

Checks:
  * Whether SKILL.md has a ``scripts:`` frontmatter section
  * Whether ``execute_skill_script`` is in the ``tools:`` whitelist
  * For each script in scripts/: detects arg convention (argv / stdin / none)
    and whether it is declared in the SKILL.md ``scripts:`` list

Returns a compatibility report so the LLM can decide whether to run adapt_skill.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path


def _find_workspace_root() -> Path:
    import os
    env = os.environ.get("OLAV_WORKSPACE_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    here = Path.cwd().resolve()
    for p in [here, *here.parents]:
        candidate = p / ".olav" / "workspace"
        if candidate.is_dir():
            return candidate
    return here / ".olav" / "workspace"


def _detect_convention(script_path: Path) -> str:
    """Return 'argv', 'stdin', or 'none' based on static source analysis."""
    try:
        src = script_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return "none"
    if "argparse" in src or "sys.argv" in src:
        return "argv"
    if "sys.stdin" in src or "stdin.read" in src:
        return "stdin"
    return "none"


def _extract_docstring(script_path: Path) -> str:
    """Return first line of the module or first function docstring."""
    try:
        src = script_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src)
        mod_doc = ast.get_docstring(tree)
        if mod_doc:
            return mod_doc.splitlines()[0].strip()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                fn_doc = ast.get_docstring(node)
                if fn_doc:
                    return fn_doc.splitlines()[0].strip()
    except Exception:
        pass
    return ""


def _parse_frontmatter(skill_md: Path) -> dict:
    """Parse YAML frontmatter from SKILL.md. Returns {} on failure."""
    try:
        import yaml
        text = skill_md.read_text(encoding="utf-8")
        if not text.startswith("---"):
            return {}
        front = text.split("---", 2)[1]
        return yaml.safe_load(front) or {}
    except Exception:
        return {}


def analyze_skill(skill_name: str = "", path: str = "") -> dict:
    """Inspect a skill directory for OLAV compatibility gaps.

    Args:
        skill_name: Skill name to look up under .olav/workspace/ (e.g. "netops").
        path: Explicit filesystem path to the skill directory. Takes precedence
              over skill_name if both are given.

    Returns:
        Dict with keys:
          skill_name, skill_path, needs_adaptation, issues (list[str]),
          scripts (list of per-script info dicts), has_scripts_field,
          has_execute_skill_script_in_tools.
    """
    # Resolve skill directory
    if path:
        skill_dir = Path(path).expanduser().resolve()
    elif skill_name:
        ws = _find_workspace_root()
        # Direct match
        direct = ws / skill_name
        if (direct / "SKILL.md").exists():
            skill_dir = direct
        else:
            # One-level search
            found = None
            for parent in ws.iterdir():
                if not parent.is_dir():
                    continue
                candidate = parent / skill_name
                if (candidate / "SKILL.md").exists():
                    found = candidate
                    break
            if found is None:
                return {"status": "error", "error": f"skill '{skill_name}' not found"}
            skill_dir = found
    else:
        return {"status": "error", "error": "provide skill_name or path"}

    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return {"status": "error", "error": f"no SKILL.md at {skill_dir}"}

    meta = _parse_frontmatter(skill_md)
    declared_scripts: list[dict] = [
        e for e in meta.get("scripts", []) if isinstance(e, dict)
    ]
    declared_files = {e.get("file", "") for e in declared_scripts}
    tools_list: list[str] = [
        t for t in (meta.get("tools") or []) if isinstance(t, str)
    ]

    has_scripts_field: bool = "scripts" in meta
    has_execute: bool = "execute_skill_script" in tools_list

    # Scan scripts/ directory
    scripts_dir = skill_dir / "scripts"
    script_infos: list[dict] = []
    if scripts_dir.is_dir():
        for py in sorted(scripts_dir.glob("*.py")):
            convention = _detect_convention(py)
            declared_entry = next(
                (e for e in declared_scripts if e.get("file") == py.name), None
            )
            argv_flagged = bool(declared_entry and declared_entry.get("argv", False))
            script_infos.append({
                "file": py.name,
                "convention": convention,
                "in_skill_md": py.name in declared_files,
                "argv_flagged": argv_flagged,
                "description": _extract_docstring(py),
            })

    # Build issues list
    issues: list[str] = []
    if not has_scripts_field and script_infos:
        issues.append("SKILL.md missing scripts: field — scripts are undiscoverable by the LLM")
    if not has_execute and script_infos:
        issues.append("execute_skill_script missing from tools: whitelist — scripts cannot be called")
    for s in script_infos:
        if not s["in_skill_md"]:
            issues.append(f"script '{s['file']}' not declared in SKILL.md scripts: field")
        if s["convention"] == "argv" and not s["argv_flagged"]:
            issues.append(f"script '{s['file']}' uses argparse/sys.argv but lacks argv: true — will fail with JSON stdin")

    return {
        "status": "ok",
        "skill_name": meta.get("name", skill_dir.name),
        "skill_path": str(skill_dir),
        "has_scripts_field": has_scripts_field,
        "has_execute_skill_script_in_tools": has_execute,
        "scripts": script_infos,
        "needs_adaptation": len(issues) > 0,
        "issues": issues,
    }


if __name__ == "__main__":
    _args = json.loads(sys.stdin.read() or "{}")
    print(json.dumps(analyze_skill(**_args), default=str))
