#!/usr/bin/env python3
"""
Network Tool - Execute commands and query devices on network infrastructure.

Core Features:
1. Execute CLI commands on network devices via Nornir
2. List and filter network devices from inventory
3. Device role/site/platform filtering
4. Command execution with timeout control

Usage in DeepAgents:
    from .tools import network
    agent = create_deep_agent(tools=[network.execute_cli, network.list_devices])
"""

import json
import re
import sys
from pathlib import Path

from pydantic import BaseModel, Field, validator
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

# Import from shared tools where the real implementation lives
_shared_tools = _find_project_root() / ".olav" / "skills" / "shared" / "tools"
sys.path.insert(0, str(_shared_tools))

from network_executor import get_executor, get_nornir


# ============================================================================
# Models for CLI Execution
# ============================================================================

class CLIExecutionInput(BaseModel):
    """CLI command execution input parameters - type-safe validation"""
    device: str = Field(
        ...,
        description="Target device hostname",
        max_length=100
    )
    command: str = Field(
        ...,
        description="CLI command to execute",
        min_length=1,
        max_length=1000
    )
    timeout: int = Field(
        default=30,
        description="Command timeout in seconds",
        ge=5,
        le=300
    )
    
    @validator('device')
    def validate_device_name(cls, v):
        """Device name validation - only alphanumerics, underscores, hyphens allowed"""
        if not v or len(v) == 0:
            raise ValueError("Device name cannot be empty")
        if not re.match(r'^[a-zA-Z0-9_\-.]+$', v):
            raise ValueError(
                f"Invalid device name format: {v}. "
                "Only alphanumerics, underscores, hyphens, and dots allowed."
            )
        return v
    
    @validator('command')
    def validate_command_not_empty(cls, v):
        """Command validation - cannot be just whitespace"""
        if not v.strip():
            raise ValueError("Command cannot be empty or whitespace only")
        return v


class CLIExecutionOutput(BaseModel):
    """CLI command execution result - unified response format"""
    output: str | None = Field(
        None,
        description="Command output/result"
    )
    device: str = Field(
        ...,
        description="Device that command was executed on"
    )
    command: str = Field(
        ...,
        description="Command that was executed"
    )
    status: str = Field(
        ...,
        description="Execution status (success or failed)"
    )
    error: str | None = Field(
        None,
        description="Error message if execution failed"
    )


# ============================================================================
# Models for Device Listing
# ============================================================================

class ListDevicesInput(BaseModel):
    """List devices input parameters - all filter conditions optional"""
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
    """Single device information"""
    name: str = Field(..., description="Device name")
    hostname: str = Field(..., description="Device hostname/IP")
    platform: str = Field(..., description="Device platform")
    role: str = Field(..., description="Device role")
    site: str = Field(..., description="Device site/location")


class ListDevicesOutput(BaseModel):
    """List devices result - unified response format"""
    devices: list[DeviceInfo] = Field(..., description="List of devices")
    count: int = Field(..., description="Number of devices returned")
    status: str = Field(..., description="Operation status (success or failed)")
    error: str | None = Field(None, description="Error message if failed")


# ============================================================================
# CLI Execution Implementation
# ============================================================================

def execute_cli_main(params: dict) -> dict:
    """Execute a command on a network device.

    Args:
        params: {
            "device": "R1",
            "command": "show version",
            "timeout": 30  # optional, default 30 seconds (5-300)
        }

    Returns:
        {
            "output": "Cisco IOS Software...",
            "device": "R1",
            "command": "show version",
            "status": "success"
        }
    """
    try:
        args = CLIExecutionInput(**params)
    except Exception as e:
        device = params.get("device", "unknown")
        command = params.get("command", "unknown")
        output = CLIExecutionOutput(
            device=device,
            command=command,
            status="failed",
            error=f"Invalid parameters: {str(e)}"
        )
        return output.model_dump(exclude_none=True)

    try:
        executor = get_executor()
        result = executor.execute(
            device=args.device,
            command=args.command,
            timeout=args.timeout
        )

        if result.success:
            output = CLIExecutionOutput(
                output=result.output or "",
                device=args.device,
                command=args.command,
                status="success"
            )
        else:
            output = CLIExecutionOutput(
                device=args.device,
                command=args.command,
                status="failed",
                error=result.error or "Unknown error occurred during command execution"
            )

    except Exception as e:
        output = CLIExecutionOutput(
            device=args.device,
            command=args.command,
            status="failed",
            error=f"Execution error: {str(e)}"
        )

    return output.model_dump(exclude_none=True)


# ============================================================================
# Device Listing Implementation
# ============================================================================

def list_devices_main(params: dict) -> dict:
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

        output = ListDevicesOutput(
            devices=devices,
            count=len(devices),
            status="success"
        )

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
def execute_cli(device: str, command: str, timeout: int = 30) -> dict:
    """Execute CLI command on network device via Nornir.
    
    This tool executes commands on network devices using the Nornir framework.
    It supports all devices configured in the Nornir inventory.
    
    Args:
        device: Target device hostname (alphanumerics, hyphens, underscores, dots allowed)
        command: CLI command to execute (e.g., "show version", "show interfaces")
        timeout: Command timeout in seconds (5-300, default 30)
    
    Returns:
        Command output or error information
    
    Examples:
        execute_cli(device="R1", command="show version")
        execute_cli(device="core-01", command="show bgp summary", timeout=60)
    """
    params = {"device": device, "command": command, "timeout": timeout}
    return execute_cli_main(params)


@tool
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10)
)
def list_devices_inventory(role: str | None = None, site: str | None = None, 
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
        list_devices_inventory()  # List all devices
        list_devices_inventory(role="core")  # List only core devices
        list_devices_inventory(site="prod", platform="cisco_ios")
    """
    params = {
        "role": role,
        "site": site, 
        "platform": platform
    }
    return list_devices_main(params)


if __name__ == "__main__":
    try:
        input_str = sys.stdin.read()
        input_data = json.loads(input_str) if input_str.strip() else {}
        
        # Determine which function to call based on input
        if "device" in input_data and "command" in input_data:
            result = execute_cli_main(input_data)
        else:
            result = list_devices_main(input_data)
            
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
