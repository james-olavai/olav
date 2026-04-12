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
            return "error: usage: olav skill install <path|url> [--merge-into <workspace>]"

        # Parse --merge-into flag
        merge_into: str | None = None
        filtered: list[str] = []
        i = 0
        while i < len(args):
            if args[i] == "--merge-into" and i + 1 < len(args):
                merge_into = args[i + 1]
                i += 2
            else:
                filtered.append(args[i])
                i += 1
        if not filtered:
            return "error: usage: olav skill install <path|url> [--merge-into <workspace>]"
        source = filtered[0]

        # GAP-06: git URL support — clone to temp dir then proceed
        tmp_dir: Path | None = None
        if _is_git_url(source):
            clone_result = _git_clone(source)
            if clone_result["status"] == "error":
                return f"error: git clone failed: {clone_result['error']}"
            tmp_dir = Path(clone_result["path"])
            source_path = tmp_dir
        elif _is_archive_url(source):
            extract_result = _download_and_extract(source)
            if extract_result["status"] == "error":
                return f"error: archive download/extract failed: {extract_result['error']}"
            tmp_dir = Path(extract_result["path"])
            source_path = tmp_dir
        else:
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

        # GAP-07: --merge-into appends tools to an existing workspace
        # SkillPack kind requires --merge-into (it's a toolset, not a standalone workspace)
        if getattr(decl, "kind", "Agent").lower() == "skillpack" and not merge_into:
            if tmp_dir:
                import shutil as _sh
                _sh.rmtree(tmp_dir, ignore_errors=True)
            return (
                "error: workspace.yaml declares kind: SkillPack — "
                "use --merge-into <workspace> to append tools to an existing workspace"
            )

        if merge_into:
            result = _merge_into_workspace(source_path, decl, merge_into)
            if tmp_dir:
                import shutil as _sh
                _sh.rmtree(tmp_dir, ignore_errors=True)
            return result

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

        # Copy workspace files into target directory.
        # If workspace.yaml declares `source: <subdir>`, copy from that subdir
        # instead of the repo root (avoids copying src/, tests/, .venv/, etc.)
        copy_source = source_path
        if decl.source:
            candidate = source_path / decl.source
            if candidate.is_dir():
                copy_source = candidate
        _copy_skill_files(copy_source, workspace_dir)

        # Create agent subdirectories from declaration (if declared)
        for agent in decl.agents:
            _create_agent_dir(workspace_dir, agent, decl.version)

        # Write lock file — record original git URL as source if cloned
        lock_source = source if not tmp_dir else source
        _write_lock_file(workspace_dir, decl, lock_source)

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

        # inject_into_core: symlink tools into core workspace
        inject_tools_into_core(decl, workspace_dir, workspace_root)

        # Clean up temp clone dir
        if tmp_dir:
            import shutil as _sh
            _sh.rmtree(tmp_dir, ignore_errors=True)

        warn_str = ""
        if warnings:
            warn_str = "\n  ⚠ " + "\n  ⚠ ".join(warnings)

        # Rebuild global agent registry so routing table reflects the new agent
        try:
            from olav.cli.commands.refresh import refresh_workspace

            refresh_workspace()
        except Exception as exc:  # noqa: BLE001
            logger.warning("refresh_workspace failed after skill install: %s", exc)

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
            "  install <path|url>              Install workspace from local dir or git URL\n"
            "  install <path|url> --merge-into <ws>  Append tools into existing workspace\n"
            "  list                            List installed workspaces\n"
            "  status <name>                   Show workspace status"
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
    """Persist the active workspace name in api.json."""
    api_path = Path(".olav") / "config" / "api.json"
    api_path.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if api_path.exists():
        try:
            data = json.loads(api_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            data = {}
    data["active_workspace"] = name
    api_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ── GAP-06: git URL detection + clone ─────────────────────────────────────────


def _is_git_url(source: str) -> bool:
    """Return True if source looks like a git remote URL."""
    return (
        source.startswith("https://")
        or source.startswith("http://")
        or source.startswith("git@")
        or source.startswith("git://")
        or source.endswith(".git")
    )


def _git_clone(url: str) -> dict:
    """Clone a git repository to a temporary directory.

    Returns:
        {"status": "ok", "path": str}  on success
        {"status": "error", "error": str}  on failure
    """
    import tempfile

    tmp = tempfile.mkdtemp(prefix="olav_skill_")
    result = subprocess.run(
        ["git", "clone", "--depth=1", url, tmp],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
        return {"status": "error", "error": result.stderr.strip() or "git clone failed"}
    return {"status": "ok", "path": tmp}


def _is_archive_url(source: str) -> bool:
    """Return True if source looks like a downloadable archive URL."""
    return (source.startswith("https://") or source.startswith("http://")) and (
        source.endswith(".tar.gz")
        or source.endswith(".tgz")
        or source.endswith(".zip")
    )


def _download_and_extract(url: str) -> dict:
    """Download an archive URL and extract it to a temporary directory.

    Supports .tar.gz / .tgz and .zip archives.

    Returns:
        {"status": "ok", "path": str}  on success
        {"status": "error", "error": str}  on failure
    """
    import shutil
    import tempfile
    import urllib.request

    tmp_dir = tempfile.mkdtemp(prefix="olav_skill_")
    suffix = ".zip" if url.endswith(".zip") else ".tar.gz"
    archive_path = Path(tmp_dir) / f"skillpack{suffix}"

    try:
        urllib.request.urlretrieve(url, str(archive_path))  # noqa: S310 (intentional)
    except Exception as exc:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return {"status": "error", "error": f"download failed: {exc}"}

    extract_dir = Path(tmp_dir) / "extracted"
    extract_dir.mkdir()

    try:
        if suffix == ".zip":
            import zipfile

            with zipfile.ZipFile(archive_path, "r") as zf:
                zf.extractall(extract_dir)
        else:
            import tarfile

            with tarfile.open(archive_path, "r:gz") as tf:
                tf.extractall(extract_dir)
    except Exception as exc:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return {"status": "error", "error": f"extraction failed: {exc}"}

    # If archive contains a single top-level dir, descend into it
    entries = list(extract_dir.iterdir())
    if len(entries) == 1 and entries[0].is_dir():
        return {"status": "ok", "path": str(entries[0])}
    return {"status": "ok", "path": str(extract_dir)}


# ── GAP-07: --merge-into ────────────────────────────────────────────────────


def _merge_into_workspace(
    source_path: Path,
    decl: "WorkspaceDeclaration",
    target_name: str,
) -> str:
    """Append tool references from source workspace into an existing workspace's SKILL.md.

    Steps:
    1. Locate target workspace directory (.olav/workspace/<target_name>).
    2. Copy tool files from source into target (skip duplicates).
    3. Parse target SKILL.md frontmatter and append new tool paths.
    4. Rewrite SKILL.md with merged tool list.

    Returns a human-readable status string.
    """
    workspace_root = Path(".olav") / "workspace"
    target_dir = workspace_root / target_name
    if not target_dir.exists():
        return f"error: target workspace '{target_name}' not found at {target_dir}"

    skill_md_path = target_dir / "SKILL.md"
    if not skill_md_path.exists():
        return f"error: target workspace '{target_name}' has no SKILL.md"

    # Parse existing SKILL.md frontmatter
    try:
        text = skill_md_path.read_text(encoding="utf-8").lstrip()
        if not text.startswith("---"):
            return f"error: SKILL.md in '{target_name}' has no frontmatter — cannot merge"
        parts = text.split("---", 2)
        if len(parts) < 3:
            return f"error: malformed SKILL.md frontmatter in '{target_name}'"
        fm_text, body = parts[1], parts[2]
        fm_data: dict = yaml.safe_load(fm_text) or {}
    except Exception as exc:  # noqa: BLE001
        return f"error: cannot parse SKILL.md in '{target_name}': {exc}"

    existing_tools: list[dict] = fm_data.get("tools", [])
    existing_paths = {t.get("path", "") for t in existing_tools if isinstance(t, dict)}

    # Copy source tool files into target workspace tools/ dir
    tools_src = source_path / "tools"
    tools_dest = target_dir / "tools"
    added_tools: list[str] = []

    if tools_src.is_dir():
        tools_dest.mkdir(exist_ok=True)
        import shutil
        for tool_file in sorted(tools_src.glob("*.py")):
            dest_file = tools_dest / tool_file.name
            if not dest_file.exists():
                shutil.copy2(tool_file, dest_file)
            # Record relative path for SKILL.md
            rel = str(dest_file.relative_to(Path(".")))
            if rel not in existing_paths:
                existing_tools.append({"path": rel})
                added_tools.append(rel)

    if not added_tools:
        return f"merge-into '{target_name}': no new tools to add (all already present)"

    # Rewrite SKILL.md frontmatter with merged tools
    fm_data["tools"] = existing_tools
    new_fm = yaml.dump(fm_data, default_flow_style=False, allow_unicode=True).rstrip()
    skill_md_path.write_text(f"---\n{new_fm}\n---{body}", encoding="utf-8")

    return (
        f"merged {len(added_tools)} tool(s) into '{target_name}':\n"
        + "\n".join(f"  + {p}" for p in added_tools)
    )


# ── inject_into_core ─────────────────────────────────────────────────────────


def inject_tools_into_core(
    decl: "WorkspaceDeclaration",
    skill_workspace_dir: Path,
    workspace_root: Path,
) -> None:
    """Inject tools declared in inject_into_core into the core workspace.

    For each tool path in decl.inject_into_core.tools:
    - Creates a symlink (or copy on non-POSIX) in core/tools/<toolname>
    - Appends an entry to core/SKILL.md if not already present

    Idempotent — safe to call multiple times.
    """
    if not decl.inject_into_core:
        return
    if not decl.inject_into_core.tools and not decl.inject_into_core.references:
        return

    core_dir = workspace_root / "core"
    if not core_dir.exists():
        return  # core workspace not present — skip silently

    core_tools_dir = core_dir / "tools"
    core_tools_dir.mkdir(parents=True, exist_ok=True)

    injected_names: list[str] = []

    for rel_tool_path in decl.inject_into_core.tools:
        src_file = skill_workspace_dir / rel_tool_path
        if not src_file.exists():
            continue
        tool_name = src_file.name
        dest = core_tools_dir / tool_name
        if dest.exists() or dest.is_symlink():
            continue  # already present — idempotent
        try:
            dest.symlink_to(src_file.resolve())
        except OSError:
            import shutil as _sh
            _sh.copy2(src_file, dest)
        injected_names.append(tool_name)

    if injected_names:
        _append_tools_to_skill_md(core_dir / "SKILL.md", injected_names, decl.name)


def remove_injected_tools_from_core(skill_name: str, workspace_root: Path) -> None:
    """Remove symlinks and SKILL.md entries injected by a skill from core workspace.

    Called during `olav skill uninstall <skill_name>`.
    """
    core_dir = workspace_root / "core"
    if not core_dir.exists():
        return

    core_tools_dir = core_dir / "tools"
    # Remove symlinks that point into the uninstalled skill's workspace dir
    if core_tools_dir.exists():
        skill_ws_dir = (workspace_root / skill_name).resolve()
        for entry in list(core_tools_dir.iterdir()):
            if entry.is_symlink():
                target = entry.resolve()
                try:
                    target.relative_to(skill_ws_dir)
                    entry.unlink()
                except ValueError:
                    pass  # symlink points elsewhere — keep it

    # Remove SKILL.md lines annotated with the skill name
    skill_md = core_dir / "SKILL.md"
    if skill_md.exists():
        lines = skill_md.read_text(encoding="utf-8").splitlines(keepends=True)
        new_lines = [
            ln for ln in lines
            if f"injected by {skill_name}" not in ln
        ]
        skill_md.write_text("".join(new_lines), encoding="utf-8")


def _append_tools_to_skill_md(skill_md_path: Path, tool_names: list[str], skill_name: str) -> None:
    """Append tool entries to SKILL.md, skipping entries already present."""
    if not skill_md_path.exists():
        return
    content = skill_md_path.read_text(encoding="utf-8")
    lines_to_add = []
    for name in tool_names:
        stem = Path(name).stem
        if stem not in content and name not in content:
            lines_to_add.append(f"  - {stem:<22} # injected by {skill_name}\n")
    if lines_to_add:
        skill_md_path.write_text(content + "".join(lines_to_add), encoding="utf-8")
