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
import subprocess
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

        # GAP-01: workspace.yaml is preferred; fall back to MANIFEST.yaml
        workspace_yaml_path = source_path / "workspace.yaml"
        manifest_yaml_path = source_path / "MANIFEST.yaml"

        if workspace_yaml_path.exists():
            try:
                decl = WorkspaceDeclaration.from_yaml(workspace_yaml_path)
            except KeyError as e:
                return f"error: workspace.yaml missing required field {e}"
            except Exception as e:  # noqa: BLE001
                return f"error: invalid workspace.yaml: {e}"
        elif manifest_yaml_path.exists():
            try:
                decl = _decl_from_manifest(manifest_yaml_path, source_path)
            except Exception as e:  # noqa: BLE001
                return f"error: invalid MANIFEST.yaml: {e}"
        else:
            return f"error: neither workspace.yaml nor MANIFEST.yaml found in {source}"

        # Binary check (warn, don't block)
        warnings: list[str] = []
        missing_bins = check_binary_requirements(decl.requires)
        if missing_bins:
            warnings.append(f"missing binaries: {', '.join(missing_bins)}")

        # Package check (warn, don't block)
        missing_pkgs = _check_packages(decl.requires.packages)
        if missing_pkgs:
            warnings.append(f"missing packages: {', '.join(missing_pkgs)}")

        # Create workspace directory and copy source files
        workspace_root = Path(".olav") / "workspace"
        workspace_dir = workspace_root / decl.name
        workspace_dir.mkdir(parents=True, exist_ok=True)

        # Copy all source files into workspace (preserving structure)
        _copy_skill_files(source_path, workspace_dir)

        # Create agent subdirectories from declaration (if declared)
        for agent in decl.agents:
            _create_agent_dir(workspace_dir, agent, decl.version)

        # Write lock file
        _write_lock_file(workspace_dir, decl, str(source_path.resolve()))

        # GAP-02: update PLATFORM.md agents list
        _update_platform_md(workspace_root, decl.name)

        # GAP-10: create per-skill venv if SKILL.md declares requires_packages
        venv_msg = ""
        skill_md_path = workspace_dir / "SKILL.md"
        packages = _read_requires_packages(skill_md_path)
        if packages:
            venv_result = _create_skill_venv(workspace_dir, packages)
            if venv_result["status"] == "ok":
                venv_msg = f"\n  venv: {venv_result.get('venv', workspace_dir / '.venv')} ({len(packages)} packages)"
            else:
                warnings.append(f"venv creation failed: {venv_result.get('error', 'unknown')}")

        # Update settings.json if set_active
        if decl.set_active:
            _update_active_workspace(decl.name)

        warn_str = ""
        if warnings:
            warn_str = "\n  ⚠ " + "\n  ⚠ ".join(warnings)

        return f"installed {decl.name} v{decl.version} → .olav/workspace/{decl.name}/{venv_msg}{warn_str}"

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


def _decl_from_manifest(manifest_path: Path, source_path: Path) -> "WorkspaceDeclaration":
    """Build a minimal WorkspaceDeclaration from a MANIFEST.yaml (GAP-01)."""
    import yaml as _yaml
    from olav.core.workspace import WorkspaceDeclaration, RequiresDeclaration

    raw = _yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    name = raw.get("name") or source_path.name
    version = str(raw.get("version", "0.0.0"))
    description = raw.get("description", f"{name} skill")

    # Synthesize a minimal declaration — no sub-agents, no requirements
    return WorkspaceDeclaration(
        name=name,
        version=version,
        description=description,
        agents=[],
        requires=RequiresDeclaration(packages=[], binaries=[]),
        set_active=False,
    )


def _copy_skill_files(source: Path, dest: Path) -> None:
    """Copy workspace files from source into dest (skip lock/workspace.yaml)."""
    import shutil
    skip = {"workspace.lock.yaml", "__pycache__"}
    for item in source.iterdir():
        if item.name in skip:
            continue
        target = dest / item.name
        if item.is_dir():
            if target.exists():
                # Merge: copy files not already present
                for sub in item.rglob("*"):
                    rel = sub.relative_to(item)
                    t = target / rel
                    if sub.is_dir():
                        t.mkdir(parents=True, exist_ok=True)
                    elif not t.exists():
                        shutil.copy2(sub, t)
            else:
                shutil.copytree(item, target)
        elif not target.exists():
            shutil.copy2(item, target)


def _read_requires_packages(skill_md: Path) -> list[str]:
    """Parse requires_packages from SKILL.md frontmatter (GAP-10)."""
    if not skill_md.exists():
        return []
    try:
        text = skill_md.read_text(encoding="utf-8").lstrip()
        if not text.startswith("---"):
            return []
        parts = text.split("---", 2)
        if len(parts) < 2:
            return []
        meta = yaml.safe_load(parts[1]) or {}
        return list(meta.get("requires_packages", []) or [])
    except Exception:  # noqa: BLE001
        return []


def _create_skill_venv(workspace_dir: Path, packages: list[str]) -> dict:
    """Create a per-skill .venv and install packages using uv (GAP-10).

    Returns:
        {"status": "ok", "venv": str} on success
        {"status": "error", "error": str} on failure
    """
    venv_dir = workspace_dir / ".venv"
    result = subprocess.run(
        ["uv", "venv", str(venv_dir)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return {"status": "error", "error": result.stderr or "uv venv failed"}

    pip_python = str(venv_dir / "bin" / "python")
    result = subprocess.run(
        ["uv", "pip", "install", "--python", pip_python, *packages],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return {"status": "error", "error": result.stderr or "uv pip install failed"}

    return {"status": "ok", "venv": str(venv_dir)}


def _update_platform_md(workspace_root: Path, agent_name: str) -> None:
    """GAP-02: append agent_name to PLATFORM.md agents list if not present."""
    from olav.core.platform_registry import PlatformRegistry, _parse_frontmatter

    platform_md = workspace_root / "PLATFORM.md"
    reg = PlatformRegistry.load(workspace_root)

    if agent_name in reg.agents:
        return  # already registered, no-op

    new_agents = reg.agents + [agent_name]

    if platform_md.exists():
        text = platform_md.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter(text)
    else:
        meta, body = {}, ""

    meta["agents"] = new_agents
    if not meta.get("active") and new_agents:
        meta["active"] = new_agents[0]

    import yaml as _yaml
    new_text = "---\n" + _yaml.dump(meta, default_flow_style=False) + "---\n"
    if body:
        new_text += "\n" + body
    platform_md.write_text(new_text, encoding="utf-8")
    logger.info("PLATFORM.md updated: agents=%s", new_agents)


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
