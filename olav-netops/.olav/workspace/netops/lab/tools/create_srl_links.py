"""Create inter-node veth pairs for SRL containers deployed via CLAB REST API.

CLAB REST API (≤0.74.1) creates SRL containers but does NOT create inter-node
data plane veth pairs from the topology links: section.  The clab-api-server
container lacks --pid=host so it cannot access host-level /proc/<PID>/ns/net.

This tool injects the missing veths by running a single privileged Alpine
container on the Docker host.  It also restarts sr_device_mgr on all affected
nodes so SRL detects the new physical links (changing lower-layer-down →
port-admin-disabled).

Tool: create_srl_links

Args (JSON):
    lab_name:     str        — ContainerLab lab name (e.g. "digital-twin")
    links:        list[dict] — veths to create:
                    [{"a_node": "R4", "a_iface": "e1-1",
                      "b_node": "R2", "b_iface": "e1-3"}, ...]
                    Accepts both "ethernet-1/1" and "e1-1" formats.
                    If omitted, auto-reads from domain.duckdb topology_links.
    restart_mgr:  bool       — restart sr_device_mgr after veth injection (default: True)
    wait_secs:    int        — seconds to wait for mgmd after restart (default: 40)
    dry_run:      bool       — return generated script without executing (default: False)
    ssh_host:     str | None — SSH host for remote docker execution (e.g. resolved from containerlab service endpoint)
    ssh_user:     str | None — SSH user (default: "admin")
    db_path:      str | None — domain.duckdb path for auto-discovery of topology links

Returns: JSON string
    {"created": [...], "restarted": [...], "failed": [...], "script"?: "..."}

Requirements:
    - Docker must be accessible (locally or via ssh_host) with privilege to run
      containers and access /proc/<PID>/ns/net.
    - On the Docker host, the privileged Alpine image must be pullable.
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

_OLAV_SRC = Path(__file__).parents[5] / "src"
if str(_OLAV_SRC) not in sys.path:
    sys.path.insert(0, str(_OLAV_SRC))

from olav.core.config import MAIN_DB_PATH as _DEFAULT_DB
_DEFAULT_SSH_USER = "olav"
_DEFAULT_WAIT = 40


# ---------------------------------------------------------------------------
# Interface name helpers
# ---------------------------------------------------------------------------

def _to_kernel_iface(iface: str) -> str:
    """Convert SRL interface name to Linux kernel name.

    ethernet-1/1 → e1-1
    e1-1         → e1-1  (pass-through)
    """
    m = re.match(r"ethernet-(\d+)/(\d+)", iface.strip().lower())
    if m:
        return f"e{m.group(1)}-{m.group(2)}"
    return iface.strip()


def _parse_endpoint(endpoint: str) -> tuple[str, str]:
    """Parse 'R3:ethernet-1/1' → ('R3', 'e1-1')."""
    node, _, iface = endpoint.partition(":")
    return node.strip(), _to_kernel_iface(iface)


# ---------------------------------------------------------------------------
# Auto-discovery of topology links from domain.duckdb
# ---------------------------------------------------------------------------

def _discover_links_from_db(lab_name: str, db_path: Path) -> list[dict]:
    """Read topology_links for the lab from domain.duckdb."""
    try:
        import duckdb

        con = duckdb.connect(str(db_path), read_only=True)
        # Try topology_links table (schema may vary)
        rows = con.execute(
            """
            SELECT a_node, a_iface, b_node, b_iface
            FROM netops.topology_links
            WHERE lab_name = ?
            """,
            [lab_name],
        ).fetchall()
        con.close()
        return [
            {
                "a_node": r[0],
                "a_iface": _to_kernel_iface(r[1]),
                "b_node": r[2],
                "b_iface": _to_kernel_iface(r[3]),
            }
            for r in rows
        ]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Script generation
# ---------------------------------------------------------------------------

def _build_inject_script(
    links: list[dict],
    node_pids_var: dict[str, str],  # node → bash variable name for PID
) -> str:
    """Build the Alpine shell script (runs inside privileged container).

    Uses 'create_link A B PID_A PID_B' function to:
      1. Create veth pair in host namespace (A gets its final name)
      2. Detect peer's auto-generated name
      3. Move A → A's container namespace, peer → B's namespace
      4. Rename peer to B's final interface name via nsenter
      5. Bring both up
    """
    link_cmds: list[str] = []
    for lnk in links:
        a_node = lnk["a_node"]
        b_node = lnk["b_node"]
        a_iface = _to_kernel_iface(lnk.get("a_iface", ""))
        b_iface = _to_kernel_iface(lnk.get("b_iface", ""))
        a_pid_var = node_pids_var.get(a_node, f"UNKNOWN_{a_node}_PID")
        b_pid_var = node_pids_var.get(b_node, f"UNKNOWN_{b_node}_PID")
        link_cmds.append(
            f'create_link "{a_iface}" "{b_iface}" "${a_pid_var}" "${b_pid_var}"'
            f"  # {a_node}:{a_iface} <-> {b_node}:{b_iface}"
        )

    link_section = "\n".join(link_cmds)
    return f"""#!/bin/sh
set -e

create_link() {{
  local A_NAME="$1" B_NAME="$2" A_PID="$3" B_PID="$4"
  # Remove stale interfaces in both namespaces
  nsenter -n -t "$A_PID" -- ip link del "$A_NAME" 2>/dev/null || true
  nsenter -n -t "$B_PID" -- ip link del "$B_NAME" 2>/dev/null || true
  # Create veth in host namespace; peer gets an auto-generated name.
  # Alpine iproute2 doesn't accept mtu after "type veth" — set MTU separately.
  ip link add name "$A_NAME" type veth
  PEER=$(ip link show "$A_NAME" 2>/dev/null | awk -F'@' '{{print $2}}' | awk '{{print $1}}' | tr -d ':')
  ip link set "$A_NAME" mtu 9500
  ip link set "$PEER" mtu 9500
  # Move each end into its container namespace
  ip link set "$A_NAME" netns "$A_PID"
  ip link set "$PEER" netns "$B_PID"
  # Rename peer to its final interface name inside B's namespace
  nsenter -n -t "$B_PID" -- ip link set "$PEER" name "$B_NAME"
  # Bring both up
  nsenter -n -t "$A_PID" -- ip link set "$A_NAME" up
  nsenter -n -t "$B_PID" -- ip link set "$B_NAME" up
  echo "  ok: $A_NAME <-> $B_NAME"
}}

{link_section}
"""


def _build_full_bash_script(links: list[dict]) -> str:
    """Build the complete bash script to run on the Docker host.

    1. Get PIDs for all involved nodes via docker inspect
    2. Run privileged Alpine container with PIDs as env vars
    3. Restart sr_device_mgr on each node
    """
    # Collect unique nodes
    nodes: list[str] = []
    seen: set[str] = set()
    for lnk in links:
        for n in (lnk["a_node"], lnk["b_node"]):
            if n not in seen:
                nodes.append(n)
                seen.add(n)

    # PID variable names: R1 → R1_PID, clab-olav-lab-R1 → clab_olav_lab_R1_PID
    # Bash variable names cannot contain hyphens — replace with underscores.
    def _safe_var(name: str) -> str:
        return re.sub(r"[^A-Za-z0-9_]", "_", name) + "_PID"

    pid_vars: dict[str, str] = {n: _safe_var(n) for n in nodes}

    # Build inspect lines
    inspect_lines = "\n".join(
        f'{var}=$(docker inspect {node} --format \'{{{{.State.Pid}}}}\')'
        for node, var in pid_vars.items()
    )

    # Build -e flags for docker run
    env_flags = " ".join(f"-e {var}=${var}" for var in pid_vars.values())

    # Inner Alpine script (injected via stdin with -i flag)
    alpine_script = _build_inject_script(links, pid_vars)

    # Restart sr_device_mgr by killing the existing process.
    # Killing it causes sr_app_mgr (which owns the process) to restart it cleanly,
    # which triggers full hardware rescan including new veth interfaces.
    # Do NOT launch a new sr_device_mgr externally — that bypasses sr_app_mgr.
    restart_lines = "\n".join(
        f"docker exec {node} sh -c 'kill $(pgrep -x sr_device_mgr) 2>/dev/null || true'"
        for node in nodes
    )

    return f"""#!/bin/bash
set -e
echo "=== Getting container PIDs ==="
{inspect_lines}

echo "=== Creating veth pairs ==="
docker run --rm -i --privileged --net=host --pid=host \\
  {env_flags} \\
  alpine sh << 'INNEREOF'
{alpine_script}
INNEREOF

echo "=== Restarting sr_device_mgr ==="
{restart_lines}

echo "=== Done. Wait ~40s for management plane to restart ==="
"""


# ---------------------------------------------------------------------------
# Execution helpers
# ---------------------------------------------------------------------------

def _run_script(script: str, ssh_host: str | None, ssh_user: str) -> tuple[int, str, str]:
    """Run a bash script locally or on a remote host via SSH.

    Encodes the script as base64 to avoid stdin piping and quoting issues.
    Uses SSHBackend / LocalBackend for consistent connection options.
    """
    from olav.platform.execution import ExecutionConfig, LocalBackend, SSHBackend

    b64 = base64.b64encode(script.encode()).decode()
    cmd = f"echo {b64} | base64 -d | bash"

    if ssh_host:
        backend: SSHBackend | LocalBackend = SSHBackend(
            host=ssh_host, user=ssh_user or None
        )
        cfg = ExecutionConfig(timeout=120)
    else:
        backend = LocalBackend()
        cfg = ExecutionConfig(timeout=120, shell=True)

    result = backend.execute(cmd, cfg)
    return result.returncode, result.stdout, result.stderr


def _wait_mgmd(node: str, wait_secs: int, ssh_host: str | None, ssh_user: str) -> bool:
    """Poll sr_cli show version until SRL management plane is up."""
    from olav.platform.execution import ExecutionConfig, LocalBackend, SSHBackend

    check_cmd = f"docker exec {node} sr_cli show version"
    cfg = ExecutionConfig(timeout=10, shell=True)

    if ssh_host:
        backend: SSHBackend | LocalBackend = SSHBackend(
            host=ssh_host, user=ssh_user or None
        )
    else:
        backend = LocalBackend()

    deadline = time.monotonic() + wait_secs
    while time.monotonic() < deadline:
        try:
            result = backend.execute(check_cmd, cfg)
            if result.ok and "SR Linux" in result.stdout:
                return True
        except Exception:
            pass
        time.sleep(3)
    return False


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def create_srl_links(args: dict) -> str:
    """Create inter-node veth pairs for SRL lab nodes."""
    lab_name: str = args["lab_name"]
    links_raw: list[dict] | None = args.get("links")
    restart_mgr: bool = bool(args.get("restart_mgr", True))
    wait_secs: int = int(args.get("wait_secs") or _DEFAULT_WAIT)
    dry_run: bool = bool(args.get("dry_run", False))
    ssh_host: str | None = args.get("ssh_host")
    ssh_user: str = args.get("ssh_user") or _DEFAULT_SSH_USER
    db_path_str: str | None = args.get("db_path")

    # Resolve links
    links: list[dict] = []
    if links_raw:
        for lnk in links_raw:
            links.append({
                "a_node": lnk["a_node"],
                "a_iface": _to_kernel_iface(lnk.get("a_iface", "")),
                "b_node": lnk["b_node"],
                "b_iface": _to_kernel_iface(lnk.get("b_iface", "")),
            })
    else:
        db_path = Path(db_path_str) if db_path_str else _DEFAULT_DB
        links = _discover_links_from_db(lab_name, db_path)

    if not links:
        return json.dumps({
            "error": (
                "no links provided and auto-discovery found none. "
                "Pass 'links' explicitly or ensure topology_links table has rows for this lab."
            )
        })

    script = _build_full_bash_script(links)

    if dry_run:
        return json.dumps({"dry_run": True, "script": script, "links": links})

    # Execute
    rc, stdout, stderr = _run_script(script, ssh_host, ssh_user)

    output = (stdout or "") + (stderr or "")

    if rc != 0:
        return json.dumps({
            "created": [],
            "restarted": [],
            "failed": [lnk for lnk in links],
            "error": f"script exited {rc}",
            "output": output,
        })

    # Collect created links from output
    created: list[dict] = []
    for lnk in links:
        a = f"{lnk['a_iface']}"
        b = f"{lnk['b_iface']}"
        if f"ok: {a} <-> {b}" in output:
            created.append(lnk)

    # Restart and wait (if not already done in script)
    # The script handles restart; here we optionally wait for mgmd
    restarted: list[str] = []
    if restart_mgr and wait_secs > 0:
        nodes = list({lnk["a_node"] for lnk in links} | {lnk["b_node"] for lnk in links})
        for node in nodes:
            ready = _wait_mgmd(node, wait_secs, ssh_host, ssh_user)
            if ready:
                restarted.append(node)

    return json.dumps({
        "created": created,
        "restarted": restarted,
        "failed": [lnk for lnk in links if lnk not in created],
        "output": output,
    })


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Create SRL inter-node veth pairs")
    parser.add_argument("args_json", nargs="?", default="{}")
    parsed = parser.parse_args()
    result = create_srl_links(json.loads(parsed.args_json))
    print(result)
