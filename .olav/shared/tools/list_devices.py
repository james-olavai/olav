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

from pydantic import BaseModel, Field
from langchain_core.tools import tool
from tenacity import retry, stop_after_attempt, wait_exponential


def _find_project_root():
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()

sys.path.insert(0, str(_find_project_root() / "src"))

from olav.tools.network_executor import get_nornir


# ============================================================================
# Pydantic Models for Type-Safe Parameter Validation
# ============================================================================

class ListDevicesInput(BaseModel):
    """List devices 输入参数 - 所有过滤条件都是可选的"""
    role: str | None = Field(
        None,
        description="Filter by device role (e.g., 'core', 'access')"
    )
    site: str | None = Field(
        None,
        description="Filter by site/location (e.g., 'lab', 'prod')"
    )
    platform: str | None = Field(
        None,
        description="Filter by platform (e.g., 'cisco_ios', 'junos')"
    )


class DeviceInfo(BaseModel):
    """单个设备信息"""
    name: str = Field(..., description="Device name")
    hostname: str = Field(..., description="Device hostname/IP")
    platform: str = Field(..., description="Device platform")
    role: str = Field(..., description="Device role")
    site: str = Field(..., description="Device site/location")


class ListDevicesOutput(BaseModel):
    """List devices 结果输出模型 - 统一的返回格式"""
    devices: list[DeviceInfo] = Field(..., description="List of devices")
    count: int = Field(..., description="Number of devices returned")
    status: str = Field(..., description="Operation status (success or failed)")
    error: str | None = Field(None, description="Error message if failed")


def main(params: dict) -> dict:
    """List devices from Nornir inventory with optional filtering.

    Args:
        params: {
            "role": "core",           # optional
            "site": "lab",            # optional  
            "platform": "cisco_ios"   # optional
        }

    Returns:
        ListDevicesOutput as dict with device list or error
    """
    # ========== STEP 1: Validate parameters with Pydantic ==========
    try:
        args = ListDevicesInput(**params)
    except Exception as e:
        output = ListDevicesOutput(
            devices=[],
            count=0,
            status="failed",
            error=f"Invalid parameters: {str(e)}"
        )
        return output.model_dump(exclude_none=True)

    # ========== STEP 2: Query Nornir inventory ==========
    try:
        nr = get_nornir()
        devices = []

        for name, host in nr.inventory.hosts.items():
            hostname = host.hostname or name
            host_platform = host.platform or "unknown"
            host_role = host.get("role", "unknown")
            host_site = host.get("site", "unknown")

            # Apply filters
            if args.role and host_role != args.role:
                continue
            if args.site and host_site != args.site:
                continue
            if args.platform and host_platform != args.platform:
                continue

            devices.append(DeviceInfo(
                name=name,
                hostname=hostname,
                platform=host_platform,
                role=host_role,
                site=host_site
            ))

        # ========== STEP 3: Return results ==========
        output = ListDevicesOutput(
            devices=devices,
            count=len(devices),
            status="success"
        )

    # ========== STEP 4: Handle errors ==========
    except Exception as e:
        output = ListDevicesOutput(
            devices=[],
            count=0,
            status="failed",
            error=f"Failed to list devices: {str(e)}"
        )

    return output.model_dump(exclude_none=True)


# ============================================================================
# LangChain Tool Registration (for DeepAgents integration)
# ============================================================================

@tool
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10)
)
def list_devices(role: str | None = None, site: str | None = None, 
                 platform: str | None = None) -> dict:
    """List network devices from Nornir inventory with optional filtering.
    
    This tool queries the Nornir inventory to list all available network devices.
    Results can be filtered by device role, site, or platform.
    
    Args:
        role: Optional device role filter (e.g., "core", "access", "edge")
        site: Optional site/location filter (e.g., "lab", "prod", "branch-01")
        platform: Optional platform filter (e.g., "cisco_ios", "junos", "iosxr")
    
    Returns:
        List of devices with their details (name, hostname, platform, role, site)
    
    Examples:
        list_devices()  # List all devices
        list_devices(role="core")  # List only core devices
        list_devices(site="prod", platform="cisco_ios")  # Filter by site and platform
    """
    # Use Pydantic model for validation
    params = {
        "role": role,
        "site": site, 
        "platform": platform
    }
    return main(params)


if __name__ == "__main__":
    try:
        input_str = sys.stdin.read()
        input_data = json.loads(input_str) if input_str.strip() else {}
        result = main(input_data)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except json.JSONDecodeError as e:
        error_result = {
            "status": "failed",
            "error": f"Invalid JSON input: {str(e)}"
        }
        print(json.dumps(error_result, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        error_result = {
            "status": "failed",
            "error": f"Unexpected error: {str(e)}"
        }
        print(json.dumps(error_result, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(1)
