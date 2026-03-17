"""
src/olav/core/agent_registry.py
────────────────────────────────
Declarative agent / skill manifest discovery.

Scans a workspace root directory recursively for MANIFEST.yaml files and
returns a dict of ``{name: AgentManifest}`` for use by the platform router
and workspace status commands.

Design reference: dev_docs/olav_platform.md §6.2 – §6.3
"""

from __future__ import annotations

import importlib
import importlib.metadata
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

logger = logging.getLogger(__name__)

AvailabilityState = Literal["available", "unavailable"]


@dataclass
class DependencyCheckResult:
    """Result of checking an AgentManifest's runtime dependencies.

    Attributes
    ----------
    state:
        ``"available"`` if all dependencies are satisfied,
        ``"unavailable"`` if any are missing.
    missing_modules:
        Python modules declared in ``required_modules`` that cannot be imported.
    missing_binaries:
        External binaries declared in ``required_binaries`` not found on ``$PATH``.
    missing_provider:
        True if ``provider_package`` is declared but not installed.
    """

    state: AvailabilityState = "available"
    missing_modules: list[str] = field(default_factory=list)
    missing_binaries: list[str] = field(default_factory=list)
    missing_provider: bool = False

    def summary(self) -> str:
        """Return a human-readable summary of missing dependencies."""
        parts: list[str] = []
        if self.missing_provider:
            parts.append("provider package not installed")
        if self.missing_modules:
            parts.append(f"missing modules: {', '.join(self.missing_modules)}")
        if self.missing_binaries:
            parts.append(f"missing binaries: {', '.join(self.missing_binaries)}")
        return "; ".join(parts) if parts else "all dependencies satisfied"


@dataclass
class AgentManifest:
    """Parsed representation of a MANIFEST.yaml file.

    Attributes
    ----------
    name:
        Unique name of the agent or skill (MANIFEST.yaml ``name`` field).
    kind:
        ``"Agent"`` or ``"Skill"`` (MANIFEST.yaml ``kind`` field).
    version:
        Semantic version string, e.g. ``"0.11.0"``.
    path:
        Absolute path to the MANIFEST.yaml file on disk.
    agent:
        For Skills only — the parent agent this skill registers to.
    route_keywords:
        List of natural-language utterances used by the semantic router.
    tools_dir:
        Relative path to the tools directory (Agents only, optional).
    requires:
        List of Python package requirements, e.g. ``["olav-platform>=0.11"]``.
    provider_package:
        Python package that provides the runtime implementation (e.g. ``"olav-netops"``).
    required_modules:
        Python modules that must be importable for the skill to be available.
    required_binaries:
        External binaries that must exist on ``$PATH``.
    config_namespace:
        Configuration namespace under ``.olav/config/domains/`` (e.g. ``"netops"``).
    """

    name: str
    kind: str
    version: str
    path: Path
    agent: str | None = None
    route_keywords: list[str] = field(default_factory=list)
    tools_dir: str | None = None
    requires: list[str] = field(default_factory=list)
    provider_package: str | None = None
    required_modules: list[str] = field(default_factory=list)
    required_binaries: list[str] = field(default_factory=list)
    config_namespace: str | None = None

    # ── factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_yaml(cls, path: Path) -> AgentManifest:
        """Parse *path* and return an :class:`AgentManifest`.

        Raises
        ------
        ValueError
            If the YAML is valid but missing required keys (``name`` / ``kind``).
        yaml.YAMLError
            If the file is not valid YAML.
        """
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"MANIFEST.yaml at {path} must be a YAML mapping")

        name = raw.get("name")
        kind = raw.get("kind")
        if not name or not kind:
            raise ValueError(
                f"MANIFEST.yaml at {path} is missing required fields: 'name' and/or 'kind'"
            )

        return cls(
            name=str(name),
            kind=str(kind),
            version=str(raw.get("version", "0.0.0")),
            path=path,
            agent=raw.get("agent"),
            route_keywords=list(raw.get("route_keywords") or []),
            tools_dir=raw.get("tools_dir"),
            requires=list(raw.get("requires") or []),
            provider_package=raw.get("provider_package"),
            required_modules=list(raw.get("required_modules") or []),
            required_binaries=list(raw.get("required_binaries") or []),
            config_namespace=raw.get("config_namespace"),
        )

    # ── dependency checking ───────────────────────────────────────────────────

    def check_dependencies(self) -> DependencyCheckResult:
        """Check whether this manifest's runtime dependencies are satisfied.

        Returns
        -------
        DependencyCheckResult
            Contains the availability state and details of any missing deps.
        """
        missing_modules: list[str] = []
        missing_binaries: list[str] = []
        missing_provider = False

        if self.provider_package:
            try:
                importlib.metadata.version(self.provider_package)
            except importlib.metadata.PackageNotFoundError:
                missing_provider = True

        for mod in self.required_modules:
            spec = importlib.util.find_spec(mod)
            if spec is None:
                missing_modules.append(mod)

        for binary in self.required_binaries:
            if shutil.which(binary) is None:
                missing_binaries.append(binary)

        state: AvailabilityState = "available"
        if missing_provider or missing_modules or missing_binaries:
            state = "unavailable"

        return DependencyCheckResult(
            state=state,
            missing_modules=missing_modules,
            missing_binaries=missing_binaries,
            missing_provider=missing_provider,
        )


# ── discovery ─────────────────────────────────────────────────────────────────


def discover_agents(workspace_root: Path) -> dict[str, AgentManifest]:
    """Scan *workspace_root* recursively for MANIFEST.yaml files.

    Parameters
    ----------
    workspace_root:
        Root directory to scan (e.g. ``Path(".olav/workspace")``).

    Returns
    -------
    dict[str, AgentManifest]
        Mapping of ``{manifest.name: manifest}``.  Manifests that fail to
        parse are silently skipped and a warning is emitted.  Returns an
        empty dict if *workspace_root* does not exist.
    """
    if not workspace_root.is_dir():
        return {}

    manifests: dict[str, AgentManifest] = {}
    for manifest_path in workspace_root.rglob("MANIFEST.yaml"):
        try:
            m = AgentManifest.from_yaml(manifest_path)
            manifests[m.name] = m
        except Exception as exc:  # noqa: BLE001
            logger.warning("Skipping malformed MANIFEST.yaml at %s: %s", manifest_path, exc)

    return manifests


# ── config merging ────────────────────────────────────────────────────────────


def merge_into_config(
    olav_config: dict,
    manifests: dict[str, AgentManifest],
    agent_id: str,
) -> dict:
    """Merge MANIFEST-discovered subagents into an agent's AGENT.md config dict.

    Rules (from olav_platform.md §11.5):
    - AGENT.md explicit subagents are authoritative — they are never removed.
    - MANIFEST entries whose ``agent`` field matches *agent_id* are appended
      as new subagents **only if not already declared** in AGENT.md.
    - Same-name MANIFEST entries: last writer wins (dict insertion order).

    Parameters
    ----------
    olav_config:
        Parsed AGENT.md frontmatter dict (mutable copy will be returned).
    manifests:
        ``{name: AgentManifest}`` mapping from :func:`discover_agents`.
    agent_id:
        The current agent's identifier (e.g. ``"quick"``).  Only MANIFEST
        entries whose ``agent == agent_id`` are injected.

    Returns
    -------
    dict
        Updated config dict with any new subagent paths appended.
    """
    import copy

    config = copy.deepcopy(olav_config)
    existing_subagents: list = config.get("subagents") or []

    # Normalise existing entries to a set of path strings for dedup check
    existing_paths: set[str] = set()
    for entry in existing_subagents:
        if isinstance(entry, str):
            existing_paths.add(entry)
        elif isinstance(entry, dict):
            p = entry.get("path", "")
            if p:
                existing_paths.add(p)

    injected = 0
    for name, manifest in manifests.items():
        # Only inject Skills that declare they belong to this agent
        if manifest.kind != "Skill":
            continue
        if manifest.agent != agent_id:
            continue

        # ── HP-3: dependency gating — skip if deps unavailable ────────────
        dep_result = manifest.check_dependencies()
        if dep_result.state == "unavailable":
            logger.warning("Skipping %s: dependencies unavailable — %s", name, dep_result.summary())
            continue

        # Derive a workspace-relative SKILL.md path from the manifest path.
        # manifest.path is the absolute path to MANIFEST.yaml;
        # the SKILL.md lives next to it.
        skill_md = manifest.path.parent / "SKILL.md"
        if not skill_md.exists():
            logger.debug("Skipping %s: SKILL.md not found at %s", name, skill_md)
            continue

        # Build a path relative to the agent's own workspace dir
        # (two levels up from MANIFEST.yaml for standard structure).
        # Format expected by _build_subagents: "<subagent-name>/SKILL.md"
        rel_path = str(manifest.path.parent.name) + "/SKILL.md"

        if rel_path in existing_paths:
            logger.debug("Subagent %s already declared in AGENT.md — skipping", name)
            continue

        existing_subagents.append(rel_path)
        existing_paths.add(rel_path)
        injected += 1
        logger.info("MANIFEST injection: added subagent '%s' to agent '%s'", name, agent_id)

    if injected:
        config["subagents"] = existing_subagents
        logger.info(
            "merge_into_config: injected %d MANIFEST subagent(s) into '%s'",
            injected,
            agent_id,
        )
    return config
