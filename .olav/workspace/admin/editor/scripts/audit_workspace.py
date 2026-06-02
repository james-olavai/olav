#!/usr/bin/env python3
"""audit_workspace.py - OLAV Workspace Code Quality Auditor.

Scans .olav/workspace/ for:
1. Python syntax errors in tool files
2. @tool name collisions within a skill
3. SKILL.md declared tools vs physical @tool functions (drift detection)
4. Missing prompts/system.md in subagent directories
5. Broken static_context: file references
"""

import ast
import json
from pathlib import Path

import yaml


def _find_project_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


_PROJECT_ROOT = _find_project_root()
_WORKSPACE_DIR = _PROJECT_ROOT / ".olav" / "workspace"


def _extract_tool_names(py_file: Path) -> tuple[list[str], str | None]:
    """Parse a Python file with AST; extract @tool-decorated function names.

    Returns (tool_names, syntax_error_message_or_None).
    """
    # Detect broken symlinks before attempting to read
    if py_file.is_symlink() and not py_file.exists():
        return [], f"BrokenSymlink: target does not exist → {py_file.resolve()}"
    try:
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(py_file))
    except SyntaxError as e:
        return [], f"SyntaxError at line {e.lineno}: {e.msg}"
    except Exception as e:
        return [], str(e)

    tool_names: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            is_tool = False
            if isinstance(decorator, ast.Name) and decorator.id == "tool":
                is_tool = True
            elif isinstance(decorator, ast.Call):
                func = decorator.func
                if isinstance(func, ast.Name) and func.id == "tool":
                    is_tool = True
                elif isinstance(func, ast.Attribute) and func.attr == "tool":
                    is_tool = True
            elif isinstance(decorator, ast.Attribute) and decorator.attr == "tool":
                is_tool = True
            if is_tool:
                tool_names.append(node.name)
    return tool_names, None


def _parse_skill_md(skill_md: Path) -> dict:
    """Extract YAML frontmatter from a SKILL.md file."""
    try:
        content = skill_md.read_text(encoding="utf-8")
        if not content.startswith("---"):
            return {}
        parts = content.split("---", 2)
        if len(parts) < 2:
            return {}
        return yaml.safe_load(parts[1]) or {}
    except Exception:
        return {}


def _declared_tools(meta: dict) -> list[str]:
    """Extract tool names from SKILL.md metadata, stripping inline comments.

    Handles two formats:
    - Root-level strings:  ``tools:\n  - tool_name  # comment``
    - Path-based dicts:    ``tools:\n  - path: ./tools/file.py``  (skip — no name check)
    """
    raw = meta.get("tools") or []
    result = []
    for t in raw:
        # Path-based format (e.g. audit/ subagents): skip drift check
        if isinstance(t, dict):
            continue
        # String format: strip inline comment and take first token
        name = str(t).split("#")[0].strip().split()[0] if t else ""
        if name:
            result.append(name)
    return result


def _audit_subagent(subagent_dir: Path) -> dict:
    """Run all checks on a single subagent directory."""
    result: dict = {
        "subagent": subagent_dir.name,
        "path": str(subagent_dir.relative_to(_PROJECT_ROOT)),
        "issues": [],
        "ok": [],
    }

    # --- 1. prompts/system.md existence ---
    prompt_file = subagent_dir / "prompts" / "system.md"
    if prompt_file.exists():
        result["ok"].append("prompts/system.md ✓")
    else:
        result["issues"].append({
            "type": "missing_prompt",
            "message": "Missing prompts/system.md",
            "severity": "error",
        })

    # --- 2. Tool file syntax + @tool extraction ---
    tools_dir = subagent_dir / "tools"
    tool_name_map: list[tuple[str, str]] = []  # (tool_name, filename)

    if tools_dir.exists():
        py_files = sorted(f for f in tools_dir.glob("*.py") if f.name != "__init__.py")
        for py_file in py_files:
            names, err = _extract_tool_names(py_file)
            if err:
                issue_type = "broken_symlink" if err.startswith("BrokenSymlink:") else "syntax_error"
                result["issues"].append({
                    "type": issue_type,
                    "file": py_file.name,
                    "message": err,
                    "severity": "error",
                })
            else:
                for name in names:
                    tool_name_map.append((name, py_file.name))

        # Detect @tool name collisions within this skill
        seen: dict[str, str] = {}
        for name, fname in tool_name_map:
            if name in seen:
                result["issues"].append({
                    "type": "tool_collision",
                    "tool": name,
                    "files": [seen[name], fname],
                    "message": f"@tool '{name}' defined in both '{seen[name]}' and '{fname}'",
                    "severity": "error",
                })
            else:
                seen[name] = fname
    else:
        result["ok"].append("tools/ not present (pure-prompt subagent)")

    discovered_names = [n for n, _ in tool_name_map]

    # --- 3. SKILL.md declared vs discovered drift ---
    skill_md = subagent_dir / "SKILL.md"
    if skill_md.exists():
        meta = _parse_skill_md(skill_md)
        declared = _declared_tools(meta)

        for d in declared:
            if d not in discovered_names:
                result["issues"].append({
                    "type": "undiscovered_tool",
                    "tool": d,
                    "message": f"SKILL.md declares '{d}' but no @tool found in tools/",
                    "severity": "warning",
                })

        for d in discovered_names:
            if d not in declared:
                result["issues"].append({
                    "type": "undeclared_tool",
                    "tool": d,
                    "message": f"@tool '{d}' exists but not listed in SKILL.md",
                    "severity": "warning",
                })

        matched = [d for d in declared if d in discovered_names]
        if declared:
            result["ok"].append(f"tools matched: {len(matched)}/{len(declared)}")

        # --- 4. static_context: file references ---
        static_ctx = meta.get("static_context") or []
        for entry in static_ctx:
            rel = entry.get("path", entry) if isinstance(entry, dict) else entry
            rel = str(rel).removeprefix("$ref:").strip()
            full = (subagent_dir / rel).resolve()
            if full.exists():
                result["ok"].append(f"static_context '{rel}' ✓")
            else:
                result["issues"].append({
                    "type": "broken_static_context",
                    "path": rel,
                    "message": f"static_context references missing file: '{rel}'",
                    "severity": "error",
                })
    else:
        result["issues"].append({
            "type": "missing_skill_md",
            "message": "Missing SKILL.md",
            "severity": "error",
        })

    return result


def _check_platform_md_stale() -> dict | None:
    """Check if olav.md is missing or lists agents not in the workspace.

    Returns a warning dict (compatible with audit issue format) if stale,
    or None if olav.md is up-to-date.
    """
    platform_md = _WORKSPACE_DIR / "olav.md"

    # Actual agent dirs (those with an AGENT.md)
    actual_agents = {
        d.name
        for d in _WORKSPACE_DIR.iterdir()
        if d.is_dir() and (d / "AGENT.md").exists()
    }

    if not platform_md.exists():
        if actual_agents:
            return {
                "type": "platform_md_missing",
                "message": f"olav.md does not exist — run `olav refresh` ({len(actual_agents)} agents found)",
                "severity": "warning",
            }
        return None

    # Parse agents list from olav.md frontmatter
    try:
        text = platform_md.read_text(encoding="utf-8")
        if text.startswith("---"):
            parts = text.split("---", 2)
            meta = yaml.safe_load(parts[1]) if len(parts) >= 2 else {}
        else:
            meta = {}
        registered: set[str] = set(meta.get("agents") or [])
    except Exception:
        registered = set()

    missing = actual_agents - registered
    extra = registered - actual_agents
    if missing or extra:
        parts_msg = []
        if missing:
            parts_msg.append(f"unregistered: {sorted(missing)}")
        if extra:
            parts_msg.append(f"stale: {sorted(extra)}")
        return {
            "type": "platform_md_stale",
            "message": "olav.md is out of date — " + ", ".join(parts_msg) + " — run `olav refresh`",
            "severity": "warning",
        }
    return None


def audit_workspace(agent_dir: str = "") -> str:
    """Audit .olav/workspace/ for code quality issues.

    Scans all subagent SKILL.md directories (or a specific agent subtree) and reports:
    - Python syntax errors in tool files
    - @tool name collisions within a skill
    - SKILL.md declared tool list vs actual @tool functions (drift)
    - Missing prompts/system.md
    - Broken static_context: file references
    - olav.md staleness (missing or out-of-date agent list)

    Args:
        agent_dir: Optional agent folder name to limit scope (e.g. "config", "ops").
                   Leave empty to scan the entire workspace.

    Returns:
        JSON with keys: summary (counts), report (human-readable text), details (per-subagent),
        platform_issues (olav.md staleness warnings).
    """
    if not _WORKSPACE_DIR.exists():
        return json.dumps({"error": f"Workspace not found: {_WORKSPACE_DIR}"})

    search_root = _WORKSPACE_DIR / agent_dir if agent_dir else _WORKSPACE_DIR
    if not search_root.exists():
        return json.dumps({"error": f"Directory not found: {search_root}"})

    skill_dirs = sorted(p.parent for p in search_root.rglob("SKILL.md"))
    if not skill_dirs:
        return json.dumps({"error": f"No SKILL.md found under {search_root}"})

    audit_results = []
    total_errors = 0
    total_warnings = 0

    for skill_dir in skill_dirs:
        audit = _audit_subagent(skill_dir)
        audit_results.append(audit)
        total_errors += sum(1 for i in audit["issues"] if i.get("severity") == "error")
        total_warnings += sum(1 for i in audit["issues"] if i.get("severity") == "warning")

    # olav.md staleness check (only when scanning whole workspace)
    platform_issues: list[dict] = []
    if not agent_dir:
        stale = _check_platform_md_stale()
        if stale:
            platform_issues.append(stale)
            total_warnings += 1

    summary = {
        "scanned": len(audit_results),
        "errors": total_errors,
        "warnings": total_warnings,
        "total_issues": total_errors + total_warnings,
        "status": "clean" if total_errors == 0 and total_warnings == 0 else
                  "has_errors" if total_errors > 0 else "has_warnings",
    }

    # Human-readable report
    lines = [
        f"=== OLAV Workspace Audit ({len(audit_results)} subagents scanned) ===",
        f"Summary: {total_errors} errors  |  {total_warnings} warnings",
        "",
    ]
    if platform_issues:
        lines.append("[platform]")
        for issue in platform_issues:
            lines.append(f"  ⚠️  [{issue['type']}] {issue['message']}")
        lines.append("")
    for r in audit_results:
        if r["issues"]:
            lines.append(f"[{r['subagent']}]  {r['path']}")
            for issue in r["issues"]:
                icon = "❌" if issue.get("severity") == "error" else "⚠️"
                lines.append(f"  {icon} [{issue['type']}] {issue['message']}")
        else:
            lines.append(f"[{r['subagent']}]  ✅ clean")

    return json.dumps({
        "summary": summary,
        "report": "\n".join(lines),
        "details": audit_results,
        "platform_issues": platform_issues,
    }, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    import json as _json, sys as _sys
    _args = _json.loads(_sys.stdin.read() or "{}")
    result = audit_workspace(**_args)
    print(result)
