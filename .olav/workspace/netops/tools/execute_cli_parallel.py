#!/usr/bin/env python3
"""
Execute CLI commands on multiple devices in parallel via Nornir.

Replaces execute_cli (single-device) — pass devices=["R1"] for a single device.
Same whitelist/blacklist validation as the retired execute_cli:
- check_approval gate (command-level; blocks all devices if triggered)
- Commands table: blacklisted, pipe_allowed
- Device name sanitisation
- Environment label filter (per-device; skips hosts whose tag doesn't match)
- Compact output by default (full=True for untruncated)
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

# ARCH-18 #2: compact output policy. Per-device output is trimmed to this many
# chars unless the caller passes full=True. First+last slices kept around a
# truncation marker so context is preserved at both ends.
_COMPACT_OUTPUT_CHARS = 4000


# ── Command + device validation ───────────────────────────────────────────────

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


# ── Nornir singleton ──────────────────────────────────────────────────────────

_nornir_instance = None


def _get_nornir():
    from nornir import InitNornir
    global _nornir_instance
    if _nornir_instance is None:
        config_file = _resolve_nornir_config_path()
        _nornir_instance = InitNornir(config_file=str(config_file.resolve()))
    return _nornir_instance


# ── Circuit breaker (R-VERTICAL-SLICE 2026-05-09, dev_docs/74) ───────────────
# Prevents LLM from retrying the same unreachable device 3+ times, each
# costing a full SSH timeout (~30s).

import time as _time

_CIRCUIT_TTL_S = 60.0
_recent_failures: dict[str, tuple[float, str]] = {}

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
    full: bool = False,
    environment: str | None = None,
) -> dict:
    """Execute a CLI command on one or more devices in parallel via Nornir.

    ⚠️  FALLBACK TOOL. Use execute_sql first. Only use when live data is
    required. See tool_help("execute_cli_parallel") for full usage.

    Single device: devices=["R1"]. Safety: check_approval → blacklist →
    environment filter → circuit breaker (60s TTL on failures).

    Args:
        devices:     Device hostnames. Must be non-empty.
        command:     CLI command to run on every device.
        timeout:     Per-device seconds (5–120, default 30).
        full:        Return full output (default False trims to 4 000 chars).
        environment: If set, skip devices whose Nornir tag doesn't match
                     (status="environment mismatch").

    Returns: {"status": ..., "total": N, "results": [...], "skipped": [...]}
    """
    timeout = min(max(timeout, 5), 120)

    if not devices:
        return {
            "status": "error",
            "error_kind": "empty_devices",
            "message": (
                "execute_cli_parallel requires at least one device hostname. "
                "This tool runs a CLI command on named devices; it does not auto-discover."
            ),
            "total": 0, "successful": 0, "failed": 0, "results": [],
        }

    # ── 1. Dangerous command approval gate (command-level; blocks all devices) ─
    try:
        from olav.platform.safety.approval import check_approval
        approval = check_approval(command, device=devices[0], environment=environment)
        if approval.requires_approval:
            return {
                "status": "requires_approval",
                "command": command,
                "devices": devices,
                "severity": approval.severity,
                "reason": approval.reason,
                "suggested_action": approval.suggested_action,
            }
    except ImportError:
        pass  # approval module unavailable — fail open

    # ── 2. Blacklist / pipe_allowed validation ────────────────────────────────
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

    # ── 3. Device name validation ─────────────────────────────────────────────
    results = []
    valid_devices = []
    for d in devices:
        check = _validate_device(d)
        if not check["ok"]:
            results.append({"device": d, "status": "error", "error": check["reason"]})
        else:
            valid_devices.append(d)

    # ── 4. Environment label filter (per-device) ──────────────────────────────
    skipped: list[dict] = []
    if environment is not None:
        try:
            nr = _get_nornir()
            filtered: list[str] = []
            for d in valid_devices:
                host = nr.inventory.hosts.get(d)
                host_env = (host.data or {}).get("environment") if host else None
                if host_env != environment:
                    skipped.append({
                        "device": d,
                        "status": "environment mismatch",
                        "reason": f"host env={host_env!r}, requested={environment!r}",
                    })
                else:
                    filtered.append(d)
            valid_devices = filtered
        except Exception:
            pass  # fail open if Nornir unavailable at filter stage

    # ── 5. Parallel execution ─────────────────────────────────────────────────
    # Skip pool when there is nothing to run — ThreadPoolExecutor(max_workers=0)
    # raises ValueError; this happened with empty / all-invalid device lists.
    if valid_devices:
        with ThreadPoolExecutor(max_workers=min(len(valid_devices), 20)) as pool:
            futures = {pool.submit(_run_on_device, d, command, timeout): d for d in valid_devices}
            for future in as_completed(futures):
                results.append(future.result())

    # ── 6. Compact output truncation ──────────────────────────────────────────
    if not full:
        for r in results:
            if r.get("status") == "success" and r.get("output"):
                raw = r["output"]
                if len(raw) > _COMPACT_OUTPUT_CHARS:
                    half = _COMPACT_OUTPUT_CHARS // 2
                    r["output"] = (
                        raw[:half]
                        + f"\n… [truncated at {_COMPACT_OUTPUT_CHARS} chars; re-run with full=True for complete output] …\n"
                        + raw[-half:]
                    )

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
    if skipped:
        out["skipped"] = skipped
    if cmd_check.get("warning"):
        out["warning"] = cmd_check["warning"]
    return out
