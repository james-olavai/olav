#!/usr/bin/env python3
"""
Config Diff Tool - Compare raw CLI outputs between snapshots to detect drift.

This tool uses snapshot_id instead of date for precise snapshot targeting.

Usage:
    from langchain_core.tools import tool
    diff_configs(device="R1", command="show running-config", snapshot_id_1="20260226_100000", snapshot_id_2="20260226_120000")
    diff_configs(device="R1", command="show running-config", snapshot_id_1="20260226_100000", snapshot_id_2="latest")
    diff_configs(device="R1", command="show running-config", snapshot_id_1="latest", snapshot_id_2="latest", sections=["aaa", "line vty"])
"""

import difflib
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain_core.tools import tool


def _find_project_root():
    """Locate project root (contains pyproject.toml)."""
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


# Snapshot base directory
_PROJECT_ROOT = _find_project_root()
_SNAPSHOTS = _PROJECT_ROOT / "exports" / "snapshots"

# IOS metadata lines that change every snapshot — excluded from changed_lines count
_METADATA_PATTERNS = [
    "current configuration",
    "last configuration change at",
    "building configuration",
    "bytes",
]


def _to_slug(command: str) -> str:
    """Convert command to file slug format (spaces → dashes, lowercase)."""
    return command.strip().lower().replace(" ", "-")


def _resolve_snapshot_id(snapshot_id: str) -> str:
    """Resolve 'latest' to actual snapshot_id, or validate existing snapshot_id."""
    if snapshot_id.lower() != "latest":
        return snapshot_id

    # Find most recent snapshot directory
    if not _SNAPSHOTS.exists():
        raise FileNotFoundError(f"Snapshots directory not found: {_SNAPSHOTS}")

    # Look for directories with snapshot_id pattern
    candidates = []
    for d in _SNAPSHOTS.iterdir():
        if d.is_dir() and d.name != "latest":
            # Extract timestamp from directory name (format: YYYYMMDD_HHMMSS or date_id)
            candidates.append(d.name)

    if not candidates:
        raise FileNotFoundError("No snapshots found")

    # Sort by name (which should include date)
    candidates.sort(reverse=True)
    return candidates[0]


def _find_file_by_snapshot_id(device: str, cmd_slug: str, snapshot_id: str) -> Path:
    """Find snapshot file for device/command/snapshot_id."""
    resolved_id = _resolve_snapshot_id(snapshot_id)
    base = _SNAPSHOTS / resolved_id / "raw" / device

    if not base.exists():
        raise FileNotFoundError(
            f"No snapshot directory for {device} with snapshot_id {resolved_id}"
        )

    # Try exact match
    exact = base / f"{cmd_slug}.txt"
    if exact.exists():
        return exact

    # Try word-based fuzzy match
    words = cmd_slug.split("-")
    candidates = []
    for f in sorted(base.glob("*.txt")):
        if all(w in f.stem for w in words):
            candidates.append(f)

    if candidates:
        return candidates[0]

    raise FileNotFoundError(
        f"No file matching '{cmd_slug}' in {device}/{resolved_id}. "
        f"Available: {[f.stem for f in base.glob('*.txt')]}"
    )


def _extract_sections(text: str, sections: list[str]) -> str:
    """Extract only lines belonging to named IOS config sections."""
    lines = text.splitlines()
    result = []
    in_section = False

    for line in lines:
        is_top_level = line.strip() and not line.startswith((" ", "\t"))

        if is_top_level:
            in_section = any(line.lower().startswith(s.lower()) for s in sections)

        if in_section:
            result.append(line)
            if line.strip() == "!":
                in_section = False

    return "\n".join(result)


def _count_significant_changes(diff_lines: list[str]) -> tuple[int, int]:
    """Count added/removed lines, excluding IOS metadata churn."""
    added = removed = 0

    for line in diff_lines:
        if any(pattern in line.lower() for pattern in _METADATA_PATTERNS):
            continue

        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1

    return added, removed


def _generate_diff(text_a: str, text_b: str, context_lines: int = 3) -> str:
    """Generate unified diff between two texts."""
    lines_a = text_a.splitlines(keepends=True)
    lines_b = text_b.splitlines(keepends=True)

    diff = difflib.unified_diff(lines_a, lines_b, lineterm="", n=context_lines)

    return "\n".join(diff)


def _summarize_diff(
    changed_lines: int, added_lines: int, removed_lines: int, sections: list[str] | None = None
) -> str:
    """Generate human-readable summary of changes."""
    net = added_lines - removed_lines
    net_str = f"+{net}" if net >= 0 else str(net)

    summary = f"{changed_lines} lines changed ({net_str})"

    if sections and changed_lines > 0:
        summary += f". Sections: {', '.join(sections)}"

    return summary


@tool
def diff_configs(
    device: str,
    command: str,
    snapshot_id_1: str | None = None,
    snapshot_id_2: str | None = None,
    sections: list[str] | None = None,
    context_lines: int = 3,
) -> dict[str, Any]:
    """Compare raw CLI output snapshots between two snapshot_ids to detect configuration drift.

    Reads files from exports/snapshots/{snapshot_id}/raw/{device}/{cmd-slug}.txt
    and returns a unified diff. Uses snapshot_id for precise targeting.

    Args:
        device: Device hostname, e.g. "R1"
        command: CLI command name, e.g. "show running-config" (spaces allowed)
        snapshot_id_1: Baseline snapshot ID (e.g., "20260226_100000") or "latest"
        snapshot_id_2: Target snapshot ID (e.g., "20260226_120000") or "latest"
        sections: Optional list of IOS config section keywords to filter diff
                  (e.g. ["aaa", "line vty", "ip access-list"])
        context_lines: Lines of unchanged context around each change (default 3)

    Returns:
        Dictionary containing:
        - status: "success" or "error"
        - device: Device name
        - command: Original command name
        - snapshot_id_1: Resolved baseline snapshot ID
        - snapshot_id_2: Resolved target snapshot ID
        - added_lines: Number of added lines (excludes metadata)
        - removed_lines: Number of removed lines (excludes metadata)
        - changed_lines: Total changes
        - diff: Unified diff output
        - summary: Human-readable summary string
        - message: Error description (if status="error")

    Examples:
        >>> diff_configs("R1", "show running-config")
        >>> diff_configs("R1", "show running-config", snapshot_id_1="20260226_100000")
        >>> diff_configs("R1", "show running-config", sections=["aaa", "line vty"])
        >>> diff_configs("R2", "show ip ospf neighbor", snapshot_id_1="latest", snapshot_id_2="latest")
    """
    try:
        # Resolve snapshot IDs
        if snapshot_id_2 is None:
            snapshot_id_2 = "latest"

        if snapshot_id_1 is None:
            # Auto-detect: find second-to-latest
            try:
                resolved_2 = _resolve_snapshot_id(snapshot_id_2)
                # List all snapshots, exclude the target
                all_snapshots = []
                if _SNAPSHOTS.exists():
                    for d in _SNAPSHOTS.iterdir():
                        if d.is_dir() and d.name not in ("latest", resolved_2):
                            all_snapshots.append(d.name)
                all_snapshots.sort(reverse=True)
                snapshot_id_1 = all_snapshots[0] if all_snapshots else "latest"
            except:
                snapshot_id_1 = "latest"

        cmd_slug = _to_slug(command)

        # Resolve to actual IDs
        id_1 = _resolve_snapshot_id(snapshot_id_1)
        id_2 = _resolve_snapshot_id(snapshot_id_2)

        # Read files
        try:
            file_1 = _find_file_by_snapshot_id(device, cmd_slug, id_1)
            text_1 = file_1.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError as e:
            return {
                "status": "error",
                "device": device,
                "command": command,
                "snapshot_id_1": id_1,
                "snapshot_id_2": id_2,
                "message": f"Baseline file not found: {e}",
            }

        try:
            file_2 = _find_file_by_snapshot_id(device, cmd_slug, id_2)
            text_2 = file_2.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError as e:
            return {
                "status": "error",
                "device": device,
                "command": command,
                "snapshot_id_1": id_1,
                "snapshot_id_2": id_2,
                "message": f"Target file not found: {e}",
            }

        # Filter sections if requested
        if sections:
            text_1 = _extract_sections(text_1, sections)
            text_2 = _extract_sections(text_2, sections)

        # Generate diff
        diff_output = _generate_diff(text_1, text_2, context_lines)
        diff_lines = diff_output.splitlines()

        # Count changes
        added, removed = _count_significant_changes(diff_lines)
        changed = added + removed

        # Truncate diff if very large
        if len(diff_lines) > 100:
            diff_lines = diff_lines[:100]
            diff_lines.append(f"\n[...{len(diff_lines) - 100} more lines...]")
            diff_output = "\n".join(diff_lines)

        summary = _summarize_diff(changed, added, removed, sections)

        return {
            "status": "success",
            "device": device,
            "command": command,
            "snapshot_id_1": id_1,
            "snapshot_id_2": id_2,
            "added_lines": added,
            "removed_lines": removed,
            "changed_lines": changed,
            "diff": diff_output,
            "summary": summary,
        }

    except Exception as e:
        return {
            "status": "error",
            "device": device,
            "command": command,
            "message": f"Unexpected error: {str(e)}",
        }
