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
import subprocess
import sys
from pathlib import Path

from langchain_core.tools import tool
from olav.platform.safety.patterns import DANGEROUS_EXEC_PATTERNS

_DANGEROUS_PATTERNS = DANGEROUS_EXEC_PATTERNS

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
