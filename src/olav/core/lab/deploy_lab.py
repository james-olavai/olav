"""Deploy Lab Tool — Deploy a ContainerLab topology and run mandatory post-deploy workarounds.

Tool: deploy_lab

This tool combines the full deployment sequence into a single call:
1. POST /api/v1/labs with topology YAML
2. fix_srl_topology (fix topology.yml directory bug)
3. create_srl_links (inject inter-node veth pairs)

Use this IMMEDIATELY after run_python_simulation returns the topology YAML.

Args (JSON):
    yaml_content:  str  — topology YAML string (from run_python_simulation _result["yaml"])
    ssh_host:      str  — SSH host for create_srl_links (resolved from containerlab endpoint if omitted)
    wait_seconds:  int  — seconds to wait after fix_srl_topology (default: 40)

Returns: JSON string with deployment result
    {"status": "deployed", "lab_name": "olav-lab", "steps": {...}}
    {"status": "error", "step": "...", "error": "..."}
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

_CONFIG_PATH = (
    Path(__file__).resolve().parents[4]
    / ".olav" / "workspace" / "ops" / "lab" / "config" / "config.json"
)
_CLAB_HOST = os.environ.get("OLAV_CLAB_HOST", "192.168.100.12")


def _bootstrap_clab_env() -> None:
    """Set CLAB_USERNAME/CLAB_PASSWORD from config.json if not already in environment."""
    if os.environ.get("CLAB_USERNAME") and os.environ.get("CLAB_PASSWORD"):
        return
    try:
        cfg = json.loads(_CONFIG_PATH.read_text())
        os.environ.setdefault("CLAB_USERNAME", cfg.get("username", "admin"))
        os.environ.setdefault("CLAB_PASSWORD", cfg.get("password", "clab"))
    except Exception:
        pass


def _get_clab_ssh_host() -> str:
    """Extract SSH hostname from the containerlab service endpoint URL."""
    try:
        from olav.platform.services.registry import ServiceRegistry
        svc = ServiceRegistry.get_instance().get("containerlab")
        host = urlparse(svc.endpoint).hostname
        return host or ""
    except Exception:
        return ""


def _get_mgmt_subnet(lab_name: str = "") -> str:
    """Derive a unique mgmt subnet per lab name to avoid Docker network conflicts.

    Uses a hash of the lab name to pick a /24 in 172.21.32.0 – 172.21.63.0.
    Falls back to config.json mgmt_subnet only when lab_name is empty.
    """
    if lab_name:
        import hashlib
        h = int(hashlib.md5(lab_name.encode()).hexdigest(), 16)
        third_octet = 32 + (h % 32)  # 172.21.32.0 – 172.21.63.0
        return f"172.21.{third_octet}.0/24"
    try:
        cfg = json.loads(_CONFIG_PATH.read_text())
        return cfg.get("mgmt_subnet", "172.20.50.0/24")
    except Exception:
        return "172.20.50.0/24"


import re as _re

_VALID_SRL_IFACE = _re.compile(r"^(ethernet-\d+/\d+(/\d+)?|e\d+-\d+(-\d+)?)$")
_VALID_NODE_KINDS = {"nokia_srlinux"}
# Common aliases auto-normalized to nokia_srlinux
_KIND_ALIASES = {"srlinux": "nokia_srlinux", "srl": "nokia_srlinux"}


def _normalize_clab_topology(topo_dict: dict) -> dict:
    """Auto-correct common topology mistakes (e.g. kind=srlinux → nokia_srlinux)."""
    import copy
    topo = copy.deepcopy(topo_dict)
    nodes = topo.get("topology", {}).get("nodes", {})
    for node_cfg in nodes.values():
        if isinstance(node_cfg, dict):
            kind = node_cfg.get("kind", "")
            if kind in _KIND_ALIASES:
                node_cfg["kind"] = _KIND_ALIASES[kind]
    return topo


def _validate_clab_topology(topo_dict: dict) -> list[str]:
    """Return list of error strings for common CLAB topology mistakes.

    Checks:
    - Node kind must be nokia_srlinux (not srlinux, srl, etc.)
    - Link endpoints must use valid SRL interface names (e1-1, ethernet-1/1, etc.)
    """
    errors = []
    nodes = topo_dict.get("topology", {}).get("nodes", {})
    for node_name, node_cfg in nodes.items():
        if isinstance(node_cfg, dict):
            kind = node_cfg.get("kind", "")
            if kind and kind not in _VALID_NODE_KINDS:
                errors.append(
                    f"Node '{node_name}': kind='{kind}' is INVALID. "
                    f"Must be 'nokia_srlinux'. Got: {kind!r}"
                )
    links = topo_dict.get("topology", {}).get("links", [])
    for i, link in enumerate(links):
        if isinstance(link, dict):
            endpoints = link.get("endpoints", [])
            if not isinstance(endpoints, list) or len(endpoints) != 2:
                errors.append(
                    f"Link[{i}]: 'endpoints' must be a list of exactly 2 strings "
                    f"like [\"r1:e1-1\", \"r4:e1-1\"]. Got: {endpoints!r}"
                )
                continue
            for ep in endpoints:
                if not isinstance(ep, str) or ":" not in ep:
                    errors.append(
                        f"Link[{i}] endpoint {ep!r}: must be 'nodename:interface' "
                        f"(e.g. 'r1:e1-1')"
                    )
                    continue
                node, iface = ep.split(":", 1)
                if not _VALID_SRL_IFACE.match(iface):
                    errors.append(
                        f"Link[{i}] endpoint '{ep}': interface '{iface}' is INVALID. "
                        f"Must match ethernet-L/P or eL-P pattern (e.g. 'e1-1', 'ethernet-1/1'). "
                        f"WRONG values: eth1, eth0, eth-1, Ethernet0/0"
                    )
    return errors


def deploy_lab(
    yaml_content: str,
    ssh_host: str = "",
    wait_seconds: int = 40,
) -> dict:
    """Deploy a ContainerLab topology and run mandatory post-deploy workarounds.

    Use this IMMEDIATELY after run_python_simulation returns the topology YAML.
    This tool combines: POST /api/v1/labs + fix_srl_topology + create_srl_links.

    Args:
        yaml_content: Topology YAML string from run_python_simulation _result["yaml"].
        ssh_host: Docker host for veth pair injection. Resolved from containerlab
                  service endpoint if not provided.
        wait_seconds: Seconds to wait after topology fix (default: 40).

    Returns:
        JSON with deployment status and steps result.

    Example:
        deploy_lab(yaml_content="name: olav-lab\\ntopology: ...")
    """
    _bootstrap_clab_env()
    resolved_ssh_host = ssh_host or _get_clab_ssh_host()
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

        # Auto-inject correct image into any node that lacks one — prevents the agent
        # from searching the web for image tags and using wrong/outdated images.
        _SRL_IMAGE = "ghcr.io/nokia/srlinux:24.10.1"
        _nodes = topo_dict.get("topology", {}).get("nodes", {})
        _kinds = topo_dict.get("topology", {}).get("kinds", {})
        for _node_name, _node_cfg in _nodes.items():
            if not isinstance(_node_cfg, dict):
                _node_cfg = {}
                _nodes[_node_name] = _node_cfg
            # Inject kind if missing
            if not _node_cfg.get("kind"):
                _node_cfg["kind"] = "nokia_srlinux"
            # Inject image if missing or wrong (not the pinned version)
            if not _node_cfg.get("image") and not _kinds.get(_node_cfg.get("kind", ""), {}).get("image"):
                _node_cfg["image"] = _SRL_IMAGE
            elif _node_cfg.get("image") and "srlinux" in _node_cfg["image"] and ":24.10.1" not in _node_cfg["image"]:
                # Override any wrong srlinux tag (e.g. :latest) with the pinned version
                _node_cfg["image"] = _SRL_IMAGE
        # Also override the kinds section if it specifies a wrong image
        for _kind_name, _kind_cfg in _kinds.items():
            if isinstance(_kind_cfg, dict) and _kind_cfg.get("image"):
                if "srlinux" in _kind_cfg["image"] and ":24.10.1" not in _kind_cfg["image"]:
                    _kind_cfg["image"] = _SRL_IMAGE

        # Normalize topology before validation (auto-fix common agent mistakes like kind=srlinux)
        topo_dict = _normalize_clab_topology(topo_dict)

        # Validate topology before calling CLAB (catches common agent mistakes early)
        validation_errors = _validate_clab_topology(topo_dict)
        if validation_errors:
            return {
                "status": "error",
                "step": "validate",
                "error": "Topology YAML has errors — fix before deploying:\n" + "\n".join(f"  - {e}" for e in validation_errors),
                "hint": "Correct format: kind=nokia_srlinux, endpoints=[\"r1:e1-1\", \"r4:e1-1\"]",
            }

        # Inject unique mgmt network to avoid subnet conflicts with other labs
        lab_name = topo_dict.get("name", "olav-lab")
        if "mgmt" not in topo_dict:
            topo_dict["mgmt"] = {
                "network": f"clab-{lab_name}",
                "ipv4-subnet": _get_mgmt_subnet(lab_name),
            }

        deploy_result = service_call(
            "containerlab",
            method="POST",
            path="/api/v1/labs",
            body={"topologyContent": topo_dict},
            confirmed=True,
        )
        # service_call returns parsed JSON on 2xx, raises on 4xx/5xx.
        # Successful CLAB deploy response: {lab_name: [list_of_containers]}
        # 409 is raised as HTTPStatusError — catch separately below.
        results["deploy"] = {
            "status": "ok",
            "containers": len(deploy_result.get(lab_name, [])),
        }
    except Exception as e:
        # Include response body so agent sees the actual CLAB error (e.g., "eth1 doesn't match pattern")
        body_hint = ""
        if hasattr(e, "response") and e.response is not None:
            try:
                body_hint = " | CLAB error: " + e.response.text[:400]
            except Exception:
                pass
        err_str = str(e) + body_hint
        if "409" in err_str or "already been deployed" in err_str.lower():
            results["deploy"] = {"note": "Lab already exists, continuing with post-deploy steps"}
        else:
            return {"status": "error", "step": "deploy", "error": err_str}

    # Step 2: fix_srl_topology + Step 3: create_srl_links
    # These helpers live in the workspace tools dir (not yet folded —
    # deferred to a later round); load via spec to keep src/olav clean.
    import importlib.util
    _ws_tools_dir = (
        Path(__file__).resolve().parents[4]
        / ".olav" / "workspace" / "ops" / "lab" / "tools"
    )

    def _load_ws_module(name: str):
        spec = importlib.util.spec_from_file_location(name, _ws_tools_dir / f"{name}.py")
        if spec is None or spec.loader is None:
            raise ImportError(f"workspace helper {name} not found at {_ws_tools_dir}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    try:
        _fix_mod = _load_ws_module("fix_srl_topology")
        fix_result = _fix_mod.fix_srl_topology({"lab_name": lab_name, "wait_secs": wait_seconds, "ssh_host": resolved_ssh_host, "ssh_user": "olav"})
        results["fix_topology"] = str(fix_result)[:300]
    except Exception as e:
        results["fix_topology"] = f"error: {e}"

    try:
        _links_mod = _load_ws_module("create_srl_links")
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
            "ssh_host": resolved_ssh_host,
            "ssh_user": "olav",
            "links": links_explicit if links_explicit else None,
        })
        results["create_links"] = str(links_result)[:300]
    except Exception as e:
        results["create_links"] = f"error: {e}"

    return {
        "status": "deployed",
        "lab_name": lab_name,
        "steps": results,
        "next": (
            f"Lab '{lab_name}' is running on REMOTE host {_get_clab_ssh_host() or _CLAB_HOST}. "
            "docker exec will NOT work — containers are not local. "
            f"NEXT STEP: call push_node_config to push SRL config to each node. "
            f"Example: push_node_config({{\"lab_name\": \"{lab_name}\", \"node\": \"r1\", \"config\": \"set / interface ...\"}}). "
            "Then use exec_on_node for show commands to verify state."
        ),
    }


