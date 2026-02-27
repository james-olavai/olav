"""take_snapshot — On-demand network device data collection for olav-audit.

olav-audit is the evolution of network-inspection.  All data collection logic
now lives here; network-inspection will be removed once audit is stable.

Single entry point for all SSH data collection:
- Full sync (all devices, all commands): take_snapshot()
- Targeted refresh (specific devices/categories): take_snapshot(devices=["R1"], categories=["bgp"])
- Synchronous mode for audits: take_snapshot(..., wait=True)

Execution engine: ACE (Adaptive Connectivity Engine) from sync_tools.py.
Results are written to:
  1. exports/snapshots/YYYY-MM-DD/raw/{device}/{command}.txt  (raw output files)
  2. DuckDB parsed_outputs table (TextFSM-parsed JSON, queryable via execute_sql)

Template priority for TextFSM parsing (Stage 2):
  .olav/templates/custom/  >  .olav/templates/  >  NTC-templates
  Empty .textfsm file = collect raw, skip parsing.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def _find_project_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


PROJECT_ROOT = _find_project_root()

# Make same-directory tools importable (sync_tools, get_current_datetime, etc.)
_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))


# ---------------------------------------------------------------------------
# Command resolution via Strategy
# ---------------------------------------------------------------------------

def _load_command_strategy(platform: str) -> dict:
    """Load command intents for a specific platform."""
    import yaml
    config_path = PROJECT_ROOT / ".olav" / "workspace" / "config" / "sync" / "config" / "command_strategy.yaml"
    if not config_path.exists():
        logger.warning(f"command_strategy.yaml not found at {config_path}")
        return {}
    
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            platforms = data.get("platforms", {})
            return platforms.get(platform, {})
    except Exception as e:
        logger.error(f"Failed to load command strategy: {e}")
        return {}

def _resolve_commands_for_categories(
    platform: str,
    categories: list[str] | None,
) -> list[str]:
    """Resolve CLI commands for a platform and category set using strategy.

    Args:
        platform:   Device platform string (e.g. 'cisco_ios').
        categories: Intent names (e.g. 'configs', 'routing'). None = all.

    Returns:
        Deduplicated list of CLI commands.
    """
    strategy = _load_command_strategy(platform)
    if not strategy:
        logger.warning(f"No strategy found for platform {platform}")
        return []

    intents = strategy.get("intents", {})
    resolved_commands = []

    if categories is None:
        # Include all available intents for this platform
        for cmds in intents.values():
            resolved_commands.extend(cmds)
    else:
        # Match categories to intents
        # Support flexible mapping: e.g. 'bgp' -> 'bgp_neighbors'
        intent_map = {
            "configs": ["configs"],
            "routing": ["routes", "bgp_neighbors", "ospf_neighbors"],
            "neighbors": ["cdp_neighbors", "lldp_neighbors"],
            "interfaces": ["interfaces"],
            "system": ["version", "inventory"],
            "bgp": ["bgp_neighbors"],
            "ospf": ["ospf_neighbors"],
        }
        
        for cat in categories:
            cat_lower = cat.lower()
            target_intents = intent_map.get(cat_lower, [cat_lower])
            for intent in target_intents:
                resolved_commands.extend(intents.get(intent, []))

    # Basic cleanup and deduplication
    return sorted(list({cmd for cmd in resolved_commands if cmd}))


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------

@tool
def take_snapshot(
    devices: list[str] | None = None,
    groups: list[str] | None = None,
    categories: list[str] | None = None,
    wait: bool = True,
) -> str:
    """Pull network device state via SSH and store results to files and DuckDB.

    This is the Map phase of the audit pipeline — collect raw data before
    the rule engine evaluates it.  Results are written to:
      - exports/snapshots/{date}/raw/{device}/{command}.txt  (raw files)
      - DuckDB parsed_outputs table (TextFSM-parsed, or {"raw":...} fallback)

    TextFSM template priority:
      .olav/templates/custom/  >  .olav/templates/  >  NTC-templates
      Empty .textfsm = collect raw output, skip parsing (useful for
      show running-config and other commands without a template).

    Args:
        devices:    Device names to target. None = all inventory devices.
                    Examples: ["R1", "R2"] or None for all.
        groups:     Nornir group names. None = all groups.
                    Examples: ["core"] or ["core", "access"]
        categories: Command categories to collect. None = full collection.
                    Available: "configs", "neighbors", "routing", "interfaces",
                    "switching", "system", "environment", "logging",
                    "bgp", "ospf", "arp", "mac"
        wait:       True = block until Stage 2 (parsing) completes.
                    False = Stage 2 runs in background (faster for scheduled tasks).

    Returns:
        Status string with device count, command count, and snapshot directory.

    Examples:
        # Audit-targeted collection (system metrics + configs):
        take_snapshot(categories=["system", "configs"])

        # Targeted BGP refresh for specific devices:
        take_snapshot(devices=["R1", "R2"], categories=["bgp", "routing"])

        # Full collection, all devices:
        take_snapshot(wait=True)
    """
    import threading

    from sync_tools import (  # type: ignore[import]
        _discover_topology_from_db,
        _populate_bgp_neighbors,
        _populate_devices_table,
        _populate_ospf_neighbors,
        _populate_routes,
        _process_sync_stage2,
        _store_sync_metadata,
        _sync_device_workflow,
        get_nornir,
        get_sync_dir,
        parallel_tcp_check,
        reset_nornir,
        update_latest_link,
    )

    sync_date = datetime.now().strftime("%Y-%m-%d")
    sync_dir = get_sync_dir(sync_date)
    raw_dir = sync_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    reset_nornir()
    nr = get_nornir()

    # Apply device / group filters
    if devices:
        nr_filtered = nr.filter(lambda h: h.name in devices)
    else:
        nr_filtered = nr

    if groups:
        nr_filtered = nr_filtered.filter(
            lambda h: any(g in h.groups for g in groups)
        )

    device_names = list(nr_filtered.inventory.hosts.keys())
    if not device_names:
        return "No devices available after filtering"

    _populate_devices_table(nr_filtered)

    first_host = nr_filtered.inventory.hosts[device_names[0]]
    platform = first_host.platform
    if not platform:
        return f"Error: Device '{first_host.name}' has no platform defined in inventory"

    commands = _resolve_commands_for_categories(platform, categories)
    if not commands:
        return (
            f"Error: No commands resolved for platform='{platform}', "
            f"categories={categories}."
        )

    category_info = f"categories={categories}" if categories else "full collection"
    logger.info(
        "take_snapshot: %d devices, %d commands, %s, wait=%s",
        len(device_names), len(commands), category_info, wait,
    )

    # =========================================================================
    # STAGE 1: ACE Parallel Execution (Scrapli → Netmiko fallback per device)
    # =========================================================================
    start_time = datetime.now()

    print(f"Pre-flight: Checking connectivity for {len(device_names)} devices...")
    tcp_results = parallel_tcp_check(list(nr_filtered.inventory.hosts.values()))
    for name, is_up in tcp_results.items():
        nr_filtered.inventory.hosts[name].data["tcp_reachable"] = is_up

    print(f"DEBUG: PROJECT_ROOT={PROJECT_ROOT}")
    print(f"DEBUG: sync_dir={sync_dir}")
    print(f"DEBUG: commands={commands}")
    print(f"Executing {len(commands)} commands on {len(device_names)} devices...")
    results = nr_filtered.run(
        task=_sync_device_workflow,
        commands=commands,
        output_dir=raw_dir,
    )

    fast_path = stable_path = disconnected = 0
    for host_name, multi_result in results.items():
        res_str = str(multi_result[0].result)
        if "Scrapli Success" in res_str:
            fast_path += 1
        elif "Netmiko Fallback" in res_str:
            stable_path += 1
        else:
            disconnected += 1
            logger.warning("%s failed: %s", host_name, res_str)


    duration = (datetime.now() - start_time).total_seconds()
    update_latest_link(sync_dir)
    # _populate_topology_links(sync_date) # DEPRECATED: use _discover_topology_from_db
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
        f"✓ Snapshot complete: {len(device_names)} devices, {len(commands)} commands "
        f"({category_info})\n"
        f"  🚀 Scrapli: {fast_path}  🛡️ Netmiko: {stable_path}  ❌ Down: {disconnected}\n"
        f"  Duration: {duration:.1f}s\n"
        f"  Raw files: {sync_dir}"
    )

    # =========================================================================
    # STAGE 2: TextFSM parsing + DuckDB import
    # =========================================================================
    def _run_stage2_full():
        _process_sync_stage2(sync_dir, device_names)
        # Auto-discover topology from parsed_outputs (LLM + schema-aware)
        _discover_topology_from_db(sync_date)
        # Populate routing tables
        _populate_routes(sync_date)
        _populate_bgp_neighbors(sync_date)
        _populate_ospf_neighbors(sync_date)

    if wait:
        _run_stage2_full()
        return stage1_msg + "\n✓ Stage 2 complete: data written to DuckDB parsed_outputs"
    else:
        thread = threading.Thread(
            target=_run_stage2_full,
            daemon=True,
        )
        thread.start()
        return stage1_msg + "\n⏳ Stage 2: TextFSM parsing in background..."
