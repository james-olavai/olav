#!/usr/bin/env python3
"""
Tool 1: Execute Command on Network Device

Executes a command on a network device using existing nornir_execute infrastructure.
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
    
    # Add .olav/tools to path to import nornir_execute
    tools_path = Path(".olav/tools")
    if str(tools_path) not in sys.path:
        sys.path.insert(0, str(tools_path))
    
    try:
        from network import nornir_execute
        
        start_time = time.time()
        
        # Use existing nornir_execute
        result = nornir_execute(
            device_filter=device,
            commands=[command],
            timeout=timeout
        )
        
        execution_time = time.time() - start_time
        
        # Parse result
        if result and "success" in result and result["success"]:
            # Extract output for the device
            device_result = result.get("results", {}).get(device, {})
            output = device_result.get("output", {}).get(command, "")
            platform = device_result.get("platform", "unknown")
            
            return {
                "device": device,
                "command": command,
                "output": output,
                "success": True,
                "error": None,
                "platform": platform,
                "execution_time": round(execution_time, 2)
            }
        else:
            error = result.get("message", "Unknown error")
            return {
                "device": device,
                "command": command,
                "output": "",
                "success": False,
                "error": error,
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
