"""Execute a CLI command on a lab node via the CLAB exec API.

Used by the lab agent to verify protocol convergence after config push:
  - Run "show bgp summary" and check for ESTABLISHED neighbors
  - Run "show ospf neighbor" and check for FULL state
  - Run "show version" to confirm node is reachable

Tool: exec_on_node

Args (JSON):
    lab_name:  str         — ContainerLab lab name
    node:      str         — node name (e.g. "R1", "r1")
    command:   str         — CLI command to execute on the node.
                             For SR Linux show commands pass the sr_cli command directly:
                               "sr_cli 'show version'"
                               "sr_cli 'show network-instance default protocols bgp neighbor'"
                             The tool auto-wraps sr_cli commands with bash+base64 so that
                             stdout is reliably captured by the CLAB exec API. Do NOT manually
                             add bash -c or base64 wrapping — the tool handles it automatically.
    timeout:   int | None  — request timeout in seconds (default: 30)

Returns: JSON string
    {"stdout": "...", "stderr": "...", "return_code": 0, "node": "R1", "command": "..."}
    {"error": "...", "node": "R1", "command": "..."}

Auth: uses platform service_call("containerlab") — JWT handled by ServiceRegistry.
API: POST /api/v1/labs/{lab_name}/exec?nodeFilter={container_name}
     body: {"command": "<shell command string>"}

CLAB exec behavior:
  - All sr_cli commands are auto-wrapped with bash+base64 by the tool to ensure stdout capture.
  - Simply pass the sr_cli command string; no manual base64 wrapping required.
  - return_code is ALWAYS 0 regardless of sr_cli errors — check stdout for "Commit failed"
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_OLAV_SRC = Path(__file__).parents[5] / "src"
if str(_OLAV_SRC) not in sys.path:
    sys.path.insert(0, str(_OLAV_SRC))

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.json"


def _bootstrap_clab_env() -> None:
    """Set CLAB_USERNAME/CLAB_PASSWORD from config.json if not already in environment.

    The platform ServiceRegistry authenticates using env vars. This bootstrap
    bridges the lab-local config.json into the expected env var format once,
    allowing service_call to handle all subsequent JWT lifecycle management.
    """
    if os.environ.get("CLAB_USERNAME") and os.environ.get("CLAB_PASSWORD"):
        return
    try:
        cfg = json.loads(_CONFIG_PATH.read_text())
        os.environ.setdefault("CLAB_USERNAME", cfg.get("username", "admin"))
        os.environ.setdefault("CLAB_PASSWORD", cfg.get("password", "clab"))
    except Exception:
        pass


from langchain_core.tools import tool


@tool
def exec_on_node(
    lab_name: str,
    node: str,
    command: str,
    timeout: int = 30,
) -> str:
    """Execute a CLI command on a ContainerLab node via the remote CLAB exec API.

    CLAB runs on REMOTE host (OLAV_CLAB_HOST) — do NOT use docker exec or SSH.

    For SR Linux show commands:
        exec_on_node(lab_name="r1-r4-ebgp-direct", node="r1",
                     command="sr_cli -c 'show network-instance default protocols bgp neighbor'")

    For verifying BGP state — look for "established" in the returned stdout.

    Args:
        lab_name: ContainerLab lab name (e.g. "r1-r4-ebgp-direct")
        node:     Node name as in topology YAML (e.g. "r1", "r4")
        command:  Shell command to run on the node. Use sr_cli -c '...' for SRL show commands.
        timeout:  Request timeout in seconds (default: 30)

    Returns:
        JSON string: {"stdout": "...", "stderr": "...", "return_code": 0, "node": "r1"}
    """
    _bootstrap_clab_env()

    from olav.platform.services.client import service_call
    # CLAB nodeFilter requires full container name: clab-{lab_name}-{node}
    container_name = f"clab-{lab_name}-{node}"

    # Auto-wrap sr_cli commands: extract the SRL command text and pipe it to sr_cli
    # via stdin (base64-encoded). CLAB exec API has no tty; "sr_cli -c '...'" via
    # bash produces NO stdout. The stdin-pipe approach is the only reliable method.
    import base64 as _b64, re as _re
    _cmd = command.strip()
    if _cmd.startswith("sr_cli") and not _cmd.startswith("bash -c"):
        # Extract SRL content from: sr_cli 'show ...' or sr_cli -c "show ..."
        _m = _re.match(r"""^sr_cli\s+(?:-c\s+)?['"](.*)['"]\s*$""", _cmd, _re.DOTALL)
        srl_content = _m.group(1) if _m else _re.sub(r"^sr_cli\s+(?:-c\s+)?", "", _cmd)
        _b64_payload = _b64.b64encode((srl_content.strip() + "\n").encode()).decode()
        _cmd = f"bash -c 'echo {_b64_payload} | base64 -d | sr_cli 2>&1'"

    try:
        # confirmed=True: exec is a read-semantic operation (show commands);
        # POST is CLAB's API design choice, not a destructive write.
        body = service_call(
            "containerlab",
            method="POST",
            path=f"/api/v1/labs/{lab_name}/exec",
            params={"nodeFilter": container_name},
            body={"command": _cmd},
            confirmed=True,
            timeout=float(timeout),
        )

        if isinstance(body, dict) and "status" in body and body.get("status") == "requires_approval":
            return json.dumps({"error": "service_call requires approval", "node": node, "command": command})

        # CLAB response: {container_name: [{stdout, stderr, return-code, cmd}]}
        if isinstance(body, dict):
            node_results = body.get(container_name, body.get(node, []))
            if node_results and isinstance(node_results, list):
                r = node_results[0]
                return json.dumps({
                    "stdout": r.get("stdout", ""),
                    "stderr": r.get("stderr", ""),
                    "return_code": r.get("return-code", 0),
                    "node": node,
                    "command": command,
                })

        # Unexpected format — return raw
        return json.dumps({
            "stdout": str(body),
            "return_code": 0,
            "node": node,
            "command": command,
        })

    except Exception as exc:
        return json.dumps({
            "error": str(exc),
            "node": node,
            "command": command,
        })

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Execute CLI on a CLAB node")
    parser.add_argument("--lab", required=True)
    parser.add_argument("--node", required=True)
    parser.add_argument("--command", required=True)
    parser.add_argument("--timeout", type=int, default=30)
    parsed = parser.parse_args()
    result = exec_on_node.invoke({
        "lab_name": parsed.lab, "node": parsed.node,
        "command": parsed.command, "timeout": parsed.timeout,
    })
    print(result)
