#!/usr/bin/env python3
"""
Nornir Execute - Shared tool used by multiple skills.

Execute CLI commands on network devices.
Wraps the olav.tools.network_executor.get_executor function for skill-based invocation.

Shared by: network-analysis, network-cli, network-snapshot

Usage:
    echo '{"device": "R1", "command": "show version"}' | python3 nornir_execute.py
"""

import json
import sys
from pathlib import Path


def _find_project_root():
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()

sys.path.insert(0, str(_find_project_root() / "src"))

from olav.tools.network_executor import get_executor


def main(params: dict) -> dict:
    """Execute a command on a network device.

    Args:
        params: {
            "device": "R1",
            "command": "show version",
            "timeout": 30  # optional
        }

    Returns:
        {"output": "...", "status": "success"}
    """
    device = params.get("device")
    command = params.get("command")
    timeout = params.get("timeout", 30)

    if not device:
        return {"error": "Missing 'device' parameter", "status": "failed"}
    if not command:
        return {"error": "Missing 'command' parameter", "status": "failed"}

    try:
        executor = get_executor()
        result = executor.execute(device=device, command=command, timeout=timeout)

        if result.success:
            return {
                "output": result.output or "",
                "device": device,
                "command": command,
                "status": "success",
            }
        else:
            return {
                "error": result.error or "Unknown error",
                "device": device,
                "command": command,
                "status": "failed",
            }
    except Exception as e:
        return {"error": str(e), "device": device, "status": "failed"}


if __name__ == "__main__":
    try:
        input_str = sys.stdin.read()
        input_data = json.loads(input_str) if input_str.strip() else {}
        result = main(input_data)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e), "status": "failed"}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
