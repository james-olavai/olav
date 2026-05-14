#!/usr/bin/env python3
"""
Execute CLI commands on multiple devices in parallel via Nornir.

Same whitelist/blacklist validation as execute_cli (ops/tools):
- Checks commands table: blacklisted, pipe_allowed
- Device name sanitisation
- Fails open if commands table is not yet populated
"""

from __future__ import annotations

import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from langchain_core.tools import tool


def _find_project_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


sys.path.insert(0, str(_find_project_root() / "src"))

from olav.core.config import MAIN_DB_PATH, settings
from olav_netops.core.config_paths import resolve_nornir_config_path as _resolve_nornir_config_path


# ── Command + device validation (mirrors ops/tools/execute_cli.py) ───────────

def _validate_command(command: str, platform: str | None = None) -> dict:
    """Check command against the commands table (blacklist + pipe_allowed).

    Returns {"ok": True} or {"ok": False, "reason": str}.
    Fails open if commands table is unavailable.
    """
    try:
        import duckdb
        has_pipe = "|" in command
        base_cmd = command.split("|")[0].strip().lower()

        with duckdb.connect(str(MAIN_DB_PATH), read_only=True) as conn:
            tables = [r[0] for r in conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_name='commands' AND table_schema IN ('netops', 'main')"
            ).fetchall()]
            if not tables:
                return {"ok": True, "warning": "commands table not found; run sync_commands() to enable validation"}

            if platform:
                platform_filter = [platform, "*"]
                placeholders = ",".join(["?"] * len(platform_filter))
                rows = conn.execute(
                    f"SELECT blacklisted, pipe_allowed FROM netops.commands "
                    f"WHERE LOWER(command) = ? AND platform IN ({placeholders}) "
                    f"ORDER BY blacklisted DESC, platform ASC LIMIT 1",
                    [base_cmd] + platform_filter,
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT blacklisted, pipe_allowed FROM netops.commands "
                    "WHERE LOWER(command) = ? "
                    "ORDER BY blacklisted DESC, platform ASC LIMIT 1",
                    [base_cmd],
                ).fetchall()

        if not rows:
            return {"ok": True, "warning": f"'{base_cmd}' not in commands registry"}

        blacklisted, pipe_allowed = rows[0]
        if blacklisted:
            return {"ok": False, "reason": f"Command '{base_cmd}' is blacklisted"}
        if has_pipe and not pipe_allowed:
            return {"ok": False, "reason": f"Command '{base_cmd}' does not allow pipe filtering"}
        return {"ok": True}

    except Exception as exc:
        return {"ok": True, "warning": f"Command validation skipped (DB error: {exc})"}


_DEVICE_RE = re.compile(r"^[a-zA-Z0-9_\-.]+$")


def _validate_device(name: str) -> dict:
    if not name or not _DEVICE_RE.match(name):
        return {"ok": False, "reason": f"Invalid device name: {name!r} (alphanumerics, hyphens, underscores, dots only)"}
    return {"ok": True}


# ── Nornir singleton (shared with execute_cli) ────────────────────────────────

_nornir_instance = None


def _get_nornir():
    from nornir import InitNornir
    global _nornir_instance
    if _nornir_instance is None:
        config_file = _resolve_nornir_config_path()
        _nornir_instance = InitNornir(config_file=str(config_file.resolve()))
    return _nornir_instance


# R-VERTICAL-SLICE 2026-05-09 (dev_docs/74): circuit breaker on
# unreachable devices.  In-vivo test showed LLM retrying the SAME
# unreachable device 3+ times in a row, each costing one full SSH
# timeout (~30s).  Cache recent connection failures so subsequent
# attempts within the TTL fast-fail.
import time as _time

_CIRCUIT_TTL_S = 60.0
_recent_failures: dict[str, tuple[float, str]] = {}

# Substrings that indicate a transport-level failure (not a syntax /
# privilege error).  Only these trip the breaker — a command-not-found
# error on one command shouldn't stop other commands from being tried.
_CONN_FAILURE_HINTS = (
    "tcp connection",
    "connection refused",
    "no route to host",
    "timed out",
    "operation timed out",
    "name or service not known",
    "no such device",
    "could not connect",
    "authentication failed",
    "unable to connect",
)


def _is_connection_failure(err: str) -> bool:
    e = (err or "").lower()
    return any(h in e for h in _CONN_FAILURE_HINTS)


def _check_circuit(device: str) -> dict | None:
    """Return fast-fail dict if device is in the cool-down window."""
    rec = _recent_failures.get(device)
    if rec is None:
        return None
    ts, last_err = rec
    age = _time.time() - ts
    if age >= _CIRCUIT_TTL_S:
        _recent_failures.pop(device, None)
        return None
    return {
        "device": device,
        "status": "error",
        "error_kind": "circuit_open",
        "error": (
            f"Device {device!r} is in connection cool-down "
            f"({age:.0f}s ago: {last_err}).  Do not retry the same "
            f"command for at least {_CIRCUIT_TTL_S - age:.0f}s — "
            f"the device is genuinely unreachable, not a transient "
            f"issue.  Treat this as definitive."
        ),
    }


def _run_on_device(device: str, command: str, timeout: int) -> dict:
    """Execute command on a single device; returns per-device result dict."""
    breaker = _check_circuit(device)
    if breaker is not None:
        return breaker
    try:
        from nornir_netmiko.tasks import netmiko_send_command
        nr = _get_nornir()
        target = nr.filter(name=device)
        if not target.inventory.hosts:
            return {"device": device, "status": "error",
                    "error": f"Device '{device}' not found in inventory"}
        result = target.run(task=netmiko_send_command, command_string=command, read_timeout=timeout)
        host_result = result[device]
        if host_result.failed:
            err = str(host_result.exception or "Command failed")
            if _is_connection_failure(err):
                _recent_failures[device] = (_time.time(), err)
            return {"device": device, "status": "error", "error": err}
        return {"device": device, "status": "success", "output": host_result.result}
    except Exception as e:
        err = str(e)
        if _is_connection_failure(err):
            _recent_failures[device] = (_time.time(), err)
        return {"device": device, "status": "error", "error": err}


# ── Tool ──────────────────────────────────────────────────────────────────────

@tool
def execute_cli_parallel(
    devices: list[str],
    command: str,
    timeout: int = 30,
) -> dict:
    """Execute a CLI command on multiple devices in parallel via Nornir.

    ⚠️  FALLBACK TOOL. Use execute_sql first. Only use when live data is required.

    Same whitelist/blacklist as execute_cli: commands table is checked before
    any connection is attempted. Blocked commands are rejected for all devices.

    Args:
        devices: List of device hostnames (alphanumerics, hyphens, underscores, dots)
        command: CLI command to run on every device
        timeout: Per-device timeout in seconds (default 30, max 120)

    Returns:
        {
            "status": "success" | "blocked" | "partial",
            "total": N,
            "successful": N,
            "failed": N,
            "results": [{"device": "R1", "status": "success", "output": "..."}],
            "warning": "..."  (if command not in registry)
        }
    """
    timeout = min(max(timeout, 5), 120)

    # Reject empty devices list up front — LLMs sometimes hallucinate
    # a "scan everything" call by passing devices=[]; that's not what
    # this tool does (it's targeted CLI execution).  Returning a clean
    # error is cheaper than a stack trace from ThreadPoolExecutor.
    if not devices:
        return {
            "status": "error",
            "error_kind": "empty_devices",
            "message": (
                "execute_cli_parallel requires at least one device "
                "hostname.  This tool runs a CLI command on named "
                "devices; it does not auto-discover."
            ),
            "total": 0, "successful": 0, "failed": 0, "results": [],
        }

    # Validate command once (shared across all devices)
    cmd_check = _validate_command(command)
    if not cmd_check["ok"]:
        return {
            "status": "blocked",
            "reason": cmd_check["reason"],
            "total": len(devices),
            "successful": 0,
            "failed": len(devices),
            "results": [],
        }

    # Validate device names
    results = []
    valid_devices = []
    for d in devices:
        check = _validate_device(d)
        if not check["ok"]:
            results.append({"device": d, "status": "error", "error": check["reason"]})
        else:
            valid_devices.append(d)

    # Execute in parallel — but skip pool entirely when there is
    # nothing to run.  ThreadPoolExecutor(max_workers=0) raises
    # ValueError; this happened when an LLM called the tool with an
    # empty / all-invalid devices list.
    if valid_devices:
        with ThreadPoolExecutor(max_workers=min(len(valid_devices), 20)) as pool:
            futures = {pool.submit(_run_on_device, d, command, timeout): d for d in valid_devices}
            for future in as_completed(futures):
                results.append(future.result())

    # Sort by device name for deterministic output
    results.sort(key=lambda r: r["device"])

    success_count = sum(1 for r in results if r["status"] == "success")
    failed_count = len(results) - success_count
    overall = "success" if failed_count == 0 else ("partial" if success_count > 0 else "error")

    out: dict = {
        "status": overall,
        "total": len(devices),
        "successful": success_count,
        "failed": failed_count,
        "results": results,
    }
    if cmd_check.get("warning"):
        out["warning"] = cmd_check["warning"]
    return out
