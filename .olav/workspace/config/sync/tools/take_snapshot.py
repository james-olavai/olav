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
# FIXED: Load commands from database instead of hardcoded YAML


def _resolve_commands_for_platform(platform: str) -> list[str]:
    """Load all allowed commands for a platform from the database.
    
    This replaces the hardcoded command_strategy.yaml approach.
    """
    try:
        from olav.core.database import get_database
        db = get_database()
        
        # Get all allowed commands for this platform
        commands = db.conn.execute('''
            SELECT command_name FROM commands 
            WHERE platform = ? AND allowed = TRUE
            ORDER BY command_name
        ''', [platform]).fetchall()
        
        return [c[0] for c in commands]
    except Exception as e:
        print(f"Warning: Failed to load commands from DB for {platform}: {e}")
        return []


def _load_command_strategy(platform: str) -> dict:
    """Load command intents for a specific platform.
    
    NOW: Reads from database instead of YAML.
    """
    commands = _resolve_commands_for_platform(platform)
    
    if not commands:
        return {}
    
    # Convert flat list to intents format for compatibility
    return {
        "intents": {
            "all": commands
        }
    }

def _resolve_commands_for_categories(
    platform: str,
    categories: list[str] | None,
) -> list[str]:
    """Resolve CLI commands for a platform using LLM semantic discovery.

    LLM Native: the model semantically matches commands from the DB to the
    requested categories — zero hardcoded keyword maps, works for any vendor.

    Args:
        platform:    Nornir/NTC platform string (e.g. "cisco_ios", "juniper_junos").
        categories:  Optional list of category names (e.g. ["routing", "bgp"]).
                     None = return all commands for the platform.
    Returns:
        Ordered list of command strings appropriate for the requested scope.
    """
    all_commands = _resolve_commands_for_platform(platform)

    if not all_commands:
        logger.warning(f"No commands found for platform {platform}")
        return []

    # No filter — caller wants everything
    if categories is None:
        return all_commands

    # ── LLM Semantic Discovery ────────────────────────────────────────────
    # Let the model decide which commands belong to the requested categories
    # for this specific vendor platform. No hardcoded keyword dict needed.
    try:
        import json as _json
        from langchain_core.messages import HumanMessage, SystemMessage
        from olav.core.llm import LLMFactory

        llm = LLMFactory.get_chat_model(agent_id="sync", temperature=0, json_mode=True)

        cmd_list = "\n".join(f"- {c}" for c in all_commands)
        cat_str  = ", ".join(categories)

        resp = llm.invoke([
            SystemMessage(content=(
                "You are a network automation expert. "
                "Select CLI commands that belong to the requested categories. "
                "Respond ONLY with valid JSON: {\"commands\": [\"cmd1\", ...]}"
            )),
            HumanMessage(content=(
                f"Platform: {platform}\n"
                f"Requested categories: {cat_str}\n\n"
                f"Available commands:\n{cmd_list}\n\n"
                "Return the subset of commands that clearly belong to one of the "
                "requested categories. Include commands even if the category name "
                "differs slightly (e.g. 'routing' covers bgp, ospf, route tables). "
                "Preserve exact command strings."
            )),
        ])

        data     = _json.loads(resp.content)
        selected = set(data.get("commands", []))

        # Preserve original DB order; filter to LLM selection
        result = [c for c in all_commands if c in selected]
        logger.info(
            "LLM resolved %d/%d commands for %s categories=%s",
            len(result), len(all_commands), platform, categories,
        )
        return result

    except Exception as e:
        logger.warning(
            "LLM category resolution failed for %s/%s: %s — falling back to all commands",
            platform, categories, e,
        )
        return all_commands
    # ─────────────────────────────────────────────────────────────────────


# BACKWARD COMPATIBILITY
def _load_command_strategy(platform: str) -> dict:
    """Legacy compatibility wrapper."""
    return _resolve_commands_for_platform(platform)

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

    # Use minute-level timestamp for better debugging/diff capability
    # Format: YYYY-MM-DD_HHMM (e.g. 2026-03-01_0945)
    sync_date = datetime.now().strftime("%Y-%m-%d_%H%M")
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

    category_info = f"categories={categories}" if categories else "full collection"

    # =========================================================================
    # Group devices by platform — each platform gets its own command list
    # =========================================================================
    platform_groups: dict[str, list[str]] = {}
    for dev in device_names:
        plat = nr_filtered.inventory.hosts[dev].platform or ""
        platform_groups.setdefault(plat, []).append(dev)

    no_platform = platform_groups.pop("", [])
    if no_platform:
        logger.warning("Devices without platform skipped: %s", no_platform)

    if not platform_groups:
        return "Error: No devices with a platform defined in inventory"

    # Pre-check commands per platform
    platform_commands: dict[str, list[str]] = {}
    for plat in platform_groups:
        cmds = _resolve_commands_for_categories(plat, categories)
        if cmds:
            platform_commands[plat] = cmds
            logger.info("Platform %s: %d commands for %d devices", plat, len(cmds), len(platform_groups[plat]))
        else:
            logger.warning("No commands resolved for platform='%s' (%s), skipping", plat, platform_groups[plat])

    if not platform_commands:
        return f"Error: No commands resolved for any platform. Categories: {categories}"

    total_cmd_count = sum(len(c) for c in platform_commands.values())
    logger.info("take_snapshot: %d devices, %d total commands across %d platforms, %s, wait=%s",
                len(device_names), total_cmd_count, len(platform_commands), category_info, wait)

    print(f"\nPlatforms detected: {list(platform_commands.keys())}")
    for plat, cmds in platform_commands.items():
        devs = platform_groups[plat]
        print(f"  {plat}: {len(cmds)} commands → {devs}")

    # =========================================================================
    # STAGE 1: ACE Parallel Execution (one nornir.run() per platform group)
    # =========================================================================
    start_time = datetime.now()

    print(f"\nPre-flight: Checking connectivity for {len(device_names)} devices...")
    tcp_results = parallel_tcp_check(list(nr_filtered.inventory.hosts.values()))
    for name, is_up in tcp_results.items():
        nr_filtered.inventory.hosts[name].data["tcp_reachable"] = is_up

    all_results: dict = {}
    fast_path = stable_path = disconnected = 0

    for plat, cmds in platform_commands.items():
        plat_device_names = platform_groups[plat]
        nr_plat = nr_filtered.filter(lambda h, _devs=plat_device_names: h.name in _devs)
        print(f"\nExecuting {len(cmds)} commands on {len(plat_device_names)} {plat} devices: {plat_device_names}")
        plat_results = nr_plat.run(
            task=_sync_device_workflow,
            commands=cmds,
            output_dir=raw_dir,
        )
        for host_name, multi_result in plat_results.items():
            all_results[host_name] = multi_result
            res_str = str(multi_result[0].result)
            if "Scrapli Success" in res_str:
                fast_path += 1
            elif "Netmiko Fallback" in res_str:
                stable_path += 1
            else:
                disconnected += 1
                logger.warning("%s failed: %s", host_name, res_str)

    results = all_results
    duration = (datetime.now() - start_time).total_seconds()
    update_latest_link(sync_dir)
    _store_sync_metadata(
        sync_date=sync_date,
        sync_dir=sync_dir,
        device_count=len(device_names),
        command_count=total_cmd_count,
        success_count=fast_path + stable_path,
        failed_count=disconnected,
        duration_seconds=duration,
    )

    platform_summary = ", ".join(f"{p}: {len(platform_commands[p])} cmds" for p in platform_commands)
    stage1_msg = (
        f"✓ Snapshot complete: {len(device_names)} devices ({platform_summary})\n"
        f"  🚀 Scrapli: {fast_path}  🛡️ Netmiko: {stable_path}  ❌ Down: {disconnected}\n"
        f"  Duration: {duration:.1f}s\n"
        f"  Raw files: {sync_dir}"
    )

    # =========================================================================
    # STAGE 2: TextFSM parsing + DuckDB import
    # =========================================================================
    def _run_stage2_full() -> list[dict]:
        gaps = _process_sync_stage2(sync_dir, device_names)
        # Populate routing and neighbor tables FIRST
        _populate_routes(sync_date)
        _populate_bgp_neighbors(sync_date)
        _populate_ospf_neighbors(sync_date)
        # THEN discover topology (which uses Step 1 logical links from above tables)
        _discover_topology_from_db(sync_date)
        return gaps

    if wait:
        parsing_gaps = _run_stage2_full()
        msg = stage1_msg + "\n✓ Stage 2 complete: data written to DuckDB"
        
        if parsing_gaps:
            # Separate high severity (definite gaps) from medium
            high_severity = [g for g in parsing_gaps if g.get("severity") == "high"]
            medium_severity = [g for g in parsing_gaps if g.get("severity") == "medium"]
            
            msg += "\n\n⚠️  PARSING QUALITY WARNING (Potential Gaps):"
            
            if high_severity:
                msg += "\n\n🚨 HIGH SEVERITY (100% Gap - Keywords found but empty JSON):"
                msg += "\n| Device | Command | Raw Size |"
                msg += "\n| :--- | :--- | :--- |"
                for gap in high_severity[:10]:
                    msg += f"\n| {gap['device']} | {gap['command']} | {gap['size']} B |"
                if len(high_severity) > 10:
                    msg += f"\n| ... | ... and {len(high_severity)-10} more | ... |"
            
            if medium_severity:
                msg += "\n\n⚡ MEDIUM SEVERITY (Possible Gap - Large output but empty JSON):"
                msg += "\n| Device | Command | Raw Size |"
                msg += "\n| :--- | :--- | :--- |"
                for gap in medium_severity[:10]:
                    msg += f"\n| {gap['device']} | {gap['command']} | {gap['size']} B |"
                if len(medium_severity) > 10:
                    msg += f"\n| ... | ... and {len(medium_severity)-10} more | ... |"
            
            msg += "\n\n💡 Suggestion: Check raw files and use 'olav learner' to fix templates."
        return msg
    else:
        thread = threading.Thread(
            target=_run_stage2_full,
            daemon=True,
        )
        thread.start()
        return stage1_msg + "\n⏳ Stage 2: TextFSM parsing in background..."
