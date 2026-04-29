#!/usr/bin/env python3
"""Fault injection: BGP neighbor IP — change valid peer to a wrong IP.

Demo runsheet Ch4.5 (proposed): inject a real fault on a real device,
let the ops agent investigate from cold start using its toolset
(execute_sql + search_logs + execute_cli + diff_configs +
format_and_export), then revert.

This script is intentionally NOT exposed as an OLAV agent tool —
fault injection is a privileged operation that must run outside the
agent loop, with explicit human invocation.

Usage:
    # Inject (mutates real device config; safe for lab, dangerous for prod)
    python bgp_wrong_peer_ip.py inject --device R1

    # Revert (restores original config from state file written by inject)
    python bgp_wrong_peer_ip.py revert --device R1

    # Status (shows whether a fault is currently active for this device)
    python bgp_wrong_peer_ip.py status --device R1

State persists in ``.olav/state/fault_runs/<device>_bgp_wrong_peer_ip.json``
so revert works even if you reopen a shell or the original session is gone.

Currently supports Juniper Junos only (R1 in demo7).  Cisco IOS
support is straightforward (different config commands) but not
needed for the first scenario.
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


# ─── device inventory (hardcoded for first scenario; future: read from netops.devices) ──
DEVICES: dict[str, dict] = {
    "R1": {
        "device_type": "juniper",
        "host": "192.168.100.101",
        "username": "cisco",
        "password": "<redacted-lab-password>",
        "port": 22,
    },
}

# ─── scenario constants ───────────────────────────────────────────────────────────
ORIGINAL_NEIGHBOR_IP = "10.1.12.2"     # the legitimate Ebgp neighbor
WRONG_NEIGHBOR_IP    = "10.1.12.99"    # nonexistent peer — will fail to establish
PEER_AS              = 65001
GROUP_NAME           = "Ebgp"

STATE_DIR = Path.home() / ".olav-state" / "fault_runs"


def _state_path(device: str) -> Path:
    return STATE_DIR / f"{device}_bgp_wrong_peer_ip.json"


def _connect(device: str):
    if device not in DEVICES:
        raise SystemExit(f"Unknown device {device!r}. Known: {list(DEVICES)}")
    return ConnectHandler(**DEVICES[device])


def _show_bgp_summary(conn) -> str:
    return conn.send_command("show bgp summary")


def cmd_inject(args) -> int:
    state_file = _state_path(args.device)
    if state_file.exists():
        print(f"⚠️  fault already active per {state_file}.  "
              f"Run 'revert' first or use --force.")
        if not args.force:
            return 1

    print(f"→ connecting to {args.device}…")
    conn = _connect(args.device)
    try:
        # Capture pre-state for the audit trail
        pre_summary = _show_bgp_summary(conn)
        pre_config = conn.send_command(
            f"show configuration protocols bgp group {GROUP_NAME}"
        )

        # Verify the original neighbor exists in current config
        if ORIGINAL_NEIGHBOR_IP not in pre_config:
            raise SystemExit(
                f"ERROR: expected neighbor {ORIGINAL_NEIGHBOR_IP} not found in "
                f"BGP group {GROUP_NAME!r}.  Aborting — pre-state is not the "
                f"canonical demo state."
            )

        # IMPORTANT: write state file BEFORE any further netmiko ops so
        # that even if SSH timing issues crash post-commit cleanup, the
        # revert path is preserved.
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        state = {
            "scenario": "bgp_wrong_peer_ip",
            "device": args.device,
            "injected_at": datetime.now(timezone.utc).isoformat(),
            "platform": DEVICES[args.device]["device_type"],
            "group": GROUP_NAME,
            "original_neighbor": ORIGINAL_NEIGHBOR_IP,
            "wrong_neighbor": WRONG_NEIGHBOR_IP,
            "peer_as": PEER_AS,
            "pre_summary_excerpt": pre_summary[:2000],
            "pre_config_excerpt": pre_config[:1000],
            "revert_commands": [
                f"delete protocols bgp group {GROUP_NAME} neighbor {WRONG_NEIGHBOR_IP}",
                f"set protocols bgp group {GROUP_NAME} neighbor {ORIGINAL_NEIGHBOR_IP} peer-as {PEER_AS}",
            ],
        }
        # Junos config commands
        commands = [
            f"delete protocols bgp group {GROUP_NAME} neighbor {ORIGINAL_NEIGHBOR_IP}",
            f"set protocols bgp group {GROUP_NAME} neighbor {WRONG_NEIGHBOR_IP} peer-as {PEER_AS}",
        ]
        print(f"→ injecting fault on {args.device}: {ORIGINAL_NEIGHBOR_IP} → {WRONG_NEIGHBOR_IP}")
        result = conn.send_config_set(commands, exit_config_mode=False)
        print(result[-300:])
        commit = conn.commit()
        print(commit[-200:])

        # Save state IMMEDIATELY after commit succeeds — before any
        # cleanup that might fail.
        state_file.write_text(json.dumps(state, indent=2))
        print(f"✓ state saved → {state_file}")
        print()

        # Best-effort exit from config mode; ignore prompt-detection
        # timeouts since the commit is already persisted.
        try:
            conn.exit_config_mode()
        except Exception as exc:
            print(f"  (non-fatal: exit_config_mode timed out: {exc})")

        print(f"⏱  waiting 5s for BGP state to update…")
        time.sleep(5)
        try:
            post_summary = _show_bgp_summary(conn)
            print("=== post-injection BGP summary ===")
            print(post_summary)
        except Exception as exc:
            print(f"  (non-fatal: post-summary read failed: {exc})")
            print(f"  re-check via fresh connection.")
        print()
        print(f"💉 INJECTION COMPLETE.  Run 'revert' to restore the original config.")
    finally:
        conn.disconnect()
    return 0


def cmd_revert(args) -> int:
    state_file = _state_path(args.device)
    if not state_file.exists():
        print(f"⚠️  no active fault state at {state_file}.  Nothing to revert.")
        return 1

    state = json.loads(state_file.read_text())
    print(f"→ reverting fault on {args.device} (injected at {state['injected_at']})")
    print(f"  scenario: {state['scenario']}")
    print(f"  restoring: {state['wrong_neighbor']} → {state['original_neighbor']}")

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
    print("⏱  waiting 5s for BGP to re-converge…")
    time.sleep(5)

    # Re-open a fresh connection for verification — avoids prompt-state
    # confusion if the previous session ended in config mode.
    verify_conn = _connect(args.device)
    try:
        post = verify_conn.send_command("show bgp summary")
        print("=== post-revert BGP summary ===")
        print(post)
        post_config = verify_conn.send_command(
            f"show configuration protocols bgp group {state['group']}"
        )
        if state["original_neighbor"] not in post_config:
            print(f"⚠️  WARNING: original neighbor {state['original_neighbor']} not "
                  f"found post-revert.  State file kept for re-revert.")
            return 2
        if state["wrong_neighbor"] in post_config:
            print(f"⚠️  WARNING: wrong neighbor {state['wrong_neighbor']} still present "
                  f"post-revert.  State file kept.")
            return 2
    finally:
        verify_conn.disconnect()

    # Success — archive the state file (don't delete in case demo wants the audit trail)
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
        print(f"   injected_at: {state['injected_at']}")
        print(f"   {state['original_neighbor']} → {state['wrong_neighbor']}")
        print(f"   state file: {state_file}")
        return 0
    print(f"✓ no active fault on {args.device}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="action", required=True)

    p_inject = sub.add_parser("inject", help="apply the fault")
    p_inject.add_argument("--device", required=True, choices=list(DEVICES))
    p_inject.add_argument("--force", action="store_true",
                          help="overwrite existing state file")
    p_inject.set_defaults(func=cmd_inject)

    p_revert = sub.add_parser("revert", help="restore original config")
    p_revert.add_argument("--device", required=True, choices=list(DEVICES))
    p_revert.set_defaults(func=cmd_revert)

    p_status = sub.add_parser("status", help="show whether a fault is active")
    p_status.add_argument("--device", required=True, choices=list(DEVICES))
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
