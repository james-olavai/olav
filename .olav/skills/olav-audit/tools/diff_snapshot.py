#!/usr/bin/env python3
"""
Snapshot Diff Tool - Compare raw CLI outputs between snapshots to detect drift.

Usage:
    from langchain_core.tools import tool
    diff_snapshot(device="R1", command="show running-config")
    diff_snapshot(device="R1", command="show running-config", date_a="2026-02-19")
    diff_snapshot(device="R1", command="show running-config", sections=["aaa", "line vty"])
"""

import difflib
import sys
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


def _find_file(device: str, cmd_slug: str, date: str) -> Path:
    """
    Find snapshot file for device/command/date.
    
    Tries exact match first, then word-based fuzzy match.
    Example: "show-running-config" matches "show running-config"
    """
    base = _SNAPSHOTS / date / "raw" / device
    
    if not base.exists():
        raise FileNotFoundError(f"No snapshot directory for {device} on {date}")
    
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
        f"No file matching '{cmd_slug}' in {device}/{date}. "
        f"Available: {[f.stem for f in base.glob('*.txt')]}"
    )


def _resolve_date_a(device: str, cmd_slug: str, date_b: str) -> str:
    """
    Auto-detect most recent snapshot before date_b with the target file.
    
    Returns date string "YYYY-MM-DD".
    """
    # List all snapshot dates (skip "latest" symlink)
    try:
        all_dates = sorted([
            d.name for d in _SNAPSHOTS.iterdir()
            if d.is_dir() and d.name not in ("latest",) and d.name < date_b
        ])
    except Exception as e:
        raise FileNotFoundError(f"Failed to list snapshots: {e}")
    
    # Find most recent date that has the target file
    for date in reversed(all_dates):
        try:
            _find_file(device, cmd_slug, date)
            return date
        except FileNotFoundError:
            continue
    
    raise FileNotFoundError(
        f"No prior snapshot for {device}/{cmd_slug} before {date_b}. "
        f"Available dates: {all_dates}"
    )


def _extract_sections(text: str, sections: list[str]) -> str:
    """
    Extract only lines belonging to named IOS config sections.
    
    Example: sections=["aaa", "line vty"]
    Returns lines starting with "aaa" or "line vty" (and their content).
    """
    lines = text.splitlines()
    result = []
    in_section = False
    
    for line in lines:
        # Check if this is a top-level config line (no leading space)
        is_top_level = line.strip() and not line.startswith((" ", "\t"))
        
        if is_top_level:
            # Check if line starts with any target section
            in_section = any(
                line.lower().startswith(s.lower())
                for s in sections
            )
        
        if in_section:
            result.append(line)
            # Section ends at "!" line (common in IOS)
            if line.strip() == "!":
                in_section = False
    
    return "\n".join(result)


def _count_significant_changes(diff_lines: list[str]) -> tuple[int, int]:
    """
    Count added/removed lines, excluding IOS metadata churn.
    
    Returns (added_count, removed_count).
    """
    added = removed = 0
    
    for line in diff_lines:
        # Skip if line contains metadata pattern (case-insensitive)
        if any(pattern in line.lower() for pattern in _METADATA_PATTERNS):
            continue
        
        # Count added lines (starting with "+", not "+++")
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        # Count removed lines (starting with "-", not "---")
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    
    return added, removed


def _generate_diff(text_a: str, text_b: str, context_lines: int = 3) -> str:
    """Generate unified diff between two texts."""
    lines_a = text_a.splitlines(keepends=True)
    lines_b = text_b.splitlines(keepends=True)
    
    diff = difflib.unified_diff(
        lines_a,
        lines_b,
        lineterm="",
        n=context_lines
    )
    
    return "\n".join(diff)


def _summarize_diff(
    changed_lines: int,
    added_lines: int,
    removed_lines: int,
    sections: list[str] | None = None
) -> str:
    """Generate human-readable summary of changes."""
    net = added_lines - removed_lines
    net_str = f"+{net}" if net >= 0 else str(net)
    
    summary = f"{changed_lines} lines changed ({net_str})"
    
    if sections and changed_lines > 0:
        summary += f". Sections: {', '.join(sections)}"
    
    return summary


@tool
def diff_snapshot(
    device: str,
    command: str,
    date_a: str | None = None,
    date_b: str | None = None,
    sections: list[str] | None = None,
    context_lines: int = 3,
) -> dict[str, Any]:
    """Compare raw CLI output snapshots between two dates to detect configuration drift.

    Reads files from exports/snapshots/{date}/raw/{device}/{cmd-slug}.txt
    and returns a unified diff. Any command with a raw snapshot can be compared.

    Args:
        device: Device hostname, e.g. "R1"
        command: CLI command name, e.g. "show running-config" (spaces allowed, converted to slug)
        date_a: Baseline date as "YYYY-MM-DD", or None to auto-detect most recent before date_b
        date_b: Target date as "YYYY-MM-DD", or None for today
        sections: Optional list of IOS config section keywords to filter diff
                  (e.g. ["aaa", "line vty", "ip access-list"]).
                  None means diff the entire file.
        context_lines: Lines of unchanged context around each change (default 3)

    Returns:
        Dictionary containing:
        - status: "success" or "error"
        - device: Device name
        - command: Original command name
        - date_a: Auto-resolved baseline date
        - date_b: Auto-resolved target date
        - added_lines: Number of added lines (excludes metadata)
        - removed_lines: Number of removed lines (excludes metadata)
        - changed_lines: Total changes
        - diff: Unified diff output (may be truncated for readability)
        - summary: Human-readable summary string
        - message: Error description (if status="error")

    Examples:
        >>> diff_snapshot("R1", "show running-config")
        >>> diff_snapshot("R1", "show running-config", date_a="2026-02-14")
        >>> diff_snapshot("R1", "show running-config", sections=["aaa", "line vty"])
        >>> diff_snapshot("R2", "show ip ospf neighbor", date_a="2026-02-19")
    """
    try:
        # Resolve dates
        if date_b is None:
            date_b = datetime.now().strftime("%Y-%m-%d")
        
        cmd_slug = _to_slug(command)
        
        if date_a is None:
            date_a = _resolve_date_a(device, cmd_slug, date_b)
        
        # Read files
        try:
            file_a = _find_file(device, cmd_slug, date_a)
            text_a = file_a.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError as e:
            return {
                "status": "error",
                "device": device,
                "command": command,
                "date_a": date_a,
                "date_b": date_b,
                "message": f"Baseline file not found: {e}"
            }
        
        try:
            file_b = _find_file(device, cmd_slug, date_b)
            text_b = file_b.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError as e:
            return {
                "status": "error",
                "device": device,
                "command": command,
                "date_a": date_a,
                "date_b": date_b,
                "message": f"Target file not found: {e}"
            }
        
        # Filter sections if requested
        if sections:
            text_a = _extract_sections(text_a, sections)
            text_b = _extract_sections(text_b, sections)
        
        # Generate diff
        diff_output = _generate_diff(text_a, text_b, context_lines)
        diff_lines = diff_output.splitlines()
        
        # Count changes
        added, removed = _count_significant_changes(diff_lines)
        changed = added + removed
        
        # Truncate diff if very large
        if len(diff_lines) > 100:
            truncated = diff_lines[:100]
            truncated.append(f"\n[...{len(diff_lines) - 100} more lines...]")
            diff_output = "\n".join(truncated)
        
        summary = _summarize_diff(changed, added, removed, sections)
        
        return {
            "status": "success",
            "device": device,
            "command": command,
            "date_a": date_a,
            "date_b": date_b,
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
            "message": f"Unexpected error: {str(e)}"
        }
