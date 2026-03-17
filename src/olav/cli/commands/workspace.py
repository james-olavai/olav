"""Workspace lifecycle command skeleton."""

from __future__ import annotations

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

    _LIFECYCLE_ACTIONS = frozenset({"install", "upgrade", "remove", "rollback"})

    def __init__(self) -> None:
        super().__init__(name="workspace", description="Manage workspace lifecycle")
        self.workspace_root = Path(".olav") / "workspace"

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
        if action == "validate":
            if len(parts) < 2:
                return "workspace validate requires a skill/agent name"
            return self._validate(parts[1])

        return f"unknown workspace action: {action}"

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

        manifest_path = agent_dir / "MANIFEST.yaml"
        if not manifest_path.exists():
            return f"MANIFEST.yaml not found for {name}"

        from olav.core.agent_registry import AgentManifest

        try:
            manifest = AgentManifest.from_yaml(manifest_path)
        except (ValueError, Exception):
            return f"invalid MANIFEST.yaml for {name}"

        dep_result = manifest.check_dependencies()
        if dep_result.state == "unavailable":
            return f"{name}: valid manifest, dependencies unavailable — {dep_result.summary()}"

        return f"{name}: valid manifest, all dependencies available"
