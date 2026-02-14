#!/usr/bin/env python3
"""
Read any file in workspace - Admin Agent tool.

Security: ✅ Green (read-only operation, no restrictions)
"""

from pathlib import Path

from langchain_core.tools import tool


@tool
def read_file(path: str) -> str:
    """Read file content.
    
    Args:
        path: File path (relative to project root or absolute)
    
    Returns:
        File content as string
    
    Security:
        ✅ Green: No restrictions (read-only operation)
    
    Examples:
        read_file(".olav/skills/network-query/SKILL.md")
        read_file("dev_docs/DEVELOPER_REFERENCE.md")
        read_file("src/olav/agents/agent.py")
        read_file("config/settings.py")
    """
    # Handle both relative and absolute paths
    full_path = Path(path)
    if not full_path.is_absolute():
        full_path = Path.cwd() / path
    
    # Check file exists
    if not full_path.exists():
        return f"Error: File not found: {path}"
    
    if not full_path.is_file():
        return f"Error: Not a file: {path}"
    
    # Read file
    try:
        content = full_path.read_text(encoding="utf-8")
        return content
    except UnicodeDecodeError:
        return f"Error: Cannot decode file (not UTF-8): {path}"
    except PermissionError:
        return f"Error: Permission denied: {path}"
    except Exception as e:
        return f"Error: {e}"
