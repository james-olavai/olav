#!/usr/bin/env python3
"""Fault injection: shut down a transit interface — drops BGP via link-down.

Different failure mode from bgp_wrong_peer_ip.py: instead of changing
BGP config, we kill the L1/L2 link by disabling the interface.  The
signature in syslog is different (interface down + protocol withdrawal)
and the diagnostic path is "look at link state and physical interfaces"
rather than "look at BGP config".

Usage (same shape as bgp_wrong_peer_ip.py):

    python interface_shut.py inject --device R1
    python interface_shut.py revert --device R1
    python interface_shut.py status --device R1

Currently targets R1 (Junos) interface ge-0/0/0 — the transit link
to its Ebgp neighbour 10.1.12.2.  Auto-revertable via state file.

DO NOT shut the management interface (fxp0 on Junos / Mgmt0 on Cisco)
— that disconnects SSH and the script can't revert.
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

# Per-device target interface — the transit link, NOT mgmt
TARGET_INTERFACE: dict[str, str] = {
    "R1": "ge-0/0/0",   # BGP transit to 10.1.12.2; mgmt is fxp0
}

# Hard whitelist — refuse to ever touch these, even by typo
FORBIDDEN_INTERFACES = frozenset({
    "fxp0", "fxp1", "Mgmt0", "Mgmt1", "MgmtEthernet0", "ma1",
})

STATE_DIR = Path.home() / ".olav-state" / "fault_runs"


def _state_path(device: str) -> Path:
    return STATE_DIR / f"{device}_interface_shut.json"


def _connect(device: str):
    if device not in DEVICES:
        raise SystemExit(f"Unknown device {device!r}. Known: {list(DEVICES)}")
    return ConnectHandler(**DEVICES[device])


def cmd_inject(args) -> int:
    state_file = _state_path(args.device)
    if state_file.exists() and not args.force:
        print(f"⚠️  fault already active per {state_file}.  Run 'revert' or use --force.")
        return 1

    interface = args.interface or TARGET_INTERFACE.get(args.device)
    if not interface:
        raise SystemExit(f"No default target interface for {args.device}.  Pass --interface.")
    if interface in FORBIDDEN_INTERFACES:
        raise SystemExit(
            f"REFUSING to disable management interface {interface!r}.  "
            f"That would disconnect SSH and break revert.  Aborting."
        )

    print(f"→ connecting to {args.device}…")
    conn = _connect(args.device)
    try:
        # Pre-state for audit trail
        pre_terse = conn.send_command(
            f"show interfaces terse {interface}"
        )
        pre_bgp = conn.send_command("show bgp summary")

        # Confirm interface is currently up — refuse if already down
        # (otherwise we don't have a clean revert "to up" path)
        if " up " not in pre_terse and "\nup\n" not in pre_terse and pre_terse.count("up") < 1:
            raise SystemExit(
                f"ERROR: interface {interface} doesn't appear to be 'up' in pre-state.  "
                f"Refusing to inject — pre-state must be canonical.\n\n{pre_terse}"
            )

        # Persist state BEFORE issuing config commands so revert is preserved
        # even if SSH cleanup hiccups after commit.
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        state = {
            "scenario": "interface_shut",
            "device": args.device,
            "interface": interface,
            "injected_at": datetime.now(timezone.utc).isoformat(),
            "platform": DEVICES[args.device]["device_type"],
            "pre_terse_excerpt": pre_terse[:1000],
            "pre_bgp_excerpt": pre_bgp[:1500],
            "revert_commands": [
                f"delete interfaces {interface} disable",
            ],
        }

        # Junos: set <interface> disable
        commands = [f"set interfaces {interface} disable"]
        print(f"→ injecting fault on {args.device}: disable {interface}")
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
        print(f"⏱  waiting 8s for link + BGP state to settle…")
        time.sleep(8)
        try:
            print("=== post-injection interface state ===")
            print(conn.send_command(f"show interfaces terse {interface}"))
            print("=== post-injection BGP summary ===")
            print(conn.send_command("show bgp summary"))
        except Exception as exc:
            print(f"  (non-fatal post-state read: {exc})")
        print()
        print(f"💉 INJECTION COMPLETE.  Run 'revert' to bring {interface} back up.")
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
    print(f"  scenario: {state['scenario']}, interface: {state['interface']}")

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
    print("⏱  waiting 8s for link + BGP to re-converge…")
    time.sleep(8)

    verify_conn = _connect(args.device)
    try:
        print("=== post-revert interface state ===")
        print(verify_conn.send_command(f"show interfaces terse {state['interface']}"))
        print("=== post-revert BGP summary ===")
        print(verify_conn.send_command("show bgp summary"))

        # Verify the disable directive is gone
        post_config = verify_conn.send_command(
            f"show configuration interfaces {state['interface']}"
        )
        if "disable" in post_config:
            print(f"⚠️  WARNING: 'disable' still present on {state['interface']}.  "
                  f"State file kept for re-revert.")
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
        print(f"   interface: {state['interface']} (DISABLED)")
        print(f"   injected_at: {state['injected_at']}")
        print(f"   state file: {state_file}")
        return 0
    print(f"✓ no active fault on {args.device}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="action", required=True)

    p_inject = sub.add_parser("inject", help="disable transit interface")
    p_inject.add_argument("--device", required=True, choices=list(DEVICES))
    p_inject.add_argument("--interface", default=None,
                          help="override default interface (per-device default in TARGET_INTERFACE)")
    p_inject.add_argument("--force", action="store_true",
                          help="overwrite existing state file")
    p_inject.set_defaults(func=cmd_inject)

    p_revert = sub.add_parser("revert", help="re-enable interface")
    p_revert.add_argument("--device", required=True, choices=list(DEVICES))
    p_revert.set_defaults(func=cmd_revert)

    p_status = sub.add_parser("status", help="show whether a fault is active")
    p_status.add_argument("--device", required=True, choices=list(DEVICES))
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
