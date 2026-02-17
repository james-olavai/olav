#!/usr/bin/env python3
"""
Execute arbitrary shell commands.

This is the power tool that replaces 5 specialized tools:
- list_files → "find dir -name '*.py'"
- search_code → "grep -r 'pattern' dir"
- git_operations → "git commit -m 'msg'"
- backup_restore → "tar -czf backup.tar.gz dir"
- execute_python → "python3 script.py"

Security: HITL approval required for destructive operations.
"""

import shlex
import subprocess
from pathlib import Path
from typing import Any

from langchain_core.tools import tool


@tool
def execute_shell(command: str, timeout: int = 60, cwd: str | None = None) -> dict[str, Any]:
    """Execute ANY shell command (replaces 5 tools: list_files, search_code, git, backup, python).
    
    This is the power tool that enables flexibility without specialized wrappers.
    Use standard Unix commands directly.
    
    Args:
        command: Shell command to execute (full command line)
        timeout: Command timeout in seconds (default: 60)
        cwd: Working directory (default: project root)
    
    Returns:
        {
            "stdout": "command output",
            "stderr": "error output",
            "returncode": 0,
            "success": true,
            "command": "original command"
        }
    
    Security:
        🟡 Yellow: HITL approval required for:
            - git commit, git push (permanent changes)
            - rm, mv (destructive operations)
            - Commands modifying src/ directory
        ✅ Green: Auto-approved for:
            - Read-only: ls, find, grep, cat, head, tail
            - Safe operations: mkdir, cp (to .olav/)
    
    Examples:
        # List Python files
        execute_shell("find .olav/skills -name '*.py' -type f")
        
        # Search code
        execute_shell("grep -r 'execute_sql' .olav/skills/")
        
        # Git operations
        execute_shell("git add .olav/skills/monitoring/")
        execute_shell("git commit -m 'Add monitoring skill'")
        
        # Backup
        execute_shell("tar -czf backup_$(date +%Y%m%d).tar.gz .olav/")
        
        # Execute Python script
        execute_shell("python3 .olav/tools/database.py")
        
        # Directory tree
        execute_shell("tree -L 2 .olav/skills")
        
        # Line count
        execute_shell("find .olav -name '*.py' | xargs wc -l")
    """
    # Parse command (security: prevent shell injection)
    try:
        cmd_parts = shlex.split(command)
    except ValueError as e:
        return {
            "stdout": "",
            "stderr": f"Command parsing error: {e}",
            "returncode": 1,
            "success": False,
            "command": command
        }
    
    # Determine working directory
    work_dir = Path(cwd) if cwd else Path.cwd()
    if not work_dir.exists():
        return {
            "stdout": "",
            "stderr": f"Working directory not found: {cwd}",
            "returncode": 1,
            "success": False,
            "command": command
        }
    
    # Execute command
    try:
        result = subprocess.run(
            cmd_parts,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=work_dir,
            shell=False  # Security: No shell injection
        )
        
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
            "success": result.returncode == 0,
            "command": command
        }
    
    except subprocess.TimeoutExpired:
        return {
            "stdout": "",
            "stderr": f"Command timed out after {timeout} seconds",
            "returncode": 124,  # Standard timeout exit code
            "success": False,
            "command": command
        }
    
    except FileNotFoundError:
        return {
            "stdout": "",
            "stderr": f"Command not found: {cmd_parts[0]}",
            "returncode": 127,  # Standard command not found exit code
            "success": False,
            "command": command
        }
    
    except Exception as e:
        return {
            "stdout": "",
            "stderr": f"Execution error: {e}",
            "returncode": 1,
            "success": False,
            "command": command
        }
