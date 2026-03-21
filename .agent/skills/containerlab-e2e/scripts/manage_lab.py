#!/usr/bin/env python3
"""
manage_lab.py — Enterprise Dual-Site lab lifecycle manager via ContainerLab API.

All operations go through the ContainerLab REST API.
No shell scripts, no docker CLI commands.

Usage:
    # Deploy lab, inject Nornir hosts, disable Juniper security mode:
    uv run python manage_lab.py

    # Check status only:
    uv run python manage_lab.py --check

    # Destroy lab:
    uv run python manage_lab.py --destroy

    # Only disable Juniper security mode (lab must already be running):
    uv run python manage_lab.py --configure-routing-only

    # Deploy but skip optional steps:
    uv run python manage_lab.py --skip-routing --no-hosts-inject

API server: http://192.168.100.12:8080
Auth:       POST /login  →  JWT  →  Authorization: Bearer <token>
Deploy:     POST /api/v1/labs  with topologyContent as parsed dict
Exec:       POST /api/v1/labs/{lab_name}/exec  (NodeFilter is IGNORED — runs on ALL nodes)
Destroy:    DELETE /api/v1/labs/{lab_name}
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
SCRIPTS_DIR = Path(__file__).parent.resolve()
SKILL_ROOT = SCRIPTS_DIR.parent          # .agent/skills/containerlab-e2e
LAB_SESSION_DIR = SKILL_ROOT / "lab_sessions" / "enterprise_dual_site"

BASE_URL = "http://192.168.100.12:8080"
API_SERVER = f"{BASE_URL}/api/v1"
LOGIN_URL = f"{BASE_URL}/login"

CLAB_USERNAME = "yhvh"
CLAB_PASSWORD = "jAmes92323"

LAB_NAME = "enterprise-dual-site"
TOPOLOGY_PATH = LAB_SESSION_DIR / "topology.clab.yaml"
SESSION_PATH = LAB_SESSION_DIR / "SESSION.yaml"

# Nornir inventory path (relative to workspace root — run from /home/yhvh/Olav)
NORNIR_HOSTS_PATH = Path(".olav/config/nornir/hosts.yaml")


# ── Auth ──────────────────────────────────────────────────────────────────────

def login() -> str:
    """POST /login and return the JWT token. Also sets CLAB_API_TOKEN env var."""
    resp = httpx.post(
        LOGIN_URL,
        json={"username": CLAB_USERNAME, "password": CLAB_PASSWORD},
        timeout=10.0,
    )
    resp.raise_for_status()
    token = resp.json()["token"]
    os.environ["CLAB_API_TOKEN"] = token
    print(f"[auth] ✓ Authenticated as '{CLAB_USERNAME}'")
    return token


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ── Lab status ────────────────────────────────────────────────────────────────

def check_lab_running(token: str) -> bool:
    """Return True if enterprise-dual-site lab is already deployed."""
    resp = httpx.get(f"{API_SERVER}/labs", headers=_headers(token), timeout=10.0)
    if not resp.is_success:
        return False
    labs = resp.json()
    lab_list = labs if isinstance(labs, list) else labs.get("labs", [])
    return any(
        lab.get("name", "").lower().replace(" ", "-") == LAB_NAME
        for lab in lab_list
    )


def print_lab_status(token: str) -> None:
    """Print running containers in the lab."""
    resp = httpx.get(f"{API_SERVER}/labs", headers=_headers(token), timeout=10.0)
    if not resp.is_success:
        print(f"[status] ✗ Could not query labs: HTTP {resp.status_code}")
        return

    labs = resp.json()
    lab_list = labs if isinstance(labs, list) else labs.get("labs", [])
    for lab in lab_list:
        if lab.get("name", "").lower().replace(" ", "-") == LAB_NAME:
            containers = lab.get("containers", [])
            print(f"[status] Lab '{LAB_NAME}' — {len(containers)} containers:")
            for c in containers:
                name = c.get("name", "?")
                state = c.get("state", "?")
                ipv4 = c.get("ipv4_address", "-")
                print(f"  {name:<45}  {state:<12}  {ipv4}")
            return
    print(f"[status] Lab '{LAB_NAME}' not found in running labs.")


# ── Deploy ────────────────────────────────────────────────────────────────────

def deploy_lab(token: str) -> str:
    """Deploy topology via POST /api/v1/labs. Returns lab_name from response."""
    topology_content = yaml.safe_load(TOPOLOGY_PATH.read_text())
    print(f"[deploy] Deploying '{LAB_NAME}' from {TOPOLOGY_PATH.name} ...")
    print(f"[deploy] POST {API_SERVER}/labs  (timeout=300s)")

    resp = httpx.post(
        f"{API_SERVER}/labs",
        headers=_headers(token),
        json={"topologyContent": topology_content},
        timeout=300.0,  # 5 min — VM images can be slow
    )
    resp.raise_for_status()
    body = resp.json()

    # Response: { "<lab_name>": { "containers": [...] } }
    lab_name = next(iter(body))
    containers = body[lab_name].get("containers", [])
    print(f"[deploy] ✓ Lab '{lab_name}' deployed — {len(containers)} containers started")
    for c in containers:
        print(f"  {c.get('name', '?')}")
    return lab_name


# ── Exec ──────────────────────────────────────────────────────────────────────

def exec_command(token: str, command: str, timeout: float = 60.0) -> dict:
    """POST /api/v1/labs/{lab_name}/exec — runs on ALL containers (NodeFilter ignored).

    Returns dict[container_name, list[output]] or empty dict on failure.
    """
    resp = httpx.post(
        f"{API_SERVER}/labs/{LAB_NAME}/exec",
        headers=_headers(token),
        json={"Command": command},
        timeout=timeout,
    )
    if not resp.is_success:
        print(f"[exec] HTTP {resp.status_code}: {resp.text[:300]}")
        return {}
    return resp.json()


# ── Readiness check ───────────────────────────────────────────────────────────

def wait_for_ready(token: str, max_wait: int = 360, interval: int = 20) -> bool:
    """Poll 'hostname' exec until all nodes in SESSION.yaml respond. Returns True on success."""
    session = yaml.safe_load(SESSION_PATH.read_text())
    node_names = set(session["nodes"].keys())
    container_prefix = f"clab-{LAB_NAME}-"

    print(f"[ready] Waiting for {len(node_names)} nodes to respond (max {max_wait}s) ...")
    deadline = time.monotonic() + max_wait

    while time.monotonic() < deadline:
        result = exec_command(token, "hostname", timeout=30.0)
        if result:
            responding: set[str] = set()
            for container_name, outputs in result.items():
                if isinstance(outputs, list) and outputs:
                    out = outputs[0]
                    if out.get("return-code", 1) == 0 and out.get("stdout", "").strip():
                        node = container_name.removeprefix(container_prefix)
                        responding.add(node)

            ready = responding & node_names
            missing = node_names - responding
            print(f"[ready] {len(ready)}/{len(node_names)} nodes responding"
                  + (f" — waiting for: {', '.join(sorted(missing))}" if missing else ""))

            if not missing:
                print("[ready] ✓ All nodes are ready")
                return True

        remaining = int(deadline - time.monotonic())
        if remaining > 0:
            print(f"[ready] Retrying in {interval}s ({remaining}s remaining) ...")
            time.sleep(interval)

    print("[ready] ✗ Timeout — not all nodes responded. Continuing anyway.")
    return False


# ── Nornir hosts injection ────────────────────────────────────────────────────

def inject_nornir_hosts() -> str:
    """Update Nornir hosts.yaml with enterprise-dual-site nodes from SESSION.yaml.

    Uses per-node platform, credentials, and mgmt IPs from SESSION.yaml.
    Returns original file content so caller can restore if needed.
    """
    if not NORNIR_HOSTS_PATH.exists():
        print(f"[hosts] ⚠ Nornir inventory not found at '{NORNIR_HOSTS_PATH}' — skipping")
        return ""

    session = yaml.safe_load(SESSION_PATH.read_text())
    original_text = NORNIR_HOSTS_PATH.read_text(encoding="utf-8")
    original_data = yaml.safe_load(original_text) or {}

    lab_entries: dict = {}
    for node_name, node_data in session["nodes"].items():
        lab_entries[node_name] = {
            "hostname": node_data["mgmt_ip"],
            "platform": node_data["platform"],
            "username": node_data.get("username", "admin"),
            "password": node_data.get("password", ""),
            "groups": ["lab", f"site_{str(node_data.get('site', '')).lower()}"],
            "data": {
                "role": node_data.get("role", ""),
                "site": node_data.get("site", ""),
                "lab": LAB_NAME,
            },
        }

    updated_data = {**original_data, **lab_entries}
    NORNIR_HOSTS_PATH.write_text(
        yaml.dump(updated_data, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )

    print(f"[hosts] ✓ Injected {len(lab_entries)} nodes into '{NORNIR_HOSTS_PATH}':")
    for name, entry in lab_entries.items():
        print(f"  {name:<20} {entry['hostname']:<20} platform={entry['platform']}")
    return original_text


def restore_nornir_hosts(original_content: str) -> None:
    """Restore Nornir hosts.yaml to its pre-injection state."""
    if original_content:
        NORNIR_HOSTS_PATH.write_text(original_content, encoding="utf-8")
        print(f"[hosts] ✓ Restored '{NORNIR_HOSTS_PATH}' to original state")


# ── Juniper crpd: disable security mode ──────────────────────────────────────

def disable_juniper_security_mode(token: str) -> None:
    """Remove 'security' stanza from Juniper crpd routers (rtr-a, rtr-b) via exec API.

    crpd starts in security/firewall mode by default. This switches it to
    pure routing mode so BGP and routing tables work correctly.

    NOTE: NodeFilter is silently ignored by the ContainerLab API, so the command
    runs on ALL containers. We use $(hostname) to restrict execution to rtr-* nodes.
    """
    cmd = (
        "bash -c '"
        "H=$(hostname); "
        "if echo \"$H\" | grep -qE \"^clab-enterprise-dual-site-rtr-[ab]$\"; then "
        "  cli -c \"configure; delete security; commit and-quit\" 2>&1; "
        "else "
        "  echo \"SKIP:$H\"; "
        "fi'"
    )
    print("[juniper] Disabling security mode on crpd routers (rtr-a, rtr-b) ...")
    result = exec_command(token, cmd, timeout=90.0)
    if not result:
        print("[juniper] ⚠ No exec response received")
        return

    for container_name, outputs in result.items():
        if "rtr-" not in container_name:
            continue  # skip non-router containers
        if isinstance(outputs, list) and outputs:
            out = outputs[0]
            rc = out.get("return-code", "?")
            stdout = out.get("stdout", "").strip()[:120]
            stderr = out.get("stderr", "").strip()[:80]
            status = "✓" if rc == 0 else "✗"
            print(f"[juniper] {status} {container_name}: rc={rc}")
            if stdout:
                print(f"    stdout: {stdout}")
            if stderr:
                print(f"    stderr: {stderr}")


# ── Destroy ───────────────────────────────────────────────────────────────────

def destroy_lab(token: str) -> None:
    """Destroy the lab via DELETE /api/v1/labs/{lab_name}."""
    print(f"[destroy] Destroying lab '{LAB_NAME}' ...")
    resp = httpx.delete(
        f"{API_SERVER}/labs/{LAB_NAME}",
        headers=_headers(token),
        timeout=120.0,
    )
    if resp.is_success:
        print(f"[destroy] ✓ Lab '{LAB_NAME}' destroyed")
    else:
        print(f"[destroy] ✗ HTTP {resp.status_code}: {resp.text[:200]}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Enterprise Dual-Site lab manager — ContainerLab API only",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Print lab status and exit")
    mode.add_argument("--destroy", action="store_true", help="Destroy the lab and exit")
    mode.add_argument(
        "--configure-routing-only",
        action="store_true",
        help="Only disable Juniper security mode (lab must already be running)",
    )
    parser.add_argument(
        "--skip-routing",
        action="store_true",
        help="Skip Juniper routing mode configuration after deploy",
    )
    parser.add_argument(
        "--no-hosts-inject",
        action="store_true",
        help="Skip injecting lab nodes into Nornir hosts.yaml",
    )
    args = parser.parse_args()

    # Authenticate first — all operations need it
    token = login()

    # ── Mode: status check ────────────────────────────────────────────────────
    if args.check:
        running = check_lab_running(token)
        print(f"[status] Lab '{LAB_NAME}' is {'RUNNING ✓' if running else 'NOT running ✗'}")
        if running:
            print_lab_status(token)
        return 0

    # ── Mode: destroy ─────────────────────────────────────────────────────────
    if args.destroy:
        destroy_lab(token)
        return 0

    # ── Mode: routing config only ─────────────────────────────────────────────
    if args.configure_routing_only:
        if not check_lab_running(token):
            print(f"[error] Lab '{LAB_NAME}' is not running. Deploy it first.")
            return 1
        disable_juniper_security_mode(token)
        return 0

    # ── Mode: full deploy flow ────────────────────────────────────────────────
    running = check_lab_running(token)
    if running:
        print(f"[status] Lab '{LAB_NAME}' is already running — skipping deploy")
        print_lab_status(token)
    else:
        deploy_lab(token)
        wait_for_ready(token)

    if not args.no_hosts_inject:
        inject_nornir_hosts()

    if not args.skip_routing:
        disable_juniper_security_mode(token)

    print()
    print("=" * 60)
    print(f"[done] ✓ Lab '{LAB_NAME}' is UP and configured")
    print("[done]   Management IPs: 192.168.100.120 – 192.168.100.131")
    print("[done]   Run --check to see container status")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
