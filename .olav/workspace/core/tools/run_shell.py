#!/usr/bin/env python3
"""
run_shell — Execute shell commands on the local host.

Intended for: docker/docker-compose lifecycle, system checks, file operations.
Safety gates apply for destructive commands via the approval system.

Workflow:
  1. run_shell("docker compose ps")         → check service status
  2. run_shell("docker compose up -d")      → start services
  3. run_shell("docker compose logs --tail 50 netbox") → inspect logs
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from langchain_core.tools import tool
from olav.platform.safety.patterns import DANGEROUS_EXEC_PATTERNS

_DANGEROUS_PATTERNS = DANGEROUS_EXEC_PATTERNS
_CLAB_HOST = os.environ.get("OLAV_CLAB_HOST", "192.168.100.12")

_ALLOWED_COMMANDS = [
    "docker", "docker-compose", "docker compose",
    "git", "cat", "ls", "pwd", "echo", "curl", "wget",
    "python", "python3", "uv", "pip",
    "systemctl status", "journalctl",
    "netstat", "ss", "ps", "free", "df",
]


def _find_project_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


PROJECT_ROOT = _find_project_root()


def _is_safe(command: str) -> tuple[bool, str]:
    cmd_lower = command.lower().strip()
    for pat in _DANGEROUS_PATTERNS:
        if pat in cmd_lower:
            return False, f"Command contains dangerous pattern: '{pat}'"
    return True, ""


def _check_clab_redirect(command: str) -> str | None:
    """Return a redirect message if the command targets a CLAB container on remote host."""
    import re
    cmd = command.strip()
    # Detect: docker exec ... clab-<lab>-<node>
    m = re.search(r'docker\s+exec.*?clab-([a-z0-9_-]+)-([a-z0-9_-]+)', cmd, re.IGNORECASE)
    if m:
        lab_name = m.group(1)
        node = m.group(2)
        return (
            f"ERROR: CLAB containers run on REMOTE host {_CLAB_HOST} — docker exec will never work here.\n"
            f"Use push_node_config instead:\n"
            f'  push_node_config({{"lab_name": "{lab_name}", "node": "{node}", "config": "<your SRL set commands>"}})\n'
            f"Or use exec_on_node for show commands:\n"
            f'  exec_on_node({{"lab_name": "{lab_name}", "node": "{node}", "command": "sr_cli -c \'show version\'"}})'
        )
    # Detect: SSH to CLAB host
    if re.search(r'ssh\s+.*?192\.168\.100\.12', cmd, re.IGNORECASE):
        return (
            f"ERROR: Do not SSH to {_CLAB_HOST} to run commands.\n"
            "Use exec_on_node to run commands on lab nodes:\n"
            "  exec_on_node({\"lab_name\": \"<lab>\", \"node\": \"<node>\", \"command\": \"sr_cli -c 'show version'\"})\n"
            "Use push_node_config to push SRL config:\n"
            "  push_node_config({\"lab_name\": \"<lab>\", \"node\": \"<node>\", \"config\": \"set / ...\"})"
        )
    # Detect: containerlab or clab CLI (these run remotely too)
    if re.match(r'\s*(containerlab|clab)\s+(deploy|destroy|inspect|list)', cmd, re.IGNORECASE):
        return (
            f"ERROR: containerlab CLI is on REMOTE host {_CLAB_HOST} — it cannot be run locally.\n"
            "Use deploy_lab tool to deploy/destroy labs instead."
        )
    return None


@tool
def run_shell(
    command: str,
    cwd: str = "",
    timeout: int = 60,
) -> dict:
    """Execute a shell command on the local host.

    Use for docker/docker-compose lifecycle, health checks, and system queries.
    Destructive patterns (rm -rf, mkfs, etc.) are blocked.

    Args:
        command: Shell command to run (e.g. "docker compose up -d")
        cwd:     Working directory (relative to project root, or absolute).
                 Leave empty to use project root.
        timeout: Max seconds to wait (default 60).

    Returns:
        {
          "returncode": 0,
          "stdout": "...",
          "stderr": "...",
          "success": true
        }
    """
    safe, reason = _is_safe(command)
    if not safe:
        return {"returncode": -1, "stdout": "", "stderr": reason, "success": False,
                "blocked": True, "reason": reason}

    clab_redirect = _check_clab_redirect(command)
    if clab_redirect:
        return {"returncode": -1, "stdout": "", "stderr": clab_redirect, "success": False,
                "blocked": True, "reason": clab_redirect}

    work_dir = Path(cwd) if cwd else PROJECT_ROOT
    if not work_dir.is_absolute():
        work_dir = PROJECT_ROOT / work_dir
    # Create working directory if it doesn't exist (e.g. for first docker compose run)
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        truncated = len(stdout) > 10_000 or len(stderr) > 2_000
        return {
            "returncode": result.returncode,
            "stdout": stdout[:10_000] + ("\n…[output truncated]" if len(stdout) > 10_000 else ""),
            "stderr": stderr[:2_000] + ("\n…[stderr truncated]" if len(stderr) > 2_000 else ""),
            "success": result.returncode == 0,
            "truncated": truncated,
        }
    except subprocess.TimeoutExpired:
        return {"returncode": -1, "stdout": "", "stderr": f"Command timed out after {timeout}s",
                "success": False}
    except Exception as exc:
        return {"returncode": -1, "stdout": "", "stderr": str(exc), "success": False}


if __name__ == "__main__":
    try:
        params = json.loads(sys.stdin.read()) if sys.stdin.read().strip() else {}
        print(json.dumps(run_shell.func(**params), ensure_ascii=False, indent=2))
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)}), file=sys.stderr)
        sys.exit(1)
