"""Network command executor for OLAV v0.8.

This module provides the core NetworkExecutor class for executing commands
on network devices using Nornir/Netmiko.
Separated from network.py for better maintainability (per DESIGN_V0.81.md optimization).
"""

import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from nornir import InitNornir
from nornir.core import Nornir
from nornir.core.exceptions import NornirSubTaskError
from nornir.core.task import AggregatedResult, Result
from nornir_netmiko.tasks import netmiko_send_command
from pydantic import BaseModel, Field

from config.settings import settings
from olav.core.database import get_database

# ============================================================================
# P4: Nornir Connection Pool Singleton
# ============================================================================

_nornir_instance: Nornir | None = None


def get_nornir(
    config_file: str | Path | None = None,
) -> Nornir:
    """Get the global Nornir instance (singleton pattern).

    P4 Optimization: Reuse a single Nornir instance to avoid repeated
    initialization overhead (~200-500ms per InitNornir call).

    Args:
        config_file: Path to Nornir configuration file (defaults to agent_dir/config/nornir/config.yaml)

    Returns:
        Shared Nornir instance with credentials applied
    """
    global _nornir_instance

    if _nornir_instance is None:
        if config_file is None:
            config_file = Path(settings.agent_dir) / "config" / "nornir" / "config.yaml"
        config_path = Path(config_file).resolve()
        _nornir_instance = InitNornir(config_file=str(config_path))

        # Apply credentials from settings to all hosts
        username = getattr(settings, "device_username", None)
        password = getattr(settings, "device_password", None)

        if username or password:
            assert _nornir_instance is not None  # For type checker  # noqa: S101
            for host in _nornir_instance.inventory.hosts.values():
                if username:
                    host.username = username
                if password:
                    host.password = password

    return _nornir_instance


def reset_nornir() -> None:
    """Reset the Nornir singleton (for testing or reconnection)."""
    global _nornir_instance
    _nornir_instance = None


class CommandExecutionResult(BaseModel):
    """Result of a network command execution."""

    device: str = Field(description="Device name or IP")
    command: str = Field(description="Command that was executed")
    success: bool = Field(description="Whether execution succeeded")
    output: str | None = Field(default=None, description="Command output if successful")
    error: str | None = Field(default=None, description="Error message if failed")
    duration_ms: int = Field(default=0, description="Execution time in milliseconds")
    # Phase 4.2: TextFSM parsing fields
    structured: bool = Field(default=False, description="Whether output was parsed with TextFSM")
    raw_output: str | None = Field(default=None, description="Raw text output if parsing was used")
    # Phase 4.2: Token statistics
    raw_tokens: int | None = Field(default=None, description="Estimated raw token count")
    parsed_tokens: int | None = Field(default=None, description="Token count after parsing")
    tokens_saved: int | None = Field(default=None, description="Tokens saved by parsing")


class BatchExecutionRequest(BaseModel):
    """Request for batch command execution with validation.
    
    Scenario 5: Batch multi-device multi-command processing.
    """
    
    devices: list[str] = Field(
        min_length=1,
        max_length=50,
        description="List of device names (1-50 devices)",
    )
    commands: list[str] = Field(
        min_length=1,
        max_length=20,
        description="List of commands to execute (1-20 commands)",
    )
    output_dir: Path | None = Field(
        default=None,
        description="Output directory (default: exports/cli_batch_{timestamp})",
    )
    organize_by_device: bool = Field(
        default=True,
        description="Create device subdirectories",
    )
    use_textfsm: bool | None = Field(
        default=None,
        description="Use TextFSM parsing (None = use config default)",
    )
    cache_bypass: bool = Field(
        default=False,
        description="Bypass command cache",
    )
    timeout: int = Field(
        default=30,
        ge=5,
        le=300,
        description="Command timeout in seconds (5-300)",
    )


class DeviceCommandResult(BaseModel):
    """Result of a single command on a single device."""
    
    device: str = Field(description="Device name")
    command: str = Field(description="Command executed")
    command_index: int = Field(description="Command index (1-based)")
    success: bool = Field(description="Execution success")
    output: str | None = Field(default=None, description="Command output")
    error: str | None = Field(default=None, description="Error message")
    structured: bool = Field(default=False, description="TextFSM parsed")
    file_path: Path | None = Field(default=None, description="Saved file path")
    duration_ms: int = Field(default=0, description="Execution duration")


class BatchExecutionResult(BaseModel):
    """Result of batch command execution.
    
    Scenario 5: Contains all execution results and metadata.
    """
    
    batch_id: str = Field(description="Unique batch execution ID")
    start_time: datetime = Field(description="Batch start timestamp")
    end_time: datetime | None = Field(default=None, description="Batch end timestamp")
    total_duration_ms: int = Field(default=0, description="Total execution duration")
    
    devices: list[str] = Field(description="Devices executed")
    commands: list[str] = Field(description="Commands executed")
    
    results: list[DeviceCommandResult] = Field(
        default_factory=list,
        description="All command execution results",
    )
    
    output_dir: Path = Field(description="Output directory path")
    metadata_file: Path | None = Field(default=None, description="Metadata JSON file")
    
    total_executions: int = Field(default=0, description="Total executions")
    successful_executions: int = Field(default=0, description="Successful executions")
    failed_executions: int = Field(default=0, description="Failed executions")
    success_rate: float = Field(default=0.0, description="Success rate percentage")
    
    @property
    def summary(self) -> str:
        """Generate execution summary."""
        return (
            f"Batch {self.batch_id}: "
            f"{self.successful_executions}/{self.total_executions} succeeded "
            f"({self.success_rate:.1f}%) "
            f"in {self.total_duration_ms}ms"
        )


class NetworkExecutor:
    """Network command executor with Nornir."""

    def __init__(
        self,
        nornir_config: str | Path | None = None,
        blacklist_file: str | Path | None = None,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        """Initialize executor.

        Args:
            nornir_config: Path to Nornir configuration (defaults to agent_dir/config/nornir/config.yaml)
            blacklist_file: Path to command blacklist file (defaults to .olav/skills/network-cli/config/blacklist.txt)
            username: Device username (from .env if not provided)
            password: Device password (from .env if not provided)
        """
        if nornir_config is None:
            nornir_config = Path(settings.agent_dir) / "config" / "nornir" / "config.yaml"
        if blacklist_file is None:
            blacklist_file = (
                Path(settings.agent_dir) / "skills" / "network-cli" / "config" / "blacklist.txt"
            )

        self.nornir_config = Path(nornir_config)
        self.blacklist_file = Path(blacklist_file)
        self.username = username or getattr(settings, "device_username", "admin")
        self.password = password or getattr(settings, "device_password", "")
        self.blacklist = self._load_blacklist()
        self.db = get_database()

        # Phase 3: Load caching configuration from SKILL.md
        self.cache_config = self._load_cache_config()
        self.command_cache: dict[str, dict[str, Any]] = {}  # {cache_key: {output, timestamp}}

    def _load_cache_config(self) -> dict[str, Any]:
        """Load caching configuration from network-cli SKILL.md.

        Returns:
            Caching configuration dict with enabled, ttl, and command patterns
        """
        try:
            from olav.core.subagent_loader import load_caching_config

            config = load_caching_config("network-cli")
            return config if isinstance(config, dict) else {}
        except Exception as e:
            # Gracefully handle missing cache config - disable caching
            import logging

            logging.debug(f"Failed to load cache config from SKILL.md: {e}")
            return {"enabled": False}

    def _is_command_cacheable(self, command: str) -> bool:
        """Check if command output should be cached based on SKILL.md config.

        Args:
            command: Command to check

        Returns:
            True if command is in cached_command_patterns, False otherwise
        """
        if not self.cache_config.get("enabled"):
            return False

        cached_patterns = self.cache_config.get("cached_command_patterns", [])
        if not cached_patterns:
            return False

        cmd_lower = command.lower().strip()

        # Check if command matches any pattern (using prefix match for show commands)
        for pattern in cached_patterns:
            pattern_lower = pattern.lower()
            # Exact match or prefix match (for commands with parameters)
            if cmd_lower == pattern_lower or cmd_lower.startswith(pattern_lower + " "):
                return True

        return False

    def _get_from_cache(self, cache_key: str) -> CommandExecutionResult | None:
        """Get cached command result if not expired.

        Args:
            cache_key: Cache key (device:command)

        Returns:
            Cached CommandExecutionResult if valid, None if expired or not found
        """
        if cache_key not in self.command_cache:
            return None

        cached_entry = self.command_cache[cache_key]
        cached_result = cached_entry.get("result")
        timestamp = cached_entry.get("timestamp")

        if not cached_result or not timestamp:
            return None

        # Check TTL
        ttl = self._get_command_ttl(cached_result.command)
        age_seconds = (datetime.now() - timestamp).total_seconds()

        if age_seconds > ttl:
            # Expired - remove from cache
            del self.command_cache[cache_key]
            return None

        return cached_result

    def _save_to_cache(self, cache_key: str, result: CommandExecutionResult) -> None:
        """Save successful command result to cache.

        Args:
            cache_key: Cache key (device:command)
            result: CommandExecutionResult to cache
        """
        # Check max cache size
        max_entries = self.cache_config.get("max_cache_entries", 10000)
        if len(self.command_cache) >= max_entries:
            # Remove oldest entry (simple FIFO, could be improved with LRU)
            oldest_key = next(iter(self.command_cache))
            del self.command_cache[oldest_key]

        # Cache the result
        self.command_cache[cache_key] = {
            "result": result,
            "timestamp": datetime.now(),
        }

    def _get_command_ttl(self, command: str) -> int:
        """Get TTL for a specific command from SKILL.md config.

        Args:
            command: Command string

        Returns:
            TTL in seconds (default: 3600 if command not specifically configured)
        """
        cmd_overrides = self.cache_config.get("command_ttl_overrides", {})

        # Exact match first
        cmd_lower = command.lower().strip()
        if cmd_lower in cmd_overrides:
            return int(cmd_overrides[cmd_lower])

        # Check if command starts with a pattern
        for pattern, ttl in cmd_overrides.items():
            if cmd_lower.startswith(pattern.lower() + " "):
                return int(ttl)

        # Use default TTL
        return int(self.cache_config.get("default_ttl_seconds", 3600))

    def _load_blacklist(self) -> set[str]:
        """Load command blacklist from file.

        Returns:
            Set of blacklisted command patterns
        """
        if not self.blacklist_file.exists():
            return set()

        blacklist: set[str] = set()
        for line in self.blacklist_file.read_text(encoding="utf-8").split("\n"):
            line = line.strip()
            if line and not line.startswith("#"):
                blacklist.add(line.lower())

        return blacklist

    def _is_blacklisted(self, command: str) -> str | None:
        """Check if command is blacklisted.

        Args:
            command: Command to check

        Returns:
            Blacklisted pattern that matched, or None
        """
        cmd_lower = command.lower().strip()

        for pattern in self.blacklist:
            if pattern.endswith("*"):
                # Wildcard match
                if cmd_lower.startswith(pattern[:-1]):
                    return pattern
            else:
                # Exact match
                if cmd_lower == pattern:
                    return pattern

        return None

    def _detect_platform(self, device: str) -> str | None:
        """Detect device platform from Nornir inventory.

        Args:
            device: Device name

        Returns:
            Platform string (e.g., "cisco_ios") or None
        """
        try:
            nr = get_nornir(str(self.nornir_config))
            host = nr.inventory.hosts.get(device)

            if host:
                if host.platform:
                    return host.platform

            return None
        except Exception as e:
            import sys

            print(f"Debug: Failed to detect platform for {device}: {e}", file=sys.stderr)
            return None

    def execute(
        self,
        device: str,
        command: str,
        timeout: int | None = None,
        use_textfsm: bool | None = None,
        cache_bypass: bool = False,
    ) -> CommandExecutionResult:
        """Execute a command on a network device.

        Phase 3: Implements command result caching with per-command TTL.
        Phase 3.4: Accepts Guard parameters (use_textfsm, cache_bypass).

        Args:
            device: Device name or IP
            command: Command to execute
            timeout: Command timeout in seconds (defaults to settings.execution.timeout)
            use_textfsm: Use TextFSM structured parsing (None = use config default)
            cache_bypass: Skip cache lookup (for realtime queries)

        Returns:
            CommandExecutionResult
        """
        # Task 11.4: Use centralized timeout from settings
        if timeout is None:
            timeout = settings.execution.timeout
        
        # Phase 3.4: Determine TextFSM usage
        if use_textfsm is None:
            use_textfsm = settings.execution.use_textfsm

        start_time = datetime.now()

        # Phase 3: Check cache before executing (unless cache_bypass=True)
        cache_key = f"{device}:{command}"
        if (
            not cache_bypass
            and self.cache_config.get("enabled")
            and self._is_command_cacheable(command)
        ):
            cached_result = self._get_from_cache(cache_key)
            if cached_result:
                duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
                # Update result with actual execution time
                cached_result.duration_ms = duration_ms
                return cached_result

        # Check blacklist
        blacklisted_pattern = self._is_blacklisted(command)
        if blacklisted_pattern:
            return CommandExecutionResult(
                device=device,
                command=command,
                success=False,
                error=f"Command is blacklisted (matches pattern: {blacklisted_pattern})",
                duration_ms=0,
            )

        # Detect platform
        platform = self._detect_platform(device)

        # Check command is allowed via CommandRegistry
        if platform:
            from olav.core.registry import get_command_registry

            registry = get_command_registry()
            if not registry.validate_command(platform, command):
                return CommandExecutionResult(
                    device=device,
                    command=command,
                    success=False,
                    error=f"Command not allowed for platform {platform} (no template found)",
                    duration_ms=0,
                )

        # Execute command
        try:
            nr = get_nornir(str(self.nornir_config))

            # Filter to single device
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

            print(f"📡 Executing '{command}' on {device} (timeout={timeout}s, use_textfsm={use_textfsm})...", file=sys.stderr)

            # Phase 3.4: Run command with Guard parameters
            result: AggregatedResult = nr_filtered.run(
                task=netmiko_send_command,
                command_string=command,
                read_timeout=timeout,
                use_textfsm=use_textfsm,  # 🔥 Guard decision parameter
            )

            # Extract result
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
            # Get raw text output (no TextFSM parsing for batch)
            raw_output = str(host_result.result)
            
            # Create result with raw output
            result = CommandExecutionResult(
                device=device,
                command=command,
                success=True,
                output=raw_output,
                duration_ms=duration_ms,
            )
            
            # Log to audit trail
            self.db.log_execution(
                thread_id="main",
                device=device,
                command=command,
                output=raw_output,
                success=True,
                duration_ms=duration_ms,
            )

            # Phase 3: Cache successful results
            if self.cache_config.get("enabled") and self._is_command_cacheable(command):
                self._save_to_cache(cache_key, result)

            return result

        except NornirSubTaskError as e:
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            return CommandExecutionResult(
                device=device,
                command=command,
                success=False,
                error=str(e),
                duration_ms=duration_ms,
            )
        except Exception as e:
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            return CommandExecutionResult(
                device=device,
                command=command,
                success=False,
                error=f"Unexpected error: {e}",
                duration_ms=duration_ms,
            )

    def execute_command(
        self,
        devices: list[str],
        command: str,
        timeout: int | None = None,
        use_textfsm: bool | None = None,
        cache_bypass: bool = False,
    ) -> list[CommandExecutionResult]:
        """Execute a command on multiple devices (batch execution).

        Phase 3.4: Accepts Guard parameters (use_textfsm, cache_bypass).
        Phase 4: Uses Nornir native concurrency (nr.run) instead of for loop.

        Args:
            devices: List of device names or IPs
            command: Command to execute on all devices
            timeout: Command timeout in seconds (defaults to settings.execution.timeout)
            use_textfsm: Use TextFSM structured parsing (None = use config default)
            cache_bypass: Skip cache lookup (for realtime queries)

        Returns:
            List of CommandExecutionResult, one per device
        """
        # Determine defaults
        if timeout is None:
            timeout = settings.execution.timeout
        if use_textfsm is None:
            use_textfsm = settings.execution.use_textfsm
        
        # Phase 4: Check cache for all devices (unless cache_bypass=True)
        results = []
        devices_to_execute = []
        cache_keys = {}
        
        if not cache_bypass and self.cache_config.get("enabled") and self._is_command_cacheable(command):
            for device in devices:
                cache_key = f"{device}:{command}"
                cache_keys[device] = cache_key
                cached_result = self._get_from_cache(cache_key)
                if cached_result:
                    results.append(cached_result)
                else:
                    devices_to_execute.append(device)
        else:
            devices_to_execute = devices
        
        # If all results cached, return immediately
        if not devices_to_execute:
            return results
        
        # Phase 4: Execute commands concurrently using nr.run()
        try:
            nr = get_nornir(str(self.nornir_config))
            
            # Filter to target devices
            nr_filtered = nr.filter(lambda h: h.name in devices_to_execute)
            
            if not nr_filtered.inventory.hosts:
                # No devices found, return error results
                for device in devices_to_execute:
                    results.append(
                        CommandExecutionResult(
                            device=device,
                            command=command,
                            success=False,
                            error=f"Device '{device}' not found in inventory",
                            duration_ms=0,
                        )
                    )
                return results
            
            # Execute command on all devices concurrently
            start_time = datetime.now()
            print(f"📡 Executing '{command}' on {len(devices_to_execute)} device(s) concurrently (use_textfsm={use_textfsm})...", file=sys.stderr)
            
            agg_result: AggregatedResult = nr_filtered.run(
                task=netmiko_send_command,
                command_string=command,
                read_timeout=timeout,
                use_textfsm=use_textfsm,  # 🔥 Guard parameter
            )
            
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            
            # Process results
            for device in devices_to_execute:
                if device not in agg_result:
                    results.append(
                        CommandExecutionResult(
                            device=device,
                            command=command,
                            success=False,
                            error=f"Device '{device}' not in execution results",
                            duration_ms=0,
                        )
                    )
                    continue
                
                host_result: Result = agg_result[device]  # type: ignore[assignment]
                
                if host_result.failed:
                    error_msg = str(host_result.exception) if host_result.exception else "Unknown error"
                    results.append(
                        CommandExecutionResult(
                            device=device,
                            command=command,
                            success=False,
                            error=error_msg,
                            duration_ms=duration_ms,
                        )
                    )
                else:
                    # Success - log and cache
                    # Get raw text output
                    raw_string = str(host_result.result)
                    result = CommandExecutionResult(
                        device=device,
                        command=command,
                        success=True,
                        output=raw_string,
                        duration_ms=duration_ms,
                    )
                    
                    # Log to audit trail
                    self.db.log_execution(
                        thread_id="main",
                        device=device,
                        command=command,
                        output=raw_string,
                        success=True,
                        duration_ms=duration_ms,
                    )
                    
                    # Cache result
                    if (
                        self.cache_config.get("enabled")
                        and self._is_command_cacheable(command)
                        and device in cache_keys
                    ):
                        self._save_to_cache(cache_keys[device], result)
                    
                    results.append(result)
            
            return results
        
        except Exception as e:
            # Fallback to sequential execution on error
            print(f"⚠️ Concurrent execution failed: {e}, falling back to sequential", file=sys.stderr)
            for device in devices_to_execute:
                result = self.execute(
                    device=device,
                    command=command,
                    timeout=timeout,
                    use_textfsm=use_textfsm,
                    cache_bypass=cache_bypass,
                )
                results.append(result)
            return results

    def execute_batch(
        self,
        request: BatchExecutionRequest,
    ) -> BatchExecutionResult:
        """Execute multiple commands on multiple devices with result splitting.
        
        Scenario 5: Batch multi-device multi-command processing.
        Automatically creates output directory structure and saves results to files.
        
        Args:
            request: Batch execution request with validation
        
        Returns:
            BatchExecutionResult with execution summary and file paths
        
        Example:
            >>> from pathlib import Path
            >>> request = BatchExecutionRequest(
            ...     devices=["R1", "R2"],
            ...     commands=["show version", "show interfaces"],
            ...     organize_by_device=True,
            ... )
            >>> result = executor.execute_batch(request)
            >>> print(result.summary)
            Batch batch_20260212_123456: 4/4 succeeded (100.0%) in 5234ms
        """
        import json
        import uuid
        from datetime import datetime
        
        # Generate batch ID
        batch_id = f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        start_time = datetime.now()
        
        # Determine output directory
        if request.output_dir is None:
            from config.paths import EXPORTS_DIR
            output_dir = EXPORTS_DIR / f"cli_batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        else:
            output_dir = request.output_dir
        
        # Create output directory
        output_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"\n📦 Starting batch execution: {batch_id}", file=sys.stderr)
        print(f"   Devices: {len(request.devices)}", file=sys.stderr)
        print(f"   Commands: {len(request.commands)}", file=sys.stderr)
        print(f"   Output: {output_dir}", file=sys.stderr)
        
        # Execute all commands on all devices
        results: list[DeviceCommandResult] = []
        
        for device in request.devices:
            # Create device subdirectory if needed
            if request.organize_by_device:
                device_dir = output_dir / device
                device_dir.mkdir(parents=True, exist_ok=True)
            else:
                device_dir = output_dir
            
            print(f"\n🔹 Device: {device}", file=sys.stderr)
            
            for cmd_idx, command in enumerate(request.commands, start=1):
                print(f"   [{cmd_idx}/{len(request.commands)}] Executing: {command}", file=sys.stderr)
                
                # Execute command (force use_textfsm=False for batch to get raw output)
                exec_result = self.execute(
                    device=device,
                    command=command,
                    timeout=request.timeout,
                    use_textfsm=False,  # Always raw output for batch operations
                    cache_bypass=request.cache_bypass,
                )
                
                # Generate filename: 001_show_version.txt
                cmd_slug = command.replace(" ", "_").replace("/", "_")[:50]
                filename = f"{cmd_idx:03d}_{cmd_slug}.txt"
                file_path = device_dir / filename
                
                # Determine content to save
                if exec_result.success and exec_result.output:
                    # Save raw output
                    file_content = exec_result.output
                else:
                    # Save error message
                    file_content = f"Error: {exec_result.error}" if exec_result.error else "Unknown error"
                
                # Save to file
                try:
                    file_path.write_text(file_content, encoding="utf-8")
                    print(f"      ✅ Saved: {file_path.relative_to(output_dir)}", file=sys.stderr)
                except Exception as e:
                    print(f"      ❌ Save failed: {e}", file=sys.stderr)
                    file_path = None
                
                # Create result record
                device_result = DeviceCommandResult(
                    device=device,
                    command=command,
                    command_index=cmd_idx,
                    success=exec_result.success,
                    output=exec_result.output,
                    error=exec_result.error,
                    structured=exec_result.structured,
                    file_path=file_path,
                    duration_ms=exec_result.duration_ms,
                )
                results.append(device_result)
        
        # Calculate statistics
        end_time = datetime.now()
        total_duration_ms = int((end_time - start_time).total_seconds() * 1000)
        total_executions = len(results)
        successful_executions = sum(1 for r in results if r.success)
        failed_executions = total_executions - successful_executions
        success_rate = (successful_executions / total_executions * 100) if total_executions > 0 else 0.0
        
        # Create batch result
        batch_result = BatchExecutionResult(
            batch_id=batch_id,
            start_time=start_time,
            end_time=end_time,
            total_duration_ms=total_duration_ms,
            devices=request.devices,
            commands=request.commands,
            results=results,
            output_dir=output_dir,
            total_executions=total_executions,
            successful_executions=successful_executions,
            failed_executions=failed_executions,
            success_rate=success_rate,
        )
        
        # Save metadata.json
        metadata_file = output_dir / "metadata.json"
        try:
            metadata = {
                "batch_id": batch_id,
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "total_duration_ms": total_duration_ms,
                "devices": request.devices,
                "commands": request.commands,
                "total_executions": total_executions,
                "successful_executions": successful_executions,
                "failed_executions": failed_executions,
                "success_rate": success_rate,
                "results": [
                    {
                        "device": r.device,
                        "command": r.command,
                        "command_index": r.command_index,
                        "success": r.success,
                        "structured": r.structured,
                        "file_path": str(r.file_path.relative_to(output_dir)) if r.file_path else None,
                        "duration_ms": r.duration_ms,
                    }
                    for r in results
                ],
            }
            metadata_file.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
            batch_result.metadata_file = metadata_file
            print(f"\n📊 Metadata saved: {metadata_file}", file=sys.stderr)
        except Exception as e:
            print(f"\n⚠️ Failed to save metadata: {e}", file=sys.stderr)
        
        # Print summary
        print(f"\n✅ {batch_result.summary}", file=sys.stderr)
        
        return batch_result

    def execute_with_parsing(
        self,
        device: str,
        command: str,
        timeout: int = 30,
        use_textfsm: bool | None = None,
    ) -> CommandExecutionResult:
        """Execute command with TextFSM structured parsing.

        Phase 4.2: Implements NTC template parsing with fallback to raw text.
        Tries to parse output with TextFSM, falls back to raw text on failure.

        Args:
            device: Device name or IP
            command: Command to execute
            timeout: Command timeout in seconds
            use_textfsm: Override TextFSM setting (None = use config)

        Returns:
            CommandExecutionResult with parsed output and token statistics

        Example:
            >>> result = executor.execute_with_parsing("R1", "show ip interface brief")
            >>> print(result.structured)  # True if parsed successfully
            >>> print(result.tokens_saved)  # Token savings count
        """
        # Determine if TextFSM should be used
        if use_textfsm is None:
            use_textfsm = settings.execution.use_textfsm

        # Try TextFSM parsing if enabled
        if use_textfsm:
            try:
                return self._execute_with_textfsm(
                    device=device,
                    command=command,
                    timeout=timeout,
                )
            except Exception as e:
                # Check if fallback is enabled
                if settings.execution.textfsm_fallback_to_raw:
                    print(f"TextFSM parsing failed: {e}, falling back to raw text")
                    return self.execute(device, command, timeout)
                else:
                    return CommandExecutionResult(
                        device=device,
                        command=command,
                        success=False,
                        error=f"TextFSM parsing failed and fallback disabled: {e}",
                        duration_ms=0,
                    )
        else:
            # TextFSM disabled: use regular execute
            return self.execute(device, command, timeout)

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count for text.

        Args:
            text: Text to estimate tokens for

        Returns:
            Estimated token count (rough approximation: 1 token ≈ 4 characters)
        """
        from .network_parser import estimate_tokens

        return estimate_tokens(text)

    def _execute_with_textfsm(
        self,
        device: str,
        command: str,
        timeout: int = 30,
    ) -> CommandExecutionResult:
        """Execute command with TextFSM structured parsing (internal method).

        Phase 4.2: Implements NTC template parsing with token statistics.
        This is the internal method called by execute_with_parsing when TextFSM is enabled.

        Args:
            device: Device name or IP
            command: Command to execute
            timeout: Command timeout in seconds

        Returns:
            CommandExecutionResult with parsed output and token statistics
        """
        from .network_parser import execute_with_textfsm

        nr = get_nornir(str(self.nornir_config))
        return execute_with_textfsm(
            nr=nr,
            device=device,
            command=command,
            timeout=timeout,
            db=self.db,
            blacklist_checker=self._is_blacklisted,
            platform_detector=self._detect_platform,
        )


# Global executor instance
_executor: NetworkExecutor | None = None


def get_executor() -> NetworkExecutor:
    """Get the global network executor instance.

    Returns:
        NetworkExecutor instance
    """
    global _executor

    if _executor is None:
        _executor = NetworkExecutor()

    return _executor
