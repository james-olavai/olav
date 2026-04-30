#!/usr/bin/env python3
"""Fault injection: OSPF area mismatch — neighbour stuck in Init/ExStart.

Tests the layered diagnostic guide on a NON-BGP protocol.  R1 is
configured for OSPF on ge-0/0/2 in area 0.  Change to a different
area; R3 (still in area 0) refuses to form full adjacency.

Per the layered guide's state-to-layer table:
  OSPF `Init`   → L3 hello received, reply not (often area/network-type)
  OSPF `2-WAY`  → L7 DR/BDR (normal in multi-access)
  OSPF `ExStart` → L3 MTU mismatch
  OSPF area mismatch usually shows as `Init` — peer hellos visible
  but the local router rejects them due to area parameter mismatch.

Usage:
    python ospf_area_mismatch.py inject --device R1
    python ospf_area_mismatch.py revert --device R1
    python ospf_area_mismatch.py status --device R1
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from netmiko import ConnectHandler
except ImportError:
    print("ERROR: netmiko not installed. Run: pip install netmiko", file=sys.stderr)
    sys.exit(2)


DEVICES: dict[str, dict] = {
    "R1": {
        "device_type": "juniper",
        "host": "192.168.100.101",
        "username": "cisco",
        "password": "<redacted-lab-password>",
        "port": 22,
    },
}

# Per-device target — OSPF interface to mutate area on
OSPF_TARGETS: dict[str, dict] = {
    "R1": {
        "interface": "ge-0/0/2.0",
        "original_area": "0.0.0.0",
        "wrong_area": "0.0.0.99",  # nonsense area; neighbour stays out
    },
}

STATE_DIR = Path.home() / ".olav-state" / "fault_runs"


def _state_path(device: str) -> Path:
    return STATE_DIR / f"{device}_ospf_area_mismatch.json"


def _connect(device: str):
    if device not in DEVICES:
        raise SystemExit(f"Unknown device {device!r}. Known: {list(DEVICES)}")
    return ConnectHandler(**DEVICES[device])


def cmd_inject(args) -> int:
    state_file = _state_path(args.device)
    if state_file.exists() and not args.force:
        print(f"⚠️  fault already active per {state_file}.  Run 'revert' or use --force.")
        return 1

    target = OSPF_TARGETS.get(args.device)
    if not target:
        raise SystemExit(f"No OSPF target for {args.device}.")

    print(f"→ connecting to {args.device}…")
    conn = _connect(args.device)
    try:
        pre_neighbors = conn.send_command("show ospf neighbor")
        pre_config = conn.send_command("show configuration protocols ospf")

        # Confirm pre-state has the expected area + neighbour
        if target["original_area"] not in pre_config:
            raise SystemExit(
                f"ERROR: expected area {target['original_area']} not in pre-config.  "
                f"Aborting (state must be canonical).\n\n{pre_config}"
            )

        STATE_DIR.mkdir(parents=True, exist_ok=True)
        state = {
            "scenario": "ospf_area_mismatch",
            "device": args.device,
            "interface": target["interface"],
            "original_area": target["original_area"],
            "wrong_area": target["wrong_area"],
            "injected_at": datetime.now(timezone.utc).isoformat(),
            "platform": DEVICES[args.device]["device_type"],
            "pre_neighbors_excerpt": pre_neighbors[:1500],
            "pre_config_excerpt": pre_config[:1000],
            "revert_commands": [
                f"delete protocols ospf area {target['wrong_area']} interface {target['interface']}",
                f"set protocols ospf area {target['original_area']} interface {target['interface']}",
            ],
        }

        # Junos: move interface from area 0 to area 99
        commands = [
            f"delete protocols ospf area {target['original_area']} interface {target['interface']}",
            f"set protocols ospf area {target['wrong_area']} interface {target['interface']}",
        ]
        print(f"→ injecting fault on {args.device}: OSPF area "
              f"{target['original_area']} → {target['wrong_area']} on {target['interface']}")
        result = conn.send_config_set(commands, exit_config_mode=False)
        print(result[-300:])
        commit = conn.commit()
        print(commit[-200:])

        state_file.write_text(json.dumps(state, indent=2))
        print(f"✓ state saved → {state_file}")
        print()
        try:
            conn.exit_config_mode()
        except Exception as exc:
            print(f"  (non-fatal: exit_config_mode: {exc})")
        print(f"⏱  waiting 12s for OSPF dead-timer to clear neighbours…")
        time.sleep(12)
        try:
            print("=== post-injection OSPF neighbors ===")
            print(conn.send_command("show ospf neighbor"))
        except Exception as exc:
            print(f"  (non-fatal post-state read: {exc})")
        print()
        print(f"💉 INJECTION COMPLETE.  Run 'revert' to restore area {target['original_area']}.")
    finally:
        conn.disconnect()
    return 0


def cmd_revert(args) -> int:
    state_file = _state_path(args.device)
    if not state_file.exists():
        print(f"⚠️  no active fault state at {state_file}.  Nothing to revert.")
        return 1

    state = json.loads(state_file.read_text())
    print(f"→ reverting on {args.device} (injected {state['injected_at']})")
    print(f"  scenario: {state['scenario']}")
    print(f"  restoring area: {state['wrong_area']} → {state['original_area']}")

    conn = _connect(args.device)
    try:
        result = conn.send_config_set(state["revert_commands"], exit_config_mode=False)
        print(result[-300:])
        commit = conn.commit()
        print(commit[-200:])
        try:
            conn.exit_config_mode()
        except Exception as exc:
            print(f"  (non-fatal: exit_config_mode: {exc})")
    finally:
        conn.disconnect()

    print()
    print("⏱  waiting 12s for OSPF to re-converge…")
    time.sleep(12)

    verify_conn = _connect(args.device)
    try:
        post_neighbors = verify_conn.send_command("show ospf neighbor")
        print("=== post-revert OSPF neighbors ===")
        print(post_neighbors)
        post_config = verify_conn.send_command("show configuration protocols ospf")
        if state["wrong_area"] in post_config:
            print(f"⚠️  WARNING: wrong area {state['wrong_area']} still in config.  "
                  f"State file kept for re-revert.")
            return 2
        if state["original_area"] not in post_config:
            print(f"⚠️  WARNING: original area {state['original_area']} not restored.  "
                  f"State file kept.")
            return 2
    finally:
        verify_conn.disconnect()

    archive_dir = state_file.parent / "completed"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archived = archive_dir / f"{state_file.stem}_{int(time.time())}.json"
    state_file.rename(archived)
    print(f"\n✓ revert complete.  Audit trail → {archived}")
    return 0


def cmd_status(args) -> int:
    state_file = _state_path(args.device)
    if state_file.exists():
        state = json.loads(state_file.read_text())
        print(f"💉 ACTIVE FAULT on {args.device}:")
        print(f"   scenario: {state['scenario']}")
        print(f"   {state['original_area']} → {state['wrong_area']} on {state['interface']}")
        print(f"   injected_at: {state['injected_at']}")
        print(f"   state file: {state_file}")
        return 0
    print(f"✓ no active fault on {args.device}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="action", required=True)

    p_inject = sub.add_parser("inject", help="apply OSPF area mismatch")
    p_inject.add_argument("--device", required=True, choices=list(DEVICES))
    p_inject.add_argument("--force", action="store_true",
                          help="overwrite existing state file")
    p_inject.set_defaults(func=cmd_inject)

    p_revert = sub.add_parser("revert", help="restore original area")
    p_revert.add_argument("--device", required=True, choices=list(DEVICES))
    p_revert.set_defaults(func=cmd_revert)

    p_status = sub.add_parser("status", help="show whether a fault is active")
    p_status.add_argument("--device", required=True, choices=list(DEVICES))
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
