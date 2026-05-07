"""Patch O'-B — surgical CliBlock edits on an existing TCF.

Use case: human-in-the-loop CAB review.  After lab writes
``prod_review_findings``, the operator can either edit the YAML
directly or ask sim to make a targeted change.  This helper keeps the
"ask sim" path **non-destructive**: only the requested lines are
added/removed; everything else (other devices, lab section, post_check,
tvt, manual edits) is preserved.

Public API:

    tcf_patch_block(spec_path, device, *,
                    add_lines=[...], del_lines=[...],
                    action="configure", phase=1,
                    revised_by="operator") -> dict envelope

Semantics:

  * Loads the existing TCF.
  * Locates the CliBlock matching ``device + phase + action`` in
    ``implementation`` (creates one if no match — common when adding
    a new phase).
  * Removes any lines matching ``del_lines`` (exact match).
  * Appends ``add_lines`` at the end of the block.
  * Bumps ``revision_count`` + sets ``last_revised_at`` /
    ``last_revised_by``.
  * Atomically writes back via ``tcf_emit``.

The helper is rollback-aware: pass ``rollback=True`` to edit the
``rollback`` block instead.

Idempotence: re-running ``tcf_patch_block`` with the same args after
a successful patch will *still* increment ``revision_count`` (each
write is a logical revision); but the CLI body is idempotent because
we always remove ``del_lines`` first and dedupe ``add_lines``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .tcf_io import tcf_emit, tcf_load
from .tcf_schema import CabTcf, CliBlock


def _find_or_create_block(
    blocks: list[CliBlock],
    device: str,
    phase: int,
    action: str,
) -> CliBlock:
    for blk in blocks:
        if (blk.device == device and blk.phase == phase and blk.action == action):
            return blk
    new_blk = CliBlock(device=device, phase=phase, action=action, cli=[])
    blocks.append(new_blk)
    return new_blk


def tcf_patch_block(
    spec_path: str | Path,
    device: str,
    *,
    add_lines: list[str] | None = None,
    del_lines: list[str] | None = None,
    action: str = "configure",
    phase: int = 1,
    rollback: bool = False,
    revised_by: str = "operator",
) -> dict[str, Any]:
    """Surgically edit a single CliBlock in a TCF spec.

    Args:
        spec_path: Path to the TCF yaml.
        device: Device name (must exist in ``tcf.devices``).
        add_lines: Lines to append.  Already-present lines are deduped.
        del_lines: Lines to remove (exact match against existing block).
        action: CliBlock.action value to match (default ``"configure"``).
        phase: CliBlock.phase value (default 1).
        rollback: When True, edit ``tcf.rollback`` instead of
            ``tcf.implementation``.
        revised_by: Free-form actor string for audit metadata.

    Returns: envelope with
        ``status`` (ok / error), ``spec_path``, ``device``, ``phase``,
        ``action``, ``rollback``, ``added`` (count), ``removed``
        (count), ``revision_count``, ``last_revised_by``, plus the
        ``cli_after`` list reflecting the block's lines after the edit.
    """
    spec_path = Path(spec_path)
    add = list(add_lines or [])
    rm = list(del_lines or [])
    if not add and not rm:
        return {
            "status": "error",
            "error": "no add_lines or del_lines provided — nothing to do",
        }

    try:
        tcf: CabTcf = tcf_load(spec_path)
    except FileNotFoundError:
        return {"status": "error", "error": f"TCF file not found: {spec_path}"}
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "error",
            "error": f"TCF load failed: {type(exc).__name__}: {exc}",
        }

    known_devices = {d.name for d in tcf.devices}
    if device not in known_devices:
        return {
            "status": "error",
            "error": (
                f"device {device!r} not in tcf.devices "
                f"({sorted(known_devices)})"
            ),
        }

    blocks = tcf.rollback if rollback else tcf.implementation
    blk = _find_or_create_block(blocks, device, phase, action)

    before = list(blk.cli)
    removed = 0
    if rm:
        rm_set = set(rm)
        kept = [line for line in blk.cli if line not in rm_set]
        removed = len(blk.cli) - len(kept)
        blk.cli = kept

    added = 0
    existing = set(blk.cli)
    for line in add:
        if line not in existing:
            blk.cli.append(line)
            existing.add(line)
            added += 1

    if not rollback and not blk.cli:
        # Empty implementation block after delete is meaningless;
        # surface as error rather than silently writing nothing.
        return {
            "status": "error",
            "error": (
                f"block ({device}, phase={phase}, action={action!r}) "
                f"became empty after del_lines — refusing to write."
            ),
            "cli_before": before,
        }

    tcf.revision_count += 1
    tcf.last_revised_at = datetime.now(UTC)
    tcf.last_revised_by = revised_by

    try:
        out = tcf_emit(tcf, spec_path)
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "error",
            "error": f"TCF emit failed: {type(exc).__name__}: {exc}",
        }

    return {
        "status": "ok",
        "spec_path": str(out),
        "device": device,
        "phase": phase,
        "action": action,
        "rollback": rollback,
        "added": added,
        "removed": removed,
        "cli_after": list(blk.cli),
        "revision_count": tcf.revision_count,
        "last_revised_by": tcf.last_revised_by,
    }
