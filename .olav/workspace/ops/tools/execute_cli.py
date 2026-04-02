#!/usr/bin/env python3
"""
Network Tool - Execute commands and query devices on network infrastructure.

Core Features:
1. Execute CLI commands on network devices via Nornir
2. List and filter network devices from inventory
3. Device role/site/platform filtering
4. Command execution with timeout control

Usage in DeepAgents:
    from .tools import execute_cli
    agent = create_deep_agent(tools=[execute_cli.execute_cli])
"""

import json
import re
import sys
from pathlib import Path

import duckdb
from langchain_core.tools import tool
from pydantic import BaseModel, Field, validator
from tenacity import retry, stop_after_attempt, wait_exponential


def _find_project_root():
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


sys.path.insert(0, str(_find_project_root() / "src"))

from olav.core.config import MAIN_DB_PATH, settings
from olav.platform.safety.approval import check_approval

# Lazy imports for Nornir to improve startup time
# from nornir import InitNornir
# from nornir.core import Nornir
# from nornir_netmiko.tasks import netmiko_send_command


# ============================================================================
# Command Validation (checks commands table: blacklisted + pipe_allowed)
# ============================================================================


def _validate_command(command: str, platform: str | None = None) -> dict:
    """Check command against the commands table.

    Returns:
        {"ok": True} if command is allowed
        {"ok": False, "reason": str} if blocked
        {"ok": True, "warning": str} if commands table not yet populated (graceful degradation)
    """
    try:

        has_pipe = "|" in command
        # Normalize: strip pipe and everything after it to get base command
        base_cmd = command.split("|")[0].strip().lower()

        with duckdb.connect(str(MAIN_DB_PATH), read_only=True) as conn:
            # Check if commands table exists
            tables = [
                r[0]
                for r in conn.execute(
                    "SELECT table_name FROM information_schema.tables WHERE table_name = 'commands'"
                ).fetchall()
            ]
            if not tables:
                # commands table not yet created — skip validation
                return {
                    "ok": True,
                    "warning": "commands table not found; run sync_commands() to enable validation",
                }

            # Query for this command (match platform or wildcard)
            platform_filter = [platform, "*"] if platform else ["*"]
            placeholders = ",".join(["?"] * len(platform_filter))
            rows = conn.execute(
                f"SELECT blacklisted, pipe_allowed, allowed "
                f"FROM commands "
                f"WHERE LOWER(command_name) = ? "
                f"  AND platform IN ({placeholders}) "
                f"ORDER BY blacklisted DESC, platform ASC "
                f"LIMIT 1",
                [base_cmd] + platform_filter,
            ).fetchall()

        if not rows:
            # Command not in registry (no template, not in allowed list) — allow but warn
            return {
                "ok": True,
                "warning": f"'{base_cmd}' not in commands registry; run sync_commands() to register it",
            }

        blacklisted, pipe_allowed, allowed = rows[0]

        if blacklisted:
            return {"ok": False, "reason": f"Command '{base_cmd}' is blacklisted in commands table"}

        if has_pipe and not pipe_allowed:
            return {
                "ok": False,
                "reason": (
                    f"Command '{base_cmd}' does not allow pipe filtering (pipe_allowed=false). "
                    "Run execute_cli without '|' filter, or ask olav-config to update allowed_commands.yaml."
                ),
            }

        return {"ok": True}

    except Exception as exc:
        # DB unavailable or schema mismatch — fail open to not block real-time queries
        return {"ok": True, "warning": f"Command validation skipped (DB error: {exc})"}


# ============================================================================
# Nornir Singleton + Executor (inlined from shared/tools/network_executor.py)
# ============================================================================

_nornir_instance = None


def get_nornir():
    """Get global Nornir instance (singleton pattern to avoid repeated init)."""
    # Lazy import to avoid heavy startup cost if tool is not used
    from nornir import InitNornir

    global _nornir_instance
    if _nornir_instance is None:
        config_file = Path(settings.agent_dir) / "config" / "nornir" / "config.yaml"
        _nornir_instance = InitNornir(config_file=str(config_file.resolve()))

    return _nornir_instance


class _ExecutionResult:
    """Minimal result container for execute_cli_main."""

    def __init__(self, success: bool, output: str | None = None, error: str | None = None):
        self.success = success
        self.output = output
        self.error = error


class _Executor:
    """Thin wrapper around Nornir for single-device command execution."""

    def execute(self, device: str, command: str, timeout: int = 30) -> _ExecutionResult:
        try:
            # Lazy import task
            from nornir_netmiko.tasks import netmiko_send_command

            nr = get_nornir()
            target = nr.filter(name=device)
            if not target.inventory.hosts:
                return _ExecutionResult(
                    False, error=f"Device '{device}' not found in Nornir inventory"
                )

            result = target.run(
                task=netmiko_send_command, command_string=command, read_timeout=timeout
            )
            host_result = result[device]
            if host_result.failed:
                return _ExecutionResult(False, error=str(host_result.exception or "Command failed"))
            return _ExecutionResult(True, output=host_result.result)
        except Exception as e:
            return _ExecutionResult(False, error=str(e))


_executor_instance: _Executor | None = None


def get_executor() -> _Executor:
    global _executor_instance
    if _executor_instance is None:
        _executor_instance = _Executor()
    return _executor_instance


# ============================================================================
# Models for CLI Execution
# ============================================================================


class CLIExecutionInput(BaseModel):
    """CLI command execution input parameters - type-safe validation"""

    device: str = Field(..., description="Target device hostname", max_length=100)
    command: str = Field(..., description="CLI command to execute", min_length=1, max_length=1000)
    timeout: int = Field(default=30, description="Command timeout in seconds", ge=5, le=300)

    @validator("device")
    def validate_device_name(cls, v):
        """Device name validation - only alphanumerics, underscores, hyphens allowed"""
        if not v or len(v) == 0:
            raise ValueError("Device name cannot be empty")
        if not re.match(r"^[a-zA-Z0-9_\-.]+$", v):
            raise ValueError(
                f"Invalid device name format: {v}. "
                "Only alphanumerics, underscores, hyphens, and dots allowed."
            )
        return v

    @validator("command")
    def validate_command_not_empty(cls, v):
        """Command validation - cannot be just whitespace"""
        if not v.strip():
            raise ValueError("Command cannot be empty or whitespace only")
        return v


class CLIExecutionOutput(BaseModel):
    """CLI command execution result - unified response format"""

    output: str | None = Field(None, description="Command output/result")
    device: str = Field(..., description="Device that command was executed on")
    command: str = Field(..., description="Command that was executed")
    status: str = Field(..., description="Execution status (success or failed)")
    error: str | None = Field(None, description="Error message if execution failed")
    warning: str | None = Field(
        None, description="Non-fatal warning (e.g., command not in registry)"
    )


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
            device=device, command=command, status="failed", error=f"Invalid parameters: {str(e)}"
        )
        return output.model_dump(exclude_none=True)

    # --- Command validation (blacklist + pipe_allowed) ---
    # Look up device platform from Nornir inventory for accurate matching
    try:
        nr = get_nornir()
        host = nr.inventory.hosts.get(args.device)
        platform = str(host.platform) if host and host.platform else None
    except Exception:
        platform = None

    validation = _validate_command(args.command, platform)
    if not validation["ok"]:
        return CLIExecutionOutput(
            device=args.device,
            command=args.command,
            status="failed",
            error=f"[BLOCKED] {validation['reason']}",
        ).model_dump(exclude_none=True)

    # --- Dangerous command approval gate ---
    approval = check_approval(args.command, device=args.device)
    if approval.requires_approval:
        return {
            "status": "requires_approval",
            "device": args.device,
            "command": args.command,
            "severity": approval.severity,
            "reason": approval.reason,
            "suggested_action": approval.suggested_action,
        }

    try:
        executor = get_executor()
        result = executor.execute(device=args.device, command=args.command, timeout=args.timeout)

        if result.success:
            output = CLIExecutionOutput(
                output=result.output or "",
                device=args.device,
                command=args.command,
                status="success",
                warning=validation.get("warning"),
            )
        else:
            output = CLIExecutionOutput(
                device=args.device,
                command=args.command,
                status="failed",
                error=result.error or "Unknown error occurred during command execution",
            )

    except Exception as e:
        output = CLIExecutionOutput(
            device=args.device,
            command=args.command,
            status="failed",
            error=f"Execution error: {str(e)}",
        )

    return output.model_dump(exclude_none=True)


# ============================================================================
# LangChain Tool Registration (for DeepAgents integration)
# ============================================================================


@tool
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def execute_cli(device: str, command: str, timeout: int = 30) -> dict:
    """Execute CLI command on network device via Nornir.
    ⚠️ FALLBACK TOOL. Use execute_sql FIRST. Only use this when:
    - Data does NOT exist in the database (parsed_outputs table)
    - User explicitly requests real-time/live data
    - Data in DB is stale (>24h old) AND fresh data needed

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



if __name__ == "__main__":
    try:
        input_str = sys.stdin.read()
        input_data = json.loads(input_str) if input_str.strip() else {}

        result = execute_cli_main(input_data)

        print(json.dumps(result, ensure_ascii=False, indent=2))
    except json.JSONDecodeError as e:
        error_result = {"status": "failed", "error": f"Invalid JSON input: {str(e)}"}
        print(json.dumps(error_result, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        error_result = {"status": "failed", "error": f"Unexpected error: {str(e)}"}
        print(json.dumps(error_result, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(1)
