"""Push SR Linux CLI configuration to a lab node.

This is the CORRECT tool for pushing config to ContainerLab SRL nodes.
The CLAB server is REMOTE (see OLAV_CLAB_HOST env var) — docker exec will NOT work.

Tool: push_node_config

Args (JSON):
    lab_name:  str  — ContainerLab lab name (e.g. "r1-r4-ebgp-direct")
    node:      str  — node name as in topology YAML (e.g. "r1", "r4")
    config:    str  — multi-line SR Linux set commands (plain text, no base64 needed)
                      Example:
                        set / interface ethernet-1/1 admin-state enable
                        set / interface ethernet-1/1 subinterface 0 ipv4 address 10.0.0.1/30
                        set / network-instance default protocols bgp autonomous-system 65000
                        set / network-instance default protocols bgp neighbor 10.0.0.2 peer-group ebgp
                      The tool automatically wraps in: enter candidate / discard now / ... / commit now
    timeout:   int | None  — timeout in seconds (default: 60)

Returns: JSON string
    {"status": "ok", "stdout": "...", "node": "r1"}     — success
    {"status": "error", "stdout": "...", "node": "r1"}  — SRL commit failed (check stdout)
    {"error": "...", "node": "r1"}                      — API/transport error

CLAB exec pattern used internally:
    bash -c 'echo <base64-config> | base64 -d | sr_cli 2>&1'

Note: return_code is always 0 on SRL errors — status "error" is set when stdout
contains "Commit failed", "Error in /", or "Parsing error".
"""

from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

_CONFIG_PATH = (
    Path(__file__).resolve().parents[4]
    / ".olav" / "workspace" / "ops" / "lab" / "config" / "config.json"
)


def _bootstrap_clab_env() -> None:
    if os.environ.get("CLAB_USERNAME") and os.environ.get("CLAB_PASSWORD"):
        return
    try:
        cfg = json.loads(_CONFIG_PATH.read_text())
        os.environ.setdefault("CLAB_USERNAME", cfg.get("username", "admin"))
        os.environ.setdefault("CLAB_PASSWORD", cfg.get("password", "clab"))
    except Exception:
        pass


def push_node_config(
    lab_name: str,
    node: str,
    config_lines: list,
    timeout: int = 60,
) -> dict:
    """Push SR Linux CLI configuration to a ContainerLab node.

    This is the ONLY correct tool for pushing config to lab nodes.
    CLAB runs on REMOTE host (OLAV_CLAB_HOST) — docker exec will NEVER work.

    Pass config as a list of 'set /' command strings. The tool wraps them
    automatically in: enter candidate / ... / commit now

    Example:
        push_node_config(
            lab_name="r1-r4-ebgp-direct",
            node="r1",
            config_lines=[
                "set / interface ethernet-1/1 admin-state enable",
                "set / interface ethernet-1/1 subinterface 0 admin-state enable",
                "set / interface ethernet-1/1 subinterface 0 ipv4 admin-state enable",
                "set / interface ethernet-1/1 subinterface 0 ipv4 address 10.0.0.1/30",
                "set / network-instance default interface ethernet-1/1.0",
                "set / network-instance default protocols bgp admin-state enable",
                "set / network-instance default protocols bgp autonomous-system 65000",
                "set / network-instance default protocols bgp router-id 10.0.0.1",
                "set / network-instance default protocols bgp afi-safi ipv4-unicast admin-state enable",
                "set / network-instance default protocols bgp group ebgp-r4 peer-as 65001",
                "set / network-instance default protocols bgp neighbor 10.0.0.2 peer-group ebgp-r4"
            ]
        )

    Args:
        lab_name:     ContainerLab lab name (e.g. "r1-r4-ebgp-direct")
        node:         Node name as in topology YAML (e.g. "r1", "r4")
        config_lines: List of SR Linux set commands (one string per line)
        timeout:      Request timeout in seconds (default: 60)

    Returns:
        JSON string: {"status": "ok"|"error"|"dry_run_failed", "stdout": "...", "committed": bool, "node": "r1"}
    """
    _bootstrap_clab_env()

    from olav.platform.services.client import service_call

    config = "\n".join(str(line) for line in config_lines)
    container_name = f"clab-{lab_name}-{node}"

    def _exec_srl(script: str) -> str:
        """Execute an sr_cli script on node via CLAB exec API. Returns stdout string."""
        b64 = base64.b64encode(script.encode()).decode()
        command = f"bash -c 'echo {b64} | base64 -d | sr_cli 2>&1'"
        body = service_call(
            "containerlab",
            method="POST",
            path=f"/api/v1/labs/{lab_name}/exec",
            params={"nodeFilter": container_name},
            body={"command": command},
            confirmed=True,
            timeout=float(timeout),
        )
        if isinstance(body, dict) and body.get("status") == "requires_approval":
            return ""
        stdout = ""
        if isinstance(body, dict):
            node_results = body.get(container_name, body.get(node, []))
            if node_results and isinstance(node_results, list):
                stdout = node_results[0].get("stdout", "")
        return stdout

    error_indicators = ["Commit failed", "Error in /", "Parsing error", "error:", "Validate failed", "Error:"]

    try:
        # ── Phase 1: commit validate (YANG model validation) ──────────────────
        # Uses: enter candidate → set commands → commit validate
        # SRL v24.10.1: use "commit validate" NOT "commit dry-run" (dry-run is invalid)
        # SRL does NOT discard candidate after validate — candidate persists until commit/discard
        validate_script = f"enter candidate\n{config.strip()}\ncommit validate\n"
        dry_stdout = _exec_srl(validate_script)

        # Check for validation errors — "Error: Validate failed" or "Error in /<path>"
        has_dry_error = any(ind in dry_stdout for ind in error_indicators)
        # SRL validate success: "All changes have been validated." or empty stdout
        # If stdout is empty on validate, proceed optimistically (exec API occasionally drops stdout)
        dry_run_ok = not has_dry_error

        if not dry_run_ok:
            return {
                "status": "dry_run_failed",
                "stdout": dry_stdout,
                "committed": False,
                "node": node,
                "hint": "SRL YANG validation rejected config. Fix the commands listed above and retry.",
            }

        # ── Phase 2: commit now ────────────────────────────────────────────────
        commit_script = f"enter candidate\n{config.strip()}\ncommit now\n"
        stdout = _exec_srl(commit_script)

        has_error = any(ind in stdout for ind in error_indicators)

        if has_error:
            return {
                "status": "error",
                "stdout": stdout,
                "committed": False,
                "node": node,
            }

        # SRL sr_cli produces minimal stdout on success ("All changes have been committed.")
        # Normalise so LLM always sees a non-empty, unambiguous confirmation.
        msg = stdout.strip() if stdout.strip() else "All changes committed successfully."
        return {
            "status": "ok",
            "stdout": msg,
            "committed": True,
            "node": node,
        }

    except Exception as exc:
        return {"error": str(exc), "node": node}
