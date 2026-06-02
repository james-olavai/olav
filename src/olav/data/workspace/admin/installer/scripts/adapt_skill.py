#!/usr/bin/env python3
"""adapt_skill.py — Patch a skill's SKILL.md to meet OLAV conventions.

Applied fixes (only what is needed per the analysis report):
  1. Add ``execute_skill_script`` to ``tools:`` if missing
  2. Add ``scripts:`` section for undeclared scripts (name from filename,
     description from docstring, argv: true if argparse-style detected)
  3. Set ``argv: true`` on existing script entries that use sys.argv/argparse

All changes are written in-place. The original frontmatter structure is
preserved; only the minimum required fields are added or modified.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def _read_skill_md(skill_md: Path) -> tuple[str, str, str]:
    """Return (pre_front, front_yaml, body) splitting on --- delimiters."""
    text = skill_md.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return ("", "", text)
    parts = text.split("---", 2)
    if len(parts) < 3:
        return ("", "", text)
    return ("---", parts[1], "---" + parts[2])


def _write_skill_md(skill_md: Path, front_yaml: str, body: str) -> None:
    skill_md.write_text(f"---{front_yaml}---{body}", encoding="utf-8")


def adapt_skill(skill_path: str, analysis: dict | None = None) -> dict:
    """Patch SKILL.md to meet OLAV compatibility conventions.

    Args:
        skill_path: Absolute or relative path to the skill directory.
        analysis: Output dict from analyze_skill. If omitted, re-runs
                  analysis internally.

    Returns:
        Dict with ``changes`` (list of applied fixes) and ``modified`` (bool).
    """
    skill_dir = Path(skill_path).expanduser().resolve()
    skill_md = skill_dir / "SKILL.md"

    if not skill_md.is_file():
        return {"status": "error", "error": f"no SKILL.md at {skill_dir}"}

    # Re-analyse if not supplied
    if analysis is None:
        import importlib.util, pathlib
        spec = importlib.util.spec_from_file_location(
            "analyze_skill",
            pathlib.Path(__file__).parent / "analyze_skill.py",
        )
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        analysis = mod.analyze_skill(path=skill_path)

    if analysis.get("status") == "error":
        return analysis

    if not analysis.get("needs_adaptation"):
        return {"status": "ok", "modified": False, "changes": []}

    _, front_yaml, body = _read_skill_md(skill_md)
    changes: list[str] = []

    # ── 1. Inject execute_skill_script into tools: ────────────────────────
    if not analysis["has_execute_skill_script_in_tools"] and analysis["scripts"]:
        if re.search(r"^tools\s*:", front_yaml, re.MULTILINE):
            # Append under existing tools: block
            front_yaml = re.sub(
                r"(^tools\s*:(?:\n(?:[ \t]+[^\n]*))*)",
                lambda m: m.group(0).rstrip() + "\n  - execute_skill_script",
                front_yaml,
                flags=re.MULTILINE,
            )
        else:
            # Add tools: block before first non-name/description line
            front_yaml = front_yaml.rstrip("\n") + "\ntools:\n  - execute_skill_script\n"
        changes.append("added execute_skill_script to tools:")

    # ── 2. Build / update scripts: section ───────────────────────────────
    script_infos: list[dict] = analysis.get("scripts", [])
    undeclared = [s for s in script_infos if not s["in_skill_md"]]
    argv_needs_flag = [
        s for s in script_infos
        if s["in_skill_md"] and s["convention"] == "argv" and not s["argv_flagged"]
    ]

    if undeclared or argv_needs_flag:
        if not analysis["has_scripts_field"]:
            # Build fresh scripts: block
            lines = ["\nscripts:"]
            for s in script_infos:
                name = s["file"].removesuffix(".py")
                lines.append(f"  - name: {name}")
                lines.append(f"    file: {s['file']}")
                if s["description"]:
                    # Escape any YAML-special chars in description
                    desc = s["description"].replace('"', '\\"')
                    lines.append(f'    description: "{desc}"')
                if s["convention"] == "argv":
                    lines.append("    argv: true")
            front_yaml = front_yaml.rstrip("\n") + "\n".join(lines) + "\n"
            changes.append(
                f"added scripts: section with {len(script_infos)} entr{'y' if len(script_infos)==1 else 'ies'}"
            )
            if any(s["convention"] == "argv" for s in script_infos):
                changes.append("set argv: true on argparse-style scripts")
        else:
            # Append undeclared entries to existing scripts: block
            for s in undeclared:
                name = s["file"].removesuffix(".py")
                entry_lines = [f"  - name: {name}", f"    file: {s['file']}"]
                if s["description"]:
                    desc = s["description"].replace('"', '\\"')
                    entry_lines.append(f'    description: "{desc}"')
                if s["convention"] == "argv":
                    entry_lines.append("    argv: true")
                entry_str = "\n".join(entry_lines)
                # Insert before the end of the scripts: block
                front_yaml = re.sub(
                    r"(^scripts\s*:(?:\n(?:[ \t]+[^\n]*))*)",
                    lambda m, e=entry_str: m.group(0).rstrip() + "\n" + e,
                    front_yaml,
                    flags=re.MULTILINE,
                )
                changes.append(f"declared undeclared script '{s['file']}'")

            # Set argv: true on existing entries that need it
            for s in argv_needs_flag:
                # Find the entry by file: <name> and add argv: true after it
                front_yaml = re.sub(
                    rf"(file\s*:\s*{re.escape(s['file'])}[^\n]*)",
                    r"\1\n    argv: true",
                    front_yaml,
                )
                changes.append(f"set argv: true on '{s['file']}'")

    if not changes:
        return {"status": "ok", "modified": False, "changes": []}

    _write_skill_md(skill_md, front_yaml, body)
    return {
        "status": "ok",
        "modified": True,
        "skill_path": str(skill_dir),
        "changes": changes,
    }


if __name__ == "__main__":
    _args = json.loads(sys.stdin.read() or "{}")
    print(json.dumps(adapt_skill(**_args), default=str))
