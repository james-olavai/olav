"""TextFSM parsing utilities for network command output.

This module provides TextFSM-based parsing for structured network data extraction.
Separated from network.py for better maintainability (per DESIGN_V0.81.md optimization).
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from nornir.core import Nornir
from nornir.core.exceptions import NornirSubTaskError
from nornir.core.task import AggregatedResult, Result
from nornir_netmiko.tasks import netmiko_send_command

from config.settings import settings

if TYPE_CHECKING:
    from olav.core.database import OlavDatabase
    from olav.tools.network_executor import CommandExecutionResult


def estimate_tokens(text: str) -> int:
    """Estimate token count for text.

    Args:
        text: Text to estimate tokens for

    Returns:
        Estimated token count (rough approximation: 1 token ≈ 4 characters)
    """
    # Rough approximation: 1 token ≈ 4 characters for English text
    # For network output, this is a reasonable estimate
    return len(text) // 4


def execute_with_textfsm(
    nr: Nornir,
    device: str,
    command: str,
    timeout: int | None = None,
    db: "OlavDatabase | None" = None,
    blacklist_checker: object = None,  # Function that takes str and returns str|None
    platform_detector: object = None,  # Function that takes str and returns str|None
) -> "CommandExecutionResult":
    """Execute command with TextFSM parsing.

    Args:
        nr: Nornir instance
        device: Device name or IP
        command: Command to execute
        timeout: Command timeout in seconds (defaults to settings.execution.timeout)
        db: Database instance for whitelist/audit
        blacklist_checker: Function to check if command is blacklisted
        platform_detector: Function to detect device platform

    Returns:
        CommandExecutionResult with structured output and token statistics

    Raises:
        Exception: If TextFSM parsing fails
    """
    # Task 11.4: Use centralized timeout from settings
    if timeout is None:
        timeout = settings.execution.timeout

    from olav.tools.network_executor import CommandExecutionResult

    start_time = datetime.now()

    # Check blacklist
    blacklisted_pattern = blacklist_checker(command) if callable(blacklist_checker) else None  # type: ignore[arg-type]
    if blacklisted_pattern:
        return CommandExecutionResult(
            device=device,
            command=command,
            success=False,
            error=f"Command is blacklisted (matches pattern: {blacklisted_pattern})",
            duration_ms=0,
        )

    # Detect platform
    platform = platform_detector(device) if callable(platform_detector) else None  # type: ignore[arg-type]

    # Check command is allowed via CommandValidator (supports blacklist/whitelist/hybrid modes)
    if platform and isinstance(platform, str):
        from olav.core.command_validator import get_command_validator

        validator = get_command_validator()
        validation_result = validator.validate_command(platform, command)

        if not validation_result.allowed:
            return CommandExecutionResult(
                device=device,
                command=command,
                success=False,
                error=f"Command validation failed: {validation_result.reason}",
                duration_ms=0,
            )

        # If no template but raw_fallback is allowed, use raw mode
        if not validation_result.has_template and validation_result.raw_fallback:
            print(f"⚠️ No TextFSM template for '{command}', using raw output mode", file=sys.stderr)
            # Execute without TextFSM
            use_textfsm = False
        else:
            use_textfsm = True
    else:
        use_textfsm = True

    # Set TextFSM template directory (priority: config > .olav/templates)
    # Priority 1: Custom config directory (if exists)
    custom_textfsm_dir = Path(settings.agent_dir) / "config" / "textfsm"
    if custom_textfsm_dir.exists() and (custom_textfsm_dir / "index").exists():
        os.environ["NET_TEXTFSM"] = str(custom_textfsm_dir.resolve())
        print(f"📁 Using custom TextFSM templates: {custom_textfsm_dir}", file=sys.stderr)
    else:
        # Priority 2: Default .olav/templates directory
        default_textfsm_dir = Path(settings.execution.textfsm_template_dir)
        if not default_textfsm_dir.is_absolute():
            default_textfsm_dir = Path(settings.agent_dir).parent / default_textfsm_dir
        
        if default_textfsm_dir.exists() and (default_textfsm_dir / "index").exists():
            os.environ["NET_TEXTFSM"] = str(default_textfsm_dir.resolve())
            print(f"📁 Using default TextFSM templates: {default_textfsm_dir}", file=sys.stderr)
        else:
            print(f"⚠️ TextFSM template directory not found: {default_textfsm_dir}", file=sys.stderr)
            print(f"   TextFSM parsing will be disabled", file=sys.stderr)

    # Execute command with TextFSM
    try:
        nr_filtered = nr.filter(name=device)

        if not nr_filtered.inventory.hosts:
            msg = f"❌ Device '{device}' not found in inventory"
            print(msg, file=sys.stderr)
            return CommandExecutionResult(
                device=device,
                command=command,
                success=False,
                error=msg,
                duration_ms=0,
            )

        mode_str = "parsed" if use_textfsm else "raw"
        print(
            f"📡 Executing '{command}' ({mode_str}) on {device} (timeout={timeout}s)...",
            file=sys.stderr,
        )

        # Run command with or without TextFSM
        result: AggregatedResult = nr_filtered.run(
            task=netmiko_send_command,
            command_string=command,
            read_timeout=timeout,
            use_textfsm=use_textfsm,  # Conditional TextFSM parsing
        )

        host_result: Result = result[device]  # type: ignore[assignment]
        duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

        if host_result.failed:
            error_msg = str(host_result.exception) if host_result.exception else "Unknown error"
            return CommandExecutionResult(
                device=device,
                command=command,
                success=False,
                error=error_msg,
                duration_ms=duration_ms,
            )

        # Get result (parsed or raw)
        if use_textfsm:
            # TextFSM parsed result (list or dict)
            parsed_output = host_result.result

            # Estimate tokens
            structured_output = json.dumps(parsed_output, default=str)
            parsed_tokens = estimate_tokens(structured_output)
            raw_tokens = int(parsed_tokens * 3)  # Estimate raw was 3x larger
            tokens_saved = raw_tokens - parsed_tokens

            # Log to audit trail
            if db:
                db.log_execution(
                    thread_id="main",
                    device=device,
                    command=command,
                    output=structured_output,
                    success=True,
                    duration_ms=duration_ms,
                )

            return CommandExecutionResult(
                device=device,
                command=command,
                success=True,
                output=structured_output,
                raw_output=str(parsed_output),
                duration_ms=duration_ms,
                structured=True,
                raw_tokens=raw_tokens,
                parsed_tokens=parsed_tokens,
                tokens_saved=tokens_saved,
            )
        else:
            # Raw output mode (no TextFSM)
            raw_output = str(host_result.result)

            # Estimate tokens (raw is larger)
            raw_tokens = estimate_tokens(raw_output)
            parsed_tokens = 0
            tokens_saved = 0

            # Log to audit trail
            if db:
                db.log_execution(
                    thread_id="main",
                    device=device,
                    command=command,
                    output=raw_output,
                    success=True,
                    duration_ms=duration_ms,
                )

            return CommandExecutionResult(
                device=device,
                command=command,
                success=True,
                output=raw_output,
                raw_output=raw_output,
                duration_ms=duration_ms,
                structured=False,  # Raw output, not structured
                raw_tokens=raw_tokens,
                parsed_tokens=parsed_tokens,
                tokens_saved=tokens_saved,
            )

    except NornirSubTaskError as e:
        # TextFSM parsing error (only in TextFSM mode)
        if use_textfsm:
            raise Exception(f"TextFSM parsing failed: {e}") from e
        else:
            raise Exception(f"Command execution failed: {e}") from e
    except Exception as e:
        raise Exception(f"Command execution failed: {e}") from e
