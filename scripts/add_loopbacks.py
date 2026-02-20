#!/usr/bin/env python3
"""Add test loopback interfaces to R1 and R2.

R1: Loopback11  11.11.11.11/32
R2: Loopback22  22.22.22.22/32

Usage:
    .venv/bin/python3 scripts/add_loopbacks.py
    .venv/bin/python3 scripts/add_loopbacks.py --remove   # undo
"""

from __future__ import annotations

import argparse
import sys
from netmiko import ConnectHandler

DEVICES = {
    "R1": {
        "host": "192.168.100.101",
        "add_cmds": [
            "interface Loopback11",
            "ip address 11.11.11.11 255.255.255.255",
            "no shutdown",
            "end",
        ],
        "remove_cmds": [
            "no interface Loopback11",
            "end",
        ],
        "verify_cmd": "show interfaces Loopback11 brief",
    },
    "R2": {
        "host": "192.168.100.102",
        "add_cmds": [
            "interface Loopback22",
            "ip address 22.22.22.22 255.255.255.255",
            "no shutdown",
            "end",
        ],
        "remove_cmds": [
            "no interface Loopback22",
            "end",
        ],
        "verify_cmd": "show interfaces Loopback22 brief",
    },
}

USERNAME = "cisco"
PASSWORD = "cisco"


def push(device_name: str, info: dict, remove: bool = False) -> bool:
    cmds = info["remove_cmds"] if remove else info["add_cmds"]
    action = "Removing" if remove else "Adding"
    print(f"\n[{device_name}] {action} loopback on {info['host']} ...")
    try:
        conn = ConnectHandler(
            device_type="cisco_ios",
            host=info["host"],
            username=USERNAME,
            password=PASSWORD,
            timeout=30,
        )
        output = conn.send_config_set(cmds)
        print(output)

        # Save config
        conn.save_config()
        print(f"[{device_name}] Config saved.")

        if not remove:
            verify = conn.send_command(info["verify_cmd"])
            print(f"[{device_name}] Verify: {verify}")

        conn.disconnect()
        print(f"[{device_name}] ✅ Done.")
        return True
    except Exception as e:
        print(f"[{device_name}] ❌ Failed: {e}", file=sys.stderr)
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Add/remove test loopback interfaces")
    parser.add_argument("--remove", action="store_true", help="Remove the loopbacks instead of adding")
    args = parser.parse_args()

    results = {}
    for name, info in DEVICES.items():
        results[name] = push(name, info, remove=args.remove)

    print("\n--- Summary ---")
    for name, ok in results.items():
        print(f"  {name}: {'✅ OK' if ok else '❌ FAILED'}")

    if not all(results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
