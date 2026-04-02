"""Workspace lifecycle command (§8).

Subcommands:
  list              — list installed workspaces (managed + active marker)
  use <name>        — set active workspace in settings.json
  status            — show agents within workspaces
  validate <name>   — verify workspace integrity (lock file, agent dirs)
  migrate           — migrate flat agents → .olav/workspace/core/<agent>/
  diff              — diff local vs upstream versions
  upgrade <name>    — upgrade managed agent
  disable <name>    — disable agent
  remove <name>     — remove managed agent
  prune             — remove orphan entries
  rollback <n> --from <dir>  — restore from archive
  install <dir>     — install from local MANIFEST.yaml source
"""

from __future__ import annotations

import json
import re
import shlex
import shutil
from pathlib import Path

from olav.cli.commands.base import BaseCommand
from olav.core.auth.authz import AuthorizationError, require_permission


def _extract_source(requires: list[str]) -> str | None:
    """Return the base package name from the first requires entry, or None."""
    if not requires:
        return None
    # Strip version specifier: "olav-netops>=0.11" → "olav-netops"
    return re.split(r"[><=!]", requires[0])[0].strip()


class WorkspaceCommand(BaseCommand):
    """Manage workspace lifecycle for package-managed agents and skills."""

    _LIFECYCLE_ACTIONS = frozenset({"install", "upgrade", "remove", "rollback", "migrate", "use"})

    def __init__(self) -> None:
        super().__init__(name="workspace", description="Manage workspace lifecycle")
        from olav.core.workspace import resolve_workspace_root
        self.workspace_root = resolve_workspace_root()

    async def execute(self, args: str = "", role: str = "admin") -> str:
        parts = shlex.split(args.strip()) if args.strip() else ["status"]
        action = parts[0]

        if action in self._LIFECYCLE_ACTIONS:
            try:
                require_permission(role, "workspace", "*", "admin")
            except AuthorizationError as exc:
                return f"denied: {exc}"
        else:
            try:
                require_permission(role, "workspace", "*", "use")
            except AuthorizationError as exc:
                return f"denied: {exc}"

        if action in ("list", "ls"):
            return self._list_workspaces()
        if action == "use":
            if len(parts) < 2:
                return "error: usage: olav workspace use <name>"
            return self._use(parts[1])
        if action == "validate":
            if len(parts) < 2:
                return "error: usage: olav workspace validate <name>"
            return self._validate(parts[1])
        if action == "migrate":
            return self._migrate()
        if action == "status":
            return self._status()
        if action == "diff":
            return self._diff()
        if action == "upgrade":
            if len(parts) < 2:
                return "workspace upgrade requires an agent name"
            return self._upgrade(parts[1])
        if action == "disable":
            if len(parts) < 2:
                return "workspace disable requires an agent name"
            return self._disable(parts[1])
        if action == "remove":
            if len(parts) < 2:
                return "workspace remove requires an agent name"
            return self._remove(parts[1])
        if action == "prune":
            return self._prune()
        if action == "rollback":
            if len(parts) < 4 or parts[2] != "--from":
                return "workspace rollback usage: rollback <agent> --from <archive_dir>"
            return self._rollback(parts[1], parts[3])
        if action == "install":
            if len(parts) < 2:
                return "workspace install requires a source directory path"
            return self._install(parts[1])

        return f"unknown workspace action: {action}"

    # ── §8 new commands ───────────────────────────────────────────────────────

    def _list_workspaces(self) -> str:
        """List installed workspaces with version and active marker."""
        import yaml as _yaml
        from olav.core.workspace import get_active_workspace

        if not self.workspace_root.exists():
            return "no workspaces installed"

        active = get_active_workspace()
        lines = []
        for d in sorted(self.workspace_root.iterdir()):
            if not d.is_dir():
                continue
            lock_path = d / "workspace.lock.yaml"
            if lock_path.exists():
                try:
                    data = _yaml.safe_load(lock_path.read_text(encoding="utf-8")) or {}
                except Exception:  # noqa: BLE001
                    data = {}
                ver = data.get("version", "?")
                marker = "* " if d.name == active else "  "
                lines.append(f"{marker}{d.name:20s}  v{ver}  (managed)")
            elif self._is_agent_dir(d):
                marker = "* " if d.name == active else "  "
                lines.append(f"{marker}{d.name:20s}  -       (user)")

        return "\n".join(lines) if lines else "no workspaces installed"

    def _use(self, name: str) -> str:
        """Set active workspace in settings.json."""
        settings_path = Path(".olav") / "config" / "settings.json"
        settings_path.parent.mkdir(parents=True, exist_ok=True)

        data: dict = {}
        if settings_path.exists():
            try:
                data = json.loads(settings_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                data = {}

        ws_dir = self.workspace_root / name
        if not ws_dir.exists():
            # Warn but proceed — user may create the workspace later
            result_msg = f"⚠ workspace '{name}' not found at {ws_dir} (will set anyway)"
        else:
            result_msg = f"active workspace → {name}"

        data["active_workspace"] = name
        settings_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        # GAP-05: sync PLATFORM.md active: field
        _update_platform_md_active(self.workspace_root, name)

        return result_msg

    def _validate_workspace(self, name: str) -> str:
        """Validate workspace integrity: lock file presence and agent subdirs."""
        import yaml as _yaml

        ws_dir = self.workspace_root / name
        if not ws_dir.exists():
            return f"error: workspace '{name}' not found"

        lock_path = ws_dir / "workspace.lock.yaml"
        if not lock_path.exists():
            # Check if it's a flat agent dir (unmanaged)
            if self._is_agent_dir(ws_dir):
                return f"⚠ '{name}' is an unmanaged agent (no lock file) — run 'olav skill install' to manage it"
            return f"error: no lock file found for '{name}'"

        try:
            data = _yaml.safe_load(lock_path.read_text(encoding="utf-8")) or {}
        except Exception as e:  # noqa: BLE001
            return f"error: invalid lock file for '{name}': {e}"

        issues = []
        # Check declared agents exist
        # (lock file doesn't currently declare agents list — skip this check for now)

        if issues:
            return f"⚠ '{name}': {'; '.join(issues)}"
        return f"✓ '{name}' v{data.get('version', '?')} — valid"

    def _migrate(self) -> str:
        """Migrate flat agent dirs to .olav/workspace/core/<agent>/.

        Flat agents: dirs with AGENT.md but no workspace.lock.yaml
        (managed workspaces with lock files are left in place).
        """
        if not self.workspace_root.exists():
            return "workspace root not found — nothing to migrate"

        core_dir = self.workspace_root / "core"
        moved: list[str] = []
        skipped: list[str] = []

        for d in sorted(self.workspace_root.iterdir()):
            if not d.is_dir():
                continue
            if d.name == "core":
                continue  # skip the target dir itself
            if (d / "workspace.lock.yaml").exists():
                skipped.append(d.name)  # managed workspace — leave it
                continue
            if not self._is_agent_dir(d):
                continue  # not an agent dir at all

            target = core_dir / d.name
            if target.exists():
                skipped.append(d.name)  # already migrated
                continue

            core_dir.mkdir(parents=True, exist_ok=True)
            shutil.copytree(d, target)
            shutil.rmtree(d)
            moved.append(d.name)

        parts = []
        if moved:
            parts.append(f"migrated to core/: {', '.join(moved)}")
        if skipped:
            parts.append(f"skipped: {', '.join(skipped)}")
        if not moved and not skipped:
            parts.append("nothing to migrate")
        return "\n".join(parts)

    def _iter_agent_dirs(self) -> list[Path]:
        if not self.workspace_root.exists():
            return []
        return sorted([path for path in self.workspace_root.iterdir() if path.is_dir()])

    def _is_agent_dir(self, agent_dir: Path) -> bool:
        return any(
            (agent_dir / marker).exists() for marker in ["AGENT.md", "SKILL.md", "MANIFEST.yaml"]
        )

    def _status(self) -> str:
        from olav.core.agent_registry import discover_agents

        manifests = discover_agents(self.workspace_root)
        lines = []
        for agent_dir in self._iter_agent_dirs():
            if not self._is_agent_dir(agent_dir):
                continue
            name = agent_dir.name
            managed = (agent_dir / ".version").exists()
            disabled = (agent_dir / ".disabled").exists()
            managed_str = "managed" if managed else "user"
            state_str = "disabled" if disabled else "enabled"

            # MANIFEST.yaml enrichment
            m = manifests.get(name)
            if m:
                version = m.version
                kind_str = m.kind
                kw_count = len(m.route_keywords)
                source = _extract_source(m.requires)
                source_str = f"  ({source})" if source else ""

                dep_result = m.check_dependencies()
                dep_str = dep_result.state
                dep_detail = ""
                if dep_result.state == "unavailable":
                    dep_detail = f"  [{dep_result.summary()}]"

                lines.append(
                    f"{name:16s}  {kind_str:6s}  v{version}  [{managed_str}/{state_str}]"
                    f"  {dep_str}  {kw_count} route_keywords{source_str}{dep_detail}"
                )
            else:
                version = (
                    (agent_dir / ".version").read_text(encoding="utf-8").strip() if managed else "-"
                )
                lines.append(f"{name:16s}  -       v{version}  [{managed_str}/{state_str}]")
        return "\n".join(lines) if lines else "workspace empty"

    def _diff(self) -> str:
        lines = []
        for agent_dir in self._iter_agent_dirs():
            if not self._is_agent_dir(agent_dir):
                continue
            local = (
                (agent_dir / ".version").read_text(encoding="utf-8").strip()
                if (agent_dir / ".version").exists()
                else "-"
            )
            upstream = (
                (agent_dir / ".upstream-version").read_text(encoding="utf-8").strip()
                if (agent_dir / ".upstream-version").exists()
                else local
            )
            state = "in-sync" if local == upstream else "drift"
            lines.append(f"{agent_dir.name}: local={local} upstream={upstream} state={state}")
        return "\n".join(lines) if lines else "workspace empty"

    def _upgrade(self, agent_name: str) -> str:
        agent_dir = self.workspace_root / agent_name
        if not (agent_dir / ".version").exists():
            return f"refusing to upgrade unmanaged workspace entry: {agent_name}"
        current = (agent_dir / ".version").read_text(encoding="utf-8").strip()

        # Priority 1: explicit .upstream-version file
        upstream_file = agent_dir / ".upstream-version"
        if upstream_file.exists():
            target = upstream_file.read_text(encoding="utf-8").strip()
        else:
            # Priority 2/3: resolve from installed package metadata
            target = self._resolve_upstream_version(agent_name)
            if target is None:
                return (
                    f"no upstream version found for {agent_name} "
                    f"(install olav-workspace-{agent_name} or olav package, or create .upstream-version)"
                )

        if target == current:
            return f"{agent_name} already at {current} (up-to-date)"

        (agent_dir / ".version").write_text(f"{target}\n", encoding="utf-8")
        return f"upgraded {agent_name}: {current} -> {target}"

    def _resolve_upstream_version(self, agent_name: str) -> str | None:
        """Resolve upstream version from installed package metadata.

        Lookup order:
        1. ``olav-workspace-{agent_name}`` — dedicated agent package
        2. ``olav`` — platform package (used as fallback)

        Returns the version string, or None if neither package is installed.
        """
        import importlib.metadata as meta

        candidates = [f"olav-workspace-{agent_name}", "olav"]
        for pkg in candidates:
            try:
                return meta.version(pkg)
            except meta.PackageNotFoundError:
                continue
        return None

    def _disable(self, agent_name: str) -> str:
        agent_dir = self.workspace_root / agent_name
        if not agent_dir.exists():
            return f"workspace entry not found: {agent_name}"
        (agent_dir / ".disabled").write_text("disabled\n", encoding="utf-8")
        return f"disabled {agent_name}"

    def _remove(self, agent_name: str) -> str:
        agent_dir = self.workspace_root / agent_name
        if not (agent_dir / ".version").exists():
            return f"refusing to remove unmanaged workspace entry: {agent_name}"
        shutil.rmtree(agent_dir)
        return f"removed {agent_name}"

    def _prune(self) -> str:
        removed = 0
        for agent_dir in self._iter_agent_dirs():
            if self._is_agent_dir(agent_dir):
                continue
            shutil.rmtree(agent_dir)
            removed += 1
        return f"pruned {removed} orphan workspace entries"

    def _rollback(self, agent_name: str, archive_dir: str) -> str:
        source_dir = Path(archive_dir) / agent_name
        if not source_dir.exists():
            return f"archive entry not found: {source_dir}"
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        target_dir = self.workspace_root / agent_name
        if target_dir.exists():
            shutil.rmtree(target_dir)
        shutil.copytree(source_dir, target_dir)
        return f"restored {agent_name} from {source_dir}"

    def _install(self, source: str) -> str:
        source_dir = Path(source)
        if not source_dir.is_dir():
            return f"source directory not found: {source}"

        manifest_path = source_dir / "MANIFEST.yaml"
        if not manifest_path.exists():
            return f"MANIFEST.yaml not found in {source}"

        from olav.core.agent_registry import AgentManifest

        try:
            manifest = AgentManifest.from_yaml(manifest_path)
        except (ValueError, Exception):
            return f"invalid MANIFEST.yaml in {source}"

        self.workspace_root.mkdir(parents=True, exist_ok=True)
        target_dir = self.workspace_root / manifest.name
        if target_dir.exists():
            shutil.rmtree(target_dir)
        shutil.copytree(source_dir, target_dir)

        dep_result = manifest.check_dependencies()
        dep_info = ""
        if dep_result.state == "unavailable":
            dep_info = f" (warning: {dep_result.summary()})"

        return f"installed {manifest.name} into workspace{dep_info}"

    def _validate(self, name: str) -> str:
        agent_dir = self.workspace_root / name
        if not agent_dir.exists():
            return f"workspace entry not found: {name}"

        lock_path = agent_dir / "workspace.lock.yaml"
        if lock_path.exists():
            # Managed workspace — validate lock file + agent dirs
            return self._validate_workspace(name)

        # Flat (unmanaged) agent — check MANIFEST.yaml + dependencies
        manifest_path = agent_dir / "MANIFEST.yaml"
        if not manifest_path.exists():
            return f"⚠ '{name}' is an unmanaged agent (no lock file) — run 'olav skill install' to manage it"

        from olav.core.agent_registry import AgentManifest

        try:
            manifest = AgentManifest.from_yaml(manifest_path)
        except (ValueError, Exception):
            return f"invalid MANIFEST.yaml for {name}"

        dep_result = manifest.check_dependencies()
        if dep_result.state == "unavailable":
            return f"{name}: valid manifest, dependencies unavailable — {dep_result.summary()}"

        return f"{name}: valid manifest, all dependencies available"


# ── module-level helpers ──────────────────────────────────────────────────────

def _update_platform_md_active(workspace_root: Path, agent_name: str) -> None:
    """GAP-05: update PLATFORM.md active: field when workspace use is called."""
    from olav.core.platform_registry import PlatformRegistry, _parse_frontmatter
    import yaml as _yaml

    platform_md = workspace_root / "PLATFORM.md"
    if not platform_md.exists():
        return  # nothing to update if PLATFORM.md doesn't exist

    try:
        text = platform_md.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter(text)
        meta["active"] = agent_name
        new_text = "---\n" + _yaml.dump(meta, default_flow_style=False) + "---\n"
        if body:
            new_text += "\n" + body
        platform_md.write_text(new_text, encoding="utf-8")
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Failed to update PLATFORM.md active: %s", exc)
