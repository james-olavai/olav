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
# Category → intent keyword mapping
# ---------------------------------------------------------------------------

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    # Keywords must be substrings of actual NTC template command names
    "configs":     ["running"],
    "neighbors":   ["cdp", "lldp"],
    "routing":     ["route", "ospf", "bgp", "eigrp", "isis", "cef"],
    "interfaces":  ["interface"],
    "switching":   ["vlan", "spanning", "mac"],
    "system":      ["version", "cpu", "memory", "inventory", "clock", "boot"],
    "environment": ["environment", "power"],
    "logging":     ["log"],
    # Convenience aliases
    "bgp":         ["bgp"],
    "ospf":        ["ospf"],
    "arp":         ["arp"],
    "mac":         ["mac"],
}

# Minimal safe collection set used as fallback when no templates are available
_FALLBACK_COMMANDS: list[str] = [
    "show version",
    "show interfaces",
    "show ip interface brief",
    "show ip route",
    "show cdp neighbors",
]


# ---------------------------------------------------------------------------
# Command resolution
# ---------------------------------------------------------------------------

def _resolve_commands_for_categories(
    platform: str,
    categories: list[str] | None,
) -> list[str]:
    """Resolve CLI commands for a platform and category set.

    Priority:
      1. DB commands table (populated by sync_commands, trusted source of truth)
      2. File system scan fallback (if DB is empty / sync_commands not yet run)

    Args:
        platform:   Device platform string (e.g. 'cisco_ios').
        categories: Category names from CATEGORY_KEYWORDS, or None for all.

    Returns:
        Deduplicated list of CLI commands.
    """
    # --- Primary: query commands table ---
    db_commands = _resolve_commands_from_db(platform, categories)
    if db_commands:
        logger.debug(
            "_resolve_commands: %d commands from DB (platform=%s, categories=%s)",
            len(db_commands), platform, categories,
        )
        return db_commands

    # --- Fallback: file system scan (first-time / sync_commands not yet run) ---
    logger.info(
        "commands table empty for platform=%s — falling back to file system scan. "
        "Run sync_commands() to populate DB.",
        platform,
    )
    return _resolve_commands_from_files(platform, categories)


def _resolve_commands_from_db(
    platform: str,
    categories: list[str] | None,
) -> list[str]:
    """Query commands table for allowed commands for this platform/category."""
    try:
        from olav.core.database import get_database
        db = get_database()
    except Exception:
        return []

    try:
        # Build WHERE clause for categories
        if categories is None:
            sql = """
                SELECT command_name FROM commands
                WHERE platform IN (?, '*')
                  AND allowed = true
                  AND blacklisted = false
                  AND command_name LIKE 'show%'
                ORDER BY command_name
            """
            rows = db.conn.execute(sql, [platform]).fetchall()
        else:
            # Expand category keywords for SQL LIKE filtering
            keywords: list[str] = []
            for cat in categories:
                keywords.extend(CATEGORY_KEYWORDS.get(cat.lower(), [cat.lower()]))

            if not keywords:
                return []

            # Build OR conditions for keyword matching
            like_clauses = " OR ".join(
                ["LOWER(command_name) LIKE ?" for _ in keywords]
            )
            sql = f"""
                SELECT command_name FROM commands
                WHERE platform IN (?, '*')
                  AND allowed = true
                  AND blacklisted = false
                  AND ({like_clauses})
                ORDER BY command_name
            """
            params = [platform] + [f"%{kw}%" for kw in keywords]
            rows = db.conn.execute(sql, params).fetchall()

            # Always include running-config for configs category
            if "configs" in [c.lower() for c in categories]:
                config_rows = db.conn.execute(
                    "SELECT command_name FROM commands "
                    "WHERE platform IN (?, '*') AND allowed = true AND blacklisted = false "
                    "AND command_name = 'show running-config'",
                    [platform]
                ).fetchall()
                existing = {r[0] for r in rows}
                rows = list(rows) + [r for r in config_rows if r[0] not in existing]

        return [row[0] for row in rows]
    except Exception as exc:
        logger.debug("DB command query failed: %s", exc)
        return []


def _resolve_commands_from_files(
    platform: str,
    categories: list[str] | None,
) -> list[str]:
    """File system fallback: scan TextFSM templates for commands."""
    # --- User templates take priority ---
    user_dirs = [
        PROJECT_ROOT / ".olav" / "templates" / "custom",
        PROJECT_ROOT / ".olav" / "templates",
    ]
    user_cmds: set[str] = set()
    for user_dir in user_dirs:
        if user_dir.is_dir():
            for t in user_dir.glob(f"{platform}_*.textfsm"):
                user_cmds.add(t.stem.replace(f"{platform}_", "", 1).replace("_", " "))

    # --- NTC templates augment (user templates win on conflicts) ---
    try:
        import ntc_templates as _ntc
        ntc_dir = Path(_ntc.__file__).parent / "templates"
        ntc_commands = [
            t.stem.replace(f"{platform}_", "", 1).replace("_", " ")
            for t in ntc_dir.glob(f"{platform}_*.textfsm")
        ]
    except Exception:
        ntc_commands = []

    seen: set[str] = set(user_cmds)
    all_commands: list[str] = list(user_cmds)
    for cmd in ntc_commands:
        if cmd not in seen:
            all_commands.append(cmd)
            seen.add(cmd)

    if not all_commands:
        logger.warning(
            "No templates found in .olav/templates or NTC — using fallback command set"
        )
        return list(_FALLBACK_COMMANDS)

    if categories is None:
        return sorted({c for c in all_commands if c.startswith("show")})

    keywords: set[str] = set()
    for cat in categories:
        keywords.update(CATEGORY_KEYWORDS.get(cat.lower(), [cat.lower()]))

    seen_cmds: set[str] = set()
    commands: list[str] = []
    for cmd in all_commands:
        cmd_lower = cmd.lower()
        if any(kw in cmd_lower for kw in keywords):
            if cmd not in seen_cmds:
                commands.append(cmd)
                seen_cmds.add(cmd)

    if "configs" in [c.lower() for c in (categories or [])]:
        if "show running-config" not in seen_cmds:
            commands.append("show running-config")

    return commands


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
        _populate_devices_table,
        _populate_topology_links,
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
    _populate_topology_links(sync_date)
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
    if wait:
        _process_sync_stage2(sync_dir, device_names)
        return stage1_msg + "\n✓ Stage 2 complete: data written to DuckDB parsed_outputs"
    else:
        thread = threading.Thread(
            target=_process_sync_stage2,
            args=(sync_dir, device_names),
            daemon=True,
        )
        thread.start()
        return stage1_msg + "\n⏳ Stage 2: TextFSM parsing in background..."
