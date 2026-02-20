#!/usr/bin/env python3
"""
Tool 1: Execute Command on Network Device

Executes a command on a network device using existing execute_cli from network.py.
"""

import logging
from typing import Any

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


@tool
def execute_command(device: str, command: str, timeout: int = 60) -> dict[str, Any]:
    """Execute command on network device.
    
    Args:
        device: Device name or IP (from inventory)
        command: Command to execute (e.g., "show ip bgp summary")
        timeout: Command timeout in seconds (default: 60)
    
    Returns:
        dict: {
            "device": str,
            "command": str,
            "output": str,
            "success": bool,
            "error": str | None,
            "platform": str,
            "execution_time": float
        }
    
    Example:
        >>> execute_command("R1", "show version")
        {"device": "R1", "command": "show version", "output": "...", "success": True}
    """
    import time
    from pathlib import Path
    import sys
    from config.paths import SKILL_BASE_PATH
    
    # Add olav-ops/tools to path to import execute_cli (CWD-independent)
    tools_path = SKILL_BASE_PATH / "olav-ops" / "tools"
    if str(tools_path) not in sys.path:
        sys.path.insert(0, str(tools_path))
    
    try:
        from execute_cli import execute_cli
        
        start_time = time.time()
        
        # Execute command using execute_cli tool (it's a LangChain tool, use .invoke())
        result = execute_cli.invoke({"device": device, "command": command, "timeout": timeout})
        
        execution_time = time.time() - start_time
        
        # Parse result from execute_cli
        # Result format: {"output": str, "device": str, "command": str, "status": str, "error": str}
        if result.get("status") == "success":
            return {
                "device": device,
                "command": command,
                "output": result.get("output", ""),
                "success": True,
                "error": None,
                "platform": "cisco_ios",  # TODO: get from inventory
                "execution_time": round(execution_time, 2)
            }
        else:
            return {
                "device": device,
                "command": command,
                "output": result.get("output", ""),
                "success": False,
                "error": result.get("error", "Unknown error"),
                "platform": "unknown",
                "execution_time": round(execution_time, 2)
            }
            
    except Exception as e:
        logger.error(f"Failed to execute command on {device}: {e}")
        return {
            "device": device,
            "command": command,
            "output": "",
            "success": False,
            "error": str(e),
            "platform": "unknown",
            "execution_time": 0.0
        }
