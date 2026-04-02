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
import re
import socket
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from functools import lru_cache
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


try:
    from olav.services.netconf_collector import NetconfCollector, resolve_oc_domains

    _HAS_NETCONF = True
except ImportError:
    NetconfCollector = None  # type: ignore[assignment, misc]
    resolve_oc_domains = None  # type: ignore[assignment, misc]
    _HAS_NETCONF = False

# ---------------------------------------------------------------------------
# NETCONF Platform Map — loaded from config YAML at import time.
# To add a new platform: edit .olav/config/protocol_platform_map.yaml — no code changes.
# ---------------------------------------------------------------------------

def _load_protocol_platform_maps() -> tuple[dict[str, str], dict[str, str]]:
    """Load NETCONF_PLATFORM_MAP from config YAML.

    Falls back to empty dict (Scrapli/Netmiko-only) if the file is missing.
    """
    try:
        import yaml as _yaml  # noqa: PLC0415

        _p = Path(__file__).resolve()
        for _parent in [_p.parent, *_p.parents]:
            _candidate = _parent / ".olav" / "config" / "protocol_platform_map.yaml"
            if _candidate.exists():
                _data = _yaml.safe_load(_candidate.read_text()) or {}
                return {}, dict(_data.get("netconf", {}))
    except Exception:
        pass
    return {}, {}


_UNUSED, NETCONF_PLATFORM_MAP = _load_protocol_platform_maps()

# ---------------------------------------------------------------------------
# Self-contained path + settings resolution
# Falls back to framework imports when available; works standalone otherwise.
# ---------------------------------------------------------------------------


def _find_project_root() -> Path:
    """Walk up from this file and return the outermost pyproject.toml root."""
    p = Path(__file__).resolve().parent
    found = None
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            found = p
        p = p.parent
    if found is not None:
        return found
    return Path(__file__).resolve().parents[5]


_PROJECT_ROOT = _find_project_root()  # /home/yhvh/Olav
_OLAV_DIR = _PROJECT_ROOT / ".olav"  # .olav/
_SYNC_DIR = _PROJECT_ROOT / "exports" / "snapshots"  # exports/snapshots/


def _get_scrapli_timeout_ops() -> int:
    """Read scrapli_timeout_ops from settings.json (netops-private, DC-1 compliant)."""
    try:
        import json as _j

        data = _j.loads((_OLAV_DIR / "config" / "settings.json").read_text(encoding="utf-8"))
        return int(data.get("execution", {}).get("scrapli_timeout_ops", 30))
    except Exception:
        return 30


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
            scrapli_timeout_ops=_get_scrapli_timeout_ops(),
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
        import os

        settings = get_settings()
        config_file = Path(settings.agent_dir) / "config" / "nornir" / "config.yaml"
        original_cwd = os.getcwd()
        try:
            os.chdir(_PROJECT_ROOT)
            _nornir_instance = InitNornir(config_file=str(config_file.resolve()))
        finally:
            os.chdir(original_cwd)
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
# ── Empty-feature filter ──────────────────────────────────────────────────────
# Patterns that indicate a feature is simply not configured/enabled on the
# device.  These are NOT parse gaps — the device legitimately has no data.
_NOT_CONFIGURED_PATTERNS: tuple[str, ...] = (
    # Generic patterns
    "not configured",
    "not enabled",
    "not running",
    "not active",
    "no entries",
    "no routes",
    "no neighbors",
    "no peers",
    "0 routes",
    "0 entries",
    "0 neighbors",
    "0 peers",
    # Cisco patterns
    "snmp agent not enabled",
    "agent not enabled",
    "mpls not",
    "dmvpn not",
    "vrrp is not",
    "bgp not active",
    "ospf is not enabled",
    "nve not",
    "nve is not",
    "dhcp is not",
    "cluster is not",
    "cluster is not enabled",
    # Juniper patterns
    "rsvp not configured",
    "lacp subsystem not running",
    "chassis cluster is not enabled",
    "chassis cluster not enabled",
    # Generic
    "not supported",
    "feature not available",
    "command not available",
)

_EXPLICIT_EMPTY_SUMMARY_PATTERNS: tuple[str, ...] = (
    r"total\s+(?:cdp|lldp)?\s*entries\s+displayed\s*:\s*0\b",
    r"total\s+entries\s*:\s*0\b",
)

# ── Priority map by command category ─────────────────────────────────────────
_P0_CATEGORIES: frozenset[str] = frozenset({"bgp", "ospf", "interfaces", "neighbors", "routing"})
_P1_CATEGORIES: frozenset[str] = frozenset({"arp", "switching", "system", "mac"})

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


def _is_empty_feature(raw_text: str, size: int) -> bool:
    """Return True when output indicates a feature is simply not configured.

    These cases are NOT parse gaps — they are expected empty responses.
    Caller should return ``None`` from gap detection (no error to report).
    """
    if size < 150:
        return True  # Trivially small → feature absent or command not applicable
    txt_lower = raw_text.lower()
    if any(p in txt_lower for p in _NOT_CONFIGURED_PATTERNS):
        return True
    return any(re.search(pattern, txt_lower) for pattern in _EXPLICIT_EMPTY_SUMMARY_PATTERNS)


def _is_wrap_artifact(raw_text: str) -> bool:
    """Detect terminal-width 80-col line wrapping (e.g. Juniper vJunos/EVE-NG).

    Heuristic: if ≥2 lines end mid-word at column 78+ AND the next line
    continues with a lowercase letter (no leading indent = not a new field),
    the raw output was truncated by the terminal — re-collection will fix it.
    """
    lines = raw_text.splitlines()
    wrap_count = 0
    for i in range(len(lines) - 1):
        line = lines[i]
        next_line = lines[i + 1].lstrip()
        # Mid-word wrap: line hits col boundary AND continuation is lowercase
        if len(line) >= 78 and line[-1].isalnum() and next_line and next_line[0].islower():
            wrap_count += 1
    return wrap_count >= 2


def _detect_parse_quality_gap(
    raw_text: str,
    command: str,
    parsed_data: str,
) -> dict | None:
    """Detect whether parsed_data represents a quality gap.

    Returns a dict with {severity, error_type, reason, ...} if a gap is
    detected, or ``None`` if the output is either healthy or expectedly empty.

    Detection order:
    1. ≥1 real rows in parsed_data → no gap.
    2. ``_is_empty_feature()``  → feature not configured → return None (silent).
    3. ``_is_wrap_artifact()``  → Juniper 80-col wrap → collection_wrap HIGH.
    4. Category keyword match   → zero_rows_semantic HIGH.
    5. Large output (>300 B)    → zero_rows_generic MEDIUM.
    """
    import json as _json

    # 1. Healthy data — no gap
    try:
        parsed = _json.loads(parsed_data) if isinstance(parsed_data, str) else parsed_data
        if isinstance(parsed, list) and len(parsed) > 0:
            return None
        if isinstance(parsed, dict) and parsed and "raw" not in parsed:
            return None
    except Exception:
        pass

    txt_lower = raw_text.lower()
    size = len(raw_text.encode("utf-8", errors="replace"))

    # 2. Feature simply not configured — silent skip
    if _is_empty_feature(raw_text, size):
        return None

    # 3. Terminal line-wrap artifact — flag for re-collection, not LLM repair
    if _is_wrap_artifact(raw_text):
        return {
            "severity": "high",
            "error_type": "collection_wrap",
            "category": _infer_category_from_command(command),
            "matched_keywords": [],
            "reason": "Terminal width wrap detected (≥78-col line ending mid-word). Re-collect needed.",
            "size": size,
        }

    category = _infer_category_from_command(command)
    signatures = CATEGORY_SIGNATURES.get(category, [])
    has_signature = any(sig in txt_lower for sig in signatures) if signatures else False

    # 4. Data keywords present but 0 rows → real template gap
    if has_signature:
        matched = [sig for sig in signatures if sig in txt_lower][:3]
        return {
            "severity": "high",
            "error_type": "zero_rows_semantic",
            "category": category,
            "matched_keywords": matched,
            "reason": f"Keywords found ({matched}) but JSON empty — template regex gap",
            "size": size,
        }

    # 5. Large output, no keywords → suspicious but unclassified
    if size > 300:
        return {
            "severity": "medium",
            "error_type": "zero_rows_generic",
            "category": category,
            "matched_keywords": [],
            "reason": f"Large output ({size}B) but JSON empty — possible parse gap",
            "size": size,
        }

    return None


def _get_priority_for_gap(gap: dict) -> str:
    """Map a gap dict to a repair queue priority level."""
    category = gap.get("category", "general")
    if category in _P0_CATEGORIES:
        return "P0_core"
    if category in _P1_CATEGORIES:
        return "P1_important"
    return "P2_optional"


def _write_repair_queue(
    gaps: list[dict],
    snapshot_id: str,
    device_platforms: dict[str, str],
) -> None:
    """Persist gap list as a structured repair_queue.json.

    Groups gaps by (platform, command) so each unique template bug appears
    once.  Multiple devices hitting the same NTC template bug are listed as
    ``affected_devices`` with one ``sample_device`` chosen for LLM repair.

    Writes to: ``.olav/config/repair_queue.json``
    """
    import json as _json
    from datetime import datetime

    if not gaps:
        return

    # Group gaps by (platform, command) — template bugs are platform-level
    grouped: dict[tuple[str, str], dict] = {}
    for g in gaps:
        device = g.get("device", "")
        command = g.get("command", "")
        platform = device_platforms.get(device, "")
        key = (platform, command)
        if key not in grouped:
            grouped[key] = {
                "platform": platform,
                "command": command,
                "error_type": g.get("error_type", "zero_rows_generic"),
                "priority": _get_priority_for_gap(g),
                "severity": g.get("severity", "medium"),
                "affected_devices": [],
                "raw_file": g.get("raw_file", ""),
                "raw_size": g.get("size", 0),
                "reason": g.get("reason", ""),
                "matched_keywords": g.get("matched_keywords", []),
            }
        grouped[key]["affected_devices"].append(device)

    queue: list[dict] = []
    for (platform, command), entry in grouped.items():
        error_type = entry["error_type"]
        status = "pending_recollect" if error_type == "collection_wrap" else "pending_repair"
        cmd_slug = command.replace(" ", "_").replace("-", "_")
        entry_id = f"{platform}__{cmd_slug}"
        # Use the first device as sample for LLM repair
        sample_device = entry["affected_devices"][0] if entry["affected_devices"] else ""
        queue.append(
            {
                "id": entry_id,
                "platform": platform,
                "command": command,
                "error_type": error_type,
                "priority": entry["priority"],
                "status": status,
                "affected_devices": sorted(set(entry["affected_devices"])),
                "sample_device": sample_device,
                "raw_file": entry["raw_file"],
                "raw_size": entry["raw_size"],
                "attempt_count": 0,
                "reason": entry["reason"],
                "matched_keywords": entry["matched_keywords"],
            }
        )

    # Sort: P0 first, then by command name
    priority_order = {"P0_core": 0, "P1_important": 1, "P2_optional": 2}
    queue.sort(key=lambda x: (priority_order.get(x["priority"], 9), x["command"]))

    summary = {
        "total_gaps": len(queue),
        "P0_core": sum(1 for q in queue if q["priority"] == "P0_core"),
        "P1_important": sum(1 for q in queue if q["priority"] == "P1_important"),
        "P2_optional": sum(1 for q in queue if q["priority"] == "P2_optional"),
        "collection_wrap": sum(1 for q in queue if q["error_type"] == "collection_wrap"),
        "textfsm_exception": sum(1 for q in queue if q["error_type"] == "textfsm_exception"),
        "zero_rows_semantic": sum(1 for q in queue if q["error_type"] == "zero_rows_semantic"),
    }

    output = {
        "schema_version": 1,
        "snapshot_id": snapshot_id,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": "onboard",
        "summary": summary,
        "queue": queue,
    }

    from olav.core.config import CONFIG_DIR

    out_path = Path(CONFIG_DIR / "repair_queue.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(
        "_write_repair_queue: %d entries written to %s (%s)",
        len(queue),
        out_path.name,
        summary,
    )


def _load_command_strategy(platform: str) -> dict:
    """Load command intents and platform metadata for a specific platform."""
    import yaml

    from olav.core.config import CONFIG_DIR

    config_path = Path(CONFIG_DIR / "command_strategy.yaml")
    try:
        with open(config_path, encoding="utf-8") as f:
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


def _classify_transport_result(result_text: str) -> str:
    """Classify a workflow result string by collection transport."""
    if "NETCONF Success" in result_text:
        return "netconf"
    if "Scrapli Success" in result_text:
        return "scrapli"
    if "Netmiko Fallback" in result_text:
        return "netmiko"
    return "disconnected"


def _write_api_collected_domains(
    *,
    device_dir: Path,
    host_name: str,
    snapshot_id: str,
    domain_prefix: str,
    collected_domains: dict[str, dict],
) -> None:
    """Persist API-collected structured payloads and staging records."""
    import json as _json

    for domain, data in collected_domains.items():
        json_file = device_dir / f"{domain_prefix}_{domain}.json"
        json_file.write_text(
            _json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    try:
        from olav.core.config import SNAPSHOTS_DIR

        staging_dir = Path(SNAPSHOTS_DIR) / "json"
    except ImportError:
        staging_dir = _SYNC_DIR / "json"

    staging_dir.mkdir(parents=True, exist_ok=True)
    staging_records = []
    for domain, data in collected_domains.items():
        staging_records.append(
            {
                "device_name": host_name,
                "command": f"{domain_prefix}_{domain}",
                "parsed_data": data,
                "snapshot_id": snapshot_id,
                "raw_output": _json.dumps(data, ensure_ascii=False),
            }
        )

    staging_file = staging_dir / f"{host_name}_{snapshot_id}.staging.json"
    staging_file.write_text(
        _json.dumps(staging_records, ensure_ascii=False, indent=None),
        encoding="utf-8",
    )


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
    """ACE Workflow: Try NETCONF -> Scrapli -> Netmiko."""
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
    scrapli_timeout_ops = _get_scrapli_timeout_ops()  # DC-1: netops-private, read locally

    # 1. Check if device is unreachable (from pre-check)
    if not host.data.get("tcp_reachable", True):
        host.data["ace_status"] = "DISCONNECTED"
        return Result(host=host, failed=True, result="Device unreachable (TCP 22/23)")

    # 2. Try NETCONF (Platinum Path)
    netconf_vendor = NETCONF_PLATFORM_MAP.get(host.platform or "")
    if _HAS_NETCONF and netconf_vendor:
        try:
            host.data["ace_driver"] = "netconf"
            collector = NetconfCollector(
                host=host.hostname,
                username=host.username or "",
                password=host.password or "",
                device_params={"name": netconf_vendor},
            )

            all_data = collector.collect_all()
            normalized_domains = (
                resolve_oc_domains(all_data) if resolve_oc_domains is not None else all_data
            )
            collected_domains: dict[str, dict] = {}
            for domain, data in normalized_domains.items():
                if data is not None:
                    collected_domains[domain] = data

            if collected_domains:
                _write_api_collected_domains(
                    device_dir=device_dir,
                    host_name=host.name,
                    snapshot_id=output_dir.parent.name,
                    domain_prefix="netconf",
                    collected_domains=collected_domains,
                )

                host.data["ace_status"] = "ACTIVE_NETCONF"
                _update_capability_cache(host.name, "netconf")
                logger.info(
                    "Host %s: NETCONF Success — %d domains collected: %s",
                    host.name,
                    len(collected_domains),
                    list(collected_domains.keys()),
                )
                return Result(
                    host=host,
                    result=f"NETCONF Success: {len(collected_domains)} domains collected",
                )

            logger.debug("Host %s: NETCONF returned no data, falling back to SSH", host.name)

        except Exception as e:
            logger.debug("NETCONF failed for %s: %s", host.name, e)
            print(f"DEBUG: NETCONF failed for {host.name}, falling back to SSH...")

    # 4. Try Scrapli (Fast Path)
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
                    cmd_filename = cmd.replace(" ", "_").replace("/", "_") + ".txt"
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

    # 5. Fallback to Netmiko (Stable Path)
    try:
        print(f"🔄 Using Netmiko for {host.name}...")
        host.data["ace_driver"] = "netmiko"
        saved = 0
        total = len(commands)

        # Platform pre-commands: disable paging/line-wrap before collection.
        # Loaded from .olav/config/platform_precommands.yaml — keyed by platform
        # prefix (first match wins). No hardcoded platform logic here.
        _platform_str = host.platform or ""
        _pre_cmds: list[str] = []
        try:
            import yaml as _yaml  # noqa: PLC0415
            from olav.core.config import AGENT_DIR as _ADIR  # noqa: PLC0415
            _precommands_file = _ADIR / "config" / "platform_precommands.yaml"
            if _precommands_file.exists():
                _pc_map: dict = _yaml.safe_load(_precommands_file.read_text()) or {}
                for _prefix, _cmds in _pc_map.items():
                    if _platform_str.startswith(str(_prefix)):
                        _pre_cmds = list(_cmds)
                        break
        except Exception:
            pass
        for pre_cmd in _pre_cmds:
            try:
                task.run(
                    task=netmiko_send_command,
                    command_string=pre_cmd,
                    read_timeout=timeout,
                    delay_factor=global_delay_factor,
                    max_loops=max_loops,
                )
            except Exception:
                pass  # Best-effort; don't abort on pre-command failure

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
                    cmd_filename = command.replace(" ", "_").replace("/", "_") + ".txt"
                    (device_dir / cmd_filename).write_text(str(res.result), encoding="utf-8")
                    saved += 1
                else:
                    print(
                        f"DEBUG: {host.name}: Command '{command}' failed or produced error output: {str(res.result)[:100]}"
                    )

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
    Falls back to direct YAML parsing if nornir Python package is not installed.

    Args:
        nr_filtered: Filtered Nornir object (legacy support, no longer used)

    Note:
        v0.11.0+: Uses InitNornir() via sync_inventory._import_devices_from_nornir()
        which is backend-agnostic (SimpleInventory / NetBox / Ansible / etc.).
        nr_filtered is kept for backward compatibility but unused.

    """
    import sys as _sys

    from olav.core.config import AGENT_DIR, MAIN_DB_PATH

    nornir_config_path = AGENT_DIR / "config" / "nornir" / "config.yaml"

    if not nornir_config_path.exists():
        logger.warning(
            f"nornir config.yaml not found at {nornir_config_path}, skipping device import"
        )
        return

    # Path 1: nornir Python library (preferred — backend-agnostic)
    try:
        _tools_dir = str(Path(__file__).parent)
        if _tools_dir not in _sys.path:
            _sys.path.insert(0, _tools_dir)
        from sync_inventory import _import_devices_from_nornir  # noqa: PLC0415

        stats = _import_devices_from_nornir(
            nornir_config_path=nornir_config_path,
            db_path=MAIN_DB_PATH,
            table_name="netops.devices",
        )
        logger.info(
            f"Devices imported (nornir): {stats['imported']} total, "
            f"roles={stats['roles_found']}, sites={stats['sites_found']}"
        )
        return
    except ModuleNotFoundError:
        logger.info("nornir not installed — falling back to direct hosts.yaml YAML parse")
    except Exception as e:
        logger.warning(f"nornir import path failed: {e} — falling back to YAML parse")

    # Path 2: Direct YAML parse of hosts.yaml (no nornir dependency)
    try:
        import yaml as _yaml
        import duckdb as _duckdb
        from datetime import datetime as _dt

        hosts_file = nornir_config_path.parent / "hosts.yaml"
        if not hosts_file.exists():
            logger.warning("hosts.yaml not found at %s, cannot import devices", hosts_file)
            return

        with open(hosts_file, encoding="utf-8") as _f:
            hosts = _yaml.safe_load(_f) or {}

        with _duckdb.connect(str(MAIN_DB_PATH)) as _con:
            imported = 0
            for name, cfg in hosts.items():
                if not isinstance(cfg, dict):
                    continue
                data = cfg.get("data") or {}
                _con.execute(
                    """
                    INSERT INTO netops.devices
                        (hostname, ip_address, platform, site, role, last_seen)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT (hostname) DO UPDATE SET
                        ip_address = EXCLUDED.ip_address,
                        platform   = EXCLUDED.platform,
                        site       = EXCLUDED.site,
                        role       = EXCLUDED.role,
                        last_seen  = EXCLUDED.last_seen
                    """,
                    [
                        name,
                        cfg.get("hostname"),
                        cfg.get("platform"),
                        data.get("site"),
                        data.get("role"),
                        _dt.now(),
                    ],
                )
                imported += 1
        logger.info("Devices imported (yaml-fallback): %d from %s", imported, hosts_file)
    except Exception as e:
        logger.warning(f"YAML-fallback device import failed: {e}")


import ipaddress as _ipaddress

# ---------------------------------------------------------------------------
# Post-TextFSM record normalization (netutils-based)
# ---------------------------------------------------------------------------

# Fields whose values are interface names — normalize with netutils
_IFACE_FIELDS = frozenset(
    {
        "interface",
        "local_interface",
        "port",
        "port_id",
        "neighbor_interface",
        "destination_interface",
        "source_interface",
        "mgmt_address_interface",
    }
)

# Fields whose values are device/hostname — strip domain suffix
_DEVICE_FIELDS = frozenset(
    {
        "neighbor_id",
        "device_id",
        "destination_device",
        "neighbor_device",
        "neighbor_name",
        "system_name",
    }
)

# Fields whose values are protocol names — uppercase
_PROTOCOL_FIELDS = frozenset({"discovery_protocol", "protocol"})


def _normalize_iface(value: str) -> str:
    """Normalize an interface name using netutils canonical form.

    Strips known LLDP port-id artifacts (e.g. 'Uni ' prefix from some Cisco
    IOS LLDP output) before passing to netutils.
    Falls back to the original value if netutils cannot parse the interface.
    """
    if not value:
        return value
    # Strip LLDP port-id prefix artifacts
    cleaned = value.strip()
    for prefix in ("Uni ", "uni "):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
    try:
        from netutils.interface import canonical_interface_name  # noqa: PLC0415

        normalized = canonical_interface_name(cleaned)
        return normalized if normalized else cleaned
    except Exception:
        return cleaned


def _normalize_parsed_records(records: list[dict]) -> list[dict]:
    """Apply post-TextFSM field normalization to a list of parsed records.

    Normalizes in-place (returns same list for convenience):
    - Interface fields → netutils canonical form
    - Device/hostname fields → strip domain suffix
    - Protocol fields → uppercase
    """
    for rec in records:
        for field, value in rec.items():
            if not isinstance(value, str):
                continue
            if field in _IFACE_FIELDS:
                rec[field] = _normalize_iface(value)
            elif field in _DEVICE_FIELDS:
                rec[field] = _strip_domain(value)
            elif field in _PROTOCOL_FIELDS:
                rec[field] = value.strip().upper()
    return records


def _is_ip(value: str | None) -> bool:
    """Return True if value is a bare IPv4 or IPv6 address."""
    if not value:
        return False
    try:
        _ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def _strip_domain(name: str | None) -> str | None:
    """Strip DNS domain suffix from a device name.

    Converts 'R3.local', 'R3.corp.example.com' → 'R3'.
    IP addresses are returned as-is (no stripping).
    Returns None unchanged so callers can still do ``if not src_dev`` checks.
    """
    if not name:
        return name
    if _is_ip(name):
        return name
    return name.split(".")[0]


# Fallback view names when the LLM-compiled _auto view does not yet exist.
_BOOTSTRAP_VIEWS: dict[str, str] = {
    "ospf_neighbors": "v_ospf_neighbors",
    "bgp_neighbors": "v_bgp_neighbors",
    "interfaces": "v_interfaces",
}


def _best_view(con, concept: str) -> str | None:
    """Return the best available view for a concept.

    Prefers the LLM-compiled _auto view (multi-vendor, multi-command).
    Falls back to the bootstrap hardcoded view.
    Returns None if neither exists.
    """
    auto = f"v_{concept}_auto"
    try:
        if con.execute("SELECT 1 FROM duckdb_views() WHERE view_name = ?", [auto]).fetchone():
            return auto
    except Exception:
        pass
    return _BOOTSTRAP_VIEWS.get(concept)


def _discover_topology_from_db(sync_date: str) -> dict:
    """Populate topology_links driven by topology_protocol_recipes (v0.12.0).

    Zero hardcoded protocol logic: each row in topology_protocol_recipes defines
    a concept, the link_type (L2/L3), how to classify link_status from the state
    field (up_keywords), and whether to resolve neighbor_ip → device_name via
    v_interfaces.  Views are selected by _best_view() which prefers _auto views.

    Adding a new protocol requires only:
        INSERT INTO topology_protocol_recipes VALUES ('isis_neighbors','L3','IS-IS','["up"]',true)
    """
    import hashlib
    import json as _json

    from olav.core.database import get_database

    db = get_database()
    stats = {"added": 0, "updated": 0}
    now = datetime.now()
    try:
        recipes = db.conn.execute("""
            SELECT concept, link_type, protocol_label, up_keywords, ip_device_resolve
            FROM topology_protocol_recipes
            ORDER BY link_type DESC
        """).fetchall()

        if not recipes:
            logger.warning("topology_protocol_recipes is empty — skipping topology ETL")
            return stats

        iface_view = _best_view(db.conn, "interfaces")

        for concept, link_type, proto_label, up_kw_json, ip_resolve in recipes:
            view = _best_view(db.conn, concept)
            if not view:
                logger.debug("No view for concept=%s, skipping", concept)
                continue
            try:
                # Introspect columns once — handle naming differences between
                # _auto views (device_name, local_interface) and bootstrap views
                # (source_device, source_interface) without failing on either.
                view_cols = {r[0] for r in db.conn.execute(f"DESCRIBE {view}").fetchall()}

                def _vcol(*candidates: str) -> str:
                    return next((c for c in candidates if c in view_cols), "NULL")

                # Batch INSERT: accumulate rows then executemany once per link_type
                batch_rows: list[list] = []

                if link_type == "L2":
                    dev_col = _vcol("device_name", "source_device")
                    if_col = _vcol("local_interface", "source_interface")
                    rows = db.conn.execute(f"""
                        SELECT {dev_col},
                               {if_col} AS src_if,
                               destination_device,
                               destination_interface AS dst_if,
                               COALESCE(discovery_protocol, '{proto_label}') AS proto
                        FROM {view}
                        WHERE destination_device IS NOT NULL
                          AND destination_device != ''
                          AND snapshot_id IN (
                              SELECT MAX(snapshot_id)
                              FROM netops.parsed_outputs
                              GROUP BY device_name
                          )
                    """).fetchall()
                    for src_dev, src_if, dst_dev, dst_if, proto in rows:
                        src_dev = _strip_domain(src_dev)
                        dst_dev = _strip_domain(dst_dev)
                        if not src_dev or not dst_dev or src_dev == dst_dev:
                            continue
                        # Canonicalize direction so A→B and B→A share the same link_id.
                        # Always store the lexicographically smaller device as source.
                        if src_dev > dst_dev:
                            src_dev, dst_dev = dst_dev, src_dev
                            src_if, dst_if = dst_if, src_if
                        link_id = hashlib.md5(
                            f"{src_dev}|{src_if or ''}|{dst_dev}|{dst_if or ''}".encode()
                        ).hexdigest()[:16]
                        batch_rows.append(
                            [link_id, src_dev, src_if, dst_dev, dst_if, proto, now, now, sync_date]
                        )
                        stats["added"] += 1

                    if batch_rows:
                        db.conn.executemany(
                            """
                            INSERT INTO netops.topology_links
                            (link_id, source_device, source_interface, destination_device,
                             destination_interface, discovery_protocol, link_type, link_status,
                             first_seen, last_seen, snapshot_id, platform, status_changes)
                            VALUES (?, ?, ?, ?, ?, ?, 'L2', 'up', ?, ?, ?, '', 0)
                            ON CONFLICT (link_id) DO UPDATE SET
                                link_status = EXCLUDED.link_status,
                                last_seen   = EXCLUDED.last_seen,
                                snapshot_id = EXCLUDED.snapshot_id
                        """,
                            batch_rows,
                        )

                elif link_type == "L3":
                    up_keywords: list[str] = _json.loads(up_kw_json) if up_kw_json else []
                    has_iface = "interface" in view_cols
                    iface_sel = "v.interface" if has_iface else "NULL"
                    _latest_snap_subq = (
                        "SELECT MAX(snapshot_id) FROM netops.parsed_outputs "
                        "GROUP BY device_name"
                    )
                    if ip_resolve and iface_view:
                        rows = db.conn.execute(f"""
                            SELECT v.device_name, {iface_sel} AS v_interface,
                                   v.neighbor_ip, v.state,
                                   COALESCE(i.device_name, v.neighbor_ip) AS dst_dev,
                                   i.interface AS dst_if
                            FROM {view} v
                            LEFT JOIN {iface_view} i ON i.ip_address = v.neighbor_ip
                            WHERE v.snapshot_id IN ({_latest_snap_subq})
                        """).fetchall()
                    else:
                        rows = db.conn.execute(f"""
                            SELECT device_name, {iface_sel} AS v_interface,
                                   neighbor_ip, state,
                                   neighbor_ip AS dst_dev, NULL AS dst_if
                            FROM {view}
                            WHERE snapshot_id IN ({_latest_snap_subq})
                        """).fetchall()
                    for src_dev, src_if, nbr_ip, state, dst_dev, dst_if in rows:
                        src_dev = _strip_domain(src_dev)
                        dst_dev = _strip_domain(dst_dev)
                        # Skip links where dst_dev is still an unresolved IP —
                        # indicates the neighbor wasn't found in the interface table.
                        # Store the record only when we have a real device name.
                        if not src_dev or not dst_dev:
                            continue
                        if _is_ip(dst_dev):
                            # Unresolved: keep the link but mark dst as IP placeholder
                            # so it's visible for debugging but doesn't pollute topology.
                            dst_dev = f"[{dst_dev}]"
                        if src_dev == dst_dev:
                            continue
                        status = (
                            "up"
                            if (
                                not up_keywords
                                or any(kw in (state or "").lower() for kw in up_keywords)
                            )
                            else "down"
                        )
                        link_id = hashlib.md5(
                            f"{proto_label}|{src_dev}|{dst_dev}".encode()
                        ).hexdigest()[:16]
                        batch_rows.append(
                            [
                                link_id,
                                src_dev,
                                src_if or "",  # empty = unknown local interface
                                dst_dev,
                                dst_if or nbr_ip or "",  # peer IP as dst_if when interface unknown
                                proto_label,
                                status,
                                now,
                                now,
                                sync_date,
                            ]
                        )
                        stats["updated"] += 1

                    if batch_rows:
                        db.conn.executemany(
                            """
                            INSERT INTO netops.topology_links
                            (link_id, source_device, source_interface, destination_device,
                             destination_interface, discovery_protocol, link_type, link_status,
                             first_seen, last_seen, snapshot_id, platform, status_changes)
                            VALUES (?, ?, ?, ?, ?, ?, 'L3', ?, ?, ?, ?, 'logical', 0)
                            ON CONFLICT (link_id) DO UPDATE SET
                                link_status        = EXCLUDED.link_status,
                                last_seen          = EXCLUDED.last_seen,
                                snapshot_id        = EXCLUDED.snapshot_id,
                                destination_device = EXCLUDED.destination_device
                        """,
                            batch_rows,
                        )

                logger.debug("topology ETL: concept=%s view=%s", concept, view)
            except Exception as _ce:
                logger.warning("topology ETL failed for concept=%s: %s", concept, _ce)

        db.conn.commit()
        logger.info(
            "Topology ETL complete: %d L2 links, %d L3 links (snapshot=%s)",
            stats["added"],
            stats["updated"],
            sync_date,
        )
    except Exception as e:
        logger.warning("Failed to discover topology from DB: %s", e)
    return stats


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
    """Scheduled full-network sync. Alias for collect_commands(wait=True).

    Collects all device data. For targeted on-demand collection
    (e.g. during troubleshooting) use collect_commands() directly with devices
    and categories parameters.

    Args:
        devices:    Device names to target. None = all inventory devices.
        categories: Command categories. None = full collection.

    Returns:
        dict with snapshot_id, parse_errors, and summary.

    """
    from collect_commands import collect_commands as _collect_commands

    # Invoke via .func to bypass LangChain tool wrapper for internal call
    return _collect_commands.func(devices=devices, categories=categories, wait=True)


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

        # sync_date format is "%Y-%m-%d_%H%M" (e.g. "2026-03-20_1216")
        try:
            start_ts = _dt.strptime(str(sync_date), "%Y-%m-%d_%H%M")
        except ValueError:
            # Fallback for date-only format (legacy / unit tests)
            start_ts = _dt.strptime(str(sync_date)[:10], "%Y-%m-%d")
        from datetime import timedelta as _td

        end_ts = start_ts + _td(seconds=duration_seconds)

        extra = _json.dumps(
            {
                "sync_dir": str(sync_dir),
                "command_count": command_count,
                "failed_count": failed_count,
                "duration_seconds": duration_seconds,
            }
        )

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
    except Exception as _meta_err:  # noqa: BLE001
        logger.warning("sync_metadata write failed (non-fatal): %s", _meta_err)


def _find_textfsm_template(platform: str, command: str) -> tuple["Path | None", str]:
    """Find the best TextFSM template for a platform + command pair.

    Search order (first match wins — higher priority first):
      1. .olav/templates/{platform}_{cmd_slug}.textfsm
      2. NTC-templates package

    Returns:
        (template_path, content) if a template file exists, else (None, "").
        An empty content string means "collect but don't parse" (empty template).
    """
    from olav.core.config import TEXTFSM_TEMPLATES_DIR

    # Build two candidate slugs:
    #   1. Hyphen-preserving (matches NTC convention: running-config, access-list)
    #   2. All-underscores fallback (legacy templates created before this fix)
    cmd_slug_hyphen = command.replace(" ", "_")  # spaces→_, hyphens kept
    cmd_slug_legacy = command.replace(" ", "_").replace("-", "_")  # all separators→_

    search_dirs: list[Path] = [
        Path(TEXTFSM_TEMPLATES_DIR),
    ]
    try:
        import ntc_templates as _ntc

        search_dirs.append(Path(_ntc.__file__).parent / "templates")
    except Exception:
        pass

    # Try hyphen-preserving name first (NTC-compatible), then legacy all-underscore
    for slug in (cmd_slug_hyphen, cmd_slug_legacy):
        template_filename = f"{platform}_{slug}.textfsm"
        for d in search_dirs:
            candidate = d / template_filename
            if candidate.is_file():
                try:
                    content = candidate.read_text(encoding="utf-8")
                except Exception:
                    content = ""
                return candidate, content

    return None, ""


@lru_cache(maxsize=4096)
def _cached_textfsm_template(platform: str, command: str) -> tuple["Path | None", str]:
    """Cached wrapper for template lookup to avoid repeated disk IO."""
    return _find_textfsm_template(platform, command)


# ---------------------------------------------------------------------------
# TextFSM compiled object cache — avoids re-parsing templates per command
# ---------------------------------------------------------------------------

import threading as _threading

import textfsm as _textfsm_mod

_textfsm_cache: dict[str, _textfsm_mod.TextFSM] = {}
_textfsm_cache_lock = _threading.Lock()


def _get_cached_textfsm(template_path: Path, template_content: str):
    """Return a TextFSM object compiled from *template_content*.

    Uses a module-level cache keyed by template file path.  A **shallow copy**
    is returned so each caller gets an independent parse state while sharing
    the compiled template (immutable after TextFSM construction).

    This avoids the per-command-per-device cost of ``TextFSM(StringIO(content))``
    which re-parses the template definition every call.
    """
    cache_key = str(template_path)
    with _textfsm_cache_lock:
        cached = _textfsm_cache.get(cache_key)
        if cached is None:
            import io as _io

            cached = _textfsm_mod.TextFSM(_io.StringIO(template_content))
            _textfsm_cache[cache_key] = cached
    # Shallow copy: shares compiled _template (immutable), isolates parse state
    import copy as _copy

    return _copy.copy(cached)


def _process_sync_stage2(sync_dir: Path, device_names: list[str]) -> list[dict]:
    """Stage 2: Import raw outputs to DuckDB parsed_outputs table.

    For each raw .txt file:
      - Tries TextFSM parsing with template priority:
          .olav/templates/  >  NTC-templates
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
    device_platforms: dict[str, str] = {}  # populated inside try; needed by _write_repair_queue

    try:
        import io as _io
        import json as _json

        from olav.core.config import SNAPSHOTS_DIR
        from olav.core.database import get_database
        from olav.core.ingest_manager import IngestManager

        try:
            import orjson as _orjson

            def _dumps(obj: object) -> str:
                return _orjson.dumps(obj).decode("utf-8")

        except Exception:

            def _dumps(obj: object) -> str:
                return _json.dumps(obj, ensure_ascii=False)

        raw_dir = sync_dir / "raw"
        sync_date_str = sync_dir.name  # e.g. "2026-02-19"

        # Staging directory — JSON files are written here and overwritten each run.
        staging_dir = Path(SNAPSHOTS_DIR) / "json"
        staging_dir.mkdir(parents=True, exist_ok=True)

        db = get_database()

        # Ensure netops schema tables exist before thread pool starts
        try:
            from olav_netops.core.tables import DevicesTable, OcOutputsTable, TopologyLinksTable
            DevicesTable().ensure_schema(db.conn)
            TopologyLinksTable().ensure_schema(db.conn)
            OcOutputsTable().ensure_schema(db.conn)
        except Exception as _e:
            logger.debug("netops schema init failed (non-fatal): %s", _e)

        # Populate netops.devices from hosts.yaml if empty — use existing connection
        # to avoid DuckDB single-writer lock conflict (new connection would fail).
        try:
            _count = db.conn.execute("SELECT COUNT(*) FROM netops.devices").fetchone()[0]
            if _count == 0:
                import yaml as _yaml  # noqa: PLC0415
                from olav.core.config import AGENT_DIR as _AGENT_DIR  # noqa: PLC0415
                from datetime import datetime as _dtnow  # noqa: PLC0415

                _hosts_file = _AGENT_DIR / "config" / "nornir" / "hosts.yaml"
                if _hosts_file.exists():
                    _hosts = _yaml.safe_load(_hosts_file.read_text(encoding="utf-8")) or {}
                    _imported = 0
                    for _hname, _hcfg in _hosts.items():
                        if not isinstance(_hcfg, dict):
                            continue
                        _hdata = _hcfg.get("data") or {}
                        db.conn.execute(
                            """
                            INSERT INTO netops.devices
                                (hostname, ip_address, platform, site, role, last_seen)
                            VALUES (?, ?, ?, ?, ?, ?)
                            ON CONFLICT (hostname) DO UPDATE SET
                                ip_address = EXCLUDED.ip_address,
                                platform   = EXCLUDED.platform,
                                site       = EXCLUDED.site,
                                role       = EXCLUDED.role,
                                last_seen  = EXCLUDED.last_seen
                            """,
                            [
                                _hname,
                                _hcfg.get("hostname"),
                                _hcfg.get("platform"),
                                _hdata.get("site"),
                                _hdata.get("role"),
                                _dtnow.now(),
                            ],
                        )
                        _imported += 1
                    db.conn.commit()
                    logger.info("Populated netops.devices from hosts.yaml: %d devices", _imported)
        except Exception as _dpe:
            logger.debug("Device table pre-populate skipped: %s", _dpe)

        # Fetch device → platform mapping from netops.devices (canonical source).
        device_platforms: dict[str, str] = {}
        try:
            rows = db.conn.execute(
                "SELECT hostname, platform FROM netops.devices WHERE platform IS NOT NULL"
            ).fetchall()
            device_platforms = {r[0]: r[1] for r in rows}
        except Exception:
            pass  # Platform lookup is advisory; raw fallback covers all cases.

        def _process_device(device_name: str) -> tuple[str, list[dict], list[dict], int, int, int]:
            device_dir = raw_dir / device_name
            if not device_dir.exists():
                logger.debug(f"Stage 2: raw dir missing for {device_name}, skipping")
                return device_name, [], [], 0, 0, 0

            platform = device_platforms.get(device_name, "")
            txt_files = sorted(device_dir.glob("*.txt"))
            parsed_count = 0
            skipped_count = 0
            error_count = 0
            staging_records: list[dict] = []  # Accumulated records for this device
            device_gaps: list[dict] = []
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
                parse_error_msg: str | None = None  # Set on TextFSM exception or 0-rows

                if platform:
                    tmpl_path, tmpl_content = _cached_textfsm_template(platform, command)
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
                                fsm = _get_cached_textfsm(tmpl_path, tmpl_content)
                                fsm_rows = fsm.ParseText(raw_output)
                                if fsm_rows:
                                    headers = [h.lower() for h in fsm.header]
                                    records = [
                                        dict(zip(headers, row, strict=False)) for row in fsm_rows
                                    ]
                                    records = _normalize_parsed_records(records)
                                    parsed_data = _dumps(records)
                                    print(
                                        f"    ✅ {command:<40} {len(records):>4} rows  ({tmpl_path.name})"
                                    )
                                    parsed_count += 1
                                else:
                                    print(
                                        f"    ⚠️  {command:<40}  0 rows  ({tmpl_path.name}) — no match"
                                    )
                                    parse_error_msg = "0 rows (no pattern match)"
                                    skipped_count += 1
                            except Exception as parse_err:
                                parse_error_msg = (
                                    f"{type(parse_err).__name__}: {str(parse_err)[:80]}"
                                )
                                print(f"    ❌ {command:<40} parse error: {parse_error_msg[:60]}")
                                error_count += 1
                    # else: no template found → raw lives on disk

                # ── Intent-driven Quality Gap Detection ────────────────────
                # Runs for non-success outcomes WITH a known template only:
                #   A) Template found + TextFSM exception     → always HIGH
                #   B) Template found + 0 rows                → keyword/size decides
                #   C) No template found                      → sync_commands bug, log WARNING only
                # NOTE: Case C is intentionally NOT reported as a gap. The commands
                # table is built entirely from template scanning, so has_template=False
                # means sync_commands and sync_tools are out of sync — not a parse gap.
                if parsed_data is None and platform:
                    if not has_template:
                        # Case C: template lookup miss — this is a sync_commands
                        # consistency issue, not a TextFSM gap. Log and skip.
                        logger.warning(
                            "sync_commands consistency issue: raw file exists for "
                            "%s/%s but no template found (platform=%s). "
                            "Run sync_commands to rebuild the command registry.",
                            device_name,
                            command,
                            platform,
                        )
                        gap_info: dict | None = None
                    elif parse_error_msg and "0 rows" not in parse_error_msg:
                        # Case A: TextFSM syntax/state error.
                        _raw_size = len(raw_output.encode("utf-8", errors="replace"))

                        # Check 1: Is this just a feature not enabled? (silent skip)
                        if _is_empty_feature(raw_output, _raw_size):
                            gap_info = None  # Feature not enabled — expected empty response
                        # Check 2: Is this caused by terminal line wrapping?
                        elif _is_wrap_artifact(raw_output):
                            _err_type = "collection_wrap"
                            _reason = f"Line wrapping detected (TextFSM error masked by truncated output): {parse_error_msg}"
                            gap_info = {
                                "severity": "high",
                                "error_type": _err_type,
                                "category": _infer_category_from_command(command),
                                "matched_keywords": [],
                                "reason": _reason,
                                "size": _raw_size,
                            }
                        # Check 3: True TextFSM syntax/state error
                        else:
                            _err_type = "textfsm_exception"
                            _reason = f"TextFSM error: {parse_error_msg}"
                            gap_info = {
                                "severity": "high",
                                "error_type": _err_type,
                                "category": _infer_category_from_command(command),
                                "matched_keywords": [],
                                "reason": _reason,
                                "size": _raw_size,
                            }
                    else:
                        # Case B: 0 rows — use keyword/size detection
                        gap_info = _detect_parse_quality_gap(raw_output, command, "[]")

                    if gap_info:
                        device_gaps.append(
                            {
                                "device": device_name,
                                "command": command,
                                "raw_file": str(txt_file),
                                **gap_info,
                            }
                        )
                        logger.info(
                            "Quality gap [%s] %s/%s: %s",
                            gap_info["severity"].upper(),
                            device_name,
                            command,
                            gap_info.get("reason", ""),
                        )
                # ────────────────────────────────────────────────────────────

                # Only insert into DB if we have actual structured data
                # Skip commands with no template, parse errors, or 0 rows
                if parsed_data is None:
                    continue  # No template or parse failed — raw file is on disk

                # ── Gap detection for SUCCESSFUL parses (partial gaps) ──────
                # Only runs when parsed_data is populated — checks if result is
                # suspiciously sparse given what the raw output contains.
                if has_template:
                    gap = _detect_parse_quality_gap(raw_output, command, parsed_data)
                    if gap:
                        device_gaps.append(
                            {
                                "device": device_name,
                                "command": command,
                                "raw_file": str(txt_file),
                                **gap,
                            }
                        )
                        logger.info(
                            "Quality gap [%s] %s/%s: %s",
                            gap["severity"].upper(),
                            device_name,
                            command,
                            gap["reason"],
                        )

                # Accumulate into staging list — written to JSON at end of device loop
                staging_records.append(
                    {
                        "device_name": device_name,
                        "command": command,
                        "parsed_data": _json.loads(parsed_data),  # native list — flat TextFSM dicts
                        "snapshot_id": sync_date_str,
                        "raw_output": raw_output,  # raw CLI text for diff engine
                    }
                )


            return (
                device_name,
                staging_records,
                device_gaps,
                parsed_count,
                skipped_count,
                error_count,
            )

        max_workers = max(1, min(len(device_names), 16))
        device_results: list[tuple[str, list[dict], list[dict], int, int, int]] = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            device_results = list(executor.map(_process_device, device_names))

        for (
            device_name,
            staging_records,
            device_gaps,
            parsed_count,
            skipped_count,
            error_count,
        ) in device_results:
            gaps.extend(device_gaps)
            # Write staging JSON for this device (minute-level timestamp for traceability)
            # Format: {device}_{YYYYMMDD_HHMM}.staging.json
            timestamp = sync_date_str.replace("-", "").replace("_", "_")  # 20260301_0945 format
            staging_file = staging_dir / f"{device_name}_{timestamp}.staging.json"
            staging_file.write_text(
                _dumps(staging_records),
                encoding="utf-8",
            )
            print(
                f"    → {device_name} summary: {parsed_count} parsed, {skipped_count} 0-rows, {error_count} errors  → {staging_file.name} ({len(staging_records)} records)"
            )

        # Bulk-load all staging files into DuckDB in one atomic read_json_auto pass
        import olav_netops.core.tables  # noqa: F401  # ensure netops table registration

        ingest_result = IngestManager(db_path=db.db_path, staging_dir=staging_dir).bulk_load()
        logger.info(
            "Stage 2 ingest: %s — %d files, %d records inserted for %s",
            ingest_result["status"],
            ingest_result.get("files_processed", 0),
            ingest_result.get("records_inserted", 0),
            sync_date_str,
        )
        if ingest_result["status"] == "success":
            # Ensure topology_protocol_recipes exists (idempotent, fast) before ETL
            try:
                import sync_schemas as _ss  # noqa: PLC0415
                _ss.sync_schemas.invoke({"force_recreate": False})
            except Exception as _schema_err:
                logger.warning("sync_schemas pre-check failed: %s", _schema_err)
            # LLM-native schema discovery: classify new commands and compile auto views
            # MUST run before topology ETL so that v_topology_l2_auto exists for CDP/LLDP links.
            try:
                import sys as _sys
                from pathlib import Path as _Path

                from olav.core.config import AGENT_DIR as _AGENT_DIR

                _candidate_dirs = [
                    _AGENT_DIR / "workspace" / "config" / "discovery" / "tools",
                    _Path(__file__).parent.parent.parent / "discovery" / "tools",
                ]
                for _candidate in _candidate_dirs:
                    if _candidate.exists() and str(_candidate) not in _sys.path:
                        _sys.path.insert(0, str(_candidate))
                from discover_view_schemas import discover_view_schemas as _dvs

                _dvs_result = _dvs.func()
                logger.info(
                    "Schema discovery: %d new recipes, views=%s",
                    _dvs_result.get("new_recipes", 0),
                    _dvs_result.get("views_compiled", []),
                )
            except Exception as _dvs_err:
                logger.warning("Schema discovery failed (non-critical): %s", _dvs_err)
            # Populate topology_links from CDP/LLDP/OSPF — runs after auto views are compiled
            try:
                _discover_topology_from_db(sync_date_str)
                logger.info("topology_links populated for snapshot %s", sync_date_str)
            except Exception as _topo_err:
                logger.warning("Failed to populate topology_links: %s", _topo_err)
        if gaps:
            high = sum(1 for g in gaps if g.get("severity") == "high")
            med = sum(1 for g in gaps if g.get("severity") == "medium")
            logger.warning(
                "Stage 2 quality gaps: %d HIGH, %d MEDIUM (total %d)", high, med, len(gaps)
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

    # Persist repair queue for onboard gap-routing
    try:
        _write_repair_queue(gaps, sync_dir.name, device_platforms)
    except Exception as _rq_err:
        logger.warning("Failed to write repair_queue.json: %s", _rq_err)

    return gaps  # Always return gaps list (may be partial on exception)
