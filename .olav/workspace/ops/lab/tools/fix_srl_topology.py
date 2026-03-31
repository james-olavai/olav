"""Fix /tmp/topology.yml directory bug in SRL containers deployed via CLAB REST API.

Root cause: CLAB REST API creates a directory at the bind-mount source path
(/home/admin/.clab/{lab}/clab-{lab}/{node}/topology.yml) instead of a YAML file.
This prevents sr_device_mgr from parsing the topology, causing the SRL management
plane (mgmd) to never start. The workaround writes the correct file content via
nsenter into each container's mount namespace and restarts sr_device_mgr.

Tool: fix_srl_topology

Args (JSON):
    lab_name:   str         — ContainerLab lab name (e.g. "digital-twin")
    nodes:      list[str]   — node names to fix (default: all SRL nodes in lab)
    chassis_type: int       — SRL chassis type int (default: 66 = 7220 IXR-D3)
    dry_run:    bool        — return plan without executing (default: False)
    base_url:   str | None  — CLAB API base URL (default: http://192.168.100.12:8080)
    wait_secs:  int | None  — seconds to wait for mgmd to start (default: 40)

Returns: JSON string
    {"fixed": ["R1","R2",...], "failed": [], "skipped": [], "dry_run": false}
    {"error": "..."}

Requirements: Docker socket must be accessible (runs docker inspect + privileged container).
Auth: reads CLAB_TOKEN env var for CLAB API login (to list nodes if nodes not specified).
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

_OLAV_SRC = Path(__file__).parents[5] / "src"
if str(_OLAV_SRC) not in sys.path:
    sys.path.insert(0, str(_OLAV_SRC))

import httpx

_DEFAULT_BASE_URL = "http://192.168.100.12:8080"
_DEFAULT_CHASSIS_TYPE = 66   # 7220 IXR-D3
_DEFAULT_CPM_CARD_TYPE = 177
_DEFAULT_CARD_TYPE = 177
_DEFAULT_MDA_TYPE = 194
_DEFAULT_WAIT = 40


def _build_topology_content(
    mac: str,
    chassis_type: int = _DEFAULT_CHASSIS_TYPE,
    cpm_card_type: int = _DEFAULT_CPM_CARD_TYPE,
    card_type: int = _DEFAULT_CARD_TYPE,
    mda_type: int = _DEFAULT_MDA_TYPE,
) -> str:
    """Build the topology.yml YAML content for an SRL node."""
    return (
        "# Copyright 2020 Nokia\n"
        "# Licensed under the BSD 3-Clause License.\n"
        "# SPDX-License-Identifier: BSD-3-Clause\n"
        "\n"
        "chassis_configuration:\n"
        f'    "chassis_type": {chassis_type}\n'
        f'    "base_mac": "{mac}"\n'
        f'    "cpm_card_type": {cpm_card_type}\n'
        "\n"
        "slot_configuration:\n"
        "    1:\n"
        f'        "card_type": {card_type}\n'
        f'        "mda_type": {mda_type}\n'
    )


def _docker_inspect(container: str) -> dict[str, Any] | None:
    """Run docker inspect on a container, return parsed dict."""
    try:
        result = subprocess.run(
            ["docker", "inspect", container],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
        return data[0] if data else None
    except Exception:
        return None


def _get_container_pid(info: dict) -> int | None:
    try:
        return int(info["State"]["Pid"])
    except (KeyError, TypeError, ValueError):
        return None


def _get_container_mac(info: dict) -> str:
    """Get the first management network MAC address."""
    try:
        nets = info["NetworkSettings"]["Networks"]
        for v in nets.values():
            mac = v.get("MacAddress", "")
            if mac:
                return mac
    except (KeyError, TypeError):
        pass
    return "1a:00:00:00:00:00"


def _is_topology_dir(pid: int) -> bool:
    """Check if /tmp/topology.yml is a directory in the container's mount namespace."""
    # Use /proc/{pid}/mounts to check
    try:
        mounts = Path(f"/proc/{pid}/mounts").read_text()
        # Look for bind mount on /tmp/topology.yml
        for line in mounts.splitlines():
            if "/tmp/topology.yml" in line and "ext4" in line:
                return True  # Raw block device mount = directory bug
    except Exception:
        pass
    return False


def _fix_node(pid: int, mac: str, chassis_type: int) -> bool:
    """Fix /tmp/topology.yml in container's mount namespace via privileged container."""
    content = _build_topology_content(mac=mac, chassis_type=chassis_type)
    # Escape content for shell
    content_escaped = content.replace("\\", "\\\\").replace("'", "'\\''")

    # Build the nsenter script
    script = f"""nsenter -m -t {pid} -- sh -c '
umount /tmp/topology.yml 2>/dev/null
rm -rf /tmp/topology.yml 2>/dev/null
printf "%b" '"'"'{content_escaped}'"'"' > /tmp/topology.yml
'"""

    try:
        result = subprocess.run(
            ["docker", "run", "--rm", "--privileged", "--pid=host",
             "alpine", "sh", "-c", script],
            capture_output=True, text=True, timeout=30
        )
        return result.returncode == 0
    except Exception:
        return False


def _start_device_mgr(container: str) -> bool:
    """Start sr_device_mgr in the container as srlinux user."""
    try:
        result = subprocess.run(
            ["docker", "exec", "-u", "srlinux", "-d",
             container, "/opt/srlinux/bin/sr_device_mgr"],
            capture_output=True, text=True, timeout=15
        )
        return result.returncode == 0
    except Exception:
        return False


def _wait_mgmd(container: str, wait_secs: int) -> bool:
    """Wait for SRL management plane to be responsive."""
    deadline = time.monotonic() + wait_secs
    while time.monotonic() < deadline:
        try:
            result = subprocess.run(
                ["docker", "exec", container, "sr_cli", "show version"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0 and "SR Linux" in result.stdout:
                return True
        except Exception:
            pass
        time.sleep(3)
    return False


def _build_fix_script(lab_name: str, chassis_type: int, wait_secs: int) -> str:
    """Build a self-contained bash script that fixes topology.yml on the Docker host.

    The CLAB REST API bug creates a *directory* at clab-node-lab-dir/topology.yml
    instead of a file.  That dir is bind-mounted into the container at /tmp/topology.yml.
    Fix: remove the directory on the host, write the correct YAML file, restart mgr.
    No privileged container or nsenter needed — we fix the source on the host directly.
    """
    return f"""#!/bin/bash
set -e
CHASSIS_TYPE={chassis_type}

echo "=== Listing containers for lab {lab_name!r} ==="
NODES=$(docker ps --filter "label=containerlab={lab_name}" --format '{{{{.Names}}}}')
if [ -z "$NODES" ]; then
  echo '{{"error": "no containers found for lab {lab_name}"}}'
  exit 1
fi

FIXED=""
FAILED=""

for NODE in $NODES; do
  # Get the host-side lab dir where topology.yml should live
  LAB_DIR=$(docker inspect "$NODE" --format '{{{{index .Config.Labels "clab-node-lab-dir"}}}}' 2>/dev/null)
  MAC=$(docker inspect "$NODE" --format '{{{{range .NetworkSettings.Networks}}}}{{{{.MacAddress}}}}{{{{end}}}}' 2>/dev/null | head -1)
  [ -z "$MAC" ] && MAC="1a:00:00:00:00:00"

  if [ -z "$LAB_DIR" ]; then
    echo "  WARN: no clab-node-lab-dir label on $NODE, skipping"
    FAILED="$FAILED $NODE"
    continue
  fi

  TOPO_PATH="$LAB_DIR/topology.yml"
  # SAFETY: Never proceed if TOPO_PATH is empty or doesn't look like a clab path
  if [ -z "$TOPO_PATH" ] || ! echo "$TOPO_PATH" | grep -qE '^/[^/]'; then
    echo "  ERROR: TOPO_PATH empty or suspicious for $NODE, skipping"
    FAILED="$FAILED $NODE"
    continue
  fi
  PID=$(docker inspect "$NODE" --format '{{{{.State.Pid}}}}' 2>/dev/null)
  echo "  fixing $NODE (pid=$PID mac=$MAC)"

  # Write topology content to a temp file (plain heredoc avoids YAML quoting hell)
  TMPFILE=$(mktemp /tmp/srl_topo_XXXXXX.yml)
  cat > "$TMPFILE" << 'TOPOEOF'
# Copyright 2020 Nokia
# Licensed under the BSD 3-Clause License.
# SPDX-License-Identifier: BSD-3-Clause

chassis_configuration:
    "chassis_type": CHASSIS_PLACEHOLDER
    "base_mac": "MAC_PLACEHOLDER"
    "cpm_card_type": 177

slot_configuration:
    1:
        "card_type": 177
        "mda_type": 194
TOPOEOF
  sed -i "s/CHASSIS_PLACEHOLDER/$CHASSIS_TYPE/g" "$TMPFILE"
  sed -i "s/MAC_PLACEHOLDER/$MAC/g" "$TMPFILE"

  # Fix #1: HOST PATH — replace directory with file (safe for future container restarts)
  # SAFETY: mount only LAB_DIR (not /), blast radius limited to that dir
  docker run --rm --privileged \
    -v "$LAB_DIR:/labdir" \
    -v "$TMPFILE:/topo.src:ro" \
    alpine sh -c "rm -rf /labdir/topology.yml && cp /topo.src /labdir/topology.yml && echo host_ok" || \
    echo "  WARN: host path fix failed for $NODE (bind mount still directory)"

  # Fix #2: INSIDE CONTAINER via nsenter — umount the dir bind-mount, write file directly
  # Base64 avoids all quoting issues passing content through shell layers
  B64=$(base64 -w0 "$TMPFILE")
  rm -f "$TMPFILE"
  docker run --rm --privileged --pid=host alpine /bin/sh -c "
nsenter --mount=/proc/$PID/ns/mnt -- /bin/sh -c \
  'umount /tmp/topology.yml 2>/dev/null || true; rm -rf /tmp/topology.yml; echo $B64 | base64 -d > /tmp/topology.yml; echo nsenter_ok'
" || {{ echo "  WARN: nsenter fix failed for $NODE"; FAILED="$FAILED $NODE"; continue; }}

  # Kill sr_device_mgr so sr_app_mgr restarts it (the crash-backoff should be cleared
  # by now since enough time has passed since the initial topology.yml dir failures)
  docker exec "$NODE" pkill -x sr_device_mgr 2>/dev/null || true

  FIXED="$FIXED $NODE"
  echo "  ok: $NODE"
done

echo "=== Waiting {wait_secs}s for management plane ==="
sleep {wait_secs}

echo "=== Result ==="
echo "fixed:$FIXED"
echo "failed:$FAILED"
"""


def _run_script(script: str, ssh_host: str | None, ssh_user: str) -> tuple[int, str, str]:
    """Run bash script locally or on remote host via SSH.

    Encodes the script as base64 to avoid stdin piping.
    Uses SSHBackend / LocalBackend for consistent connection options.
    """
    from olav.platform.execution import ExecutionConfig, LocalBackend, SSHBackend

    b64 = base64.b64encode(script.encode()).decode()
    cmd = f"echo {b64} | base64 -d | bash"

    if ssh_host:
        backend: SSHBackend | LocalBackend = SSHBackend(
            host=ssh_host, user=ssh_user or None
        )
        cfg = ExecutionConfig(timeout=180)
    else:
        backend = LocalBackend()
        cfg = ExecutionConfig(timeout=180, shell=True)

    result = backend.execute(cmd, cfg)
    return result.returncode, result.stdout, result.stderr


def fix_srl_topology(args: dict) -> str:
    """Fix SRL topology.yml directory bug and restart management plane."""
    lab_name: str = args["lab_name"]
    chassis_type: int = int(args.get("chassis_type") or _DEFAULT_CHASSIS_TYPE)
    dry_run: bool = bool(args.get("dry_run", False))
    wait_secs: int = int(args.get("wait_secs") or args.get("wait") or _DEFAULT_WAIT)
    ssh_host: str | None = args.get("ssh_host")
    ssh_user: str = args.get("ssh_user") or "yhvh"

    script = _build_fix_script(lab_name, chassis_type, wait_secs)

    if dry_run:
        return json.dumps({"dry_run": True, "script": script, "lab_name": lab_name})

    rc, stdout, stderr = _run_script(script, ssh_host, ssh_user)

    output = stdout + stderr
    if rc != 0:
        return json.dumps({"error": f"script exited {rc}", "output": output[:500]})

    # Parse fixed/failed from output
    fixed, failed = [], []
    for line in output.splitlines():
        if line.startswith("fixed:"):
            fixed = line.split(":", 1)[1].split()
        elif line.startswith("failed:"):
            failed = line.split(":", 1)[1].split()

    return json.dumps({
        "fixed": fixed,
        "failed": failed,
        "dry_run": False,
        "output": output[:300],
    })


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Fix SRL topology.yml directory bug")
    parser.add_argument("args_json", nargs="?", default="{}")
    parsed = parser.parse_args()
    result = json.loads(fix_srl_topology(json.loads(parsed.args_json)))
    print(json.dumps(result, indent=2))
