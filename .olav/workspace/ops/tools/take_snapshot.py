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

Usage in DeepAgents:
    from .tools import take_snapshot
    agent = create_deep_agent(tools=[take_snapshot.take_snapshot])
"""

from __future__ import annotations

import json
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from langchain_core.tools import tool

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

from olav.core.config import MAIN_DB_PATH, settings

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
        config_file = (
            Path(settings.agent_dir) / "config" / "nornir" / "config.yaml"
        )
        _nornir_instance = InitNornir(config_file=str(config_file.resolve()))
    return _nornir_instance


# ---------------------------------------------------------------------------
# TextFSM parsing (when ntc_templates available)
# ---------------------------------------------------------------------------

def _try_parse_textfsm(output: str, command: str, platform: str) -> list[dict] | None:
    """Attempt TextFSM parse; return list of dicts or None if unavailable."""
    try:
        from ntc_templates.parse import parse_output  # type: ignore
        parsed = parse_output(platform=platform, command=command, data=output)
        if parsed:
            return parsed
    except Exception:
        pass
    # Fallback: check .olav/templates/
    try:
        template_root = Path(settings.agent_dir) / "templates"
        safe_cmd = re.sub(r"[^\w]", "_", command.lower()).strip("_")
        tpl = template_root / platform / f"{safe_cmd}.textfsm"
        if tpl.exists() and tpl.stat().st_size > 0:
            import textfsm  # type: ignore
            with tpl.open() as f:
                fsm = textfsm.TextFSM(f)
            rows = fsm.ParseText(output)
            headers = [h.lower() for h in fsm.header]
            return [dict(zip(headers, r, strict=False)) for r in rows] if rows else None
    except Exception:
        pass
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
    """Execute one command on one device; return result dict."""
    nr = _get_nornir()
    target = nr.filter(name=device)
    if not target.inventory.hosts:
        return {
            "device": device,
            "command": command,
            "status": "failed",
            "error": f"Device '{device}' not found in Nornir inventory",
        }
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
    safe_cmd = re.sub(r"[^\w]", "_", command.lower()).strip("_")
    out_dir = (
        _PROJECT_ROOT
        / "exports"
        / "snapshots"
        / snapshot_date
        / "raw"
        / device
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{safe_cmd}.txt").write_text(raw, encoding="utf-8")


def _insert_parsed_output(
    conn,
    device: str,
    command: str,
    parsed: list[dict] | None,
    snapshot_id: str,
) -> None:
    """Insert row in parsed_outputs for today's snapshot."""
    parsed_json = json.dumps(parsed, ensure_ascii=False) if parsed else "[]"
    conn.execute(
        """
        INSERT OR REPLACE INTO parsed_outputs
            (device_name, command, parsed_data, snapshot_id)
        VALUES (?, ?, ?::JSON, ?)
        """,
        [device, command, parsed_json, snapshot_id],
    )


# ---------------------------------------------------------------------------
# @tool
# ---------------------------------------------------------------------------

@tool
def take_snapshot(
    devices: list[str],
    commands: list[str],
    timeout: int = 30,
    max_workers: int = 6,
) -> dict:
    """Collect fresh CLI output from specific devices for fault investigation.

    Use this when DB data is stale and you need real-time device state.
    Runs commands in parallel across devices, writes results to parsed_outputs
    table and raw files, then returns a structured summary.

    Typical fault investigation workflow:
      1. search_commands(device="R1", keyword="ospf") — find the right command
      2. take_snapshot(devices=["R1","R2"], commands=["show ip ospf neighbor"])
      3. execute_sql("SELECT device_name, parsed_data->>'state' FROM parsed_outputs
                      WHERE command='show ip ospf neighbor' AND snapshot_id=(SELECT MAX(snapshot_id) FROM parsed_outputs)")

    Args:
        devices:     List of device names to collect from (e.g. ["R1", "R2"]).
                     Must exist in Nornir inventory.
        commands:    List of CLI commands to execute on every device.
        timeout:     Per-command timeout in seconds (default 30, max 120).
        max_workers: Parallel threads (default 6, max 20).

    Returns:
        {
          "snapshot_date": "2026-02-20",
          "devices": 2, "commands": 1,
          "successful": 2, "failed": 0,
          "results": [
            {"device": "R1", "command": "show ip ospf neighbor",
             "status": "success", "parsed_rows": 3},
            ...
          ]
        }
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
    for dev in devices:
        host = nr.inventory.hosts.get(dev)
        platform_map[dev] = str(host.platform) if host and host.platform else None

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

    try:
        with _ddb.connect(str(MAIN_DB_PATH)) as conn:
            for r in all_results:
                if r["status"] == "success":
                    raw = r.get("raw", "")
                    parsed = r.get("parsed")
                    try:
                        _insert_parsed_output(
                            conn,
                            r["device"],
                            r["command"],
                            parsed,
                            snapshot_date,
                        )
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
                        summary_rows.append(
                            {
                                "device": r["device"],
                                "command": r["command"],
                                "status": "db_write_failed",
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
    except Exception as exc:
        # DB unavailable — still return raw results
        logger.error("DB write failed: %s", exc)
        for r in all_results:
            if r["status"] == "success":
                successful += 1
                summary_rows.append(
                    {"device": r["device"], "command": r["command"],
                     "status": "success_no_db", "warning": str(exc)}
                )
            else:
                failed += 1
                summary_rows.append(
                    {"device": r["device"], "command": r["command"],
                     "status": "failed", "error": r.get("error")}
                )

    return {
        "status": "success" if failed == 0 else ("partial" if successful > 0 else "failed"),
        "snapshot_id": snapshot_id,
        "devices": len(devices),
        "commands": len(commands),
        "total_tasks": len(tasks),
        "successful": successful,
        "failed": failed,
        "results": summary_rows,
        "next_step": (
            f"Query results with execute_sql: "
            f"SELECT device_name, parsed_data FROM parsed_outputs "
            f"WHERE command='{commands[0]}' AND snapshot_id='{snapshot_id}'"
        ) if commands else "",
    }


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    try:
        input_str = sys.stdin.read()
        params = json.loads(input_str) if input_str.strip() else {}
        result = take_snapshot.func(**params)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
