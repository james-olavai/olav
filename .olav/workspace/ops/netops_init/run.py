#!/usr/bin/env python3
"""
/netops_init — Full network discovery and SSH collection pipeline.

Stages:
  1. Environment check (Nornir config, nornir-netmiko installed)
  2. Device inventory load (hosts.yaml)
  3. SSH collection (discovery commands on all devices in parallel)
  4. Report (summary per device, parse rate, topology hint)

Usage:
  olav --agent ops "/netops_init"             # Full collection
  olav --agent ops "/netops_init --dry-run"   # Env check only, no SSH
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# ── Bootstrap ──────────────────────────────────────────────────────────────

def _find_project_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    # Fallback: look for .olav/workspace
    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / ".olav" / "workspace").exists():
            return parent
    return Path.cwd()


_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _find_project_root()
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

# ── Discovery command list ──────────────────────────────────────────────────

DISCOVERY_COMMANDS = [
    "show version",
    "show interfaces",
    "show ip interface brief",
    "show cdp neighbors detail",
    "show lldp neighbors detail",
    "show bgp summary",
    "show bgp all summary",
    "show ip bgp summary",
    "show ip ospf neighbors",
    "show ip route",
    "show ip arp",
    "show vlan brief",
    "show spanning-tree",
    "show running-config",
]

# ── Stage helpers ──────────────────────────────────────────────────────────

def _check_environment() -> tuple[bool, list[str]]:
    """Stage 1: verify nornir config and packages."""
    issues = []

    # Check nornir-netmiko
    try:
        import nornir  # noqa: F401
        import nornir_netmiko  # noqa: F401
    except ImportError as e:
        issues.append(f"Missing dependency: {e}. Run: pip install nornir nornir-netmiko")

    # Check nornir config
    try:
        from olav.core.config import _resolve_nornir_config_path
        cfg = _resolve_nornir_config_path()
        hosts = cfg.parent / "hosts.yaml"
        if not hosts.exists():
            issues.append(
                f"hosts.yaml not found at {hosts}. "
                f"Copy from: .olav/workspace/ops/probe/config/nornir/hosts.yaml.example"
            )
        else:
            # Count devices
            import yaml
            with open(hosts) as f:
                data = yaml.safe_load(f) or {}
            device_count = len(data)
            if device_count == 0:
                issues.append(f"hosts.yaml at {hosts} contains no devices")
            else:
                print(f"  ✓ Nornir config: {cfg}")
                print(f"  ✓ Devices found: {device_count} ({', '.join(list(data.keys())[:6])}{'...' if device_count > 6 else ''})")
    except Exception as e:
        issues.append(f"Nornir config error: {e}")

    return len(issues) == 0, issues


def _load_devices() -> list[str]:
    """Stage 2: load device names from nornir inventory."""
    from olav.core.config import _resolve_nornir_config_path
    import yaml

    cfg = _resolve_nornir_config_path()
    hosts = cfg.parent / "hosts.yaml"
    with open(hosts) as f:
        data = yaml.safe_load(f) or {}
    return list(data.keys())


def _run_collection(devices: list[str], commands: list[str]) -> dict:
    """Stage 3: SSH collection via Nornir."""
    import sys
    # Reuse take_snapshot logic
    _tools_dir = _SCRIPT_DIR.parent / "tools"
    if str(_tools_dir) not in sys.path:
        sys.path.insert(0, str(_tools_dir))

    # Import inline to avoid langchain decorator at import time
    import importlib.util

    spec = importlib.util.spec_from_file_location("take_snapshot", _tools_dir / "take_snapshot.py")
    mod = importlib.util.load_from_spec(spec) if hasattr(importlib.util, "load_from_spec") else None

    # Direct nornir execution (simpler path)
    from nornir import InitNornir
    from nornir_netmiko.tasks import netmiko_send_command
    from olav.core.config import _resolve_nornir_config_path, MAIN_DB_PATH, SNAPSHOTS_DIR
    import duckdb
    import json
    import uuid
    from datetime import datetime

    now = datetime.now()
    snapshot_id = f"snap_{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    snapshot_date = now.strftime("%Y-%m-%d")

    nornir_cfg = str(_resolve_nornir_config_path())
    nr = InitNornir(config_file=nornir_cfg, logging={"enabled": False})

    # Filter to requested devices
    target = nr.filter(filter_func=lambda h: h.name in devices)

    results_summary = []
    total_ok = 0
    total_fail = 0

    for cmd in commands:
        print(f"  → Collecting: {cmd} ... ", end="", flush=True)
        try:
            result = target.run(task=netmiko_send_command, command_string=cmd)
            cmd_ok = 0
            cmd_fail = 0
            rows_to_insert = []

            for host, multi in result.items():
                if multi.failed:
                    cmd_fail += 1
                    results_summary.append({"device": host, "command": cmd, "status": "failed",
                                            "error": str(multi.exception)[:100]})
                    continue
                raw_output = multi[0].result or ""
                cmd_ok += 1
                raw_dir = SNAPSHOTS_DIR / snapshot_date / "raw" / host
                raw_dir.mkdir(parents=True, exist_ok=True)
                safe_cmd = cmd.replace(" ", "_").replace("/", "_")[:60]
                (raw_dir / f"{safe_cmd}.txt").write_text(raw_output)

                # Try TextFSM parse
                parsed_data = None
                parsed_rows = 0
                try:
                    from olav.core.ingest_manager import IngestManager
                    mgr = IngestManager()
                    platform = nr.inventory.hosts[host].platform or "cisco_ios"
                    parsed = mgr.parse_output(platform, cmd, raw_output)
                    if parsed:
                        parsed_data = json.dumps(parsed)
                        parsed_rows = len(parsed) if isinstance(parsed, list) else 1
                except Exception:
                    pass

                rows_to_insert.append({
                    "snapshot_id": snapshot_id,
                    "snapshot_date": snapshot_date,
                    "device_name": host,
                    "command": cmd,
                    "raw_output": raw_output,
                    "parsed_data": parsed_data,
                })
                results_summary.append({"device": host, "command": cmd,
                                        "status": "success", "parsed_rows": parsed_rows})

            # Write to DuckDB
            if rows_to_insert:
                with duckdb.connect(str(MAIN_DB_PATH)) as conn:
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS parsed_outputs (
                            snapshot_id TEXT, snapshot_date DATE, device_name TEXT,
                            command TEXT, raw_output TEXT, parsed_data JSON,
                            created_at TIMESTAMP DEFAULT current_timestamp
                        )
                    """)
                    for row in rows_to_insert:
                        conn.execute(
                            "INSERT INTO parsed_outputs VALUES (?,?,?,?,?,?,current_timestamp)",
                            [row["snapshot_id"], row["snapshot_date"], row["device_name"],
                             row["command"], row["raw_output"], row["parsed_data"]]
                        )
            total_ok += cmd_ok
            total_fail += cmd_fail
            print(f"✓ {cmd_ok} devices, {cmd_fail} failures")
        except Exception as e:
            total_fail += len(devices)
            print(f"✗ ERROR: {e}")

    return {
        "snapshot_id": snapshot_id,
        "snapshot_date": snapshot_date,
        "devices": len(devices),
        "commands": len(commands),
        "successful": total_ok,
        "failed": total_fail,
        "results": results_summary,
    }


# ── Main ───────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(prog="netops_init",
                                     description="Full network discovery pipeline")
    parser.add_argument("--dry-run", action="store_true",
                        help="Check environment only — no SSH connections")
    parser.add_argument("--commands", nargs="+",
                        help="Override discovery commands (default: built-in list)")
    args = parser.parse_args()

    print("\n🔍 Stage 1: Environment Check")
    t0 = time.time()
    ok, issues = _check_environment()
    if not ok:
        for issue in issues:
            print(f"  ✗ {issue}")
        print("\n❌ Environment check failed — fix issues above before running /netops_init")
        return 1
    print(f"  ✓ Environment OK ({time.time() - t0:.1f}s)")

    if args.dry_run:
        devices = _load_devices()
        cmds = args.commands or DISCOVERY_COMMANDS
        print(f"\n✅ Dry-run complete:")
        print(f"  Devices  : {len(devices)} ({', '.join(devices)})")
        print(f"  Commands : {len(cmds)}")
        print(f"  Nornir   : config loaded, SSH NOT executed (dry-run)")
        return 0

    print("\n📋 Stage 2: Loading Device Inventory")
    devices = _load_devices()
    print(f"  ✓ {len(devices)} devices: {', '.join(devices)}")

    cmds = args.commands or DISCOVERY_COMMANDS
    print(f"\n🔌 Stage 3: SSH Collection ({len(cmds)} commands × {len(devices)} devices)")
    t1 = time.time()
    result = _run_collection(devices, cmds)
    elapsed = time.time() - t1

    print(f"\n📊 Stage 4: Summary")
    print(f"  Snapshot ID : {result['snapshot_id']}")
    print(f"  Devices     : {result['devices']}")
    print(f"  Commands    : {result['commands']}")
    print(f"  Successful  : {result['successful']}")
    print(f"  Failed      : {result['failed']}")
    print(f"  Elapsed     : {elapsed:.1f}s")

    if result['failed'] > 0:
        print("\n⚠️  Some collections failed — check credentials in hosts.yaml / defaults.yaml")
        failed = [r for r in result['results'] if r['status'] == 'failed']
        for r in failed[:5]:
            print(f"  {r['device']} / {r['command']}: {r.get('error', 'unknown')}")
        return 2

    print(f"\n✅ Network initialization complete — DB populated, run 'olav \"show BGP status\"' to query")
    return 0


if __name__ == "__main__":
    sys.exit(main())
