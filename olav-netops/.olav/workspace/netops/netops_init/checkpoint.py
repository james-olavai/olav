"""NETOPS-04 — netops_init checkpoint / resume state.

Persists per-snapshot collection progress to
``.olav/workspace/ops/netops_init/state/{snapshot_id}.json`` so a partial
failure (SSH timeouts, user Ctrl-C, crashed ingest) can pick up where it
left off instead of re-sshing every device.

The checkpoint is advisory — if it's missing, malformed, or belongs to
an incompatible snapshot_id the caller falls back to a fresh run.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# Valid stage values in left-to-right progression order. Resume logic keys
# off ``stage`` to decide whether to start Stage 3 (collection) from
# scratch, skip it entirely and go straight to ingest, or no-op.
STAGES = (
    "env_check",
    "devices_loaded",
    "collecting",
    "collection_complete",
    "ingested",
    "done",
)


@dataclass
class Checkpoint:
    snapshot_id: str
    snapshot_date: str
    stage: str = "collecting"
    platform_groups: dict[str, list[str]] = field(default_factory=dict)
    devices: list[str] = field(default_factory=list)
    # Successful (device, command) pairs — serialised as list-of-lists so
    # the JSON round-trip preserves tuple semantics.
    completed: list[list[str]] = field(default_factory=list)
    results_summary: list[dict[str, Any]] = field(default_factory=list)
    all_rows: list[dict[str, Any]] = field(default_factory=list)

    def completed_set(self) -> set[tuple[str, str]]:
        """Return an O(1) lookup set of (device, command) already done."""
        return {(pair[0], pair[1]) for pair in self.completed if len(pair) >= 2}

    def mark_done(self, device: str, command: str) -> None:
        pair = [device, command]
        if pair not in self.completed:
            self.completed.append(pair)


def state_dir(project_root: Path) -> Path:
    """Directory where checkpoint JSON files live."""
    return project_root / ".olav" / "workspace" / "ops" / "netops_init" / "state"


def checkpoint_path(project_root: Path, snapshot_id: str) -> Path:
    return state_dir(project_root) / f"{snapshot_id}.json"


def load(path: Path) -> Checkpoint | None:
    """Deserialise a checkpoint file. Returns ``None`` on missing / malformed."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("checkpoint read failed (%s): %s", path, exc)
        return None
    try:
        return Checkpoint(**data)
    except TypeError as exc:
        logger.warning("checkpoint schema mismatch (%s): %s", path, exc)
        return None


def save(cp: Checkpoint, path: Path) -> None:
    """Write the checkpoint atomically. Creates parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(asdict(cp), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
