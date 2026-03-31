"""skill.py — olav skill install/list/status command.

Subcommands:
  olav skill install <path|url>  — install workspace from local dir or git URL
  olav skill list                — list installed workspaces
  olav skill status <name>       — show workspace status

Reference: dev_docs/18. ECOSYSTEM_SPLIT_PLAN.md §2
"""

from __future__ import annotations

import importlib.util
import json
import logging
import shlex
from datetime import datetime, timezone
from pathlib import Path

import yaml

from olav.cli.commands.base import BaseCommand
from olav.core.workspace import WorkspaceDeclaration, check_binary_requirements

logger = logging.getLogger(__name__)

_CORE_AGENT_MD = """\
---
name: {name}
kind: {kind}
description: "{description}"
---

# {name}

{description}
"""

_MANIFEST_YAML = """\
kind: {kind}
name: {name}
version: "{version}"
description: "{description}"
route_keywords: {route_keywords}
"""


class SkillCommand(BaseCommand):
    """Install and manage workspace skills from git repos or local directories."""

    def __init__(self) -> None:
        super().__init__(name="skill", description="Install and manage workspace skills")

    async def execute(self, args: str = "") -> str:
        parts = shlex.split(args.strip()) if args.strip() else []
        if not parts:
            return self._usage()

        sub = parts[0]
        rest = parts[1:]

        if sub == "install":
            return await self._install(rest)
        if sub in ("list", "ls"):
            return self._list()
        if sub == "status":
            return self._status(rest)
        return self._usage()

    # ── install ────────────────────────────────────────────────────────────

    async def _install(self, args: list[str]) -> str:
        if not args:
            return "error: usage: olav skill install <path>"

        source = args[0]
        source_path = Path(source)

        if not source_path.exists():
            return f"error: path not found: {source}"

        if not source_path.is_dir():
            return f"error: not a directory: {source}"

        workspace_yaml_path = source_path / "workspace.yaml"
        if not workspace_yaml_path.exists():
            return f"error: workspace.yaml not found in {source}"

        try:
            decl = WorkspaceDeclaration.from_yaml(workspace_yaml_path)
        except KeyError as e:
            return f"error: workspace.yaml missing required field {e}"
        except Exception as e:  # noqa: BLE001
            return f"error: invalid workspace.yaml: {e}"

        # Binary check (warn, don't block)
        warnings: list[str] = []
        missing_bins = check_binary_requirements(decl.requires)
        if missing_bins:
            warnings.append(f"missing binaries: {', '.join(missing_bins)}")

        # Package check (warn, don't block)
        missing_pkgs = _check_packages(decl.requires.packages)
        if missing_pkgs:
            warnings.append(f"missing packages: {', '.join(missing_pkgs)}")

        # Create workspace directory
        workspace_root = Path(".olav") / "workspace"
        workspace_dir = workspace_root / decl.name
        workspace_dir.mkdir(parents=True, exist_ok=True)

        # Create agent subdirectories from declaration
        for agent in decl.agents:
            _create_agent_dir(workspace_dir, agent, decl.version)

        # Write lock file
        _write_lock_file(workspace_dir, decl, str(source_path.resolve()))

        # Update settings.json if set_active
        if decl.set_active:
            _update_active_workspace(decl.name)

        warn_str = ""
        if warnings:
            warn_str = "\n  ⚠ " + "\n  ⚠ ".join(warnings)

        return f"installed {decl.name} v{decl.version} → .olav/workspace/{decl.name}/{warn_str}"

    # ── list / status ───────────────────────────────────────────────────────

    def _list(self) -> str:
        workspace_root = Path(".olav") / "workspace"
        if not workspace_root.exists():
            return "no workspaces installed"
        lines = []
        for d in sorted(workspace_root.iterdir()):
            if not d.is_dir():
                continue
            lock = d / "workspace.lock.yaml"
            if lock.exists():
                data = yaml.safe_load(lock.read_text()) or {}
                ver = data.get("version", "?")
                lines.append(f"{d.name:20s}  v{ver}  (managed)")
            else:
                lines.append(f"{d.name:20s}  -       (user)")
        return "\n".join(lines) if lines else "no workspaces installed"

    def _status(self, args: list[str]) -> str:
        if not args:
            return "error: usage: olav skill status <name>"
        name = args[0]
        lock = Path(".olav") / "workspace" / name / "workspace.lock.yaml"
        if not lock.exists():
            return f"workspace '{name}' not found or not managed"
        data = yaml.safe_load(lock.read_text()) or {}
        lines = [f"name:    {data.get('name', name)}",
                 f"version: {data.get('version', '?')}",
                 f"source:  {data.get('source', 'unknown')}",
                 f"installed: {data.get('installed_at', 'unknown')}"]
        return "\n".join(lines)

    def _usage(self) -> str:
        return (
            "usage: olav skill <subcommand>\n"
            "  install <path>   Install workspace from local directory\n"
            "  list             List installed workspaces\n"
            "  status <name>    Show workspace status"
        )


# ── helpers ───────────────────────────────────────────────────────────────────

def _check_packages(packages: list[str]) -> list[str]:
    """Return package specs whose base name is not importable."""
    missing = []
    for spec in packages:
        # Strip version constraint to get package name
        pkg_name = spec.split(">")[0].split("<")[0].split("=")[0].split("!")[0].strip()
        # Convert to importable name (hyphens → underscores)
        mod_name = pkg_name.replace("-", "_")
        if importlib.util.find_spec(mod_name) is None:
            missing.append(spec)
    return missing


def _create_agent_dir(
    workspace_dir: Path, agent: "AgentDeclaration", version: str
) -> None:
    agent_dir = workspace_dir / agent.name
    agent_dir.mkdir(parents=True, exist_ok=True)

    agent_md = agent_dir / "AGENT.md"
    if not agent_md.exists():
        agent_md.write_text(
            _CORE_AGENT_MD.format(
                name=agent.name,
                kind=agent.kind,
                description=agent.description or f"{agent.name} agent",
            ),
            encoding="utf-8",
        )

    manifest = agent_dir / "MANIFEST.yaml"
    if not manifest.exists():
        rk = json.dumps(agent.route_keywords) if agent.route_keywords else "[]"
        manifest.write_text(
            _MANIFEST_YAML.format(
                kind=agent.kind,
                name=agent.name,
                version=version,
                description=agent.description or f"{agent.name} agent",
                route_keywords=rk,
            ),
            encoding="utf-8",
        )

    # Recurse for sub-agents
    for sub in agent.agents:
        _create_agent_dir(agent_dir, sub, version)


def _write_lock_file(workspace_dir: Path, decl: WorkspaceDeclaration, source: str) -> None:
    lock = {
        "name": decl.name,
        "version": decl.version,
        "source": source,
        "installed_at": datetime.now(tz=timezone.utc).isoformat(),
        "requires": {
            "packages": decl.requires.packages,
            "binaries": decl.requires.binaries,
        },
    }
    lock_path = workspace_dir / "workspace.lock.yaml"
    lock_path.write_text(yaml.dump(lock, default_flow_style=False), encoding="utf-8")


def _update_active_workspace(name: str) -> None:
    settings_path = Path(".olav") / "config" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            data = {}
    data["active_workspace"] = name
    settings_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
