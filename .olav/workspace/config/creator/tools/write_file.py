#!/usr/bin/env python3
"""
Write content to file - Admin Agent tool.

Security: 🟡 Yellow (HITL approval required for .py files and src/)
"""

import shutil
from datetime import datetime
from pathlib import Path

from langchain_core.tools import tool


@tool
def write_file(
    path: str, content: str, backup: bool = True, unique: bool = False, overwrite: bool = True
) -> str:
    """Write content to file with optional collision protection.

    Args:
        path: File path (relative to project root or absolute)
        content: Content to write
        backup: Create backup before overwriting (default: True)
        unique: Add timestamp suffix if file exists (default: False)
        overwrite: Allow overwriting existing files (default: True)

    Returns:
        Success message or error

    Security:
        🟡 Yellow: HITL approval required for:
            - .py files (code changes)
            - src/ directory (framework code)
        ✅ Green: Auto-approved for:
            - .md files (documentation)
            - .json files (configuration)
            - .olav/ directory (user data)

    Examples:
        write_file(".olav/skills/monitoring/SKILL.md", content)
        write_file("config/settings.json", json_content)
        # With unique suffix to avoid overwriting:
        write_file("exports/report.csv", data, unique=True)

    Note:
        HITL (Human-in-the-Loop) approval is handled by DeepAgents middleware.
    """
    # Handle both relative and absolute paths
    full_path = Path(path)
    if not full_path.is_absolute():
        full_path = Path.cwd() / path

    # Path collision detection
    if full_path.exists():
        if unique:
            # Add timestamp suffix to avoid collision
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            stem = full_path.stem
            suffix = full_path.suffix
            full_path = full_path.parent / f"{stem}_{timestamp}{suffix}"
        elif not overwrite:
            return f"Error: File exists and overwrite=False: {path}"

    # Backup existing file if requested
    if backup and full_path.exists():
        backup_path = full_path.with_suffix(full_path.suffix + ".backup")
        try:
            shutil.copy(full_path, backup_path)
        except Exception as e:
            return f"Warning: Backup failed: {e}\nContinuing with write anyway..."

    # Create parent directories
    try:
        full_path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return f"Error: Cannot create directories: {e}"

    # Write file
    try:
        full_path.write_text(content, encoding="utf-8")

        lines = len(content.splitlines())
        size_kb = len(content.encode("utf-8")) / 1024

        action = "Modified" if backup and full_path.exists() else "Created"
        if unique and path != str(full_path):
            action = "Created (unique)"
        return f"✅ {action} {full_path} ({lines} lines, {size_kb:.1f} KB)"

    except PermissionError:
        return f"Error: Permission denied: {path}"
    except Exception as e:
        return f"Error: {e}"
