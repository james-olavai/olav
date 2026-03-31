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
                             For SR Linux nodes, prefix with "sr_cli -c": e.g.
                             "sr_cli -c 'show version'"
                             "sr_cli -c 'show network-instance default protocols bgp summary'"
    base_url:  str | None  — CLAB base URL (default: http://192.168.100.12:8080)
    timeout:   int | None  — request timeout in seconds (default: 30)

Returns: JSON string
    {"stdout": "...", "return_code": 0, "node": "R1", "command": "show bgp summary"}
    {"error": "...", "node": "R1", "command": "show bgp summary"}

Auth: reads CLAB_TOKEN env var → Authorization: Bearer header.
API: POST /api/v1/labs/{lab_name}/exec with query param nodeFilter={node} and body {"command": command}

CLAB exec response format:
    [{"name": "node", "stdout": "output", "returnCode": 0}]
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_OLAV_SRC = Path(__file__).parents[5] / "src"
if str(_OLAV_SRC) not in sys.path:
    sys.path.insert(0, str(_OLAV_SRC))

import httpx

_DEFAULT_BASE_URL = "http://192.168.100.12:8080"
_CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.json"


def _load_config() -> dict:
    try:
        data = json.loads(_CONFIG_PATH.read_text())
        return data.get("clab", data)
    except Exception:
        return {}


def _get_token(base_url: str) -> str:
    """Get auth token: env var → auto-login from config.json."""
    token = os.environ.get("CLAB_TOKEN", "")
    if token:
        return token
    cfg = _load_config()
    username = cfg.get("username", "admin")
    password = cfg.get("password", "clab")
    try:
        resp = httpx.post(
            f"{base_url.rstrip('/')}/login",
            json={"username": username, "password": password},
            timeout=10.0,
            verify=False,
        )
        token = resp.json().get("token", "")
        if token:
            os.environ["CLAB_TOKEN"] = token
        return token
    except Exception:
        return ""


def exec_on_node(args: dict) -> str:
    """Execute a CLI command on a lab node."""
    lab_name: str = args["lab_name"]
    node: str = args["node"]
    command: str = args["command"]
    cfg = _load_config()
    base_url: str = args.get("base_url") or cfg.get("base_url", _DEFAULT_BASE_URL)
    timeout: int = int(args.get("timeout") or 30)

    token = _get_token(base_url)
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    # nodeFilter requires full container name: clab-{lab_name}-{node}
    url = f"{base_url.rstrip('/')}/api/v1/labs/{lab_name}/exec"
    container_name = f"clab-{lab_name}-{node}"

    try:
        response = httpx.request(
            "POST",
            url,
            headers=headers,
            params={"nodeFilter": container_name},
            json={"command": command},
            timeout=float(timeout),
        )

        try:
            body = response.json()
        except Exception:
            body = response.text

        if response.status_code >= 400:
            return json.dumps({
                "error": f"HTTP {response.status_code}",
                "body": body,
                "node": node,
                "command": command,
            })

        # CLAB response: {container_name: [{stdout, stderr, return-code, cmd}]}
        if isinstance(body, dict):
            node_results = body.get(container_name, body.get(node, []))
            if node_results:
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
    parser.add_argument("args_json", nargs="?", default="{}")
    parsed = parser.parse_args()
    result = json.loads(exec_on_node(json.loads(parsed.args_json)))
    print(json.dumps(result, indent=2))
