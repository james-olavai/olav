#!/usr/bin/env python3
"""
Smart Query Script - Live CLI Execution

This script executes commands on network devices using Nornir/Netmiko.
It provides a way for the Agent to fetch real-time data when the database is insufficient.

Usage:
    echo '{"device": "R1", "command": "show ip bgp summary"}' | uv run python3 .olav/scripts/smart_query.py
"""

import sys
import json
from pathlib import Path

# Add src to Python Path
sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from olav.tools.network_executor import get_executor

def main(params: dict) -> dict:
    """Execute command on network device(s)."""
    # 1. Normalize 'device' or 'devices' to a list
    devices = params.get("device") or params.get("devices") or params.get("host") or params.get("hosts")
    
    if isinstance(devices, str):
        device_list = [d.strip() for d in devices.split(',')]
    elif isinstance(devices, list):
        device_list = devices
    else:
        # Check if we have regex-extracted 'device' from main block
        device_list = []

    command = params.get("command") or params.get("cmd")
    
    if not device_list:
        return {
            "status": "error",
            "message": "Missing 'device' or 'devices' parameter"
        }
        
    if not command:
         return {
            "status": "error",
            "message": "Missing 'command' parameter"
        }

    results = []
    errors = []
    executor = get_executor()

    for dev in device_list:
        try:
            # Use execute_with_parsing to benefit from TextFSM if available
            result = executor.execute_with_parsing(dev, command)
            
            if result.success:
                results.append({
                    "device": dev,
                    "data": result.output,
                    "structured": result.structured
                })
            else:
                errors.append(f"{dev}: {result.error}")
                
        except Exception as e:
            errors.append(f"{dev}: {str(e)}")
            
    if results:
        return {
            "status": "success",
            "command": command,
            "data": results if len(results) > 1 else results[0]["data"], # Simplify for single device
            "results": results, # Full detail
            "errors": errors,
            "message": f"Executed on {len(results)}/{len(device_list)} devices"
        }
    else:
        return {
            "status": "failed",
            "command": command,
            "errors": errors,
            "message": "All database and live execution attempts failed."
        }

if __name__ == "__main__":
    try:
        input_str = sys.stdin.read().strip()
        if not input_str:
            input_data = {}
        else:
            try:
                input_data = json.loads(input_str)
            except json.JSONDecodeError:
                # Handle cases where agent sends raw text instead of JSON
                # This is a common failure mode in some LLMs
                import re
                # Normalize: allow key=value, key: value, key='value'
                # Match device="R1" or device: "R1" or device='R1'
                device_match = re.search(r'["\']?(?:device|host)s?["\']?[:=]\s*["\']?([^"\',}\s]+)["\']?', input_str, re.IGNORECASE)
                command_match = re.search(r'["\']?(?:command|cmd)["\']?[:=]\s*["\']?([^"\',}]+)["\']?', input_str, re.IGNORECASE)
                input_data = {}
                if device_match: input_data["device"] = device_match.group(1)
                if command_match: input_data["command"] = command_match.group(1).strip()

        result = main(input_data)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        error_result = {"status": "error", "message": f"Global Error: {str(e)}"}
        print(json.dumps(error_result, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(1)
