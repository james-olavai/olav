#!/usr/bin/env python3
"""Live E2E test: deploy 2-node cEOS lab via CLAB REST API, push BGP config, verify BGP established.

Uses Docker management network (172.20.20.0/24) for BGP because CLAB REST API
does not create veth pairs between nodes.

Usage:
    export CLAB_API_TOKEN=<token>
    uv run python scripts/test_srl_bgp_live.py

Or get token automatically (admin/admin):
    python scripts/test_srl_bgp_live.py --auto-login
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

# Add skill scripts to path
_SKILL_SCRIPTS = Path(__file__).parent.parent / ".agent" / "skills" / "containerlab-e2e" / "scripts"
sys.path.insert(0, str(_SKILL_SCRIPTS))

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from clab_client import CLabClient, CLABAPIError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

API_SERVER = "http://192.168.100.12:8080/api/v1"
LOGIN_URL = "http://192.168.100.12:8080/login"

# Minimal 2-node cEOS topology for BGP test (dict for CLabClient.deploy)
# cEOS works correctly with CLAB REST API (unlike SRL which needs CLI deployment)
TOPOLOGY = {
    "name": "ceos-bgp-test",
    "prefix": "",   # container names = node names
    "topology": {
        "defaults": {
            "kind": "ceos",
            "image": "ceos:4.35.2",
        },
        "nodes": {
            "r1": {},
            "r2": {},
        },
        "links": [
            {"endpoints": ["r1:eth1", "r2:eth1"]},
        ],
    },
}

# CLAB REST API does not create veth pairs between nodes.
# BGP is configured over the Docker management network (Management0).
# Management IPs are passed in at runtime from the deploy response.

def _build_node_config(node_ip: str, peer_ip: str, asn: int, peer_asn: int) -> str:
    """Build complete cEOS running-config for one node using management IPs for BGP."""
    return f"""\
no aaa root
!
no service interface inactive port-id allocation disabled
!
service routing protocols model multi-agent
!
agent PowerManager shutdown
agent LedPolicy shutdown
agent Thermostat shutdown
agent PowerFuse shutdown
agent StandbyCpld shutdown
agent LicenseManager shutdown
!
spanning-tree mode mstp
!
system l1
   unsupported speed action error
   unsupported error-correction action error
!
interface Management0
   ip address {node_ip}/24
!
ip routing
!
router bgp {asn}
   router-id {node_ip}
   neighbor {peer_ip} remote-as {peer_asn}
   neighbor {peer_ip} maximum-routes 12000
   address-family ipv4
      neighbor {peer_ip} activate
   !
!
"""

async def _get_token(username: str = "admin", password: str = "admin") -> str:
    import httpx
    async with httpx.AsyncClient() as hc:
        r = await hc.post(LOGIN_URL, json={"username": username, "password": password}, timeout=10)
        r.raise_for_status()
        return r.json()["token"]


async def _wait_ceos_ready(client: CLabClient, lab_name: str, timeout: int = 120) -> bool:
    """Wait for ALL cEOS nodes to be ready (Cli responds with EOS version info)."""
    deadline = time.monotonic() + timeout
    log.info("Waiting for cEOS to be ready (all nodes)...")
    poll_round = 0
    check_cmd = "bash -c 'Cli -c \"show version\" 2>&1; echo CLI_RC=$?'"
    while time.monotonic() < deadline:
        await asyncio.sleep(5)
        poll_round += 1
        try:
            resp = await client.exec_command(lab_name, check_cmd, timeout=15.0)
            ready_nodes = set()
            all_nodes = set(resp.keys())
            for node, results in resp.items():
                out = results[0].get("stdout", "") if results else ""
                if poll_round <= 3 or poll_round % 4 == 0:
                    log.info("[ceos poll r%d] node=%s: %s", poll_round, node, out[:200])
                if "CLI_RC=0" in out and "EOS" in out:
                    ready_nodes.add(node)
            if ready_nodes and ready_nodes == all_nodes:
                t = timeout - (deadline - time.monotonic())
                log.info("All cEOS nodes ready at t≈%.1fs: %s", t, sorted(ready_nodes))
                return True
            elif ready_nodes:
                log.debug("Partial cEOS ready: %s / %s", sorted(ready_nodes), sorted(all_nodes))
        except Exception as e:
            log.debug("ceos poll: %s", e)

    log.warning("cEOS readiness timeout")
    return False


async def _push_config(client: CLabClient, lab_name: str, node_configs: dict[str, str]) -> dict:
    """Write + apply per-node configs. node_configs = {node_name: config_text}."""
    import base64

    # Build write command: write all configs to all containers (idempotent).
    write_parts = []
    for node_name, cfg in node_configs.items():
        b64 = base64.b64encode(cfg.encode()).decode()
        write_parts.append(f"echo {b64} | base64 -d > /tmp/olav_{node_name}.cfg")
    write_cmd = "bash -c '" + " && ".join(write_parts) + " && echo WRITE_OK'"

    # Write config files; use CLAB_LABEL_CLAB_NODE_NAME (not hostname — cEOS sets hostname=localhost).
    # Cancel ZTP (blocks all config changes), poll until disabled, then apply via stdin pipe.
    # ZTP cancel is asynchronous — typically takes ~15-20s to fully deactivate.
    # Use $CLAB_LABEL_CLAB_NODE_NAME for node identity (hostname = host machine, not node name).
    apply_cmd = (
        "bash -c '"
        "N=$CLAB_LABEL_CLAB_NODE_NAME; cfg=/tmp/olav_$N.cfg; "
        "Cli -p 15 -c \"zerotouch cancel\" 2>&1; "
        "for i in 1 2 3 4 5 6 7 8; do "
        "  ZS=$(Cli -p 15 -c \"show zerotouch\" 2>&1); "
        "  echo \"$ZS\" | grep -qi disabled && { echo ZTP_DISABLED_AT_$i; break; }; "
        "  sleep 5; "
        "done; "
        "[ -f \"$cfg\" ] && ({ printf \"configure\\n\"; cat \"$cfg\"; printf \"end\\n\"; } | Cli -p 15 2>&1; echo CFG_RC=$?) || echo CFG_SKIP_$N"
        "'"
    )

    log.info("Writing config files...")
    write_resp = await client.exec_command(lab_name, write_cmd, timeout=15.0)
    for node, results in write_resp.items():
        out = results[0].get("stdout", "") if results else ""
        log.info("Write on %s: %s", node, out.strip())

    log.info("Applying config via cEOS Cli (includes ZTP cancel + poll)...")
    resp = await client.exec_command(lab_name, apply_cmd, timeout=90.0)
    for node, results in resp.items():
        out = results[0].get("stdout", "") if results else ""
        log.info("Config apply output on %s:\n%s", node, out[:600])
        if "CFG_RC=0" in out:
            log.info("Config applied OK on %s", node)
        elif "CFG_SKIP" in out:
            log.warning("No config file for %s (skipped)", node)
        else:
            log.warning("Config may have failed on %s", node)
    return resp


async def _check_bgp_ceos(client: CLabClient, lab_name: str, wait_secs: int = 30) -> dict:
    """Wait for BGP convergence on cEOS and return neighbor state."""
    log.info("Waiting %ds for BGP convergence...", wait_secs)
    await asyncio.sleep(wait_secs)

    # Diagnostic: show IP interfaces and BGP config
    diag_cmd = (
        "bash -c 'echo IP_BRIEF:; Cli -p 15 -c \"show ip interface brief\" 2>&1; "
        "echo ---BGP_CFG---; Cli -p 15 -c \"show running-config | section router bgp\" 2>&1; "
        "echo ---MGMT_CFG---; Cli -p 15 -c \"show running-config | section interface Management\" 2>&1'"
    )
    try:
        diag_resp = await client.exec_command(lab_name, diag_cmd, timeout=15.0)
        for node, results in diag_resp.items():
            out = results[0].get("stdout", "") if results else ""
            log.info("Running config diag on %s:\n%s", node, out[:800])
    except Exception as e:
        log.warning("Diag failed: %s", e)

    show_cmd = "bash -c 'Cli -c \"show ip bgp summary\" 2>&1; echo BGP_RC=$?'"
    try:
        resp = await client.exec_command(lab_name, show_cmd, timeout=15.0)
        results = {}
        for node, node_results in resp.items():
            out = node_results[0].get("stdout", "") if node_results else ""
            results[node] = out
            log.info("BGP state on %s:\n%s", node, out[:500])
        return results
    except Exception as e:
        log.error("BGP check failed: %s", e)
        return {}


async def main(auto_login: bool = False):
    # Get token
    token = os.environ.get("CLAB_API_TOKEN", "")
    if not token and auto_login:
        log.info("Getting token via login...")
        token = await _get_token()
        log.info("Token obtained")
    if not token:
        log.error("No CLAB_API_TOKEN. Use --auto-login or export CLAB_API_TOKEN=<token>")
        sys.exit(1)

    client = await CLabClient.build(API_SERVER, token)
    lab_name = "ceos-bgp-test"

    # Clean up any existing lab
    try:
        await client.destroy(lab_name)
        log.info("Cleaned up existing lab")
        await asyncio.sleep(2)
    except Exception:
        pass

    try:
        # Deploy
        log.info("Deploying 2-node cEOS lab...")
        t0 = time.monotonic()
        deploy_resp = await client.deploy(TOPOLOGY, reconfigure=True)
        log.info("Deploy response: %s (%.1fs)", list(deploy_resp.keys()), time.monotonic() - t0)

        # Extract management IPs from deploy response
        nodes_in_lab = deploy_resp.get(lab_name, [])
        mgmt_ips: dict[str, str] = {}
        for n in nodes_in_lab:
            ip_cidr = n.get("ipv4_address", "")
            ip = ip_cidr.split("/")[0] if "/" in ip_cidr else ip_cidr
            if ip and ip != "N/A":
                mgmt_ips[n["name"]] = ip
        log.info("Management IPs: %s", mgmt_ips)
        if len(mgmt_ips) < 2:
            log.error("Could not determine management IPs from deploy response: %s", nodes_in_lab)
            return

        # Build per-node configs using management IPs for BGP
        node_names = sorted(mgmt_ips.keys())
        n1, n2 = node_names[0], node_names[1]
        node_configs = {
            n1: _build_node_config(mgmt_ips[n1], mgmt_ips[n2], 65001, 65002),
            n2: _build_node_config(mgmt_ips[n2], mgmt_ips[n1], 65002, 65001),
        }
        log.info("Built configs for %s (BGP via management network)", list(node_configs.keys()))

        # Wait for cEOS to be ready
        ready = await _wait_ceos_ready(client, lab_name)
        if not ready:
            log.error("cEOS readiness timeout — aborting")
            return

        # Push config
        await _push_config(client, lab_name, node_configs)

        # Check BGP
        bgp_results = await _check_bgp_ceos(client, lab_name, wait_secs=60)

        # Summary
        established = 0
        for node, out in bgp_results.items():
            if "Estab" in out or "established" in out.lower():
                established += 1
                log.info("BGP ESTABLISHED on %s", node)
            else:
                log.warning("BGP NOT established on %s: %s", node, out[:100])

        print(f"\n{'='*60}")
        print(f"RESULT: {established}/{len(bgp_results)} nodes have BGP established")
        print('='*60)

    finally:
        log.info("Destroying lab...")
        try:
            await client.destroy(lab_name)
        except Exception as e:
            log.warning("Destroy failed: %s", e)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--auto-login", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(auto_login=args.auto_login))
