#!/usr/bin/env python3
"""
take_snapshot — On-demand targeted data collection for fault investigation.

Use this during active troubleshooting when you need FRESH device state,
not historical data from the DB.  For scheduled full-network snapshots
use the olav-config agent (Cron A / take_snapshot there).

This tool is intentionally scoped to targeted, on-demand execution:
  - Specific devices (not all devices)
  - Specific commands you already know you need
  - Synchronous (waits for completion, returns results directly)

Workflow integration:
  1. search_commands(device="R1", keyword="ospf") → find commands
  2. take_snapshot(devices=["R1","R2"], commands=["show ip ospf neighbor"])
  3. execute_sql("SELECT ... FROM parsed_outputs WHERE command='...' AND snapshot_date=today")

Results are written to:
  - DuckDB parsed_outputs table (TextFSM-parsed JSON when template exists)
  - exports/snapshots/YYYY-MM-DD/raw/{device}/{safe_cmd}.txt (raw output)
"""

from __future__ import annotations

from olav.core.db_write import open_write_connection

import json
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Bootstrap project root → enable config imports
# ---------------------------------------------------------------------------

def _find_project_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


_PROJECT_ROOT = _find_project_root()
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

import duckdb as _ddb
from nornir import InitNornir
from nornir_netmiko.tasks import netmiko_send_command

from olav.core.config import SNAPSHOTS_STAGING_JSON, settings, SNAPSHOTS_DIR
from olav_netops.core.config_paths import resolve_nornir_config_path as _resolve_nornir_config_path

# Try to import Scrapli for fast path
try:
    from nornir_scrapli.tasks import send_commands as scrapli_send_commands
    _HAS_SCRAPLI = True
except ImportError:
    scrapli_send_commands = None
    _HAS_SCRAPLI = False

# Scrapli platform mapping (Nornir -> Scrapli)
SCRAPLI_PLATFORM_MAP = {
    "cisco_ios": "cisco_iosxe",
    "cisco_xe": "cisco_iosxe",
    "cisco_xr": "cisco_iosxr",
    "arista_eos": "arista_eos",
    "juniper_junos": "juniper_junos",
}

# ---------------------------------------------------------------------------
# Nornir singleton
# ---------------------------------------------------------------------------

_nornir_instance = None


def _get_nornir():
    global _nornir_instance
    if _nornir_instance is None:
        config_file = _resolve_nornir_config_path()
        _nornir_instance = InitNornir(config_file=str(config_file.resolve()))
    return _nornir_instance


# ---------------------------------------------------------------------------
# TextFSM parsing (when ntc_templates available)
# ---------------------------------------------------------------------------

def _try_parse_textfsm(output: str, command: str, platform: str) -> list[dict] | None:
    """Parse CLI output via the canonical wrapper.

    R83: previously this function had its own three-tier template lookup
    that diverged from ``/netops_init``s parser, producing
    ``interface``/``ip_address`` (lowercase) where ``/netops_init``
    produced ``INTERFACE``/``IP_ADDRESS`` (uppercase).  Same data,
    different shape -- the per-command auto-views could not unify them.
    Delegate to the single source of truth so every ingest path lands
    identical JSON in ``parsed_outputs``.
    """
    try:
        from olav_netops.tools.textfsm_parse import parse_output
        return parse_output(platform, command, output)
    except Exception as exc:
        logger.debug("parse_output(%s, %s) failed: %s", platform, command, exc)
        return None


# ---------------------------------------------------------------------------
# Single-device command execution
# ---------------------------------------------------------------------------

def _run_one(device: str, command: str, timeout: int, platform: str | None) -> dict:
    """Execute one command on one device with Scrapli→Netmiko fallback."""
    nr = _get_nornir()
    target = nr.filter(name=device)
    if not target.inventory.hosts:
        return {
            "device": device,
            "command": command,
            "status": "failed",
            "error": f"Device '{device}' not found in Nornir inventory",
        }

    host = target.inventory.hosts[device]

    # Try Scrapli first (fast path)
    if _HAS_SCRAPLI and platform:
        scrapli_platform = SCRAPLI_PLATFORM_MAP.get(platform)
        if scrapli_platform:
            try:
                from nornir.core.inventory import ConnectionOptions

                opts = host.connection_options.get("scrapli", ConnectionOptions())
                opts.platform = scrapli_platform
                if opts.extras is None:
                    opts.extras = {}
                opts.extras["ssh_config_file"] = True
                opts.extras["auth_strict_key"] = False
                opts.extras["transport"] = "paramiko"
                opts.extras["timeout_ops"] = timeout
                host.connection_options["scrapli"] = opts

                result = target.run(
                    task=scrapli_send_commands,
                    commands=[command],
                    strip_prompt=True,
                )
                host_result = result[device]
                if not host_result.failed:
                    raw = host_result.result[0].result if host_result.result else ""
                    # R83 boundary filter — same as netmiko path below.
                    from olav_netops.core.parse_helpers import is_cli_error
                    if is_cli_error(raw):
                        return {
                            "device": device,
                            "command": command,
                            "status": "rejected",
                            "error": "device CLI error / unsupported command",
                            "raw": raw,
                            "driver": "scrapli",
                        }
                    parsed = None
                    if platform:
                        parsed = _try_parse_textfsm(raw, command, platform)
                    return {
                        "device": device,
                        "command": command,
                        "status": "success",
                        "raw": raw,
                        "parsed": parsed,
                        "platform": platform,
                        "driver": "scrapli",
                    }
            except Exception as e:
                logger.debug(f"Scrapli failed for {device}: {e}")

    # Fallback to Netmiko (stable path)
    try:
        result = target.run(
            task=netmiko_send_command,
            command_string=command,
            read_timeout=timeout,
        )
        host_result = result[device]
        if host_result.failed:
            return {
                "device": device,
                "command": command,
                "status": "failed",
                "error": str(host_result.exception or "Command failed"),
            }
        raw = host_result.result or ""
        # R83 (parity with /netops_init R81 fix): reject CLI error responses
        # (``% Invalid input detected``, ``unknown command``, near-empty)
        # at the boundary so they never reach raw_output_store /
        # parsed_outputs.  Without this, take_snapshot was a back door
        # that bypassed the ingest filter ``/netops_init`` enforces.
        from olav_netops.core.parse_helpers import is_cli_error
        if is_cli_error(raw):
            return {
                "device": device,
                "command": command,
                "status": "rejected",
                "error": "device CLI error / unsupported command",
                "raw": raw,
            }
        parsed = None
        if platform:
            parsed = _try_parse_textfsm(raw, command, platform)
        return {
            "device": device,
            "command": command,
            "status": "success",
            "raw": raw,
            "parsed": parsed,
            "platform": platform,
            "driver": "netmiko",
        }
    except Exception as exc:
        return {
            "device": device,
            "command": command,
            "status": "failed",
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# DB write helpers
# ---------------------------------------------------------------------------

def _write_raw_file(device: str, command: str, raw: str, snapshot_date: str) -> None:
    """Write raw output to exports/snapshots/YYYY-MM-DD/raw/{device}/{cmd}.txt"""
    safe_cmd = re.sub(r"[^\w]", "_", command.lower()).strip("_")
    # Path: exports/snapshots/YYYY-MM-DD/raw/R1/show_interfaces_terse.txt
    out_path = SNAPSHOTS_DIR / snapshot_date / "raw" / device / f"{safe_cmd}.txt"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(raw, encoding="utf-8")


def _write_staging_json(
    device: str, command: str, parsed: list[dict] | None, snapshot_id: str,
    raw_output: str = "",
    platform: str | None = None,
) -> None:
    """Write parsed JSON to staging directory for IngestManager bulk ingestion.

    Output format matches IngestManager expectations: a JSON array with fields
    ``device_name``, ``command``, ``raw_output``, ``parsed_data``,
    ``snapshot_id``, ``platform``.

    Filename uses ``*.staging.json`` pattern so ``bulk_load()`` picks it up.
    """
    staging_dir = Path(SNAPSHOTS_STAGING_JSON)
    staging_dir.mkdir(parents=True, exist_ok=True)

    file_path = staging_dir / f"{snapshot_id}.staging.json"

    record = {
        "device_name": device,
        "command": command,
        "raw_output": raw_output,
        "parsed_data": json.dumps(parsed) if parsed else None,
        "snapshot_id": snapshot_id,
        # R-VERTICAL-SLICE 2026-05-09 (dev_docs/70): denormalise platform
        # at write time so downstream cross-vendor views don't have to
        # JOIN to netops.devices.
        "platform": platform,
    }

    # Append to existing staging file (multiple commands per snapshot)
    existing: list[dict] = []
    if file_path.exists():
        try:
            existing = json.loads(file_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = []

    existing.append(record)
    file_path.write_text(json.dumps(existing, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------

def take_snapshot(
    devices: list[str],
    commands: list[str],
    timeout: int = 30,
    max_workers: int = 6,
    environment: str | None = None,
) -> dict:
    """Collect fresh CLI output from devices; writes parsed_outputs +
    raw_output_store (RAW-05 fallback). Use when DB state is stale.

    See tool_help("take_snapshot") for the full workflow, environment
    dispatch, parallel tuning, and the RAW-05 raw-fallback policy.
    """
    if not devices:
        return {"status": "error", "message": "devices list is empty"}
    if not commands:
        return {"status": "error", "message": "commands list is empty"}

    timeout = min(max(timeout, 5), 120)
    max_workers = min(max(max_workers, 1), 20)
    import uuid
    from datetime import datetime
    now = datetime.now()
    snapshot_id = f"snap_{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    snapshot_date = now.strftime("%Y-%m-%d")

    # Resolve platforms from inventory for TextFSM parsing
    nr = _get_nornir()
    platform_map: dict[str, str | None] = {}
    env_map: dict[str, str | None] = {}
    for dev in devices:
        host = nr.inventory.hosts.get(dev)
        platform_map[dev] = str(host.platform) if host and host.platform else None
        env_map[dev] = (host.data or {}).get("environment") if host else None

    # Environment dispatch — skip hosts whose env tag mismatches.
    skipped: list[dict] = []
    if environment:
        kept = []
        for dev in devices:
            if env_map.get(dev) != environment:
                skipped.append({
                    "device": dev,
                    "reason": (
                        f"environment mismatch: host env={env_map.get(dev)!r}, "
                        f"requested={environment!r}"
                    ),
                })
            else:
                kept.append(dev)
        devices = kept

    # Build task list (device × command)
    tasks = [(dev, cmd) for dev in devices for cmd in commands]

    # Parallel execution
    all_results: list[dict] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_run_one, dev, cmd, timeout, platform_map.get(dev)): (dev, cmd)
            for dev, cmd in tasks
        }
        for future in as_completed(futures):
            all_results.append(future.result())

    # Write to DB + raw files
    successful = 0
    failed = 0
    summary_rows = []

    for r in all_results:
        if r["status"] == "success":
            raw = r.get("raw", "")
            parsed = r.get("parsed")
            try:
                # Write staging JSON (IngestManager-compatible format)
                _write_staging_json(r["device"], r["command"], parsed, snapshot_id,
                                    raw_output=raw, platform=platform_map.get(r["device"]))
                # Write raw file
                _write_raw_file(r["device"], r["command"], raw, snapshot_date)

                successful += 1
                summary_rows.append(
                    {
                        "device": r["device"],
                        "command": r["command"],
                        "status": "success",
                        "parsed_rows": len(parsed) if parsed else 0,
                    }
                )
            except Exception as exc:
                failed += 1
                logger.error(f"Failed to write staging data for {r['device']}: {exc}")
                summary_rows.append(
                    {
                        "device": r["device"],
                        "command": r["command"],
                        "status": "write_failed",
                        "error": str(exc),
                    }
                )
        else:
            failed += 1
            summary_rows.append(
                {
                    "device": r["device"],
                    "command": r["command"],
                    "status": "failed",
                    "error": r.get("error", "unknown"),
                }
            )

    # Auto-ingest staging data into DuckDB + refresh views + Device ETL.
    #
    # R83: take_snapshot used to call ``bulk_load + extract_lldp_topology``
    # only.  ``netops.devices`` (model/os/last_seen), the cross-vendor
    # semantic views, and the per-command auto-views (R83) all stayed
    # stale until the next ``/netops_init``.  Now both entry points run
    # the same ``finalise_ingest`` + ``populate_devices`` finalisation
    # — so ``v_show_<...>_auto`` views appear immediately after a
    # single-command capture.
    if successful > 0:
        try:
            from olav.core.ingest_manager import IngestManager
            from olav.core.config import MAIN_DB_PATH
            ingest = IngestManager(db_path=MAIN_DB_PATH, staging_dir=Path(SNAPSHOTS_STAGING_JSON))
            ingest.bulk_load()

            try:
                from olav_netops.core.topology_engine import extract_lldp_topology
                from olav_netops.core.view_builder import finalise_ingest
                from olav_netops.core.device_etl import populate_devices
                import duckdb
                # R83.3 ordering: populate_devices BEFORE finalise_ingest so
                # the new introspection_cache (built inside finalise_ingest)
                # sees current snapshot's device list, not stale state.
                populate_devices(MAIN_DB_PATH, snapshot_id)
                with open_write_connection(MAIN_DB_PATH) as _conn:
                    extract_lldp_topology(_conn)
                    finalise_ingest(_conn)
            except Exception as exc:
                logger.warning("post-ingest hooks (views/Device ETL) failed: %s", exc)
        except Exception as _ingest_err:
            logger.warning("Auto-ingest after snapshot failed: %s", _ingest_err)

    return {
        "status": "success" if failed == 0 else ("partial" if successful > 0 else "failed"),
        "snapshot_id": snapshot_id,
        "devices": len(devices),
        "commands": len(commands),
        "total_tasks": len(tasks),
        "successful": successful,
        "failed": failed,
        "skipped": skipped,
        "results": summary_rows,
        "next_step": (
            f"Query the auto-view: DESCRIBE netops.v_<safe_command>_auto then "
            f"SELECT * FROM netops.v_<safe_command>_auto WHERE <col>=...; "
            f"safe_command = '{commands[0]}'.replace(' ', '_'). "
            f"Raw text in netops.raw_output_store as RAW-05 fallback."
        ) if commands else "",
    }


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json as _json, sys as _sys
    _args = _json.loads(_sys.stdin.read() or "{}")
    result = take_snapshot(**_args)
    print(_json.dumps(result, default=str))
