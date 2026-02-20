#!/usr/bin/env python3
"""
Write content to file - Admin Agent tool.

Security: 🟡 Yellow (HITL approval required for .py files and src/)
"""
import shutil
from pathlib import Path

from langchain_core.tools import tool


@tool
def write_file(path: str, content: str, backup: bool = True) -> str:
    """Write content to file.
    
    Args:
        path: File path (relative to project root or absolute)
        content: Content to write
        backup: Create backup before overwriting (default: True)
    
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
        write_file(".olav/skills/monitoring/tools/check_health.py", tool_code)
        write_file("config/settings.json", json_content)
    
    Note:
        HITL (Human-in-the-Loop) approval is handled by DeepAgents middleware.
        This tool will pause and request approval before writing .py files.
    """
    # Handle both relative and absolute paths
    full_path = Path(path)
    if not full_path.is_absolute():
        full_path = Path.cwd() / path
    
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
        return f"✅ {action} {path} ({lines} lines, {size_kb:.1f} KB)"
    
    except PermissionError:
        return f"Error: Permission denied: {path}"
    except Exception as e:
        return f"Error: {e}"
