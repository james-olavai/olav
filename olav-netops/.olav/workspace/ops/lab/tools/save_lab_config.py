"""Save SR Linux configuration lines for a node to a temp file.

Use this tool to store config lines for each node BEFORE calling deploy_and_push_lab.
deploy_and_push_lab will automatically load configs from these files when configs={}.

Tool: save_lab_config

Args (JSON):
    lab_name:     str        — Lab name (e.g. "r1-r4-ebgp-direct")
    node:         str        — Node name (e.g. "r1" or "r4")
    config_lines: list[str]  — All SRL "set /" commands for this node
                               Include ALL commands in correct SRL v24.10.1 syntax.
                               Do NOT include "commit now" — deploy_and_push_lab adds it.

Returns: JSON confirming save
    {"saved": true, "node": "r1", "lines": 20, "lab_name": "r1-r4-ebgp-direct"}

Example:
    save_lab_config(
        lab_name="r1-r4-ebgp-direct",
        node="r1",
        config_lines=[
            "set / interface ethernet-1/1 admin-state enable",
            "set / interface ethernet-1/1 subinterface 0 admin-state enable",
            "set / interface ethernet-1/1 subinterface 0 ipv4 admin-state enable",
            "set / interface ethernet-1/1 subinterface 0 ipv4 address 10.0.0.1/30",
            "set / interface system0 subinterface 0 admin-state enable",
            "set / interface system0 subinterface 0 ipv4 admin-state enable",
            "set / interface system0 subinterface 0 ipv4 address 1.1.1.1/32",
            "set / network-instance default interface ethernet-1/1.0",
            "set / network-instance default interface system0.0",
            "set / routing-policy prefix-set loopbacks prefix 1.1.1.1/32 mask-length-range exact",
            "set / routing-policy policy export-bgp statement 10 match prefix-set loopbacks",
            "set / routing-policy policy export-bgp statement 10 action policy-result accept",
            "set / routing-policy policy export-bgp default-action policy-result reject",
            "set / network-instance default protocols bgp admin-state enable",
            "set / network-instance default protocols bgp autonomous-system 65000",
            "set / network-instance default protocols bgp router-id 1.1.1.1",
            "set / network-instance default protocols bgp afi-safi ipv4-unicast admin-state enable",
            "set / network-instance default protocols bgp ebgp-default-policy import-reject-all false",
            "set / network-instance default protocols bgp group ebgp-r4 peer-as 65001",
            "set / network-instance default protocols bgp group ebgp-r4 export-policy [export-bgp]",
            "set / network-instance default protocols bgp neighbor 10.0.0.2 peer-group ebgp-r4"
        ]
    )
"""

from __future__ import annotations

import json
from pathlib import Path

from langchain_core.tools import tool


@tool
def save_lab_config(
    lab_name: str,
    node: str,
    config_lines: list,
) -> str:
    """Save SR Linux config lines for a node to a temp file.

    Call this for each node BEFORE calling deploy_and_push_lab.
    deploy_and_push_lab will auto-load these configs.

    Args:
        lab_name:     Lab name (e.g. "r1-r4-ebgp-direct")
        node:         Node name (e.g. "r1" or "r4")
        config_lines: List of SRL "set /" commands (do NOT include "commit now")

    Returns:
        JSON confirming save with node name and line count
    """
    if not config_lines:
        return json.dumps({
            "saved": False,
            "error": "config_lines is empty — provide all SRL set commands for this node",
            "node": node,
        })

    try:
        # R86 follow-up: move config dropbox from /tmp/clab_config_*.json
        # to exports/lab/<lab_name>/<node>.json — files are now under
        # the same audit-traceable EXPORTS_DIR as the rest of R85's
        # save outputs.  deploy_and_push_lab reads from the same path.
        from olav.core.config import EXPORTS_DIR
        out_dir = EXPORTS_DIR / "lab" / lab_name
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{node}.json"
        path.write_text(json.dumps(config_lines, indent=2, ensure_ascii=False))
        return json.dumps({
            "saved": True,
            "node": node,
            "lab_name": lab_name,
            "lines": len(config_lines),
            "path": str(path),
            "message": f"Config for {node} saved ({len(config_lines)} lines). Call save_lab_config for all remaining nodes, then call deploy_and_push_lab.",
        })
    except Exception as e:
        return json.dumps({"saved": False, "error": str(e), "node": node})
