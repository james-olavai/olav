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
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from langchain_core.tools import tool
from nornir import InitNornir
from nornir.core import Nornir
from nornir.core.task import Result, Task
from nornir_netmiko.tasks import netmiko_send_command

try:
    from nornir_scrapli.tasks import send_commands as scrapli_send_commands
    _HAS_SCRAPLI = True
except ImportError:
    scrapli_send_commands = None
    _HAS_SCRAPLI = False

# ---------------------------------------------------------------------------
# Self-contained path + settings resolution
# Falls back to framework imports when available; works standalone otherwise.
# ---------------------------------------------------------------------------

def _find_project_root() -> Path:
    """Walk up from this file until we find pyproject.toml (the project anchor)."""
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path(__file__).resolve().parents[5]  # fallback: tools/sync/config/workspace/.olav/project

_PROJECT_ROOT = _find_project_root()                         # /home/yhvh/Olav
_OLAV_DIR    = _PROJECT_ROOT / ".olav"                       # .olav/
_SYNC_DIR    = _PROJECT_ROOT / "exports" / "snapshots"      # exports/snapshots/

# Try framework imports; use simple fallbacks if running standalone.
try:
    from olav.core.config import SYNC_DIR as _FW_SYNC_DIR  # noqa: F401
    _SYNC_DIR = _FW_SYNC_DIR
except ImportError:
    pass  # _SYNC_DIR already set above

try:
    from olav.core.config import get_settings as _fw_get_settings
    def get_settings() -> SimpleNamespace:  # type: ignore[misc]
        return _fw_get_settings()
except ImportError:

    def get_settings() -> SimpleNamespace:  # type: ignore[misc]  # noqa: E302
        """Minimal settings fallback used when framework is not installed."""
        exec_ns = SimpleNamespace(
            timeout=60,
            global_delay_factor=1.0,
            max_loops=150,
            scrapli_timeout_ops=30,
        )
        return SimpleNamespace(
            agent_dir=_OLAV_DIR,
            device_username=None,
            device_password=None,
            execution=exec_ns,
        )

try:
    from inspection_views import create_inspection_views
except ImportError:
    create_inspection_views = None

logger = logging.getLogger(__name__)

# =============================================================================
# Nornir Singleton
# =============================================================================

_nornir_instance: Nornir | None = None


def get_nornir() -> Nornir:
    """Get global Nornir instance (singleton — initialised once per process)."""
    global _nornir_instance
    if _nornir_instance is None:
        settings = get_settings()
        config_file = Path(settings.agent_dir) / "config" / "nornir" / "config.yaml"
        _nornir_instance = InitNornir(config_file=str(config_file.resolve()))
    return _nornir_instance


def reset_nornir() -> None:
    """Reset the Nornir singleton so next get_nornir() re-reads credentials."""
    global _nornir_instance
    _nornir_instance = None


# =============================================================================


def get_sync_base_dir() -> Path:
    """Get the base directory for all sync data."""
    return _SYNC_DIR


def get_sync_dir(date: str | None = None) -> Path:
    """Get sync directory for a given date.
    
    Args:
        date: Date string. If None, uses minute-level timestamp (YYYY-MM-DD_HHMM)
              to support multiple snapshots per day.
    """
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d_%H%M")
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

# =============================================================================
# Intent-Driven Parse Quality Detection (Issue #3 Fix)
# =============================================================================

# Signature keywords for each category.
# If raw output contains ANY of these words but JSON is empty → HIGH severity gap.
CATEGORY_SIGNATURES: dict[str, list[str]] = {
    "routing": ["neighbor", "peer", "via", "gateway", "prefix", "network", "metric", "route"],
    "bgp": ["neighbor", "peer", "established", "active", "idle", "prefix", "as-path", "bgp"],
    "ospf": ["neighbor", "state", "full", "loading", "dr", "bdr", "area", "ospf"],
    "interfaces": ["up", "down", "protocol", "bandwidth", "mtu", "encapsulation", "line protocol"],
    "neighbors": ["device id", "capability", "platform", "port id", "interface"],
    "switching": ["vlan", "trunk", "access", "spanning", "mac", "stp"],
    "system": ["version", "uptime", "cpu", "memory", "flash", "nvram"],
    "environment": ["temperature", "fan", "power", "status"],
    "arp": ["internet", "arpa", "incomplete"],
    "mac": ["vlan", "dynamic", "static", "secure"],
}

# Maps command keywords → category (for determining expected signatures)
_CMD_CATEGORY_MAP: list[tuple[str, str]] = [
    ("show ip bgp", "bgp"),
    ("show bgp", "bgp"),
    ("show ip ospf neighbor", "ospf"),
    ("show ospf neighbor", "ospf"),
    ("show ip route", "routing"),
    ("show route", "routing"),
    ("show interfaces", "interfaces"),
    ("show ip interface", "interfaces"),
    ("show cdp neighbor", "neighbors"),
    ("show lldp neighbor", "neighbors"),
    ("show mac", "switching"),
    ("show spanning", "switching"),
    ("show vlan", "switching"),
    ("show arp", "arp"),
    ("show version", "system"),
    ("show processes", "system"),
    ("show environment", "environment"),
]


def _infer_category_from_command(command: str) -> str:
    """Infer the data category from a CLI command string.

    Returns a key matching CATEGORY_SIGNATURES, or 'general' if unknown.
    """
    cmd_lower = command.lower()
    for cmd_prefix, category in _CMD_CATEGORY_MAP:
        if cmd_prefix in cmd_lower:
            return category
    return "general"


def _detect_parse_quality_gap(
    raw_text: str,
    command: str,
    parsed_data: str,
) -> dict | None:
    """Detect whether parsed_data represents a quality gap.

    Returns a dict with severity/reason if a gap is detected, else None.

    Detection algorithm (Intent-driven Signature Matching):
    1. If JSON has ≥1 real rows → no gap.
    2. Infer category from command.
    3. Check if raw_text contains any category signature keywords:
       - YES → HIGH severity (100% gap: keywords present but nothing parsed)
       - NO, but raw_text is large (>300B) → MEDIUM severity (possible gap)
    """
    import json as _json

    # Check if parsed_data is genuinely populated
    try:
        parsed = _json.loads(parsed_data) if isinstance(parsed_data, str) else parsed_data
        if isinstance(parsed, list) and len(parsed) > 0:
            return None  # Good data — no gap
        if isinstance(parsed, dict) and parsed and "raw" not in parsed:
            return None  # Dict form with real fields
    except Exception:
        pass

    # JSON is empty ([] or {}) — check signatures
    txt_lower = raw_text.lower()
    size = len(raw_text.encode("utf-8", errors="replace"))

    category = _infer_category_from_command(command)
    signatures = CATEGORY_SIGNATURES.get(category, [])

    has_signature = any(sig in txt_lower for sig in signatures) if signatures else False

    if has_signature:
        matched = [sig for sig in signatures if sig in txt_lower][:3]
        return {
            "severity": "high",
            "category": category,
            "matched_keywords": matched,
            "reason": f"Keywords found ({matched}) but JSON empty — 100% parse gap",
            "size": size,
        }
    elif size > 300:
        return {
            "severity": "medium",
            "category": category,
            "matched_keywords": [],
            "reason": f"Large output ({size}B) but JSON empty — possible parse gap",
            "size": size,
        }

    return None


def _load_command_strategy(platform: str) -> dict:
    """Load command intents and platform metadata for a specific platform."""
    import yaml
    config_path = _PROJECT_ROOT / ".olav" / "workspace" / "config" / "sync" / "config" / "command_strategy.yaml"
    if not config_path.exists():
        return {}
    
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            platforms = data.get("platforms", {})
            return platforms.get(platform, {})
    except Exception:
        return {}


def _get_scrapli_platform(platform: str) -> str | None:
    """Map Nornir platform to Scrapli platform using strategy."""
    strategy = _load_command_strategy(platform)
    return strategy.get("scrapli_platform")


def _get_intent_commands(platform: str, intent: str) -> list[str]:
    """Get platform-specific commands for a standard intent."""
    strategy = _load_command_strategy(platform)
    return strategy.get("intents", {}).get(intent, [])


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
    global_delay_factor = settings.execution.global_delay_factor
    max_loops = settings.execution.max_loops
    scrapli_timeout_ops = settings.execution.scrapli_timeout_ops

    # 1. Check if device is unreachable (from pre-check)
    if not host.data.get("tcp_reachable", True):
        host.data["ace_status"] = "DISCONNECTED"
        return Result(host=host, failed=True, result="Device unreachable (TCP 22/23)")

    # 2. Try Scrapli (Platinum Path)
    try:
        scrapli_platform = _get_scrapli_platform(host.platform or "")
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
        opts.extras["timeout_ops"] = scrapli_timeout_ops  # Use config value
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
                    cmd_filename = cmd.replace(" ", "_").replace("/", "_").replace("-", "_") + ".txt"
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
                    # Use config value for slow devices (netmiko 4.x: delay_factor)
                    delay_factor=global_delay_factor,
                    max_loops=max_loops,  # Use config value for long outputs
                )
                if res.result and not _is_error_output(str(res.result)):
                    cmd_filename = command.replace(" ", "_").replace("/", "_").replace("-", "_") + ".txt"
                    (device_dir / cmd_filename).write_text(str(res.result), encoding="utf-8")
                    saved += 1
                else:
                    print(f"DEBUG: {host.name}: Command '{command}' failed or produced error output: {str(res.result)[:100]}")

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


def _populate_devices_table(nr_filtered: Nornir) -> None:
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
        import sys as _sys

        from olav.core.config import AGENT_DIR, MAIN_DB_PATH
        _tools_dir = str(Path(__file__).parent)
        if _tools_dir not in _sys.path:
            _sys.path.insert(0, _tools_dir)
        from sync_inventory import _import_devices_from_nornir

        hosts_yaml_path = AGENT_DIR / "config" / "nornir" / "hosts.yaml"

        if not hosts_yaml_path.exists():
            logger.warning(f"hosts.yaml not found at {hosts_yaml_path}, skipping device import")
            return

        # Use inlined import helper (from sync_inventory)
        stats = _import_devices_from_nornir(
            hosts_yaml_path=hosts_yaml_path,
            db_path=MAIN_DB_PATH,
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
        import hashlib
        import json

        from olav.core.config import SNAPSHOTS_DIR
        from olav.core.database import get_database

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
                with open(cdp_file) as f:
                    data = json.load(f)

                if not isinstance(data, list):
                    continue

                # Process each neighbor link
                from olav.core.value_normalizer import get_normalizer as _get_norm
                _norm = _get_norm()
                for neighbor in data:
                    try:
                        local_if = _norm.interface_name(neighbor.get("local_interface", ""))
                        remote_device = neighbor.get("neighbor_name", "")
                        remote_if = _norm.interface_name(neighbor.get("neighbor_interface", ""))
                        platform = neighbor.get("platform", "")

                        if not all([local_if, remote_device, remote_if]):
                            continue

                        # Generate unique link_id (hash of endpoints)
                        link_components = f"{source_device}|{local_if}|{remote_device}|{remote_if}"
                        link_id = hashlib.md5(link_components.encode()).hexdigest()[:16]

                        # Check if link exists
                        existing = db.conn.execute(
                            "SELECT link_id, status_changes FROM topology_links "
                            "WHERE link_id = ? ORDER BY last_seen DESC LIMIT 1",
                            [link_id]
                        ).fetchone()

                        if existing:
                            # Update existing link
                            old_changes = existing[1] or 0
                            db.conn.execute(
                                """
                                INSERT INTO topology_links
                                (link_id, source_device, source_interface,
                                 destination_device, destination_interface,
                                 discovery_protocol, link_type, link_status,
                                 first_seen, last_seen, snapshot_id,
                                 platform, status_changes, last_verified)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?,
                                        (SELECT first_seen FROM topology_links
                                         WHERE link_id = ?
                                         ORDER BY last_seen DESC LIMIT 1),
                                        CURRENT_TIMESTAMP, ?, ?, ?, CURRENT_TIMESTAMP)
                                """,
                                [link_id, source_device, local_if, remote_device,
                                 remote_if, "CDP", "L2", "up", link_id, sync_date,
                                 platform, old_changes]
                            )
                            links_updated += 1
                        else:
                            # Insert new link
                            db.conn.execute(
                                """
                                INSERT INTO topology_links
                                (link_id, source_device, source_interface,
                                 destination_device, destination_interface,
                                 discovery_protocol, link_type, link_status,
                                 first_seen, last_seen, snapshot_id, platform,
                                 status_changes)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?,
                                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?, ?, 0)
                                """,
                                [link_id, source_device, local_if, remote_device,
                                 remote_if, "CDP", "L2", "up", sync_date, platform]
                            )
                            links_added += 1

                    except Exception as e:
                        logger.debug(f"Failed to process neighbor link: {e}")
                        continue

            except Exception as e:
                logger.debug(f"Failed to process CDP file {cdp_file}: {e}")
                continue

        if links_added > 0 or links_updated > 0:
            logger.info(
                f"Topology links: {links_added} added, "
                f"{links_updated} updated for {sync_date}"
            )

    except Exception as e:
        logger.warning(f"Failed to populate topology links: {e}")



def _discover_topology_from_db(sync_date: str) -> dict:
    """Populate topology_links from Schema-on-Read VIEWs (v0.11.0).

    Reads deduped, CIDR-stripped data from:
      - v_topology_from_parsed  → L2 physical links (CDP/LLDP)
      - v_ospf_neighbors        → L3 OSPF adjacencies (with IP→device resolution)
      - v_bgp_neighbors         → L3 BGP sessions (with IP→device resolution)

    Inserts/upserts into topology_links with history tracking.
    """
    stats = {"added": 0, "updated": 0, "commands_processed": 3}
    try:
        import hashlib

        from olav.core.database import get_database

        db = get_database()
        now = datetime.now()

        # ── L2: CDP / LLDP physical links ─────────────────────────────────────
        l2_links = db.conn.execute("""
            SELECT source_device, source_interface, destination_device,
                   destination_interface, discovery_protocol, chassis_id
            FROM v_topology_from_parsed
        """).fetchall()

        for src_dev, src_if, dst_dev, dst_if, proto, chassis in l2_links:
            if not src_dev or not dst_dev:
                continue
            link_id = hashlib.md5(
                f"{src_dev}|{src_if or ''}|{dst_dev}|{dst_if or ''}".encode()
            ).hexdigest()[:16]
            db.conn.execute("""
                INSERT INTO topology_links
                (link_id, source_device, source_interface, destination_device,
                 destination_interface, discovery_protocol, link_type, link_status,
                 first_seen, last_seen, snapshot_id, platform, status_changes)
                VALUES (?, ?, ?, ?, ?, ?, 'L2', 'up', ?, ?, ?, '', 0)
                ON CONFLICT (link_id) DO UPDATE SET
                    link_status  = EXCLUDED.link_status,
                    last_seen    = EXCLUDED.last_seen,
                    snapshot_id  = EXCLUDED.snapshot_id
            """, [link_id, src_dev, src_if, dst_dev, dst_if, proto, now, now, sync_date])
            stats["added"] += 1

        # ── L3 OSPF: Adjacencies with IP → device resolution ──────────────────
        ospf_rows = db.conn.execute("""
            SELECT o.device_name, o.interface, o.neighbor_ip, o.state,
                   COALESCE(i.device_name, o.neighbor_ip) AS dst_dev,
                   i.interface AS dst_if
            FROM v_ospf_neighbors o
            LEFT JOIN v_interfaces i ON i.ip_address = o.neighbor_ip
        """).fetchall()

        for src_dev, src_if, nbr_ip, state, dst_dev, dst_if in ospf_rows:
            link_id = hashlib.md5(
                f"OSPF|{src_dev}|{dst_dev}".encode()
            ).hexdigest()[:16]
            status = 'up' if 'full' in (state or '').lower() else 'down'
            db.conn.execute("""
                INSERT INTO topology_links
                (link_id, source_device, source_interface, destination_device,
                 destination_interface, discovery_protocol, link_type, link_status,
                 first_seen, last_seen, snapshot_id, platform, status_changes)
                VALUES (?, ?, ?, ?, ?, 'OSPF', 'L3', ?, ?, ?, ?, 'logical', 0)
                ON CONFLICT (link_id) DO UPDATE SET
                    link_status = EXCLUDED.link_status,
                    last_seen   = EXCLUDED.last_seen,
                    snapshot_id = EXCLUDED.snapshot_id
            """, [link_id, src_dev, src_if or 'OSPF', dst_dev, dst_if or nbr_ip,
                  status, now, now, sync_date])
            stats["updated"] += 1

        # ── L3 BGP: Sessions with IP → device resolution ──────────────────────
        bgp_rows = db.conn.execute("""
            SELECT b.device_name, b.neighbor_ip, b.neighbor_as, b.state,
                   COALESCE(i.device_name, b.neighbor_ip) AS dst_dev,
                   i.interface AS dst_if
            FROM v_bgp_neighbors b
            LEFT JOIN v_interfaces i ON i.ip_address = b.neighbor_ip
        """).fetchall()

        for src_dev, nbr_ip, nbr_as, state, dst_dev, dst_if in bgp_rows:
            proto_label = f"BGP-AS{nbr_as}"
            link_id = hashlib.md5(
                f"BGP|{src_dev}|{dst_dev}|{nbr_as}".encode()
            ).hexdigest()[:16]
            status = 'up' if 'establ' in (state or '').lower() else 'down'
            db.conn.execute("""
                INSERT INTO topology_links
                (link_id, source_device, source_interface, destination_device,
                 destination_interface, discovery_protocol, link_type, link_status,
                 first_seen, last_seen, snapshot_id, platform, status_changes)
                VALUES (?, ?, ?, ?, ?, ?, 'L3', ?, ?, ?, ?, 'logical', 0)
                ON CONFLICT (link_id) DO UPDATE SET
                    link_status      = EXCLUDED.link_status,
                    last_seen        = EXCLUDED.last_seen,
                    snapshot_id      = EXCLUDED.snapshot_id,
                    destination_device = EXCLUDED.destination_device
            """, [link_id, src_dev, proto_label, dst_dev, dst_if or nbr_ip,
                  proto_label, status, now, now, sync_date])
            stats["updated"] += 1

        # ── Enriched data (routes etc.) ────────────────────────────────────────
        _populate_extra_networking_data(db, sync_date)

        db.conn.commit()
        logger.info(
            f"Topology ETL: L2={stats['added']} CDP/LLDP, "
            f"OSPF={len(ospf_rows)}, BGP={len(bgp_rows)} links written"
        )

    except Exception as e:
        logger.warning(f"Failed to auto-discover topology: {e}")
    return stats


def _auto_map_topology_fields(json_keys: list) -> dict:
    """Auto-map JSON keys to topology_links schema based on common patterns.
    
    KISS: Simple pattern matching, no LLM needed for common cases.
    """
    keys_lower = {k.lower(): k for k in json_keys}
    

    # Common field name patterns
    mappings = {
        "source_device": ["device", "hostname", "local_device", "host", "source", "src"],
        "source_interface": ["interface", "port", "local_port", "local_interface", "source_interface", "ifname", "src_port"],
        "destination_device": ["neighbor", "remote_device", "remote_host", "device_id", "destination", "remote", "dst", "peer"],
        "destination_interface": ["neighbor_interface", "remote_interface", "remote_port", "destination_interface", "dst_port"],
    }
    
    result = {}
    for target, patterns in mappings.items():
        for pattern in patterns:
            for key_lower, key in keys_lower.items():
                if pattern in key_lower:
                    result[target] = key
                    break
            if target in result:
                break
    
    return result


def _get_routes_schema(platform: str = "cisco_ios") -> dict:
    """Return target schema for routes table."""
    return {
        "table": "routes",
        "fields": [
            {"name": "device_name", "type": "string", "required": True},
            {"name": "network", "type": "string", "required": True},
            {"name": "mask", "type": "string", "required": True},
            {"name": "next_hop", "type": "string", "required": False},
            {"name": "interface", "type": "string", "required": False},
            {"name": "protocol", "type": "string", "required": False},
            {"name": "metric", "type": "integer", "required": False},
        ],
        "target_commands": _get_intent_commands(platform, "routes"),
    }


def _get_bgp_neighbors_schema(platform: str = "cisco_ios") -> dict:
    """Return target schema for bgp_neighbors table."""
    return {
        "table": "bgp_neighbors",
        "fields": [
            {"name": "device_name", "type": "string", "required": True},
            {"name": "neighbor_ip", "type": "string", "required": True},
            {"name": "neighbor_as", "type": "string", "required": False},
            {"name": "state", "type": "string", "required": True},
            {"name": "prefixes_received", "type": "integer", "required": False},
        ],
        "target_commands": _get_intent_commands(platform, "bgp_neighbors"),
    }


def _get_ospf_neighbors_schema(platform: str = "cisco_ios") -> dict:
    """Return target schema for ospf_neighbors table."""
    return {
        "table": "ospf_neighbors",
        "fields": [
            {"name": "device_name", "type": "string", "required": True},
            {"name": "neighbor_id", "type": "string", "required": True},
            {"name": "neighbor_ip", "type": "string", "required": False},
            {"name": "interface", "type": "string", "required": False},
            {"name": "state", "type": "string", "required": True},
            {"name": "priority", "type": "integer", "required": False},
        ],
        "target_commands": _get_intent_commands(platform, "ospf_neighbors"),
    }


def _get_interfaces_schema(platform: str = "cisco_ios") -> dict:
    """Return target schema for interfaces table."""
    return {
        "table": "interfaces",
        "fields": [
            {"name": "device_name", "type": "string", "required": True},
            {"name": "interface", "type": "string", "required": True},
            {"name": "ip_address", "type": "string", "required": False},
            {"name": "status", "type": "string", "required": False},
            {"name": "description", "type": "string", "required": False},
        ],
        "target_commands": _get_intent_commands(platform, "interfaces"),
    }


def _get_bgp_routes_schema(platform: str = "cisco_ios") -> dict:
    """Return target schema for bgp_routes table."""
    return {
        "table": "bgp_routes",
        "fields": [
            {"name": "device_name", "type": "string", "required": True},
            {"name": "network", "type": "string", "required": True},
            {"name": "mask", "type": "string", "required": True},
            {"name": "next_hop", "type": "string", "required": False},
            {"name": "as_path", "type": "string", "required": False},
            {"name": "local_pref", "type": "integer", "required": False},
            {"name": "metric", "type": "integer", "required": False},
            {"name": "weight", "type": "integer", "required": False},
            {"name": "communities", "type": "string", "required": False},
            {"name": "path_type", "type": "string", "required": False},
            {"name": "best_path", "type": "boolean", "required": False},
        ],
        "target_commands": _get_intent_commands(platform, "bgp_routes"),
    }


def _llm_map_fields(raw_keys: list, target_schema: dict) -> dict:
    """Use LLM to map raw JSON keys to target schema fields.
    
    KISS: Simple prompt, returns JSON mapping.
    """
    try:
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage
        
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
        
        fields = target_schema["fields"]
        field_desc = "\n".join([
            f"  - {f['name']}: {f['type']}, required={f.get('required', False)}"
            for f in fields
        ])
        
        prompt = f"""Map raw JSON keys to target schema fields.

Raw JSON keys from device output: {raw_keys}

Target schema:
{field_desc}

Return a JSON mapping from target field name to raw key name.
Example: {{"network": "prefix", "mask": "prefix_length", "next_hop": "gateway"}}

If a field cannot be mapped, omit it.

JSON:"""
        
        response = llm.invoke([HumanMessage(content=prompt)])
        import json
        mapping = json.loads(response.content.strip())
        return mapping
        
    except Exception as e:
        logger.warning(f"LLM mapping failed: {e}")
        return {}

def _populate_routes(sync_date: str) -> None:
    """Populate routes table from parsed_outputs table."""
    try:
        import json
        from olav.core.database import OlavDatabase
        db = OlavDatabase()
        
        # Get all show ip route* entries for this snapshot
        rows = db.conn.execute(
            "SELECT device_name, parsed_data FROM parsed_outputs "
            "WHERE command LIKE 'show ip route%' AND snapshot_id = ?",
            [sync_date]
        ).fetchall()
        
        for device_name, parsed_json in rows:
            try:
                data = json.loads(parsed_json)
                if isinstance(data, dict):
                    routes = data.get("routes") or data.get("ip_route") or []
                elif isinstance(data, list):
                    routes = data
                else:
                    continue
                
                from olav.core.value_normalizer import get_normalizer as _get_norm_r
                _norm_r = _get_norm_r()
                for route in routes:
                    try:
                        network = route.get("network") or route.get("prefix") or ""
                        mask = route.get("mask") or route.get("prefix_length") or ""
                        next_hop = route.get("next_hop") or route.get("gateway") or route.get("nexthop") or ""
                        interface = _norm_r.interface_name(route.get("interface") or route.get("out_interface") or "")
                        protocol = (route.get("protocol") or route.get("type") or "static").lower()
                        metric = route.get("metric") or route.get("cost") or 0
                        
                        if not network:
                            continue
                            
                        db.conn.execute(
                            """INSERT OR REPLACE INTO routes 
                            (device_name, network, mask, next_hop, interface, protocol, metric, snapshot_id)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                            [device_name, network, mask, next_hop, interface, protocol, metric, sync_date]
                        )
                    except Exception:
                        continue
                        
            except Exception:
                continue
                
    except Exception as e:
        logger.warning(f"Failed to populate routes: {e}")


def _populate_bgp_neighbors(sync_date: str) -> None:
    """Populate bgp_neighbors table from parsed_outputs table."""
    try:
        import json
        from olav.core.database import OlavDatabase
        db = OlavDatabase()
        
        rows = db.conn.execute(
            "SELECT device_name, parsed_data FROM parsed_outputs "
            "WHERE command LIKE 'show ip bgp summary%' AND snapshot_id = ?",
            [sync_date]
        ).fetchall()
        
        for device_name, parsed_json in rows:
            try:
                data = json.loads(parsed_json)
                if isinstance(data, dict):
                    neighbors = data.get("neighbors") or data.get("bgp_neighbor") or []
                elif isinstance(data, list):
                    neighbors = data
                else:
                    continue
                
                for neighbor in neighbors:
                    try:
                        neighbor_ip = neighbor.get("neighbor") or neighbor.get("neighbor_id") or neighbor.get("address") or ""
                        neighbor_as = neighbor.get("as") or neighbor.get("asn") or neighbor.get("remote_as") or ""
                        state = neighbor.get("state") or neighbor.get("status") or "Unknown"
                        prefixes = neighbor.get("prefixes") or neighbor.get("msg_rcv") or 0
                        
                        if not neighbor_ip:
                            continue
                        
                        db.conn.execute(
                            """INSERT OR REPLACE INTO bgp_neighbors 
                            (device_name, neighbor_ip, neighbor_as, state, prefixes_received, snapshot_id)
                            VALUES (?, ?, ?, ?, ?, ?)""",
                            [device_name, neighbor_ip, neighbor_as, state, prefixes, sync_date]
                        )
                    except Exception:
                        continue
                        
            except Exception:
                continue
                
    except Exception as e:
        logger.warning(f"Failed to populate BGP neighbors: {e}")


def _populate_ospf_neighbors(sync_date: str) -> None:
    """Populate ospf_neighbors table from parsed_outputs table."""
    try:
        import json
        from olav.core.database import OlavDatabase
        db = OlavDatabase()
        
        rows = db.conn.execute(
            "SELECT device_name, parsed_data FROM parsed_outputs "
            "WHERE command LIKE 'show ip ospf neighbor%' AND snapshot_id = ?",
            [sync_date]
        ).fetchall()
        
        for device_name, parsed_json in rows:
            try:
                data = json.loads(parsed_json)
                if isinstance(data, dict):
                    neighbors = data.get("neighbors") or data.get("ospf_neighbor") or []
                elif isinstance(data, list):
                    neighbors = data
                else:
                    continue
                
                from olav.core.value_normalizer import get_normalizer as _get_norm_o
                _norm_o = _get_norm_o()
                for neighbor in neighbors:
                    try:
                        neighbor_id = neighbor.get("neighbor_id") or neighbor.get("neighbor") or ""
                        neighbor_ip = neighbor.get("neighbor_ip") or neighbor.get("address") or ""
                        interface = _norm_o.interface_name(neighbor.get("interface") or neighbor.get("local_interface") or "")
                        state = neighbor.get("state") or neighbor.get("adjacency_state") or ""
                        priority = neighbor.get("priority") or neighbor.get("dr") or 1
                        
                        if not neighbor_id:
                            continue
                        
                        db.conn.execute(
                            """INSERT OR REPLACE INTO ospf_neighbors
                            (device_name, neighbor_id, neighbor_ip, interface, state, priority, snapshot_id)
                            VALUES (?, ?, ?, ?, ?, ?, ?)""",
                            [device_name, neighbor_id, neighbor_ip, interface, state, priority, sync_date]
                        )
                    except Exception:
                        continue
                        
            except Exception:
                continue
                
    except Exception as e:
        logger.warning(f"Failed to populate OSPF neighbors: {e}")
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
    categories: list[str] | None = None,
) -> str:
    """Scheduled full-network sync. Alias for take_snapshot(wait=False).

    Collects all device data in background. For targeted on-demand collection
    (e.g. during troubleshooting) use take_snapshot() directly with devices
    and categories parameters.

    Args:
        devices:    Device names to target. None = all inventory devices.
        categories: Command categories. None = full collection.

    Returns:
        Status message with sync directory location.

    """
    from take_snapshot import take_snapshot as _take_snapshot

    # Invoke via .func to bypass LangChain tool wrapper for internal call
    # Default to wait=True for CLI stability (ensure ingestion finishes)
    return _take_snapshot.func(devices=devices, categories=categories, wait=True)


def _store_sync_metadata(
    sync_date: str,
    sync_dir: Path,
    device_count: int,
    command_count: int,
    success_count: int,
    failed_count: int,
    duration_seconds: float,
) -> None:
    """Store sync metadata to database.

    Uses the schema pre-defined by sync_schemas.py:
        id            INTEGER PK (auto)
        sync_type     VARCHAR NOT NULL
        start_time    TIMESTAMP NOT NULL
        end_time      TIMESTAMP
        status        VARCHAR NOT NULL
        device_count  INTEGER
        success_count INTEGER
        error_count   INTEGER
        error_details JSON
        created_at    TIMESTAMP
    """
    try:
        import json as _json
        from datetime import datetime as _dt

        from olav.core.database import get_database

        db = get_database()
        conn = db.conn

        start_ts = _dt.strptime(str(sync_date), "%Y-%m-%d")
        end_ts = _dt(
            start_ts.year, start_ts.month, start_ts.day,
            23, 59, 59  # approximate end of day
        )

        extra = _json.dumps({
            "sync_dir":        str(sync_dir),
            "command_count":   command_count,
            "failed_count":    failed_count,
            "duration_seconds":duration_seconds,
        })

        conn.execute(
            """
            INSERT INTO sync_metadata
                (sync_type, start_time, end_time, status,
                 device_count, success_count, error_count, error_details)
            VALUES (?, ?, ?, ?,
                    ?, ?, ?, ?)
            """,
            [
                "snapshot",
                start_ts,
                end_ts,
                "completed",
                device_count,
                success_count,
                failed_count,
                extra,
            ],
        )
        # NOTE: no explicit commit here — the caller (stage2) commits after
        # parsed_outputs; DuckDB autocommit handles the rest.
    except Exception:
        pass  # Metadata storage is optional


def _find_textfsm_template(platform: str, command: str) -> tuple["Path | None", str]:
    """Find the best TextFSM template for a platform + command pair.

    Search order (first match wins — higher priority first):
      1. .olav/templates/custom/{platform}_{cmd_slug}.textfsm
      2. .olav/templates/{platform}_{cmd_slug}.textfsm
      3. NTC-templates package

    Returns:
        (template_path, content) if a template file exists, else (None, "").
        An empty content string means "collect but don't parse" (empty template).
    """
    cmd_slug = command.replace(" ", "_").replace("-", "_").replace("__", "_")
    template_filename = f"{platform}_{cmd_slug}.textfsm"

    search_dirs: list[Path] = [
        _PROJECT_ROOT / ".olav" / "templates" / "custom",
        _PROJECT_ROOT / ".olav" / "templates",
    ]
    try:
        import ntc_templates as _ntc
        search_dirs.append(Path(_ntc.__file__).parent / "templates")
    except Exception:
        pass

    for d in search_dirs:
        candidate = d / template_filename
        if candidate.is_file():
            try:
                content = candidate.read_text(encoding="utf-8")
            except Exception:
                content = ""
            return candidate, content

    return None, ""


def _process_sync_stage2(sync_dir: Path, device_names: list[str]) -> list[dict]:
    """Stage 2: Import raw outputs to DuckDB parsed_outputs table.

    For each raw .txt file:
      - Tries TextFSM parsing with template priority:
          .olav/templates/custom/  >  .olav/templates/  >  NTC-templates
      - Empty template → command was collected, store raw only (no parse).
      - No template found    → store raw only.
      - Parse succeeds       → store JSON array of dicts (structured data).
      - Parse fails / empty rows → fall back to {}.

    Quality Detection (Intent-driven Signature Matching):
      After parsing each file, calls _detect_parse_quality_gap() which uses
      category-aware keyword checking instead of the naive 300B threshold.
      Returns a list of gap dicts with 'severity', 'device', 'command' keys.

    Args:
        sync_dir: Sync directory path (e.g. exports/snapshots/2026-02-19)
        device_names: List of device names that were synced

    Returns:
        List of quality gap dicts. Each dict has keys:
          device, command, severity ('high'|'medium'), reason, size,
          category, matched_keywords
    """
    gaps: list[dict] = []

    try:
        import io as _io
        import json as _json

        from olav.core.config import SNAPSHOTS_STAGING_JSON
        from olav.core.database import get_database
        from olav.core.ingest_manager import IngestManager

        raw_dir = sync_dir / "raw"
        sync_date_str = sync_dir.name  # e.g. "2026-02-19"

        # Staging directory — JSON files are written here and overwritten each run.
        staging_dir = Path(SNAPSHOTS_STAGING_JSON)
        staging_dir.mkdir(parents=True, exist_ok=True)

        db = get_database()

        # Fetch device → platform mapping from devices table (best-effort).
        device_platforms: dict[str, str] = {}
        try:
            rows = db.conn.execute(
                "SELECT name, platform FROM devices WHERE platform IS NOT NULL"
            ).fetchall()
            device_platforms = {r[0]: r[1] for r in rows}
        except Exception:
            pass  # Platform lookup is advisory; raw fallback covers all cases.

        for device_name in device_names:
            device_dir = raw_dir / device_name
            if not device_dir.exists():
                logger.debug(f"Stage 2: raw dir missing for {device_name}, skipping")
                continue

            platform = device_platforms.get(device_name, "")
            txt_files = sorted(device_dir.glob("*.txt"))
            parsed_count = 0
            skipped_count = 0
            error_count = 0
            staging_records: list[dict] = []  # Accumulated records for this device
            print(f"\n  [{device_name}] platform={platform or '?'} — {len(txt_files)} raw files")

            for txt_file in txt_files:
                # Convert filename back to command: show_ip_bgp.txt -> show ip bgp
                command = txt_file.stem.replace("_", " ")
                try:
                    raw_output = txt_file.read_text(encoding="utf-8", errors="replace")
                except Exception as read_err:
                    logger.debug(f"Stage 2: cannot read {txt_file}: {read_err}")
                    continue

                if not raw_output.strip():
                    continue

                # --- TextFSM parsing (platform-aware) ---
                # Raw output stays in exports/snapshots/ only.
                # DB (parsed_outputs) receives structured data only — no raw blobs.
                parsed_data: str | None = None
                has_template = False  # Track if a template was found for gap detection

                if platform:
                    tmpl_path, tmpl_content = _find_textfsm_template(platform, command)
                    if tmpl_path is not None:
                        has_template = True
                        if not tmpl_content.strip():
                            # Empty template = intentional raw-only collection.
                            # Raw file already on disk. Nothing to insert into DB.
                            logger.debug(
                                f"Stage 2: empty template {tmpl_path.name} for "
                                f"{device_name}/{command} — raw-only, skipping DB"
                            )
                        else:
                            try:
                                import textfsm
                                fsm = textfsm.TextFSM(_io.StringIO(tmpl_content))
                                fsm_rows = fsm.ParseText(raw_output)
                                if fsm_rows:
                                    headers = [h.lower() for h in fsm.header]
                                    records = [
                                        dict(zip(headers, row, strict=False)) for row in fsm_rows
                                    ]
                                    parsed_data = _json.dumps(records)
                                    print(f"    ✅ {command:<40} {len(records):>4} rows  ({tmpl_path.name})")
                                    parsed_count += 1
                                else:
                                    print(f"    ⚠️  {command:<40}  0 rows  ({tmpl_path.name}) — no match")
                                    skipped_count += 1
                            except Exception as parse_err:
                                print(f"    ❌ {command:<40} parse error: {type(parse_err).__name__}: {str(parse_err)[:60]}")
                                error_count += 1
                    # else: no template found → raw lives on disk, nothing in DB
                # else: platform unknown → cannot parse, skip DB

                # Only insert into DB if we have actual structured data
                # Skip commands with no template, parse errors, or 0 rows
                if parsed_data is None:
                    continue  # No template or parse failed — raw file is on disk

                # ── Intent-driven Quality Gap Detection ────────────────────
                # Only flag gaps for commands where a template exists (and should
                # have produced data). Skip raw-only / no-template commands.
                if has_template:
                    gap = _detect_parse_quality_gap(raw_output, command, parsed_data)
                    if gap:
                        gaps.append({
                            "device": device_name,
                            "command": command,
                            **gap,
                        })
                        logger.info(
                            "Quality gap [%s] %s/%s: %s",
                            gap["severity"].upper(), device_name, command, gap["reason"]
                        )
                # ────────────────────────────────────────────────────────────

                # Accumulate into staging list — written to JSON at end of device loop
                staging_records.append({
                    "device_name": device_name,
                    "command": command,
                    "parsed_data": _json.loads(parsed_data),  # native list, not string
                    "snapshot_id": sync_date_str,
                })

            # Write staging JSON for this device (minute-level timestamp for traceability)
            # Format: {device}_{YYYYMMDD_HHMM}.staging.json
            timestamp = sync_date_str.replace("-", "").replace("_", "_")  # 20260301_0945 format
            staging_file = staging_dir / f"{device_name}_{timestamp}.staging.json"
            staging_file.write_text(
                _json.dumps(staging_records, ensure_ascii=False, indent=None),
                encoding="utf-8",
            )
            print(f"    → {device_name} summary: {parsed_count} parsed, {skipped_count} 0-rows, {error_count} errors  → {staging_file.name} ({len(staging_records)} records)")

        # Bulk-load all staging files into DuckDB in one atomic read_json_auto pass
        ingest_result = IngestManager(db_path=db.db_path).bulk_load()
        logger.info(
            "Stage 2 ingest: %s — %d files, %d records inserted for %s",
            ingest_result["status"],
            ingest_result.get("files_processed", 0),
            ingest_result.get("records_inserted", 0),
            sync_date_str,
        )
        if gaps:
            high = sum(1 for g in gaps if g.get("severity") == "high")
            med  = sum(1 for g in gaps if g.get("severity") == "medium")
            logger.warning(
                "Stage 2 quality gaps: %d HIGH, %d MEDIUM (total %d)",
                high, med, len(gaps)
            )

        # Materialize inspection views now that data is loaded
        logger.info("Materializing inspection views...")
        try:
            if create_inspection_views is not None:
                create_inspection_views(db.conn)
        except Exception as e:
            logger.warning(f"Failed to materialize views: {e}")

    except Exception as e:
        logger.warning(f"Stage 2 processing failed: {type(e).__name__}: {e}")
        logger.debug("Stage 2 traceback:", exc_info=True)

    return gaps  # Always return gaps list (may be partial on exception)


# ---------------------------------------------------------------------------
# Config-command → filename helpers (zero-content-read)
# ---------------------------------------------------------------------------

_config_commands_cache: list[str] | None = None


def _load_config_commands() -> list[str]:
    """Return config commands from thresholds.yaml (cached after first load).

    Loaded once per process.  Falls back to a minimal built-in list so the
    function always returns something useful even without a config file.
    """
    global _config_commands_cache  # noqa: PLW0603
    if _config_commands_cache is not None:
        return _config_commands_cache

    import yaml  # lazy import — only needed here

    thresholds_path = (
        Path(__file__).parent.parent / "config" / "thresholds.yaml"
    )
    try:
        if thresholds_path.exists():
            with open(thresholds_path, encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
            cmds = data.get("config_commands", [])
            if cmds:
                _config_commands_cache = list(cmds)
                return _config_commands_cache
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to read config_commands from thresholds.yaml: %s", exc)

    # Built-in fallback (covers the most common platforms)
    _config_commands_cache = [
        "show running-config",
        "show running-config full",
        "show configuration",
        "display current-configuration",
        "show running-config partition route-map",
        "show running-config partition access-list",
    ]
    return _config_commands_cache


def _cmd_to_filename(cmd: str) -> str:
    """Convert a CLI command to its snapshot filename (same rule as snapshot.py).

    Examples::

        "show running-config"  → "show-running-config.txt"
        "show configuration"   → "show-configuration.txt"
    """
    return cmd.replace(" ", "-").replace("/", "-") + ".txt"


def _find_running_config_files(sync_date: str, device: str) -> dict[str, Path]:
    """Return running-config files for a device on a snapshot date.

    Detection strategy (fastest first):

    1. **Command-based** (zero I/O per file): look up expected filenames
       derived from ``thresholds.yaml → config_commands``.  Full dumps
       (commands without "partition") are preferred over partition files.
    2. **Content-based fallback**: if no command-registered files are found,
       scan candidates for canonical header markers ("building configuration",
       etc.).  Covers snapshots taken before the command list existed.

    Returns ``{filename: Path}`` dict, sorted deterministically.
    """
    config_cmds = _load_config_commands()

    # Split into full-dump commands and partition commands
    full_cmds    = [c for c in config_cmds if "partition" not in c.lower()]
    partial_cmds = [c for c in config_cmds if "partition"     in c.lower()]

    full_configs: dict[str, Path] = {}
    partial_configs: dict[str, Path] = {}

    for candidate_dir in [
        get_sync_dir(sync_date) / "raw" / device,
        get_sync_dir(sync_date) / "configs" / device,
    ]:
        if not candidate_dir.exists():
            continue
        for cmd in full_cmds:
            fname = _cmd_to_filename(cmd)
            fp = candidate_dir / fname
            if fp.exists():
                full_configs[fname] = fp
        for cmd in partial_cmds:
            fname = _cmd_to_filename(cmd)
            fp = candidate_dir / fname
            if fp.exists():
                partial_configs[fname] = fp

    if full_configs:
        return dict(sorted(full_configs.items()))
    if partial_configs:
        return dict(sorted(partial_configs.items()))

    # ---- Content-based fallback (legacy snapshots / unknown platforms) ------
    logger.debug(
        "No config files found via command mapping for %s/%s — falling back to "
        "content-based detection.",
        sync_date, device,
    )
    full_fb: dict[str, Path] = {}
    part_fb: dict[str, Path] = {}
    _cfg_markers = ("building configuration", "current configuration",
                    "!command: show running-config")
    for candidate_dir in [
        get_sync_dir(sync_date) / "raw" / device,
        get_sync_dir(sync_date) / "configs" / device,
    ]:
        if not candidate_dir.exists():
            continue
        for f in sorted(candidate_dir.glob("*.txt")):
            try:
                sample = f.read_text(errors="replace")[:600].lower()
            except Exception:  # noqa: BLE001
                continue
            if not any(m in sample for m in _cfg_markers):
                continue
            if "configuration of partition" in sample:
                part_fb[f.name] = f
            else:
                full_fb[f.name] = f

    if full_fb:
        return full_fb
    return part_fb


def _find_running_config_file(sync_date: str, device: str) -> Path | None:
    """Return the first (alphabetically) running-config file for a device.

    Deterministic: results are sorted so the same file is always returned.
    """
    files = _find_running_config_files(sync_date, device)
    return next(iter(files.values())) if files else None


def _find_previous_snapshot_date(before_date: str) -> str | None:
    """Return the most recent snapshot date strictly before *before_date*, or None."""
    base_dir = get_sync_base_dir()
    if not base_dir.exists():
        return None
    dates = sorted(
        [
            d.name
            for d in base_dir.iterdir()
            if d.is_dir() and d.name not in ("latest", "archive") and d.name < before_date
        ],
        reverse=True,
    )
    return dates[0] if dates else None


@tool
def diff_configs(device: str, date1: str, date2: str) -> str:
    """Compare running-configuration of a device between two snapshot dates.

    Compares each running-config file by matching filenames across the two dates,
    so a device with multiple partition files (access-list, route-map, etc.) is
    compared correctly — the same file is always compared against itself.

    Use this after take_snapshot(categories=['configs']) to detect config changes
    that may have caused network issues.

    Args:
        device: Device name (e.g. 'R1')
        date1:  Older snapshot date in YYYY-MM-DD format (the "before" state)
        date2:  Newer snapshot date in YYYY-MM-DD format (the "after" state)

    Returns:
        Unified diff string, "no config changes" message, or an error.
        On success, also summarises which sections changed (interface / routing /
        access-list / etc.) to help triage root cause.

    """
    import difflib

    try:
        files1 = _find_running_config_files(date1, device)  # {filename: Path}
        files2 = _find_running_config_files(date2, device)  # {filename: Path}

        if not files1:
            return (
                f"No running-config snapshot found for {device} on {date1}.\n"
                f"Make sure take_snapshot(categories=['configs']) was called for that date."
            )
        if not files2:
            return (
                f"No running-config snapshot found for {device} on {date2}.\n"
                f"Make sure take_snapshot(categories=['configs']) was called for that date."
            )

        # Build comparison pairs — only compare identical-format files.
        #
        # Rule: diff is meaningful ONLY when both dates use the same file format.
        # Mixing a full running-config dump (date2) with partition files (date1)
        # produces hundreds of false diff lines because the partition files only
        # contain a small subset of sections (e.g. access-list + route-map only),
        # while the full dump contains the entire configuration.
        #
        # Valid cases:
        #   1. Both dates have a full dump  → diff the full dump
        #   2. Both dates have partitions   → diff matching partition names
        # Invalid (refuse to diff):
        #   3. One side has full dump, other has only partitions → format mismatch
        common_names = sorted(set(files1.keys()) & set(files2.keys()))

        if not common_names:
            # No filenames in common → format mismatch between dates.
            has_full_1 = any("partition" not in k.lower() for k in files1)
            has_full_2 = any("partition" not in k.lower() for k in files2)
            fmt1 = "full dump" if has_full_1 else "partition files"
            fmt2 = "full dump" if has_full_2 else "partition files"
            files1_list = ", ".join(sorted(files1.keys()))
            files2_list = ", ".join(sorted(files2.keys()))
            return (
                f"{device}: ⚠️  snapshot format mismatch — cannot compare.\n"
                f"  {date1}: {fmt1}  ({files1_list})\n"
                f"  {date2}: {fmt2}  ({files2_list})\n"
                f"Comparing different file formats produces false positives.\n"
                f"Next inspection will compare {date2} vs {date2} (same format) "
                f"and will produce accurate results."
            )

        # Normal case: same filenames on both dates
        comparison_pairs: list[tuple[list[str], list[str], str, str]] = []
        for fname in common_names:
            c1 = files1[fname].read_text(errors="replace").splitlines(keepends=True)
            c2 = files2[fname].read_text(errors="replace").splitlines(keepends=True)
            label1 = f"{device}/{fname}@{date1}"
            label2 = f"{device}/{fname}@{date2}"
            comparison_pairs.append((c1, c2, label1, label2))


        section_keywords = [
            "interface", "router ", "ip route", "access-list", "route-map",
            "prefix-list", "bgp", "ospf", "ntp", "logging", "snmp", "aaa",
            "crypto", "username", "line ", "banner",
        ]

        all_diff_lines: list[str] = []
        changed_sections: set[str] = set()

        for content1, content2, label1, label2 in comparison_pairs:
            diff = list(difflib.unified_diff(
                content1, content2,
                fromfile=label1,
                tofile=label2,
                lineterm="",
            ))
            all_diff_lines.extend(diff)
            for line in diff:
                if line.startswith(('+', '-')) and not line.startswith(('+++', '---')):
                    for kw in section_keywords:
                        if kw in line.lower():
                            changed_sections.add(kw.strip())
                            break

        if not all_diff_lines:
            return f"{device}: no config changes between {date1} and {date2} ✅"

        total_changes = sum(
            1 for line in all_diff_lines
            if line.startswith(('+', '-')) and not line.startswith(('+++', '---'))
        )
        summary = (
            f"{device}: **{total_changes} changed lines** between {date1} → {date2}\n"
            f"Sections affected: {', '.join(sorted(changed_sections)) or 'other'}\n\n"
        )

        max_lines = 200
        body = "".join(all_diff_lines[:max_lines])
        truncation = (
            f"\n... (truncated — {len(all_diff_lines) - max_lines} more lines)"
            if len(all_diff_lines) > max_lines else ""
        )
        return summary + "```diff\n" + body + truncation + "\n```"

    except Exception as e:
        return f"Error comparing configs for {device}: {e}"

def _populate_extra_networking_data(db, sync_date: str) -> None:
    """Populate interfaces and bgp_routes tables from parsed_outputs."""
    # 1. Populate Interfaces (IPAM base)
    intf_schema = _get_interfaces_schema()
    _extract_generic_data(db, intf_schema, sync_date)
    
    # 2. Populate BGP Routes (RIB)
    bgp_rib_schema = _get_bgp_routes_schema()
    _extract_generic_data(db, bgp_rib_schema, sync_date)


def _extract_generic_data(db, target_schema: dict, sync_date: str) -> None:
    """Generic extractor for mapping parsed_outputs to schema-based tables."""
    table = target_schema["table"]
    commands = target_schema["target_commands"]
    
    for cmd in commands:
        records = db.conn.execute("""
            SELECT device_name, parsed_data 
            FROM parsed_outputs 
            WHERE command LIKE ? AND snapshot_id = ?
        """, [f"%{cmd}%", sync_date]).fetchall()
        
        if not records: continue
        
        # Determine mapping from first record
        import json
        try:
            sample_data = json.loads(records[0][1]) if isinstance(records[0][1], str) else records[0][1]
            if not sample_data: continue
            items = sample_data if isinstance(sample_data, list) else [sample_data]
            raw_keys = list(items[0].keys())
            field_map = _llm_map_fields(raw_keys, target_schema)
        except: continue
        
        for dev_name, parsed in records:
            try:
                data = json.loads(parsed) if isinstance(parsed, str) else parsed
                items = data if isinstance(data, list) else [data]
                for row in items:
                    vals = {"device_name": dev_name, "snapshot_id": sync_date}
                    for f in target_schema["fields"]:
                        if f["name"] in ("device_name", "snapshot_id"): continue
                        raw_key = field_map.get(f["name"])
                        if raw_key:
                            vals[f["name"]] = row.get(raw_key)
                    
                    columns = ", ".join(vals.keys())
                    placeholders = ", ".join(["?"] * len(vals))
                    db.conn.execute(f"INSERT OR IGNORE INTO {table} ({columns}) VALUES ({placeholders})", list(vals.values()))
            except: continue
