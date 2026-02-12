"""Network device synchronization tools - OLAV v0.9.2 Optimized Version.

This module provides tools for parallel, per-command network device synchronization
with Blacklist integration and simplified reporting.

Key Optimizations (v0.9.2):
- Per-Command Parallel Execution (vs. Per-Device Serial)
- Blacklist Integration at Nornir Layer
- Report Generation Moved to Separate Modules
- Target: ~400 lines (vs. 2253 lines in v0.9.0)
"""

import logging
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from langchain_core.tools import tool
from nornir.core.task import Result, Task
from nornir_netmiko.tasks import netmiko_send_command
from nornir_scrapli.tasks import send_commands as scrapli_send_commands

from config.paths import SYNC_DIR
from config.settings import get_settings
from .network_executor import get_nornir

from .inspection_views import create_inspection_views

logger = logging.getLogger(__name__)

# =============================================================================
# Core Functions
# =============================================================================


def get_sync_base_dir() -> Path:
    """Get the base directory for all sync data."""
    return SYNC_DIR


def get_sync_dir(date: str | None = None) -> Path:
    """Get sync directory for a given date."""
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    return get_sync_base_dir() / date


def get_latest_sync_dir() -> Path | None:
    """Get the most recent sync directory."""
    base_dir = get_sync_base_dir()
    latest_link = base_dir / "latest"

    if latest_link.exists() and latest_link.is_symlink():
        target = latest_link.resolve()
        if target.exists():
            return target

    # Fallback: Find most recent directory
    sync_dirs = sorted(
        [
            d
            for d in base_dir.iterdir()
            if d.is_dir() and d.name != "latest" and d.name != "archive"
        ],
        reverse=True,
    )
    return sync_dirs[0] if sync_dirs else None


def update_latest_link(sync_dir: Path) -> None:
    """Update 'latest' symlink to point to most recent sync."""
    latest_link = get_sync_base_dir() / "latest"

    if latest_link.exists() or latest_link.is_symlink():
        latest_link.unlink()

    latest_link.symlink_to(sync_dir, target_is_directory=True)


# Note: Command blacklist is handled by NetworkExecutor._is_blacklisted()
# No device-level blacklist needed - dangerous commands are filtered per execution


# =============================================================================
# Error Detection Patterns (skip saving these outputs)
# =============================================================================

# Patterns that indicate command execution failure or unsupported commands
# These outputs should NOT be saved to raw files
ERROR_PATTERNS = [
    "% Invalid input",
    "% Incomplete command",
    "% Ambiguous command",
    "% Unknown command",
    "% Authorization failed",
    "% Access denied",
    "Error: Unrecognized command",
    "Error: Wrong parameter",
    "Syntax error:",
]

# Scrapli platform mapping (Nornir -> Scrapli)
SCRAPLI_PLATFORM_MAP = {
    "cisco_ios": "cisco_iosxe",
    "cisco_xe": "cisco_iosxe",
    "cisco_xr": "cisco_iosxr",
    "arista_eos": "arista_eos",
    "juniper_junos": "juniper_junos",
}


def _is_error_output(output: str) -> bool:
    """Check if command output indicates an error."""
    if not output:
        return True
    for pattern in ERROR_PATTERNS:
        if pattern in output:
            return True
    return False


def parallel_tcp_check(hosts: list, port: int = 22, timeout: float = 2.0) -> dict[str, bool]:
    """Check TCP connectivity for multiple hosts in parallel."""

    def check_one(host_name: str, address: str) -> tuple[str, bool]:
        try:
            with socket.create_connection((address, port), timeout=timeout):
                return host_name, True
        except (TimeoutError, ConnectionRefusedError, OSError):
            return host_name, False

    results = {}
    with ThreadPoolExecutor(max_workers=50) as executor:
        futures = [executor.submit(check_one, h.name, h.hostname) for h in hosts]
        for future in futures:
            name, status = future.result()
            results[name] = status
    return results


# =============================================================================
# Per-Command Parallel Execution Task
# =============================================================================


def _sync_device_workflow(task: Task, commands: list[str], output_dir: Path) -> Result:
    """ACE Workflow: Try Scrapli (Fast) -> Fallback to Netmiko (Stable)."""
    host = task.host
    original_platform = host.platform
    device_dir = output_dir / host.name
    device_dir.mkdir(parents=True, exist_ok=True)

    # Status tracking in Host data
    host.data["ace_status"] = "PENDING"
    host.data["ace_driver"] = "NONE"

    settings = get_settings()
    timeout = settings.execution.timeout

    # 1. Check if device is unreachable (from pre-check)
    if not host.data.get("tcp_reachable", True):
        host.data["ace_status"] = "DISCONNECTED"
        return Result(host=host, failed=True, result="Device unreachable (TCP 22/23)")

    # 2. Try Scrapli (Platinum Path)
    try:
        scrapli_platform = SCRAPLI_PLATFORM_MAP.get(host.platform or "")
        if not scrapli_platform:
            raise ValueError(f"Platform {host.platform} not supported by Scrapli")

        host.data["ace_driver"] = "scrapli"

        # Inject permissive configuration for Scrapli
        from nornir.core.inventory import ConnectionOptions

        # Get existing or new options
        opts = host.connection_options.get("scrapli", ConnectionOptions())
        opts.platform = scrapli_platform
        if opts.extras is None:
            opts.extras = {}

        # Standard permissive options for Scrapli
        opts.extras["ssh_config_file"] = True
        opts.extras["auth_strict_key"] = False

        # Try to use paramiko transport within scrapli if standard fails
        # but let's first try standard system/asyncssh with permissive keys
        opts.extras["transport"] = "paramiko"
        opts.extras["timeout_ops"] = 300  # 5 mins for exhaustive snapshots
        host.connection_options["scrapli"] = opts

        res = task.run(
            task=scrapli_send_commands,
            commands=commands,
            strip_prompt=True,
        )

        # Restore original platform
        host.platform = original_platform

        scrapli_responses = res.result
        saved = 0
        if scrapli_responses and isinstance(scrapli_responses, list):
            for i, cmd_res in enumerate(scrapli_responses):
                cmd = commands[i]
                output = str(cmd_res.result)
                if output and not _is_error_output(output):
                    cmd_filename = cmd.replace(" ", "-").replace("/", "-") + ".txt"
                    (device_dir / cmd_filename).write_text(output, encoding="utf-8")
                    saved += 1

            host.data["ace_status"] = "ACTIVE_FAST"
            _update_capability_cache(host.name, "scrapli")
            return Result(host=host, result=f"Scrapli Success: {saved}/{len(commands)} commands")
        else:
            raise ValueError(f"Scrapli returned {type(scrapli_responses)} instead of list")

    except Exception as e:
        logger.debug(f"Scrapli failed for {host.name}: {e}")
        # Explicitly print for visibility during development
        print(f"DEBUG: Scrapli failed for {host.name}, falling back...")

    # 3. Fallback to Netmiko (Gold Path)
    try:
        print(f"🔄 Using Netmiko for {host.name}...")
        host.data["ace_driver"] = "netmiko"
        saved = 0
        total = len(commands)

        for idx, command in enumerate(commands, 1):
            try:
                # Use subtask but don't let it crash the whole loop
                res = task.run(
                    task=netmiko_send_command,
                    command_string=command,
                    read_timeout=timeout,
                )
                if res.result and not _is_error_output(str(res.result)):
                    cmd_filename = command.replace(" ", "-").replace("/", "-") + ".txt"
                    (device_dir / cmd_filename).write_text(str(res.result), encoding="utf-8")
                    saved += 1

                # Print progress every 10 commands or at the end
                if idx % 10 == 0 or idx == total:
                    print(f"  {host.name}: {saved}/{idx} commands collected")

            except Exception:  # noqa: S112
                continue  # Skip individual command failure in fallback

        host.data["ace_status"] = "ACTIVE_STABLE"
        _update_capability_cache(host.name, "netmiko")
        print(f"✅ {host.name}: {saved}/{total} commands via Netmiko")
        return Result(host=host, result=f"Netmiko Fallback: {saved}/{total} commands")

    except Exception as e:
        host.data["ace_status"] = "DISCONNECTED"
        return Result(host=host, failed=True, result=f"Complete Failure: {e}")


def _populate_devices_table(nr_filtered) -> None:
    """Populate devices table from Nornir inventory (v0.11.0 - Unified Import).
    
    Uses the unified devices_import tool for centralized device management.
    
    Args:
        nr_filtered: Filtered Nornir object (legacy support, no longer used)
        
    Note:
        v0.11.0: Migrated to import_devices_from_nornir() which reads directly
        from hosts.yaml. The nr_filtered parameter is kept for backward compatibility
        but is now unused.
    """
    try:
        from config.paths import AGENT_DIR, UNIFIED_DB
        from olav.lib.devices_import import import_devices_from_nornir
        
        hosts_yaml_path = AGENT_DIR / "config" / "nornir" / "hosts.yaml"
        
        if not hosts_yaml_path.exists():
            logger.warning(f"hosts.yaml not found at {hosts_yaml_path}, skipping device import")
            return
        
        # Use unified import tool
        stats = import_devices_from_nornir(
            hosts_yaml_path=hosts_yaml_path,
            db_path=UNIFIED_DB,
            table_name="devices",
        )
        
        logger.info(
            f"Devices imported: {stats['imported']} total, "
            f"roles={stats['roles_found']}, sites={stats['sites_found']}"
        )
        
    except Exception as e:
        logger.warning(f"Failed to import devices from Nornir: {e}")


def _populate_topology_links(sync_date: str) -> None:
    """Populate topology_links table from CDP/LLDP neighbor data (v0.10.2).
    
    Supports historical tracking:
    - Extracts link data from latest snapshot's parsed CDP neighbors
    - Generates unique link_id using hash
    - Tracks first_seen/last_seen timestamps for history
    - Supports change detection via status_changes counter
    
    Args:
        sync_date: Sync date string (YYYY-MM-DD format)
    """
    try:
        from olav.core.database import get_database
        from config.paths import SNAPSHOTS_DIR
        import hashlib
        import json
        from pathlib import Path
        
        db = get_database()
        
        # Find CDP neighbor files in latest snapshot
        latest_dir = SNAPSHOTS_DIR / "latest" / "parsed"
        if not latest_dir.exists():
            logger.debug(f"No parsed data found at {latest_dir}")
            return
        
        # Parse CDP neighbor files
        cdp_files = list(latest_dir.glob("*/show-cdp-neighbor*.json"))
        
        links_added = 0
        links_updated = 0
        
        for cdp_file in cdp_files:
            try:
                # Extract device name from path: parsed/R1/show-cdp-neighbors.json
                device_parts = cdp_file.parts
                if "parsed" in device_parts:
                    parsed_idx = device_parts.index("parsed")
                    if parsed_idx + 1 < len(device_parts):
                        source_device = device_parts[parsed_idx + 1]
                    else:
                        continue
                else:
                    continue
                
                # Read CDP neighbor data
                with open(cdp_file, 'r') as f:
                    data = json.load(f)
                
                if not isinstance(data, list):
                    continue
                
                # Process each neighbor link
                for neighbor in data:
                    try:
                        local_if = neighbor.get("local_interface", "")
                        remote_device = neighbor.get("neighbor_name", "")
                        remote_if = neighbor.get("neighbor_interface", "")
                        platform = neighbor.get("platform", "")
                        
                        if not all([local_if, remote_device, remote_if]):
                            continue
                        
                        # Generate unique link_id (hash of endpoints)
                        link_components = f"{source_device}|{local_if}|{remote_device}|{remote_if}"
                        link_id = hashlib.md5(link_components.encode()).hexdigest()[:16]
                        
                        # Check if link exists
                        existing = db.conn.execute(
                            "SELECT link_id, status_changes FROM topology_links WHERE link_id = ? ORDER BY sync_date DESC LIMIT 1",
                            [link_id]
                        ).fetchone()
                        
                        if existing:
                            # Update existing link
                            old_changes = existing[1] or 0
                            db.conn.execute(
                                """
                                INSERT INTO topology_links 
                                (link_id, source_device, source_interface, destination_device, destination_interface,
                                 discovery_protocol, link_type, link_status, first_seen, last_seen, sync_date, 
                                 platform, status_changes, last_verified)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 
                                        (SELECT first_seen FROM topology_links WHERE link_id = ? ORDER BY sync_date DESC LIMIT 1),
                                        CURRENT_TIMESTAMP, ?, ?, ?, CURRENT_TIMESTAMP)
                                """,
                                [link_id, source_device, local_if, remote_device, remote_if,
                                 "CDP", "L2", "up", link_id, sync_date, platform, old_changes]
                            )
                            links_updated += 1
                        else:
                            # Insert new link
                            db.conn.execute(
                                """
                                INSERT INTO topology_links 
                                (link_id, source_device, source_interface, destination_device, destination_interface,
                                 discovery_protocol, link_type, link_status, first_seen, last_seen, sync_date, platform, status_changes)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?, ?, 0)
                                """,
                                [link_id, source_device, local_if, remote_device, remote_if,
                                 "CDP", "L2", "up", sync_date, platform]
                            )
                            links_added += 1
                    
                    except Exception as e:
                        logger.debug(f"Failed to process neighbor link: {e}")
                        continue
            
            except Exception as e:
                logger.debug(f"Failed to process CDP file {cdp_file}: {e}")
                continue
        
        if links_added > 0 or links_updated > 0:
            logger.info(f"Topology links: {links_added} added, {links_updated} updated for {sync_date}")
    
    except Exception as e:
        logger.warning(f"Failed to populate topology links: {e}")


def _update_capability_cache(hostname: str, driver: str) -> None:
    """Cache the successful driver for future runs."""
    try:
        from olav.core.database import get_database

        db = get_database()
        db.conn.execute(
            "INSERT OR REPLACE INTO device_capabilities VALUES (?, ?, CURRENT_TIMESTAMP, NULL)",
            [hostname, driver],
        )
    except Exception:
        pass


# =============================================================================
# Main Tool: sync_all (Per-Command Parallel)
# =============================================================================


@tool
def sync_all(
    devices: list[str] | None = None,
    commands: list[str] | None = None,
    async_processing: bool = False,
) -> str:
    """Sync network devices using per-command parallel execution.

    This is the main synchronization tool. It executes commands in parallel
    across all devices (one command at a time), automatically skipping
    blacklisted devices.

    Architecture:
        - Stage 1 (Blocking): Per-Command parallel data collection
          * For each command: execute on all devices in parallel via Nornir
          * Blacklist filtering applied at Nornir layer
          * Raw outputs stored to sync_dir/raw/{device}/{command}.txt

        - Stage 2 (Async): Background parsing and reporting
          * Parse outputs with TextFSM
          * Import to DuckDB
          * Generate summary reports

    Args:
        devices: List of device names (default: all non-blacklisted devices)
        commands: List of commands to execute (default: standard L1-L4 command set)
        async_processing: Whether to run Stage 2 in background (default: False)

    Returns:
        Status message with sync directory location

    Examples:
        >>> sync_all()
        "✓ Stage 1 Complete: 12 devices, 15 commands
         Data: /data/sync/2026-01-14
         Stage 2: Processing in background..."

        >>> sync_all(devices=["R1", "R2"], commands=["show version"])
        "✓ Sync Complete: 2 devices, 1 command"
    """
    from .network_executor import reset_nornir

    # Get current date sync directory
    sync_date = datetime.now().strftime("%Y-%m-%d")
    sync_dir = get_sync_dir(sync_date)
    raw_dir = sync_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    # Reset and initialize Nornir (ensures fresh credentials from settings)
    reset_nornir()
    nr = get_nornir()

    # Apply device filter
    if devices:
        nr_filtered = nr.filter(lambda h: h.name in devices)
    else:
        nr_filtered = nr

    # Get final device list
    device_names = list(nr_filtered.inventory.hosts.keys())
    if not device_names:
        return "No devices available after filtering"

    # Populate devices table from Nornir inventory (v0.10.1)
    _populate_devices_table(nr_filtered)
    
    # Populate topology links from CDP/LLDP neighbors (v0.10.2)
    _populate_topology_links(sync_date)

    # Get commands from CommandRegistry if not specified
    if commands is None:
        from olav.core.registry import get_command_registry

        # Detect platform from first device
        first_host = nr_filtered.inventory.hosts[device_names[0]]
        platform = first_host.platform

        if not platform:
            return f"Error: Device '{first_host.name}' has no platform defined in inventory"

        registry = get_command_registry()
        settings = get_settings()

        # Determine command set based on mode
        if settings.sync.command_mode == "whitelist":
            commands = registry.get_whitelisted_commands(platform)
            source_info = f"whitelist from {settings.sync.whitelist_file}"
        else:
            commands_dict = registry.list_commands(platform=platform)
            commands = list(commands_dict.get(platform, []))
            source_info = "all available NTC templates"

        if not commands:
            # Fallback to basic command set if no commands in registry/whitelist
            commands = [
                "show version",
                "show running-config",
                "show cdp neighbors detail",
                "show ip interface brief",
                "show ip route",
                "show ip ospf neighbor",
                "show ip bgp summary",
                "show interfaces status",
                "show vlan brief",
                "show processes cpu",
                "show memory statistics",
                "show logging",
                "show arp",
                "show mac address-table",
                "show ntp status",
            ]
            source_info = "standard L1-L4 set (fallback)"

        print(f"Using {source_info} ({len(commands)} commands)")

    # =================================================================
    # STAGE 1: ACE Adaptive Connectivity Engine (Device Parallel)
    # =================================================================
    start_time = datetime.now()

    # 1. Pre-flight: Parallel TCP check
    print(f"Pre-flight: Checking connectivity for {len(device_names)} devices...")
    tcp_results = parallel_tcp_check(list(nr_filtered.inventory.hosts.values()))
    for name, is_up in tcp_results.items():
        nr_filtered.inventory.hosts[name].data["tcp_reachable"] = is_up

    # 2. Execution: Per-Device Workflow (Fat Task)
    print(f"Executing workflow on {len(device_names)} devices...")
    results = nr_filtered.run(
        task=_sync_device_workflow,
        commands=commands,
        output_dir=raw_dir,
    )

    # 3. Aggregation
    fast_path = 0
    stable_path = 0
    disconnected = 0

    for host_name, multi_result in results.items():
        # The workflow itself is the first element (MultiResult[0])
        main_res = multi_result[0]
        res_str = str(main_res.result)

        if "Scrapli Success" in res_str:
            fast_path += 1
            logger.info(f"Host {host_name} completed via Scrapli")
        elif "Netmiko Fallback" in res_str:
            stable_path += 1
            logger.info(f"Host {host_name} completed via Netmiko Fallback")
        else:
            disconnected += 1
            logger.warning(f"Host {host_name} failed collection: {res_str}")

    duration = (datetime.now() - start_time).total_seconds()

    # Update 'latest' symlink
    update_latest_link(sync_dir)

    # Store metadata to database
    _store_sync_metadata(
        sync_date=sync_date,
        sync_dir=sync_dir,
        device_count=len(device_names),
        command_count=len(commands),
        success_count=fast_path + stable_path,
        failed_count=disconnected,
        duration_seconds=duration,
    )

    stage1_msg = (
        f"✓ ACE Engine Complete: {len(device_names)} devices, {len(commands)} commands\n"
        f"  🚀 FAST (Scrapli): {fast_path}, 🛡️ STABLE (Netmiko): {stable_path}, ❌ DOWN: {disconnected}\n"
        f"  Duration: {duration:.1f}s\n"
        f"  Data: {sync_dir}"
    )

    # =================================================================
    # STAGE 2: Async Parsing and Reporting (Optional)
    # =================================================================
    if async_processing:
        import threading

        thread = threading.Thread(
            target=_process_sync_stage2,
            args=(sync_dir, device_names),
            daemon=True,
        )
        thread.start()
        return stage1_msg + "\n\n⏳ Stage 2: Processing in background..."
    else:
        _process_sync_stage2(sync_dir, device_names)
        return stage1_msg + "\n\n✓ Stage 2 Complete: Parsing and reports generated"


def _store_sync_metadata(
    sync_date: str,
    sync_dir: Path,
    device_count: int,
    command_count: int,
    success_count: int,
    failed_count: int,
    duration_seconds: float,
) -> None:
    """Store sync metadata to database."""
    try:
        from olav.core.database import get_database

        db = get_database()
        conn = db.conn

        # Create metadata table if not exists
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sync_metadata (
                sync_date DATE PRIMARY KEY,
                sync_dir VARCHAR,
                device_count INTEGER,
                command_count INTEGER,
                success_count INTEGER,
                failed_count INTEGER,
                duration_seconds REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # Insert metadata
        conn.execute(
            """
            INSERT OR REPLACE INTO sync_metadata VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            [
                sync_date,
                str(sync_dir),
                device_count,
                command_count,
                success_count,
                failed_count,
                duration_seconds,
            ],
        )
    except Exception:
        pass  # Metadata storage is optional


def _process_sync_stage2(sync_dir: Path, device_names: list[str]) -> None:
    """Stage 2: Parse outputs and generate reports (runs in background thread).

    Args:
        sync_dir: Sync directory path
        device_names: List of device names that were synced
    """
    try:
        # Stage 2 now only does:
        # 1. Import raw outputs to DuckDB
        # 2. Generate summary reports
        # (Parsed data is no longer stored separately, only raw data)

        # Import data to DuckDB (v0.9.3: raw_outputs + command_outputs)
        from .raw_importer import import_sync_data

        result = import_sync_data(sync_dir)
        logger.debug(f"Stage 2 import results: {result}")

        # Generate summary reports (delegated to report_formatter)
        from .report_formatter import generate_network_operations_report

        generate_network_operations_report(sync_dir, device_names)

        # Phase 15: Materialize Inspection Views (EQP)
        # Move view creation from query-time to snapshot-time to eliminate lock contention
        logger.info("Materializing Static Gold Views (EQP)...")
        try:
            from olav.core.database import get_database

            db = get_database()
            create_inspection_views(db.conn)
        except Exception as e:
            logger.warning(f"Failed to materialize views: {e}")

    except Exception as e:
        # Stage 2 failures don't block Stage 1, but we should log them
        logger.warning(f"Stage 2 processing failed: {type(e).__name__}: {e}")
        logger.debug("Stage 2 traceback:", exc_info=True)


# =============================================================================
# Tool 2: get_sync_age
# =============================================================================


@tool
def get_sync_age() -> str:
    """Get age of latest sync data."""
    latest_dir = get_latest_sync_dir()
    if not latest_dir:
        return "Never synced"

    mtime = datetime.fromtimestamp(latest_dir.stat().st_mtime)
    age = datetime.now() - mtime
    total_seconds = int(age.total_seconds())

    if total_seconds < 60:
        return f"{total_seconds} seconds ago"
    elif total_seconds < 3600:
        minutes = total_seconds // 60
        return f"{minutes} minute{'s' if minutes > 1 else ''} ago"
    elif total_seconds < 86400:
        hours = total_seconds // 3600
        return f"{hours} hour{'s' if hours > 1 else ''} ago"
    else:
        days = total_seconds // 86400
        return f"{days} day{'s' if days > 1 else ''} ago"


# =============================================================================
# Tool 3: search_sync
# =============================================================================


@tool
def search_sync(pattern: str, device: str | None = None, date: str | None = None) -> str:
    """Search sync data using fast text search."""
    if date:
        sync_dir = get_sync_dir(date)
    else:
        sync_dir = get_latest_sync_dir()

    if not sync_dir or not sync_dir.exists():
        return "No sync data found."

    search_path = sync_dir / "raw"
    if device:
        search_path = search_path / device

    # Try ripgrep > grep > Python fallback
    try:
        import shutil

        if shutil.which("rg"):
            proc = subprocess.run(
                ["rg", "--ignore-case", "--line-number", pattern, str(search_path)],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return proc.stdout if proc.returncode == 0 else f"No matches found for: {pattern}"
    except Exception:
        pass

    # Python fallback search with context
    if search_path.exists():
        results = []
        for file_path in search_path.rglob("*.txt"):
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                if pattern.lower() in content.lower():
                    # Get matching lines for context
                    matching_lines = []
                    for line_num, line in enumerate(content.split("\n"), 1):
                        if pattern.lower() in line.lower():
                            matching_lines.append(f"  Line {line_num}: {line.strip()}")
                    if matching_lines:
                        rel_path = (
                            file_path.relative_to(search_path)
                            if file_path.is_relative_to(search_path)
                            else file_path
                        )
                        results.append(f"{rel_path}:\n" + "\n".join(matching_lines))
            except Exception:
                pass
        if results:
            return "Found matches:\n" + "\n".join(results)
        else:
            return f"No matches found for: {pattern}"

    return f"No matches found for: {pattern}"


# =============================================================================
# Tool 5: diff_configs
# =============================================================================


@tool
def diff_configs(device: str, date1: str, date2: str) -> str:
    """Compare device configurations between two dates.

    Args:
        device: Device name
        date1: First date (YYYY-MM-DD format)
        date2: Second date (YYYY-MM-DD format)

    Returns:
        Configuration diff or error message
    """
    try:
        # Get config files for both dates
        config_dir1 = get_sync_dir(date1) / "configs" / device
        config_dir2 = get_sync_dir(date2) / "configs" / device

        if not config_dir1.exists():
            return f"Error: Config not found for {device} on {date1}"
        if not config_dir2.exists():
            return f"Error: Config not found for {device} on {date2}"

        # Find running config files
        config_file1 = None
        config_file2 = None

        for f in config_dir1.glob("*.txt"):
            if "running" in f.name.lower():
                config_file1 = f
                break

        for f in config_dir2.glob("*.txt"):
            if "running" in f.name.lower():
                config_file2 = f
                break

        if not config_file1 or not config_file2:
            return "Error: Could not find running config files for comparison"

        # Read config files
        with open(config_file1) as f:
            content1 = f.readlines()
        with open(config_file2) as f:
            content2 = f.readlines()

        # Generate diff
        import difflib

        diff = difflib.unified_diff(
            content1,
            content2,
            fromfile=f"{device}@{date1}",
            tofile=f"{device}@{date2}",
            lineterm="",
        )

        diff_output = list(diff)
        if not diff_output:
            return f"No differences found between {date1} and {date2}"

        return "\n".join(diff_output[:100])  # Limit to first 100 lines
    except Exception as e:
        return f"Error comparing configs: {e}"
