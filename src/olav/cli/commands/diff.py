"""``olav diff`` — cross-snapshot diff CLI wrapper.

ARCH-13 last mile. Wraps the workspace-vendored
``.olav/workspace/ops/tools/diff_snapshots.py`` aggregator so operators
can compare two snapshots without composing SQL or dropping into the
agent shell.

Usage::

    olav diff <snap1> <snap2>
    olav diff snap_20260101_010000 latest --table parsed_outputs
    olav diff snap_a snap_b --device R1 --max-rows 10

Exit codes:
  0 — diff computed (possibly zero changes — reported)
  1 — input parameters missing or invalid
  2 — diff tool raised (bad snapshot_id, DB access, etc.)
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


def _load_diff_snapshots():
    """Locate and import the workspace-vendored diff_snapshots module.

    The tool lives under ``.olav/workspace/ops/tools/`` — not on the
    ``olav`` package path — so we load it via importlib the same way
    tests / catalog / explain do.
    """
    candidates: list[Path] = []
    # 1. Resolve via workspace_root if config is wired.
    try:
        from olav.core.config import get_paths_config
        ws_root = Path(get_paths_config().workspace_root).resolve()
        candidates.append(
            ws_root.parent / ".olav" / "workspace" / "ops" / "tools" / "diff_snapshots.py"
        )
    except Exception:
        pass
    # 2. Walk up from this file looking for .olav/workspace.
    here = Path(__file__).resolve()
    for anc in here.parents:
        alt = (
            anc / ".olav" / "workspace" / "ops" / "tools" / "diff_snapshots.py"
        )
        if alt.exists():
            candidates.append(alt)
            break

    for candidate in candidates:
        if candidate.exists():
            spec = importlib.util.spec_from_file_location(
                "_olav_diff_snapshots", candidate
            )
            mod = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(mod)  # type: ignore[union-attr]
            except Exception:
                continue
            return getattr(mod, "diff_snapshots", None)
    return None


def _format_diff(result: dict[str, Any], max_rows: int) -> str:
    """Render the diff_snapshots result dict as human-readable text."""
    if result.get("status") != "success":
        return json.dumps(result, indent=2, ensure_ascii=False, default=str)

    lines: list[str] = []
    lines.append(
        f"Snapshot 1 : {result.get('snapshot_id_1', '?')}"
    )
    lines.append(
        f"Snapshot 2 : {result.get('snapshot_id_2', '?')}"
    )
    lines.append(
        f"Totals     : +{result.get('total_added', 0)} / -{result.get('total_removed', 0)}"
    )
    lines.append("")

    for table_name, table_diff in (result.get("tables") or {}).items():
        added = table_diff.get("added", []) or []
        removed = table_diff.get("removed", []) or []
        added_n = table_diff.get("added_count", len(added))
        removed_n = table_diff.get("removed_count", len(removed))
        if added_n == 0 and removed_n == 0:
            lines.append(f"[{table_name}] unchanged")
            continue
        lines.append(f"[{table_name}] +{added_n} / -{removed_n}")
        for label, rows in (("+ added", added), ("- removed", removed)):
            if not rows:
                continue
            shown = rows[:max_rows]
            lines.append(f"  {label} ({len(shown)} of {len(rows)} shown):")
            for row in shown:
                lines.append(f"    {json.dumps(row, ensure_ascii=False, default=str)}")
            if len(rows) > len(shown):
                lines.append(
                    f"    … {len(rows) - len(shown)} more (re-run with --max-rows)"
                )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def build_diff_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Register ``olav diff`` on the root CLI subparsers."""
    p = subparsers.add_parser(
        "diff",
        help="Diff two snapshots across parsed_outputs / topology_links / raw_output_store / oc_outputs",
        description=(
            "Cross-table snapshot diff — wraps the workspace "
            ".olav/workspace/ops/tools/diff_snapshots.py aggregator. "
            "Read-only; returns added/removed row counts per table and "
            "up to --max-rows example rows per side."
        ),
    )
    p.add_argument("snapshot_id_1", help="Earlier snapshot (or 'latest-1', 'HEAD~1' style)")
    p.add_argument("snapshot_id_2", help="Later snapshot (or 'latest')")
    p.add_argument(
        "--table",
        default=None,
        help="Limit to a single table (parsed_outputs / topology_links / "
        "raw_output_store / oc_outputs). Default = all.",
    )
    p.add_argument(
        "--device",
        default=None,
        help="Limit diff to a specific device hostname.",
    )
    p.add_argument(
        "--max-rows",
        type=int,
        default=5,
        help="Max example rows to show per added/removed side (default 5).",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Dump the raw diff_snapshots() result as JSON instead of the "
        "human-readable summary.",
    )
    return p


def handle_diff_command(args) -> int:
    """Dispatch ``olav diff`` — call diff_snapshots tool and render."""
    snap1 = getattr(args, "snapshot_id_1", None)
    snap2 = getattr(args, "snapshot_id_2", None)
    if not snap1 or not snap2:
        print("error: both snapshot_id_1 and snapshot_id_2 are required", file=sys.stderr)
        return 1

    diff_snapshots = _load_diff_snapshots()
    if diff_snapshots is None:
        print(
            "error: could not load diff_snapshots from "
            ".olav/workspace/ops/tools/diff_snapshots.py — run from the repo root.",
            file=sys.stderr,
        )
        return 1

    payload: dict[str, Any] = {
        "snapshot_id_1": snap1,
        "snapshot_id_2": snap2,
    }
    table = getattr(args, "table", None)
    if table:
        payload["table_name"] = table
    device = getattr(args, "device", None)
    if device:
        payload["device"] = device

    # The workspace tool is a LangChain @tool — prefer .invoke when present.
    try:
        if hasattr(diff_snapshots, "invoke"):
            result = diff_snapshots.invoke(payload)
        else:
            result = diff_snapshots(**payload)
    except Exception as exc:
        print(f"error: diff_snapshots raised: {exc}", file=sys.stderr)
        return 2

    if getattr(args, "json", False):
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        return 0

    max_rows = max(0, int(getattr(args, "max_rows", 5) or 5))
    print(_format_diff(result, max_rows=max_rows))
    return 0
