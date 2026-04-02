"""run_pipeline — Single-entry deterministic pipeline for OLAV network onboarding.

This is the authoritative entry point for all full-cycle data collection.
It replaces the previous pattern of an LLM agent orchestrating 5-10 tool calls
across multiple subagents, which was slow and error-prone.

Architecture
------------
  Only ONE step requires LLM intelligence (TextFSM template generation).
  Everything else is deterministic Python — no agent roundtrips needed.

         collect_commands()        ← SSH + parse + diff  (no LLM)
              │
              ▼
    for gap in parse_errors:       ← deterministic for-loop  (no LLM)
        repair_template(gap)       ← ONLY LLM step (direct API, no agent)
        reparse_outputs(gap)       ← re-parse fixed command  (no LLM)
              │
              ▼
         generate_topology()       ← read DB, write links  (no LLM)

Entry points (all call run_pipeline.func() directly — no LangGraph overhead):
  - Config agent:   run_pipeline() as a @tool (one call, full pipeline)
  - olav onboard:   run_pipeline.func(mode="full")
  - Cron job:       run_pipeline.func(mode="incremental")
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Path bootstrap (same pattern as collect_commands)
# ---------------------------------------------------------------------------

def _find_project_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


_PROJECT_ROOT = _find_project_root()
_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

# Also add learner/tools and discovery/tools to path for direct imports
_LEARNER_TOOLS = _PROJECT_ROOT / ".olav" / "workspace" / "config" / "learner" / "tools"
_DISCOVERY_TOOLS = _PROJECT_ROOT / ".olav" / "workspace" / "config" / "discovery" / "tools"
for _p in (_LEARNER_TOOLS, _DISCOVERY_TOOLS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


# ---------------------------------------------------------------------------
# Pipeline tool
# ---------------------------------------------------------------------------

@tool
def run_pipeline(
    mode: str = "full",
    devices: list[str] | None = None,
    categories: list[str] | None = None,
    fix_gaps: bool = True,
) -> dict:
    """Run the complete network data collection pipeline in a single tool call.

    This is the PREFERRED way to run onboarding or daily snapshot collection.
    One call replaces the previous pattern of 5-10 agent roundtrips.

    Stages executed:
      1. collect_commands()   — SSH all devices, TextFSM parse, diff vs prev snapshot
      2. repair_template()    — For each HIGH parse gap: LLM generates + saves template,
                                then reparse_outputs() re-parses only that command
      3. generate_topology()  — Build topology_links from CDP/LLDP/OSPF data
                                (only after all gaps resolved)

    Args:
        mode:       "full"         — Stages 1 + 2 + 3 (default, for onboard/cron)
                    "snapshot_only" — Stage 1 only (SSH + parse + diff, no repair/topology)
                    "incremental"  — same as full but skips repair if no HIGH gaps
                    "topology_only" — Stage 3 only (re-run topology from existing data)
        devices:    Filter to specific devices (None = all). E.g. ["R1", "R2"]
        categories: Filter command categories (None = full). E.g. ["bgp", "routing"]
        fix_gaps:   True = auto-repair HIGH parse gaps via LLM (default).
                    False = collect only, report gaps without fixing.

    Returns:
        dict with keys:
          snapshot_id:        str   — e.g. "2026-03-02_1730"
          devices:            list  — device names collected
          raw_files:          int   — total raw output files written
          parsed_outputs:     int   — rows in parsed_outputs table
          diff_records:       int   — raw_diffs rows (0 on first snapshot)
          gaps_found:         int   — parse gaps detected
          gaps_fixed:         int   — gaps successfully repaired
          gaps_remaining:     list  — [{device, command, reason}] still failing
          topology_links:     int   — topology_links rows written
          duration_seconds:   float — total wall time
          summary:            str   — human-readable one-liner

    Examples:
        # Full pipeline — onboard or cron:
        run_pipeline()
        run_pipeline(mode="full")

        # Snapshot only (no repair, no topology):
        run_pipeline(mode="snapshot_only")

        # Targeted BGP refresh then topology:
        run_pipeline(devices=["R1", "R2"], categories=["bgp"])

        # Re-run topology from existing parsed data:
        run_pipeline(mode="topology_only")
    """
    import time

    start = time.monotonic()

    result: dict = {
        "snapshot_id": None,
        "devices": [],
        "raw_files": 0,
        "parsed_outputs": 0,
        "diff_records": 0,
        "gaps_found": 0,
        "gaps_fixed": 0,
        "gaps_remaining": [],
        "topology_links": 0,
        "duration_seconds": 0.0,
        "summary": "",
    }

    # =========================================================================
    # Stage 0: topology_only shortcut
    # =========================================================================
    if mode == "topology_only":
        topo_count = _run_topology(snapshot_id=None)
        elapsed = time.monotonic() - start
        result.update({
            "topology_links": topo_count,
            "duration_seconds": round(elapsed, 1),
            "summary": f"Topology re-run: {topo_count} links. {elapsed:.1f}s",
        })
        return result

    # =========================================================================
    # Stage 1: SSH collect + TextFSM parse + diff
    # =========================================================================
    print("\n[run_pipeline] Stage 1: collect_commands...")
    collect_result = _run_collect(devices=devices, categories=categories)

    if "error" in collect_result.get("summary", "").lower() or not collect_result.get("snapshot_id"):
        result["summary"] = f"Stage 1 failed: {collect_result.get('summary', 'unknown error')}"
        result["duration_seconds"] = round(time.monotonic() - start, 1)
        return result

    snapshot_id = collect_result["snapshot_id"]
    parse_errors = collect_result.get("parse_errors", [])

    result["snapshot_id"] = snapshot_id
    result["devices"] = collect_result.get("devices", [])
    result["diff_records"] = collect_result.get("diff_records", 0)

    # Count raw files in snapshot dir
    raw_dir = Path(collect_result.get("raw_files_dir", "")) / "raw"
    if raw_dir.exists():
        result["raw_files"] = sum(1 for _ in raw_dir.rglob("*.txt"))

    # Count parsed_outputs rows for this snapshot
    result["parsed_outputs"] = _count_parsed_outputs(snapshot_id)

    print(
        f"[run_pipeline] Stage 1 done: {len(result['devices'])} devices, "
        f"{result['raw_files']} raw files, {result['parsed_outputs']} parsed rows, "
        f"{len(parse_errors)} parse gaps"
    )

    if mode == "snapshot_only":
        elapsed = time.monotonic() - start
        result.update({
            "gaps_found": len(parse_errors),
            "duration_seconds": round(elapsed, 1),
            "summary": (
                f"Snapshot {snapshot_id}: {result['raw_files']} raw files, "
                f"{result['parsed_outputs']} parsed rows, "
                f"{len(parse_errors)} gaps (not repaired — snapshot_only mode). "
                f"{elapsed:.1f}s"
            ),
        })
        return result

    # =========================================================================
    # Stage 2: Repair HIGH parse gaps (one LLM call per gap, no agent overhead)
    # =========================================================================
    high_gaps = [
        g for g in parse_errors
        if g.get("severity") == "high" and g.get("raw_size", 0) > 200
        and not _is_feature_not_enabled(g.get("error", ""), g.get("raw_file", ""))
    ]

    result["gaps_found"] = len(high_gaps)
    gaps_remaining = []

    if fix_gaps and high_gaps:
        print(f"\n[run_pipeline] Stage 2: repairing {len(high_gaps)} HIGH parse gaps...")
        for gap in high_gaps:
            device = gap["device"]
            command = gap["command"]
            fixed = _repair_gap(device=device, command=command)
            if fixed:
                result["gaps_fixed"] += 1
                print(f"  ✅ Fixed: {device}/{command}")
            else:
                gaps_remaining.append({"device": device, "command": command, "reason": "repair failed"})
                print(f"  ❌ Failed: {device}/{command}")

        # Update parsed_outputs count after repairs
        result["parsed_outputs"] = _count_parsed_outputs(snapshot_id)
    elif not fix_gaps:
        gaps_remaining = [{"device": g["device"], "command": g["command"], "reason": "fix_gaps=False"} for g in high_gaps]

    result["gaps_remaining"] = gaps_remaining

    # =========================================================================
    # Stage 3: Generate topology (only after gaps resolved)
    # =========================================================================
    if mode in ("full", "incremental"):
        print("\n[run_pipeline] Stage 3: generate_topology...")
        topo_count = _run_topology(snapshot_id=snapshot_id)
        result["topology_links"] = topo_count
        print(f"[run_pipeline] Stage 3 done: {topo_count} topology links")

    elapsed = time.monotonic() - start
    result["duration_seconds"] = round(elapsed, 1)
    result["summary"] = (
        f"Pipeline {snapshot_id}: "
        f"{result['raw_files']} raw, "
        f"{result['parsed_outputs']} parsed, "
        f"{result['gaps_found']} gaps found, "
        f"{result['gaps_fixed']} fixed, "
        f"{len(gaps_remaining)} remaining, "
        f"{result['topology_links']} topo links. "
        f"{elapsed:.1f}s"
    )

    print(f"\n[run_pipeline] Done: {result['summary']}")
    return result


# ---------------------------------------------------------------------------
# Internal helpers — no LLM except _repair_gap
# ---------------------------------------------------------------------------

def _run_collect(
    devices: list[str] | None,
    categories: list[str] | None,
) -> dict:
    """Call collect_commands directly (no agent roundtrip)."""
    try:
        from collect_commands import collect_commands  # type: ignore[import]
        return collect_commands.func(devices=devices, categories=categories, wait=True)
    except Exception as e:
        logger.error("collect_commands failed: %s", e, exc_info=True)
        return {"summary": f"collect_commands error: {e}", "parse_errors": []}


def _repair_gap(device: str, command: str) -> bool:
    """Call repair_template directly (single LLM call, no agent roundtrip).

    repair_template already handles: read disk → LLM generate → save → reparse.
    Returns True if gap is resolved (records > 0 after repair).
    """
    try:
        from repair_template import repair_template  # type: ignore[import]
        result = repair_template.func(device=device, command=command)
        return bool(result.get("success") and result.get("records", 0) > 0)
    except Exception as e:
        logger.error("repair_template(%s, %s) failed: %s", device, command, e)
        return False


def _run_topology(snapshot_id: str | None) -> int:
    """Call generate_topology directly (no agent roundtrip). Returns link count."""
    try:
        from generate_topology import generate_topology  # type: ignore[import]

        # If no snapshot_id, use the latest one from DB
        if not snapshot_id:
            snapshot_id = _get_latest_snapshot_id()
        if not snapshot_id:
            logger.warning("No snapshot_id available for topology generation")
            return 0

        result = generate_topology.func(snapshot_id=snapshot_id)
        return result.get("total_links", 0) if isinstance(result, dict) else 0
    except Exception as e:
        logger.error("generate_topology failed: %s", e, exc_info=True)
        return 0


def _count_parsed_outputs(snapshot_id: str) -> int:
    """Count rows in parsed_outputs for this snapshot."""
    try:
        from olav.core.database import get_database
        row = get_database().conn.execute(
            "SELECT COUNT(*) FROM parsed_outputs WHERE snapshot_id = ?",
            [snapshot_id],
        ).fetchone()
        return row[0] if row else 0
    except Exception:
        return 0


def _get_latest_snapshot_id() -> str | None:
    """Return most recent snapshot_id from parsed_outputs."""
    try:
        from olav.core.database import get_database
        row = get_database().conn.execute(
            "SELECT snapshot_id FROM parsed_outputs ORDER BY snapshot_id DESC LIMIT 1"
        ).fetchone()
        return row[0] if row else None
    except Exception:
        return None


def _is_feature_not_enabled(error: str, raw_file: str) -> bool:
    """Return True if the gap is a known 'feature not enabled' non-issue."""
    skip_phrases = (
        "feature not enabled",
        "not enabled",
        "% invalid input",
        "% snmp agent not enabled",
        "no mpls",
        "invalid command",
    )
    # Check error string
    if any(p in error.lower() for p in skip_phrases):
        return True
    # Check raw file content (first 200 chars)
    try:
        raw = Path(raw_file).read_text(errors="replace")[:200].lower()
        return any(p in raw for p in skip_phrases)
    except Exception:
        return False
