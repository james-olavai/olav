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
    import sys
    import time

    from olav.core.config import SKILL_BASE_PATH

    # Add ops/tools to path to import execute_cli (CWD-independent)
    tools_path = SKILL_BASE_PATH / "ops" / "tools"
    if str(tools_path) not in sys.path:
        sys.path.insert(0, str(tools_path))

    try:
        from execute_cli import execute_cli_main

        start_time = time.time()

        # Execute command using execute_cli_main (returns dict with status field)
        result = execute_cli_main({"device": device, "command": command, "timeout": timeout})

        execution_time = time.time() - start_time

        # Parse result from execute_cli
        # Result format: {"output": str, "device": str, "command": str, "status": str, "error": str, "warning": str}
        if result.get("status") == "success":
            return {
                "device": device,
                "command": command,
                "output": result.get("output", ""),
                "success": True,
                "error": None,
                "warning": result.get("warning"),
                "platform": "juniper_junos",  # TODO: get from inventory
                "execution_time": round(execution_time, 2)
            }
        else:
            return {
                "device": device,
                "command": command,
                "output": result.get("output", ""),
                "success": False,
                "error": result.get("error", "Unknown error"),
                "warning": result.get("warning"),
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
            "warning": None,
            "platform": "unknown",
            "execution_time": 0.0
        }
