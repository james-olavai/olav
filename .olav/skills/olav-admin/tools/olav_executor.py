#!/usr/bin/env python3
"""
Execute OLAV CLI commands (specialized wrapper for testing).

This is a convenience wrapper around 'uv run olav' commands.
Could also be done with execute_command("uv run olav ask 'query'").
"""

import subprocess
from pathlib import Path
from typing import Any

from langchain_core.tools import tool


@tool
def execute_olav(command: str, timeout: int = 60) -> dict[str, Any]:
    """Execute OLAV CLI command (convenience wrapper for testing OLAV features).
    
    This is a specialized wrapper for running OLAV commands in subprocess.
    
    Args:
        command: OLAV command (without "olav" prefix)
        timeout: Command timeout in seconds (default: 60)
    
    Returns:
        {
            "stdout": "command output",
            "stderr": "error output",
            "returncode": 0,
            "success": true
        }
    
    Security:
        ✅ Green: Safe (OLAV runs in subprocess sandbox)
    
    Note: 
        This is equivalent to: execute_command("uv run olav {command}")
        But provides cleaner syntax for OLAV-specific testing.
    
    Examples:
        # Query Agent
        execute_olav("ask 'how many devices?'")
        execute_olav("-m 'show all devices'")
        
        # Admin commands
        execute_olav("admin status")
        execute_olav("backup")
        execute_olav("db-status")
        
        # Device listing
        execute_olav("devices")
        execute_olav("devices --role core")
        
        # Skills
        execute_olav("skills")
        execute_olav("skills --detail")
        
        # Search
        execute_olav("search 'execute_sql'")
        execute_olav("ls '*.py' --dir .olav/skills")
    """
    # Parse command into parts
    cmd_parts = command.split()
    
    # Build full command: uv run olav <command>
    full_cmd = ["uv", "run", "olav"] + cmd_parts
    
    # Execute
    try:
        result = subprocess.run(
            full_cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=Path.cwd()
        )
        
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
            "success": result.returncode == 0
        }
    
    except subprocess.TimeoutExpired:
        return {
            "stdout": "",
            "stderr": f"Command timed out after {timeout} seconds",
            "returncode": 124,
            "success": False
        }
    
    except Exception as e:
        return {
            "stdout": "",
            "stderr": f"Execution error: {e}",
            "returncode": 1,
            "success": False
        }
