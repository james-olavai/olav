"""Deploy Lab Tool — Deploy a ContainerLab topology and run mandatory post-deploy workarounds.

Tool: deploy_lab

This tool combines the full deployment sequence into a single call:
1. POST /api/v1/labs with topology YAML
2. fix_srl_topology (fix topology.yml directory bug)
3. create_srl_links (inject inter-node veth pairs)

Use this IMMEDIATELY after run_python_simulation returns the topology YAML.

Args (JSON):
    yaml_content:  str  — topology YAML string (from run_python_simulation _result["yaml"])
    ssh_host:      str  — SSH host for create_srl_links (default: "192.168.100.12")
    wait_seconds:  int  — seconds to wait after fix_srl_topology (default: 40)

Returns: JSON string with deployment result
    {"status": "deployed", "lab_name": "olav-lab", "steps": {...}}
    {"status": "error", "step": "...", "error": "..."}
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent
while _PROJECT_ROOT.parent != _PROJECT_ROOT and not (_PROJECT_ROOT / "pyproject.toml").exists():
    _PROJECT_ROOT = _PROJECT_ROOT.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from langchain_core.tools import tool


@tool
def deploy_lab(
    yaml_content: str,
    ssh_host: str = "192.168.100.12",
    wait_seconds: int = 40,
) -> str:
    """Deploy a ContainerLab topology and run mandatory post-deploy workarounds.

    Use this IMMEDIATELY after run_python_simulation returns the topology YAML.
    This tool combines: POST /api/v1/labs + fix_srl_topology + create_srl_links.

    Args:
        yaml_content: Topology YAML string from run_python_simulation _result["yaml"].
        ssh_host: Docker host for veth pair injection (default: 192.168.100.12).
        wait_seconds: Seconds to wait after topology fix (default: 40).

    Returns:
        JSON with deployment status and steps result.

    Example:
        deploy_lab(yaml_content="name: olav-lab\\ntopology: ...")
    """
    results = {}

    # Step 1: POST /api/v1/labs
    # CLAB REST API requires:
    #   body: {"topologyContent": <parsed YAML dict>}  (NOT "content" string)
    #   The YAML must also include a unique mgmt subnet to avoid Docker network conflicts
    try:
        tools_dir = Path(__file__).parent
        sys.path.insert(0, str(tools_dir))
        import yaml as _yaml
        from olav.platform.services.client import service_call

        # Parse YAML to dict (API requires JSON object, not raw YAML string)
        topo_dict = _yaml.safe_load(yaml_content)

        # Inject unique mgmt network to avoid subnet conflicts with other labs
        lab_name = topo_dict.get("name", "olav-lab")
        if "mgmt" not in topo_dict:
            topo_dict["mgmt"] = {
                "network": f"clab-{lab_name}",
                "ipv4-subnet": "172.20.50.0/24",
            }

        deploy_result = service_call(
            "clab",
            method="POST",
            path="/api/v1/labs",
            body={"topologyContent": topo_dict},
            confirmed=True,
        )
        if not isinstance(deploy_result, dict):
            deploy_result = {"status_code": 0, "body": str(deploy_result)}
        results["deploy"] = {
            "status_code": deploy_result.get("status_code"),
            "body": str(deploy_result.get("body", ""))[:300],
        }

        sc = deploy_result.get("status_code", 0)
        if sc == 409:
            results["deploy"]["note"] = "Lab already exists, continuing with post-deploy steps"
        elif sc not in (200, 201):
            return json.dumps({"status": "error", "step": "deploy", "error": str(deploy_result), "results": results})
    except Exception as e:
        return json.dumps({"status": "error", "step": "deploy", "error": str(e)})

    # Step 2: fix_srl_topology
    try:
        import importlib
        _fix_mod = importlib.import_module("fix_srl_topology")
        fix_result = _fix_mod.fix_srl_topology({"lab_name": lab_name, "wait_secs": wait_seconds, "ssh_host": ssh_host, "ssh_user": "olav"})
        results["fix_topology"] = str(fix_result)[:300]
    except Exception as e:
        results["fix_topology"] = f"error: {e}"

    # Step 3: create_srl_links — extract links from topology YAML
    try:
        _links_mod = importlib.import_module("create_srl_links")
        # Parse links from topology YAML
        clab_links = topo_dict.get("topology", {}).get("links", [])
        links_explicit = []
        for lnk in clab_links:
            endpoints = lnk.get("endpoints", [])
            if len(endpoints) == 2:
                a_node_raw, _, a_iface = endpoints[0].partition(":")
                b_node_raw, _, b_iface = endpoints[1].partition(":")
                # Container names are prefixed with clab-<lab_name>-
                links_explicit.append({
                    "a_node": f"clab-{lab_name}-{a_node_raw.strip()}",
                    "a_iface": a_iface.strip(),
                    "b_node": f"clab-{lab_name}-{b_node_raw.strip()}",
                    "b_iface": b_iface.strip(),
                })
        links_result = _links_mod.create_srl_links({
            "lab_name": lab_name,
            "ssh_host": ssh_host,
            "ssh_user": "olav",
            "links": links_explicit if links_explicit else None,
        })
        results["create_links"] = str(links_result)[:300]
    except Exception as e:
        results["create_links"] = f"error: {e}"

    return json.dumps({
        "status": "deployed",
        "lab_name": "olav-lab",
        "steps": results,
        "next": "Call exec_on_node to verify management plane, then run_python_simulation to push production config via exec API.",
    })


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("args_json", nargs="?", default="{}")
    parsed = parser.parse_args()
    args = json.loads(parsed.args_json)
    print(deploy_lab.invoke(args))
