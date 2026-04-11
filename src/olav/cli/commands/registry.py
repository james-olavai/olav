"""Slash command auto-registration: three-layer merge.

Layers (highest to lowest priority):
  1. platform builtin   — hardcoded in ``builtin.py``; NEVER overridable.
  2. workspace manifest — ``slash_commands:`` section in any MANIFEST.yaml
                          under ``.olav/workspace/``.
  3. Python entry point — ``olav.slash_commands`` group in installed packages.

Design reference: dev_docs/slash_command_auto_registration.md
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

logger = logging.getLogger(__name__)

# ── Reserved command names (platform core — must never be overridden) ─────────
RESERVED_NAMES: frozenset[str] = frozenset({"help", "?", "clear", "history", "quit", "exit"})

# ── Types ─────────────────────────────────────────────────────────────────────

ApprovalPolicy = Literal["none", "required"]
CommandKind = Literal["python", "shell"]
CwdPolicy = Literal["project_root", "workspace_dir", "script_dir"]


@dataclass
class SlashCommandSpec:
    """Declarative specification for a single slash command.

    Attributes
    ----------
    name:
        Command name (without leading ``/``).  Must be unique in the registry.
    kind:
        ``"python"`` — backed by a Python callable.
        ``"shell"``  — backed by an executable script.
    source:
        Where this spec was loaded from (``"builtin"`` / ``"entry_point"`` /
        ``"workspace_manifest"``).
    help:
        One-line description shown in ``/help`` output.
    aliases:
        Additional names that resolve to this command.
    entrypoint:
        ``"pkg.module:callable"`` string (``kind="python"`` only).
    script:
        Path to the executable script (``kind="shell"`` only).
    approval:
        ``"none"`` — execute immediately.
        ``"required"`` — prompt user before running.
    timeout:
        Hard wall-clock limit in seconds (``None`` = no limit).
    cwd_policy:
        Working directory for shell commands.
    env_allowlist:
        Environment variable names allowed to be forwarded.
    """

    name: str
    kind: CommandKind
    source: Literal["builtin", "entry_point", "workspace_manifest"]
    help: str = ""
    aliases: list[str] = field(default_factory=list)
    # python
    entrypoint: str | None = None
    # shell
    script: str | None = None
    # execution policy
    approval: ApprovalPolicy = "none"
    timeout: int | None = None
    cwd_policy: CwdPolicy = "project_root"
    env_allowlist: list[str] = field(default_factory=list)

    # ── resolved callable cache ────────────────────────────────────────────────

    _callable: Callable | None = field(default=None, init=False, repr=False)

    def resolve_callable(self) -> Callable:
        """Import and return the Python callable for this spec.

        Raises
        ------
        ImportError
            If the module cannot be imported.
        AttributeError
            If the callable does not exist in the module.
        RuntimeError
            If ``kind`` is not ``"python"``.
        """
        if self.kind != "python":
            raise RuntimeError(
                f"resolve_callable() is only valid for kind='python', got '{self.kind}'"
            )
        if self._callable is not None:
            return self._callable
        if not self.entrypoint:
            raise ValueError(f"SlashCommandSpec '{self.name}' has no entrypoint set")
        module_path, _, attr = self.entrypoint.rpartition(":")
        if not module_path or not attr:
            raise ValueError(
                f"Invalid entrypoint '{self.entrypoint}' — expected 'pkg.mod:callable'"
            )
        mod = importlib.import_module(module_path)
        fn = getattr(mod, attr)
        self._callable = fn  # type: ignore[assignment]
        return fn


# ── Loaders ───────────────────────────────────────────────────────────────────


def load_entrypoint_slash_commands() -> dict[str, SlashCommandSpec]:
    """Discover slash commands from ``olav.slash_commands`` entry points.

    Returns a ``{name: SlashCommandSpec}`` mapping.  Entry points are expected
    to point to a Python callable (``pkg.mod:fn``); the entry point *name*
    becomes the command name.

    Shell scripts cannot be registered via entry points — use MANIFEST.yaml
    for shell-type commands.
    """
    specs: dict[str, SlashCommandSpec] = {}
    try:
        from importlib.metadata import entry_points  # stdlib ≥ 3.9
    except ImportError:  # pragma: no cover
        return specs

    eps = entry_points(group="olav.slash_commands")
    for ep in eps:
        name = ep.name
        entrypoint = ep.value
        if name in RESERVED_NAMES:
            logger.warning(
                "entry_point slash command '%s' conflicts with a reserved name — skipped",
                name,
            )
            continue
        spec = SlashCommandSpec(
            name=name,
            kind="python",
            source="entry_point",
            entrypoint=entrypoint,
            help=f"Provided by entry point: {entrypoint}",
        )
        specs[name] = spec
        logger.debug("entry_point slash command registered: /%s → %s", name, entrypoint)

    return specs


def _parse_command_block(
    block: dict[str, Any],
    source: Literal["workspace_manifest"],
    manifest_path: Path,
) -> SlashCommandSpec | None:
    """Parse one item from a MANIFEST.yaml ``slash_commands:`` list.

    Returns ``None`` and emits a warning if the block is invalid.
    """
    name = block.get("name")
    kind = block.get("kind")

    if not name or not kind:
        logger.warning(
            "MANIFEST.yaml %s: slash_commands entry missing 'name' or 'kind' — skipped",
            manifest_path,
        )
        return None

    if kind not in ("python", "shell"):
        logger.warning(
            "MANIFEST.yaml %s: slash_command '%s' has unknown kind '%s' — skipped",
            manifest_path,
            name,
            kind,
        )
        return None

    if kind == "python" and not block.get("entrypoint"):
        logger.warning(
            "MANIFEST.yaml %s: python slash_command '%s' missing 'entrypoint' — skipped",
            manifest_path,
            name,
        )
        return None

    if kind == "shell" and not block.get("script"):
        logger.warning(
            "MANIFEST.yaml %s: shell slash_command '%s' missing 'script' — skipped",
            manifest_path,
            name,
        )
        return None

    raw_approval = block.get("approval", "none")
    approval: ApprovalPolicy = "required" if raw_approval == "required" else "none"

    raw_cwd = block.get("cwd_policy", "project_root")
    cwd_policy: CwdPolicy
    if raw_cwd in ("project_root", "workspace_dir", "script_dir"):
        cwd_policy = raw_cwd  # type: ignore[assignment]
    else:
        cwd_policy = "project_root"

    return SlashCommandSpec(
        name=str(name).lstrip("/"),  # strip leading slash to normalise "name: /cmd" → "cmd"
        kind=kind,  # type: ignore[arg-type]
        source=source,
        help=str(block.get("help", "")),
        aliases=list(block.get("aliases") or []),
        entrypoint=block.get("entrypoint"),
        script=block.get("script"),
        approval=approval,
        timeout=block.get("timeout"),
        cwd_policy=cwd_policy,
        env_allowlist=list(block.get("env_allowlist") or []),
    )


def load_workspace_slash_commands(workspace_root: Path) -> dict[str, SlashCommandSpec]:
    """Scan *workspace_root* for MANIFEST.yaml files with ``slash_commands:`` sections.

    Returns a ``{name: SlashCommandSpec}`` mapping.  Commands that conflict with
    reserved names are silently skipped with a warning.  Alias conflicts also
    trigger a warning and the duplicate alias is dropped.
    """
    specs: dict[str, SlashCommandSpec] = {}
    alias_index: dict[str, str] = {}  # alias → canonical name

    if not workspace_root.is_dir():
        return specs

    for manifest_path in workspace_root.rglob("MANIFEST.yaml"):
        try:
            raw: Any = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not parse MANIFEST.yaml at %s: %s", manifest_path, exc)
            continue

        if not isinstance(raw, dict):
            continue

        slash_cmds = raw.get("slash_commands")
        if not slash_cmds:
            continue

        for block in slash_cmds:
            if not isinstance(block, dict):
                continue
            spec = _parse_command_block(block, "workspace_manifest", manifest_path)
            if spec is None:
                continue

            if spec.name in RESERVED_NAMES:
                logger.warning(
                    "MANIFEST.yaml %s: slash_command '%s' conflicts with reserved name — skipped",
                    manifest_path,
                    spec.name,
                )
                continue

            # Deduplicate aliases
            clean_aliases: list[str] = []
            for alias in spec.aliases:
                if alias in RESERVED_NAMES:
                    logger.warning(
                        "MANIFEST.yaml %s: alias '%s' for '%s' conflicts with reserved name — dropped",
                        manifest_path,
                        alias,
                        spec.name,
                    )
                    continue
                if alias in alias_index:
                    logger.warning(
                        "MANIFEST.yaml %s: alias '%s' for '%s' already claimed by '%s' — dropped",
                        manifest_path,
                        alias,
                        spec.name,
                        alias_index[alias],
                    )
                    continue
                clean_aliases.append(alias)
                alias_index[alias] = spec.name

            spec.aliases = clean_aliases
            specs[spec.name] = spec
            logger.debug(
                "workspace_manifest slash command registered: /%s (from %s)",
                spec.name,
                manifest_path,
            )

    return specs


def build_slash_command_registry(
    workspace_root: Path,
    builtin_commands: dict[str, Any],
) -> dict[str, Any]:
    """Build the merged slash command registry.

    Merge strategy (highest wins):
      1. ``builtin_commands`` — reserved, never overridden.
      2. workspace manifest specs (as :class:`SlashCommandSpec` or callable).
      3. entry point specs (as :class:`SlashCommandSpec`).

    Aliases are expanded so a single lookup dict covers both canonical names
    and aliases.

    Parameters
    ----------
    workspace_root:
        ``.olav/workspace`` directory.
    builtin_commands:
        The existing ``SLASH_COMMANDS`` dict from ``builtin.py``.

    Returns
    -------
    dict
        Merged registry mapping command/alias name → callable or
        :class:`SlashCommandSpec`.
    """
    # Layer 3 (lowest): entry points
    registry: dict[str, Any] = {}
    for name, spec in load_entrypoint_slash_commands().items():
        registry[name] = spec
        for alias in spec.aliases:
            registry[alias] = spec

    # Layer 2: workspace manifests override entry points
    for name, spec in load_workspace_slash_commands(workspace_root).items():
        registry[name] = spec
        for alias in spec.aliases:
            registry[alias] = spec

    # Layer 1 (highest): platform builtins — cannot be overridden
    registry.update(builtin_commands)

    return registry
