"""tcf_patch_block @tool — incremental TCF spec patcher for the
lab → sim revision loop.

R-VERTICAL-SLICE follow-on (2026-05-10, dev_docs/74 audit).
Closes the lab→sim feedback gap: previously when lab found issues
in a deployed plan, sim could only re-run ``submit_change_plan``
to author a fresh spec — destroying revision history and any
manual notes the user added.

This tool:
1. Reads an existing ``exports/cab/<change_id>/spec.tcf.yaml``
2. Applies a structured patch (add/remove/replace) to a single
   block (implementation / rollback / post_check / tvt)
3. Increments the spec's revision counter
4. Appends a journal entry recording who/what/why
5. Writes back atomically (temp file + rename)

Designed for the loop:

    lab finds finding F in deployed spec
      ↓
    user (or orchestrator) reads spec.lab.findings
      ↓
    sim invokes tcf_patch_block(change_id, block, op, ...)
      ↓
    spec updated in place, lab can re-validate
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import yaml
from langchain_core.tools import tool


_VALID_BLOCKS = ("implementation", "rollback", "post_check", "tvt")


def _resolve_spec_path(change_id: str) -> Path:
    """Locate exports/cab/<change_id>/spec.tcf.yaml.

    Looks in cwd first (workspace root convention), then under
    olav-demo7 fallback.  Raises FileNotFoundError if neither exists.
    """
    candidates = [
        Path.cwd() / "exports" / "cab" / change_id / "spec.tcf.yaml",
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(
        f"No spec.tcf.yaml found for change_id={change_id!r} "
        f"(checked {[str(c) for c in candidates]}).  Did sim emit "
        f"the plan first via submit_change_plan?"
    )


def _atomic_write(path: Path, content: str) -> None:
    """Write content to path atomically via temp file + rename."""
    tmp_fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


@tool
def tcf_patch_block(
    change_id: str,
    block: Literal["implementation", "rollback", "post_check", "tvt"],
    operation: Literal["replace_device", "append", "remove_device"],
    device: str,
    payload: list[dict[str, Any]] | None = None,
    rationale: str | None = None,
) -> dict[str, Any]:
    """
    Incrementally patch one block of an existing TCF spec.

    Use this when lab validation surfaces a finding (wrong CLI,
    missing post_check, broken rollback, etc.) and the plan needs
    targeted revision instead of full re-emission.

    Args:
        change_id: The change ID whose spec to patch.  The spec must
            exist at ``exports/cab/<change_id>/spec.tcf.yaml``.
        block: Which TCF block to modify.  Only these are patchable;
            top-level fields (devices, intent, change_id) are
            immutable post-emission.
        operation:
            * ``replace_device`` — replace ALL entries for this device
              with ``payload``
            * ``append`` — add ``payload`` entries to the block (no
              device dedup; use replace_device if you want to swap)
            * ``remove_device`` — drop every entry for this device
        device: The device hostname this patch applies to.  Required
            for replace_device / remove_device; for append it's
            metadata recorded in the journal.
        payload: List of dicts to insert (for replace_device or
            append).  Each dict must match the block's row schema —
            implementation/rollback expect ``{device, phase, action,
            cli}``; post_check expects ``{device, check_id,
            description, command, expected_pattern}``; tvt expects
            ``{test_id, description, expected, severity, ...}``.
            Required for replace_device + append; ignored for
            remove_device.
        rationale: Free-form note for the journal entry explaining
            WHY this patch was applied (e.g. "lab finding LAB-04: R3
            interface GigabitEthernet0/1 was already in use, switched
            to GigabitEthernet0/2").  Strongly recommended; tracked
            in the spec's journal so reviewers can audit revisions.

    Returns:
        On success::

            {"status": "success",
             "spec_path": "exports/cab/<id>/spec.tcf.yaml",
             "revision": N,                  # incremented post-patch
             "block": "implementation",
             "operation": "replace_device",
             "device": "R3",
             "rows_before": M,
             "rows_after": K}

        On error::

            {"status": "error", "error_kind": "...", "message": "..."}

    Example (lab finding: R3 interface should be Gi0/2 not Gi0/1)::

        >>> tcf_patch_block(
        ...     change_id="r3-r4-ebgp",
        ...     block="implementation",
        ...     operation="replace_device",
        ...     device="R3",
        ...     payload=[{
        ...         "device": "R3", "phase": 1, "action": "configure",
        ...         "cli": [
        ...             "interface GigabitEthernet0/2",
        ...             " ip address 172.16.99.1 255.255.255.252",
        ...             " no shutdown",
        ...             "router bgp 65000",
        ...             " neighbor 172.16.99.2 remote-as 65001",
        ...             # ... etc
        ...         ],
        ...     }],
        ...     rationale=(
        ...         "lab finding LAB-04: Gi0/1 already in use for "
        ...         "uplink to SW1; switched to Gi0/2 (verified free "
        ...         "via inspect_topology)"
        ...     ),
        ... )
    """
    if block not in _VALID_BLOCKS:
        return {
            "status": "error",
            "error_kind": "invalid_block",
            "message": f"block must be one of {_VALID_BLOCKS}; got {block!r}",
        }

    if operation in ("replace_device", "append") and not payload:
        return {
            "status": "error",
            "error_kind": "missing_payload",
            "message": (
                f"operation={operation!r} requires non-empty ``payload`` "
                "list of row dicts.  See docstring for required keys "
                "per block."
            ),
        }

    try:
        spec_path = _resolve_spec_path(change_id)
    except FileNotFoundError as e:
        return {
            "status": "error",
            "error_kind": "spec_not_found",
            "message": str(e),
        }

    with spec_path.open("r", encoding="utf-8") as f:
        spec = yaml.safe_load(f) or {}

    rows: list[dict] = list(spec.get(block) or [])
    rows_before = len(rows)

    if operation == "replace_device":
        rows = [r for r in rows if r.get("device") != device]
        rows.extend(payload or [])
    elif operation == "append":
        rows.extend(payload or [])
    elif operation == "remove_device":
        rows = [r for r in rows if r.get("device") != device]
    else:
        return {
            "status": "error",
            "error_kind": "invalid_operation",
            "message": f"unknown operation {operation!r}",
        }

    spec[block] = rows

    # Revision counter + journal entry — sim's audit trail
    spec["revision"] = int(spec.get("revision") or 0) + 1
    journal = list(spec.get("journal") or [])
    journal.append({
        "ts": datetime.now(timezone.utc).isoformat(),
        "actor": "sim",
        "block": block,
        "operation": operation,
        "device": device,
        "rationale": rationale or "(no rationale provided)",
        "rows_before": rows_before,
        "rows_after": len(rows),
    })
    spec["journal"] = journal

    yaml_content = yaml.safe_dump(
        spec, sort_keys=False, allow_unicode=True, default_flow_style=False,
    )
    _atomic_write(spec_path, yaml_content)

    return {
        "status": "success",
        "spec_path": str(spec_path),
        "revision": spec["revision"],
        "block": block,
        "operation": operation,
        "device": device,
        "rows_before": rows_before,
        "rows_after": len(rows),
    }
