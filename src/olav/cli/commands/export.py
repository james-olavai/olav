"""Claude compatibility export command skeleton."""

from __future__ import annotations

import json
import shlex
import shutil
from pathlib import Path
from typing import Any

import yaml

from olav.cli.commands.base import BaseCommand

# OLAV-specific AGENT.md frontmatter keys that must not appear in Claude exports
_OLAV_ONLY_KEYS = frozenset({"system_prompt_file", "static_context"})


def _load_manifest_meta(agent_dir: Path) -> dict[str, Any]:
    """Load MANIFEST.yaml from *agent_dir* and return its contents as a dict.

    Returns an empty dict if no MANIFEST.yaml exists or if it is unreadable.
    """
    manifest_path = agent_dir / "MANIFEST.yaml"
    if not manifest_path.exists():
        return {}
    try:
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Extract YAML frontmatter from a Markdown document.

    Returns (frontmatter_dict, body_text).  If there is no frontmatter,
    returns ({}, text).  Uses a simple line-by-line parser to avoid
    requiring PyYAML at runtime.
    """
    if not text.startswith("---"):
        return {}, text

    lines = text.splitlines(keepends=True)
    end_idx = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return {}, text

    fm_lines = lines[1:end_idx]
    body = "".join(lines[end_idx + 1:])

    # Minimal YAML subset parser: key: value, lists, quoted strings
    result: dict[str, Any] = {}
    current_key: str | None = None
    current_list: list[str] | None = None

    for raw in fm_lines:
        stripped = raw.rstrip("\n")
        # List item
        if stripped.startswith("  - ") and current_list is not None:
            current_list.append(stripped[4:].strip())
            continue
        # Inline empty list
        if ":" in stripped:
            key, _, val = stripped.partition(":")
            key = key.strip()
            val = val.strip()
            # Flush previous list
            if current_key and current_list is not None:
                result[current_key] = current_list
            current_list = None
            current_key = key
            if val in ("[]", ""):
                if val == "[]":
                    result[key] = []
                    current_key = None
                else:
                    current_list = []
            else:
                # Strip surrounding quotes
                v = val.strip('"').strip("'")
                result[key] = v
                current_key = None
    # Flush trailing list
    if current_key and current_list is not None:
        result[current_key] = current_list

    return result, body


def _render_frontmatter(data: dict[str, Any]) -> str:
    """Render a dict as minimal YAML frontmatter."""
    lines = ["---"]
    for key, value in data.items():
        if isinstance(value, list):
            if not value:
                lines.append(f"{key}: []")
            else:
                lines.append(f"{key}:")
                for item in value:
                    lines.append(f"  - {item}")
        else:
            # Quote if contains special chars
            v = str(value)
            if any(c in v for c in ('"', "'", ":", "#", "{")):
                lines.append(f'{key}: "{v}"')
            else:
                lines.append(f"{key}: {v}")
    lines.append("---")
    return "\n".join(lines) + "\n"


class ExportCommand(BaseCommand):
    """Export workspace agents to Claude-compatible layouts."""

    def __init__(self) -> None:
        super().__init__(name="export", description="Export Claude-compatible artifacts")
        self.workspace_root = Path(".olav") / "workspace"

    async def execute(self, args: str = "") -> str:
        parts = shlex.split(args.strip()) if args.strip() else []
        if not parts:
            return "export requires a target: claude-skills or claude-plugin"

        export_kind = parts[0]
        parsed = self._parse_options(parts[1:])
        agent_name = parsed.get("agent")
        output_dir = parsed.get("output")
        if not agent_name or not output_dir:
            return "export requires --agent <name> and --output <path>"

        if export_kind == "claude-skills":
            return self._export_claude_skills(agent_name, output_dir)
        if export_kind == "claude-plugin":
            return self._export_claude_plugin(agent_name, output_dir)
        return f"unknown export target: {export_kind}"

    def _parse_options(self, args: list[str]) -> dict[str, str]:
        parsed: dict[str, str] = {}
        i = 0
        while i < len(args):
            token = args[i]
            if token.startswith("--") and i + 1 < len(args):
                parsed[token[2:]] = args[i + 1]
                i += 2
                continue
            i += 1
        return parsed

    def _agent_dir(self, agent_name: str) -> Path:
        return self.workspace_root / agent_name

    def _export_claude_skills(self, agent_name: str, output_dir: str) -> str:
        agent_dir = self._agent_dir(agent_name)
        skill_file = agent_dir / "SKILL.md"
        if not skill_file.exists():
            return f"skill file not found for agent: {agent_name}"
        target = Path(output_dir) / "skills" / agent_name
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(skill_file, target / "SKILL.md")
        return f"exported Claude skills for {agent_name} -> {target}"

    def _export_claude_plugin(self, agent_name: str, output_dir: str) -> str:
        agent_dir = self._agent_dir(agent_name)
        agent_file = agent_dir / "AGENT.md"
        skill_file = agent_dir / "SKILL.md"
        if not agent_file.exists():
            return f"agent file not found for agent: {agent_name}"

        # Parse OLAV AGENT.md frontmatter
        raw_text = agent_file.read_text(encoding="utf-8")
        frontmatter, body = _parse_frontmatter(raw_text)

        # Load MANIFEST.yaml enrichment (if present)
        manifest_meta = _load_manifest_meta(agent_dir)

        root = Path(output_dir)
        plugin_dir = root / ".claude-plugin"
        plugin_dir.mkdir(parents=True, exist_ok=True)

        # Write Claude-compatible agents/{agent}.md — strip OLAV-only keys
        agents_dir = root / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        claude_fm = {k: v for k, v in frontmatter.items() if k not in _OLAV_ONLY_KEYS}
        claude_md = _render_frontmatter(claude_fm) + "\n" + body
        (agents_dir / f"{agent_name}.md").write_text(claude_md, encoding="utf-8")

        if skill_file.exists():
            skills_dir = root / "skills" / agent_name
            skills_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(skill_file, skills_dir / "SKILL.md")

        # Build enriched plugin.json — MANIFEST takes priority for routing metadata
        plugin_meta: dict[str, Any] = {
            "name": manifest_meta.get("name") or frontmatter.get("name", f"olav-{agent_name}-plugin"),
            "version": manifest_meta.get("version", "0.1.0"),
            "agents_dir": "agents",
            "skills_dir": "skills",
            "route_keywords": manifest_meta.get("route_keywords", []),
        }
        if manifest_meta.get("kind"):
            plugin_meta["kind"] = manifest_meta["kind"]
        if "description" in frontmatter:
            plugin_meta["description"] = frontmatter["description"]
        if "subagents" in frontmatter and frontmatter["subagents"]:
            plugin_meta["subagents"] = frontmatter["subagents"]

        (plugin_dir / "plugin.json").write_text(
            json.dumps(plugin_meta, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return f"exported Claude plugin for {agent_name} -> {root}"
