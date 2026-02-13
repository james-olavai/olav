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

from olav.tools.network_executor import get_executor


# ============================================================================
# Pydantic Models for Type-Safe Parameter Validation
# ============================================================================

class NornirExecuteInput(BaseModel):
    """Nornir 命令执行输入参数 - 使用 Pydantic 自动验证"""
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
        # Allow: alphanumerics, underscores, hyphens, dots (for FQDN)
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


class NornirExecuteOutput(BaseModel):
    """Nornir 命令执行结果输出模型 - 统一的返回格式"""
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


def main(params: dict) -> dict:
    """Execute a command on a network device.

    Args:
        params: {
            "device": "R1",
            "command": "show version",
            "timeout": 30  # optional, default 30 seconds (5-300)
        }

    Returns:
        NornirExecuteOutput as dict:
        {
            "output": "Cisco IOS Software...",
            "device": "R1",
            "command": "show version",
            "status": "success"
        }
        
        On error:
        {
            "device": "R1",
            "command": "show version",
            "status": "failed",
            "error": "Connection timeout"
        }
    """
    # ========== STEP 1: Validate parameters with Pydantic ==========
    # This automatically validates:
    # - device is not empty and matches format (alphanumerics, -, _, .)
    # - command is not empty or whitespace
    # - timeout is in range 5-300 seconds
    try:
        args = NornirExecuteInput(**params)
    except Exception as e:
        # Validation error - return immediately with error details
        device = params.get("device", "unknown")
        command = params.get("command", "unknown")
        output = NornirExecuteOutput(
            device=device,
            command=command,
            status="failed",
            error=f"Invalid parameters: {str(e)}"
        )
        return output.model_dump(exclude_none=True)

    # ========== STEP 2: Execute command ==========
    try:
        executor = get_executor()
        result = executor.execute(
            device=args.device,
            command=args.command,
            timeout=args.timeout
        )

        # ========== STEP 3: Format output based on execution result ==========
        if result.success:
            output = NornirExecuteOutput(
                output=result.output or "",
                device=args.device,
                command=args.command,
                status="success"
            )
        else:
            output = NornirExecuteOutput(
                device=args.device,
                command=args.command,
                status="failed",
                error=result.error or "Unknown error occurred during command execution"
            )

    # ========== STEP 4: Handle execution errors ==========
    except Exception as e:
        output = NornirExecuteOutput(
            device=args.device,
            command=args.command,
            status="failed",
            error=f"Execution error: {str(e)}"
        )

    # ========== STEP 5: Return formatted result ==========
    return output.model_dump(exclude_none=True)


# ============================================================================
# LangChain Tool Registration (for DeepAgents integration)
# ============================================================================

@tool
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10)
)
def nornir_execute(device: str, command: str, timeout: int = 30) -> dict:
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
        nornir_execute(device="R1", command="show version")
        nornir_execute(device="core-01", command="show bgp summary", timeout=60)
    """
    # Use Pydantic model for validation
    params = {"device": device, "command": command, "timeout": timeout}
    return main(params)


if __name__ == "__main__":
    try:
        input_str = sys.stdin.read()
        input_data = json.loads(input_str) if input_str.strip() else {}
        result = main(input_data)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except json.JSONDecodeError as e:
        error_result = {
            "error": f"Invalid JSON input: {str(e)}",
            "status": "failed",
            "error_type": "json_decode_error"
        }
        print(json.dumps(error_result, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        error_result = {
            "error": f"Unexpected error: {str(e)}",
            "status": "failed",
            "error_type": "unexpected_error"
        }
        print(json.dumps(error_result, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(1)
