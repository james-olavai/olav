"""v0.20.2 filesystem layout migration.

Moves the v0.19.x OLAV workspace tree from

    .olav/workspace/<name>/AGENT.md
    .olav/workspace/<name>/<subagent>/AGENT.md

to the v0.20.2 deepagents-compatible layout

    .deepagents/agents/<name>/AGENTS.md
    .deepagents/agents/<name>/agents/<subagent>.md

Everything else (``MANIFEST.yaml``, ``tools/``, ``prompts/``,
``references/``, individual ``<skill>/SKILL.md`` subdirectories)
is carried over verbatim — deepagents-code reads the new locations,
OLAV reads both.

This module provides three entry points:

* :func:`plan_migration` — pure read, returns a declarative plan
* :func:`apply_migration` — executes a plan with optional backup
* :func:`already_migrated` — idempotence probe

See `dev_docs/53. PHASE_B_v0_20_2_CUTOVER.md` §3.1 for design rationale.
"""

from __future__ import annotations

import logging
import shutil
import tarfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

_LEGACY_WORKSPACE_ROOT = Path(".olav") / "workspace"
"""Relative location of the v0.19.x workspace tree under the project
root.  Absolute paths are derived by joining with the ``root``
argument passed to each public function."""

_NEW_AGENTS_ROOT = Path(".deepagents") / "agents"
"""Relative location of the v0.20.2 agents tree."""

_AGENT_MD_OLD = "AGENT.md"
_AGENT_MD_NEW = "AGENTS.md"
"""Filename change — AGENT.md → AGENTS.md.  deepagents-code insists
on the plural; OLAV's loader accepts both so we can read the new
layout before the migration runs."""


OperationKind = Literal[
    "create_new_agent_dir",
    "rename_agent_md",
    "flatten_subagent",
    "copy_sibling",
]
"""Operation types emitted by the planner.

* ``create_new_agent_dir`` — ``mkdir .deepagents/agents/<name>`` when
  the target doesn't exist yet.  Emitted once per agent.
* ``rename_agent_md`` — copy legacy ``AGENT.md`` → new ``AGENTS.md``
  at the agent root.
* ``flatten_subagent`` — copy ``<parent>/<sub>/AGENT.md`` → single
  file ``<parent>/agents/<sub>.md``.  Other sibling files inside the
  subagent dir (tools/, prompts/) are then moved via ``copy_sibling``
  with target ``<parent>/agents/<sub>/``.
* ``copy_sibling`` — generic file/dir copy preserving relative path.
"""


@dataclass(frozen=True)
class Operation:
    """A single filesystem change in the migration plan.

    Frozen dataclass so plans are safely shared across threads and
    :func:`apply_migration` can't accidentally mutate a plan it was
    given.  All paths are absolute.
    """

    kind: OperationKind
    source: Path
    target: Path
    agent: str = ""
    """Name of the top-level agent this operation belongs to — used
    for grouping in summary output."""

    def as_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "source": str(self.source),
            "target": str(self.target),
            "agent": self.agent,
        }


@dataclass
class MigrationPlan:
    """A full set of operations to migrate one install.

    Mutable so callers can filter / extend (e.g. a CLI ``--only``
    flag).  Not thread-safe; build once, apply once.
    """

    root: Path
    """Absolute path to the install root (typically the project
    directory containing ``.olav/``)."""
    operations: list[Operation] = field(default_factory=list)
    """Ordered list of operations.  Callers should preserve order
    when subsetting — ``create_new_agent_dir`` must precede any
    operation with a target inside that dir."""

    def summary(self) -> str:
        """Return a human-readable single-paragraph summary."""
        by_kind: dict[str, int] = {}
        agents: set[str] = set()
        for op in self.operations:
            by_kind[op.kind] = by_kind.get(op.kind, 0) + 1
            if op.agent:
                agents.add(op.agent)

        if not self.operations:
            return "Nothing to migrate — workspace is already on the new layout."

        parts = [
            f"{n} {kind.replace('_', ' ')}" for kind, n in sorted(by_kind.items())
        ]
        agents_str = (
            f" across {len(agents)} agent(s): {', '.join(sorted(agents))}"
            if agents
            else ""
        )
        return f"Planned: {', '.join(parts)}{agents_str}."

    def as_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "operations": [op.as_dict() for op in self.operations],
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def already_migrated(root: Path) -> bool:
    """Return ``True`` when *root* is on the v0.20.2 layout.

    Heuristic: the new agents dir exists and has at least one agent
    dir inside it.  An empty ``.deepagents/agents/`` counts as
    not-yet-migrated so a partial prior run can be retried.
    """
    new_root = root / _NEW_AGENTS_ROOT
    if not new_root.is_dir():
        return False
    return any(p.is_dir() for p in new_root.iterdir())


def plan_migration(root: Path) -> MigrationPlan:
    """Scan *root* and return a :class:`MigrationPlan`.

    Pure read: no filesystem mutations.  Safe to call repeatedly
    (useful for ``olav migrate --dry-run``).

    Args:
        root: Project root.  Looks for ``.olav/workspace/`` under it;
            if that doesn't exist, returns an empty plan (not an
            error — many projects have never run ``olav init``).

    Returns:
        A :class:`MigrationPlan`.  Empty ``operations`` list means
        no work needed — either already migrated or no legacy
        workspace found.
    """
    root = root.resolve()
    legacy_root = root / _LEGACY_WORKSPACE_ROOT
    new_root = root / _NEW_AGENTS_ROOT

    plan = MigrationPlan(root=root)

    if not legacy_root.is_dir():
        # Nothing to migrate (fresh install or already cleaned up).
        return plan

    for agent_dir in sorted(legacy_root.iterdir()):
        if not agent_dir.is_dir():
            continue
        agent_name = agent_dir.name
        legacy_agent_md = agent_dir / _AGENT_MD_OLD
        if not legacy_agent_md.is_file():
            # Directory without AGENT.md isn't a recognisable agent.
            continue

        new_agent_dir = new_root / agent_name

        # Skip agents that are already on the new layout (idempotent).
        if (new_agent_dir / _AGENT_MD_NEW).is_file():
            continue

        # Ensure target dir will exist before any write lands inside.
        if not new_agent_dir.is_dir():
            plan.operations.append(
                Operation(
                    kind="create_new_agent_dir",
                    source=agent_dir,
                    target=new_agent_dir,
                    agent=agent_name,
                )
            )

        # Rename the agent's own definition file.
        plan.operations.append(
            Operation(
                kind="rename_agent_md",
                source=legacy_agent_md,
                target=new_agent_dir / _AGENT_MD_NEW,
                agent=agent_name,
            )
        )

        # Subagents: each child dir that contains its own AGENT.md
        # flattens into a single markdown file under agents/.
        for child in sorted(agent_dir.iterdir()):
            if not child.is_dir():
                continue
            sub_md = child / _AGENT_MD_OLD
            if not sub_md.is_file():
                # Not a subagent (could be skills/, tools/, etc.)
                continue
            sub_name = child.name
            plan.operations.append(
                Operation(
                    kind="flatten_subagent",
                    source=sub_md,
                    target=new_agent_dir / "agents" / f"{sub_name}.md",
                    agent=agent_name,
                )
            )

    return plan


@dataclass
class MigrationResult:
    """Outcome of :func:`apply_migration`.

    Mutable so callers can inspect or log individual operation
    outcomes before disposing.  Not thread-safe.
    """

    applied_operations: int = 0
    """Count of operations that actually ran (``status=="ok"``)."""
    skipped_operations: int = 0
    """Count of operations the applier skipped (target already existed,
    or idempotent no-op)."""
    backup_path: Path | None = None
    """Absolute path to the backup tarball, or ``None`` when
    ``backup=False`` was passed or no legacy tree existed."""
    operation_results: list[dict[str, str]] = field(default_factory=list)
    """Per-operation result records with at least ``kind`` and
    ``status`` keys.  Useful for CLI output and for tests."""


def apply_migration(
    plan: MigrationPlan,
    *,
    backup: bool = True,
) -> MigrationResult:
    """Execute *plan*'s operations, optionally backing up the legacy
    tree first.

    The migration is **copy-based**: legacy files are left in place.
    This lets users fall back to ``OLAV_V0_20_LAYOUT=legacy`` without
    re-running anything, and P7 can schedule a separate cleanup pass
    that deletes ``.olav/workspace/`` once confidence is high.

    Args:
        plan: Produced by :func:`plan_migration`.
        backup: When ``True`` (default), tar ``.olav/workspace/`` into
            ``.olav.bak/v0.19-<timestamp>.tar.gz`` before applying any
            operation.  Skipped automatically when no legacy tree
            exists (empty plans, already-migrated installs).

    Returns:
        A :class:`MigrationResult` describing what happened.
    """
    result = MigrationResult()

    if not plan.operations:
        return result

    if backup:
        backup_path = _create_backup(plan.root)
        result.backup_path = backup_path

    for op in plan.operations:
        entry = {"kind": op.kind, "status": "ok", "target": str(op.target)}
        try:
            if op.kind == "create_new_agent_dir":
                op.target.mkdir(parents=True, exist_ok=True)
            elif op.kind == "rename_agent_md":
                op.target.parent.mkdir(parents=True, exist_ok=True)
                _copy_file(op.source, op.target)
            elif op.kind == "flatten_subagent":
                op.target.parent.mkdir(parents=True, exist_ok=True)
                _copy_file(op.source, op.target)
            elif op.kind == "copy_sibling":
                # Generic fallback — currently unused by plan_migration
                # but reserved for future extensions.
                op.target.parent.mkdir(parents=True, exist_ok=True)
                if op.source.is_dir():
                    shutil.copytree(op.source, op.target, dirs_exist_ok=True)
                else:
                    _copy_file(op.source, op.target)
            else:
                logger.warning("Unknown operation kind %s; skipping", op.kind)
                entry["status"] = "skipped"
                result.skipped_operations += 1
                result.operation_results.append(entry)
                continue
            result.applied_operations += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Operation %s failed (source=%s target=%s): %s",
                op.kind,
                op.source,
                op.target,
                exc,
            )
            entry["status"] = "error"
            entry["error"] = str(exc)
            result.skipped_operations += 1
        result.operation_results.append(entry)

    return result


def _copy_file(source: Path, target: Path) -> None:
    """Copy one file preserving content; target-already-exists is a
    soft no-op (idempotent)."""
    if target.is_file() and target.read_bytes() == source.read_bytes():
        return
    shutil.copy2(source, target)


def _create_backup(root: Path) -> Path | None:
    """Tar ``.olav/workspace/`` into ``.olav.bak/v0.19-<ts>.tar.gz``.

    Returns the tarball path, or ``None`` when there's nothing to
    back up.
    """
    legacy = root / _LEGACY_WORKSPACE_ROOT
    if not legacy.is_dir():
        return None

    backup_dir = root / ".olav.bak"
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    tar_path = backup_dir / f"v0.19-{ts}.tar.gz"

    with tarfile.open(tar_path, mode="w:gz") as tar:
        # arcname kept relative so an extraction anywhere reproduces
        # .olav/workspace/… structure.
        tar.add(legacy, arcname=str(_LEGACY_WORKSPACE_ROOT))

    return tar_path


__all__ = [
    "MigrationPlan",
    "MigrationResult",
    "Operation",
    "OperationKind",
    "already_migrated",
    "apply_migration",
    "plan_migration",
]
