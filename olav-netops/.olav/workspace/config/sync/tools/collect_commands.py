"""collect_commands — SSH command collection (Stage 1 + Stage 2 parse) for OLAV.

This tool ONLY covers:
  Stage 1: SSH connect all devices, run commands, save raw output files.
  Stage 2: TextFSM parse raw files → write to parsed_outputs table.
  Stage 3: Compute diffs against previous snapshot (if one exists).

NOT included (must be called separately AFTER learner fixes all gaps):
  - generate_topology()   ← only after ALL parse gaps resolved
  - sync_schemas()        ← schema cleanup after gap repair

Results written to:
  1. exports/snapshots/YYYY-MM-DD_HHMM/raw/{device}/{command}.txt
  2. DuckDB parsed_outputs table (TextFSM-parsed JSON)

Returns a structured dict so the calling LLM can immediately act on parse gaps
without reading stdout — key field: `parse_errors` (HIGH/MEDIUM severity gaps).

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
    found = None
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            found = p
        p = p.parent
    return found or Path.cwd()


PROJECT_ROOT = _find_project_root()

# Make same-directory tools importable (sync_tools, get_current_datetime, etc.)
_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))


# ---------------------------------------------------------------------------
# FIXED: Load commands from database instead of hardcoded YAML


def _parse_backup_only_yaml() -> list[dict]:
    """Load and parse backup_only_commands.yaml. Returns raw list of entries."""
    try:
        import yaml

        from olav.core.config import get_paths_config

        paths_config = get_paths_config()
        backup_only_rel = getattr(
            paths_config,
            "backup_only_commands_file",
            ".olav/config/backup_only_commands.yaml",
        )
        backup_only_file = paths_config.project_root / backup_only_rel
        if not backup_only_file.exists():
            logger.debug(f"No backup_only_commands file found at {backup_only_file}")
            return []
        with open(backup_only_file, encoding="utf-8") as f:
            return yaml.safe_load(f) or []
    except Exception as e:
        logger.warning(f"Failed to load backup_only_commands: {e}")
        return []


def _load_backup_only_commands() -> set[str]:
    """Load backup-only commands from configuration.

    These commands are executed only during snapshots, not in queries.
    Returns a set of command names (for O(1) lookup).
    """
    data = _parse_backup_only_yaml()
    commands: set[str] = set()
    for item in data:
        if isinstance(item, dict) and "command" in item:
            commands.add(item["command"].strip())
        elif isinstance(item, str):
            commands.add(item.strip())
    logger.info(f"Loaded {len(commands)} backup-only commands")
    return commands


def load_config_type_commands() -> set[str]:
    """Return command names classified as type=configuration in backup_only_commands.yaml.

    Used by diff_engine to restrict config diff to primary running-config commands
    only, avoiding spurious diffs on operational/show outputs.
    """
    data = _parse_backup_only_yaml()
    commands: set[str] = set()
    for item in data:
        if isinstance(item, dict) and item.get("type") == "configuration":
            cmd = item.get("command", "").strip()
            if cmd:
                commands.add(cmd)
    logger.debug(f"Config-type commands from YAML: {commands}")
    return commands


def _resolve_commands_for_platform(platform: str) -> list[str]:
    """Load all allowed commands for a platform from the database.

    This replaces the hardcoded command_strategy.yaml approach.
    """
    try:
        from olav.core.database import get_database

        db = get_database()

        # Get all allowed commands for this platform
        commands = db.conn.execute(
            """
            SELECT command_name FROM commands
            WHERE platform = ? AND allowed = TRUE
            ORDER BY command_name
        """,
            [platform],
        ).fetchall()

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
    return {"intents": {"all": commands}}


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
        cat_str = ", ".join(categories)

        resp = llm.invoke(
            [
                SystemMessage(
                    content=(
                        "You are a network automation expert. "
                        "Select CLI commands that belong to the requested categories. "
                        'Respond ONLY with valid JSON: {"commands": ["cmd1", ...]}'
                    )
                ),
                HumanMessage(
                    content=(
                        f"Platform: {platform}\n"
                        f"Requested categories: {cat_str}\n\n"
                        f"Available commands:\n{cmd_list}\n\n"
                        "Return the subset of commands that clearly belong to one of the "
                        "requested categories. Include commands even if the category name "
                        "differs slightly (e.g. 'routing' covers bgp, ospf, route tables). "
                        "Preserve exact command strings."
                    )
                ),
            ]
        )

        data = _json.loads(resp.content)
        selected = set(data.get("commands", []))

        # Preserve original DB order; filter to LLM selection
        result = [c for c in all_commands if c in selected]
        logger.info(
            "LLM resolved %d/%d commands for %s categories=%s",
            len(result),
            len(all_commands),
            platform,
            categories,
        )
        return result

    except Exception as e:
        logger.warning(
            "LLM category resolution failed for %s/%s: %s — falling back to all commands",
            platform,
            categories,
            e,
        )
        return all_commands
    # ─────────────────────────────────────────────────────────────────────


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sanitize_filename(cmd: str) -> str:
    """Convert a CLI command to a safe filename (e.g. 'show ip route' → 'show_ip_route.txt')."""
    safe = cmd.replace(" ", "_").replace("/", "_").replace("\\", "_")
    if not safe.endswith(".txt"):
        safe += ".txt"
    return safe


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------


def _find_previous_snapshot_id(current_snap_id: str) -> str | None:
    """Return the most recent snapshot_id from parsed_outputs before current_snap_id."""
    try:
        import duckdb as _duckdb

        from olav.core.config import MAIN_DB_PATH

        conn = _duckdb.connect(str(MAIN_DB_PATH), read_only=True)
        row = conn.execute(
            """
            SELECT snapshot_id FROM parsed_outputs
            WHERE snapshot_id != ? AND snapshot_id < ?
            ORDER BY snapshot_id DESC
            LIMIT 1
        """,
            [current_snap_id, current_snap_id],
        ).fetchone()
        conn.close()
        return row[0] if row else None
    except Exception as _e:
        logger.debug("_find_previous_snapshot_id failed: %s", _e)
        return None


@tool
def collect_commands(
    devices: list[str] | None = None,
    groups: list[str] | None = None,
    categories: list[str] | None = None,
    wait: bool = True,
    is_snapshot: bool = True,
) -> dict:
    """SSH into all network devices, collect command outputs, and parse via TextFSM.

    Covers Stage 1 (SSH collection) + Stage 2 (TextFSM parse) + Stage 3 (diffs).
    Does NOT run topology generation — call generate_topology() separately AFTER
    all parse gaps have been fixed by the learner.

    Raw output files → exports/snapshots/{date}/raw/{device}/{command}.txt
    Parsed results  → DuckDB parsed_outputs table

    Args:
        devices:    Device names to target. None = all inventory devices.
                    Examples: ["R1", "R2"] or None for all.
        groups:     Nornir group names. None = all groups.
        categories: Command categories to collect. None = full collection.
                    Available: "configs", "neighbors", "routing", "interfaces",
                    "switching", "system", "environment", "logging",
                    "bgp", "ospf", "arp", "mac"
        wait:       True = block until Stage 2 (parsing) completes (default).
                    False = Stage 2 runs in background.
        is_snapshot: True = include backup-only commands (default, for scheduled snapshots).
                     False = exclude backup-only commands (for interactive queries).

    Returns:
        dict with keys:
          snapshot_id:       str  — e.g. "2026-03-02_1730"
          devices:           list[str]  — device names collected
          commands_per_platform: dict  — {platform: count}
          raw_files_dir:     str  — path to raw output directory
          netconf_count:     int
          scrapli_count:     int
          netmiko_count:     int
          disconnected:      int
          duration_seconds:  float
          diff_records:      int  — raw_diffs written (0 on first snapshot)
          parse_errors:      list[dict]  — HIGH/MEDIUM gaps for learner to fix
                             Each item: {device, command, severity, raw_size, error}
          summary:           str  — human-readable status line

    Examples:
        # Full collection, all devices — most common:
        collect_commands(wait=True, is_snapshot=True)

        # Targeted BGP refresh (exclude backup-only commands):
        collect_commands(devices=["R1", "R2"], categories=["bgp"], is_snapshot=False)
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from sync_tools import (  # type: ignore[import]
        _classify_transport_result,
        _populate_devices_table,
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
        nr_filtered = nr_filtered.filter(lambda h: any(g in h.groups for g in groups))

    device_names = list(nr_filtered.inventory.hosts.keys())
    if not device_names:
        return {"summary": "No devices available after filtering", "parse_errors": []}

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
        return {
            "summary": "Error: No devices with a platform defined in inventory",
            "parse_errors": [],
        }

    # Load backup-only commands if needed for filtering
    backup_only_commands = set()
    if not is_snapshot:
        backup_only_commands = _load_backup_only_commands()
        if backup_only_commands:
            logger.info(f"Query mode: excluding {len(backup_only_commands)} backup-only commands")

    # Pre-check commands per platform
    platform_commands: dict[str, list[str]] = {}
    for plat in platform_groups:
        cmds = _resolve_commands_for_categories(plat, categories)

        # Filter out backup-only commands if this is not a snapshot
        if not is_snapshot and backup_only_commands:
            original_count = len(cmds)
            cmds = [c for c in cmds if c not in backup_only_commands]
            if len(cmds) < original_count:
                logger.info(
                    f"Platform {plat}: filtered {original_count - len(cmds)} backup-only commands"
                )

        if cmds:
            platform_commands[plat] = cmds
            logger.info(
                "Platform %s: %d commands for %d devices (snapshot=%s)",
                plat,
                len(cmds),
                len(platform_groups[plat]),
                is_snapshot,
            )
        else:
            logger.warning(
                "No commands resolved for platform='%s' (%s), skipping", plat, platform_groups[plat]
            )

    if not platform_commands:
        return {
            "summary": f"Error: No commands resolved for any platform. Categories: {categories}",
            "parse_errors": [],
        }

    total_cmd_count = sum(len(c) for c in platform_commands.values())
    logger.info(
        "collect_commands: %d devices, %d total commands across %d platforms, %s, wait=%s",
        len(device_names),
        total_cmd_count,
        len(platform_commands),
        category_info,
        wait,
    )

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
    netconf_path = fast_path = stable_path = disconnected = 0

    def _run_platform_batch(plat: str, cmds: list[str]) -> tuple[str, dict]:
        plat_device_names = platform_groups[plat]
        nr_plat = nr_filtered.filter(lambda h, _devs=plat_device_names: h.name in _devs)
        print(
            f"\nExecuting {len(cmds)} commands on {len(plat_device_names)} {plat} devices: {plat_device_names}"
        )
        plat_results = nr_plat.run(
            task=_sync_device_workflow,
            commands=cmds,
            output_dir=raw_dir,
        )
        return plat, plat_results

    def _accumulate_platform_results(plat_results: dict) -> None:
        nonlocal netconf_path, fast_path, stable_path, disconnected
        for host_name, multi_result in plat_results.items():
            all_results[host_name] = multi_result
            res_str = str(multi_result[0].result)
            transport = _classify_transport_result(res_str)
            if transport == "netconf":
                netconf_path += 1
            elif transport == "scrapli":
                fast_path += 1
            elif transport == "netmiko":
                stable_path += 1
            else:
                disconnected += 1
                logger.warning("%s failed: %s", host_name, res_str)

    # Run platform groups concurrently; fall back to sequential if runtime rejects parallel runs.
    max_workers = max(1, min(len(platform_commands), 4))
    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_run_platform_batch, plat, cmds): plat
                for plat, cmds in platform_commands.items()
            }
            for future in as_completed(futures):
                plat, plat_results = future.result()
                logger.info("Platform batch finished: %s", plat)
                _accumulate_platform_results(plat_results)
    except Exception as parallel_err:
        logger.warning(
            "Parallel platform execution failed (%s), falling back to sequential mode",
            parallel_err,
        )
        for plat, cmds in platform_commands.items():
            _, plat_results = _run_platform_batch(plat, cmds)
            _accumulate_platform_results(plat_results)

    duration = (datetime.now() - start_time).total_seconds()
    update_latest_link(sync_dir)
    _store_sync_metadata(
        sync_date=sync_date,
        sync_dir=sync_dir,
        device_count=len(device_names),
        command_count=total_cmd_count,
        success_count=netconf_path + fast_path + stable_path,
        failed_count=disconnected,
        duration_seconds=duration,
    )

    platform_summary = ", ".join(
        f"{p}: {len(platform_commands[p])} cmds" for p in platform_commands
    )
    stage1_msg = (
        f"✓ Snapshot complete: {len(device_names)} devices ({platform_summary})\n"
        f"  🔌 NETCONF: {netconf_path}  🚀 Scrapli: {fast_path}  🛡️ Netmiko: {stable_path}  ❌ Down: {disconnected}\n"
        f"  Duration: {duration:.1f}s\n"
        f"  Raw files: {sync_dir}"
    )

    # =========================================================================
    # STAGE 2: TextFSM parsing + DuckDB import
    # NOTE: topology discovery is intentionally NOT called here.
    # Call generate_topology() separately AFTER all learner gaps are resolved.
    # =========================================================================
    def _run_stage2_full() -> list[dict]:
        gaps = _process_sync_stage2(sync_dir, device_names)
        # ⚠️  DO NOT call _discover_topology_from_db here.
        # Topology must be generated only after learner has fixed all parse gaps.
        return gaps

    if wait:
        parsing_gaps = _run_stage2_full()
        msg = stage1_msg + "\n✓ Stage 2 complete: data written to DuckDB"

        diff_count = 0
        # =====================================================================
        # STAGE 3: Calculate raw diffs vs previous snapshot
        # =====================================================================
        prev_snap = _find_previous_snapshot_id(sync_date)
        if prev_snap:
            try:
                from olav.core.calculate_diffs import calculate_diffs

                diff_result = calculate_diffs(
                    snapshot_id_1=prev_snap,
                    snapshot_id_2=sync_date,
                )
                if diff_result["status"] == "success":
                    diff_count = diff_result.get("records_written", 0)
                    msg += f"\n✓ Stage 3 Diff: {diff_count} records ({prev_snap} → {sync_date})"
                else:
                    msg += f"\n⚠️  Stage 3 Diff: {diff_result.get('message', 'no data')}"
            except Exception as _diff_err:
                logger.warning("Stage 3 diff failed: %s", _diff_err)
                msg += f"\n⚠️  Stage 3 Diff skipped: {_diff_err}"
        else:
            msg += "\n– Stage 3 Diff: First snapshot, no previous baseline."

        # Flatten parse_errors into a normalized, LLM-readable list
        normalized_errors: list[dict] = []
        for g in parsing_gaps:
            # Prefer raw_file set directly by gap detection; fall back to reconstructed path
            raw_file = g.get("raw_file") or str(
                raw_dir / g.get("device", "") / _sanitize_filename(g.get("command", ""))
            )
            normalized_errors.append(
                {
                    "device": g.get("device", ""),
                    "command": g.get("command", ""),
                    "severity": g.get("severity", "medium"),
                    "raw_size": g.get("size", 0),
                    "error": g.get("reason", g.get("error", "")),
                    "raw_file": raw_file,
                }
            )

        high_count = sum(1 for e in normalized_errors if e["severity"] == "high")
        medium_count = sum(1 for e in normalized_errors if e["severity"] == "medium")
        status_line = (
            f"Collected {len(device_names)} devices, {total_cmd_count} commands. "
            f"Parse gaps — HIGH: {high_count}, MEDIUM: {medium_count}. "
            f"Diff records: {diff_count}. Raw dir: {sync_dir}"
        )
        return {
            "snapshot_id": sync_date,
            "devices": device_names,
            "commands_per_platform": {p: len(c) for p, c in platform_commands.items()},
            "raw_files_dir": str(sync_dir),
            "netconf_count": netconf_path,
            "scrapli_count": fast_path,
            "netmiko_count": stable_path,
            "disconnected": disconnected,
            "duration_seconds": duration,
            "diff_records": diff_count,
            "parse_errors": normalized_errors,
            "summary": status_line,
        }
    else:
        thread = threading.Thread(
            target=_run_stage2_full,
            daemon=True,
        )
        thread.start()
        return {
            "snapshot_id": sync_date,
            "devices": device_names,
            "raw_files_dir": str(sync_dir),
            "parse_errors": [],
            "summary": stage1_msg + " | Stage 2: TextFSM parsing in background...",
        }


# ---------------------------------------------------------------------------
# Backward-compatibility alias
# (audit_runner.py and legacy scripts may still import `take_snapshot`)
# ---------------------------------------------------------------------------

take_snapshot = collect_commands  # noqa: E305  # deprecated \u2014 use collect_commands()
