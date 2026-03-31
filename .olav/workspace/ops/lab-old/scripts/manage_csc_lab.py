#!/usr/bin/env python3
"""
manage_csc_lab.py — Carrier Supporting Carrier VPN lab lifecycle manager.

Deploys the carrier-supporting-carrier-vpn topology via ContainerLab REST API at .12.
Run AFTER: python3 scripts/remote_build.py --only vjunosevolved

Usage:
    python3 scripts/manage_csc_lab.py              # deploy lab
    python3 scripts/manage_csc_lab.py --check      # check status only
    python3 scripts/manage_csc_lab.py --destroy    # destroy lab

API server: http://192.168.100.12:8080
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import httpx
import yaml

# ── Constants ─────────────────────────────────────────────────────────────────
SCRIPTS_DIR   = Path(__file__).parent.resolve()
SKILL_ROOT    = SCRIPTS_DIR.parent
LAB_DIR       = SKILL_ROOT / "lab_sessions" / "carrier-supporting-carrier-vpn"
TOPOLOGY_PATH = LAB_DIR / "topology.clab.yaml"

BASE_URL  = "http://192.168.100.12:8080"
API_SERVER = f"{BASE_URL}/api/v1"
LOGIN_URL  = f"{BASE_URL}/login"

CLAB_USERNAME = "yhvh"
CLAB_PASSWORD = "jAmes92323"

LAB_NAME = "carrier-supporting-carrier-vpn"

# Expected nodes and their management IPs (from topology)
EXPECTED_NODES = {
    "pe01":   "192.168.100.110",
    "pe02":   "192.168.100.111",
    "p01":    "192.168.100.112",
    "p02":    "192.168.100.113",
    "p03":    "192.168.100.114",
    "rr01":   "192.168.100.115",
    "rr02":   "192.168.100.116",
    "asbr01": "192.168.100.117",
    "asbr02": "192.168.100.118",
    "asbr03": "192.168.100.119",
    "asbr04": "192.168.100.120",
    "ce01":   "192.168.100.121",
    "ce02":   "192.168.100.122",
}


# ── Auth ──────────────────────────────────────────────────────────────────────

def login() -> str:
    resp = httpx.post(LOGIN_URL,
                      json={"username": CLAB_USERNAME, "password": CLAB_PASSWORD},
                      timeout=10.0)
    resp.raise_for_status()
    token = resp.json()["token"]
    os.environ["CLAB_API_TOKEN"] = token
    print(f"[auth] ✓ Authenticated as '{CLAB_USERNAME}'")
    return token


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ── Lab status ────────────────────────────────────────────────────────────────

def _find_lab(token: str) -> dict | None:
    resp = httpx.get(f"{API_SERVER}/labs", headers=_headers(token), timeout=10.0)
    if not resp.is_success:
        return None
    labs = resp.json()
    lab_list = labs if isinstance(labs, list) else labs.get("labs", [])
    for lab in lab_list:
        if lab.get("name", "").lower().replace(" ", "-") == LAB_NAME:
            return lab
    return None


def check_lab_running(token: str) -> bool:
    return _find_lab(token) is not None


def print_lab_status(token: str) -> None:
    lab = _find_lab(token)
    if not lab:
        print(f"[status] Lab '{LAB_NAME}' is NOT running.")
        return
    containers = lab.get("containers", [])
    print(f"\n[status] Lab '{LAB_NAME}' — {len(containers)}/{len(EXPECTED_NODES)} containers:\n")
    print(f"  {'Node':<20} {'State':<12} {'Management IP'}")
    print(f"  {'-'*20} {'-'*12} {'-'*20}")
    for c in sorted(containers, key=lambda x: x.get("name", "")):
        name  = c.get("name", "?")
        state = c.get("state", "?")
        ipv4  = c.get("ipv4_address", "-").split("/")[0]
        expected_ip = EXPECTED_NODES.get(name, "?")
        ip_ok = "✓" if ipv4 == expected_ip else f"✗ (expected {expected_ip})"
        print(f"  {name:<20} {state:<12} {ipv4}  {ip_ok}")


# ── Deploy ────────────────────────────────────────────────────────────────────

def deploy_lab(token: str) -> None:
    topology_content = yaml.safe_load(TOPOLOGY_PATH.read_text())
    print(f"[deploy] Deploying '{LAB_NAME}' from {TOPOLOGY_PATH} ...")
    print(f"[deploy] Nodes: {len(EXPECTED_NODES)} | POST {API_SERVER}/labs (timeout=600s)")

    resp = httpx.post(
        f"{API_SERVER}/labs",
        headers=_headers(token),
        json={"topologyContent": topology_content},
        timeout=600.0,  # 10 min — Juniper vJunosEvolved is slow to boot
    )
    resp.raise_for_status()
    body = resp.json()
    lab_name = next(iter(body))
    containers = body[lab_name].get("containers", [])
    print(f"[deploy] ✓ '{lab_name}' deployed — {len(containers)} containers started")


# ── Destroy ───────────────────────────────────────────────────────────────────

def destroy_lab(token: str) -> None:
    print(f"[destroy] Destroying lab '{LAB_NAME}' ...")
    resp = httpx.delete(
        f"{API_SERVER}/labs/{LAB_NAME}",
        headers=_headers(token),
        timeout=120.0,
    )
    if resp.status_code == 404:
        print("[destroy] Lab not found — already destroyed.")
        return
    resp.raise_for_status()
    print(f"[destroy] ✓ Lab '{LAB_NAME}' destroyed.")


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check",   action="store_true", help="Print lab status only")
    parser.add_argument("--destroy", action="store_true", help="Destroy the lab")
    args = parser.parse_args()

    token = login()

    if args.check:
        print_lab_status(token)
        return

    if args.destroy:
        destroy_lab(token)
        return

    if check_lab_running(token):
        print(f"[deploy] Lab '{LAB_NAME}' already running. Use --destroy first to redeploy.")
        print_lab_status(token)
        return

    deploy_lab(token)

    # Wait briefly then print status
    print("[deploy] Waiting 15s for containers to register ...")
    time.sleep(15)
    print_lab_status(token)


if __name__ == "__main__":
    main()
