#!/usr/bin/env python3
"""
List Devices - Shared tool used by multiple skills.

Query Nornir inventory for available network devices.
Wraps the olav.tools.network_executor.get_nornir function for skill-based invocation.

Shared by: network-analysis, network-cli

Usage:
    echo '{}' | python3 list_devices.py
    echo '{"role": "core"}' | python3 list_devices.py
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

from olav.tools.network_executor import get_nornir


def main(params: dict) -> dict:
    """List devices from Nornir inventory.

    Args:
        params: {
            "role": "core",       # optional filter
            "site": "lab",        # optional filter
            "platform": "cisco_ios"  # optional filter
        }

    Returns:
        {"devices": [...], "count": N, "status": "success"}
    """
    role = params.get("role")
    site = params.get("site")
    platform = params.get("platform")

    try:
        nr = get_nornir()
        devices = []

        for name, host in nr.inventory.hosts.items():
            hostname = host.hostname or name
            host_platform = host.platform or "unknown"
            host_role = host.get("role", "unknown")
            host_site = host.get("site", "unknown")

            # Apply filters
            if role and host_role != role:
                continue
            if site and host_site != site:
                continue
            if platform and host_platform != platform:
                continue

            devices.append({
                "name": name,
                "hostname": hostname,
                "platform": host_platform,
                "role": host_role,
                "site": host_site,
            })

        return {
            "devices": devices,
            "count": len(devices),
            "status": "success",
        }

    except Exception as e:
        return {"error": str(e), "status": "failed"}


if __name__ == "__main__":
    try:
        input_str = sys.stdin.read()
        input_data = json.loads(input_str) if input_str.strip() else {}
        result = main(input_data)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e), "status": "failed"}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
