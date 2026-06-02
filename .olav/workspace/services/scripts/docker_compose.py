#!/usr/bin/env python3
"""docker_compose — Run docker compose commands in a project directory.

Security model: ALLOWLIST-FIRST, not blocklist.
- Only `docker compose` commands are accepted (no arbitrary shell).
- Subcommand must be in ALLOWED_SUBCOMMANDS — unlisted subcommands are hard-blocked.
- Command passed as a list (not a string) — prevents shell injection entirely.
- service_dir is resolved and must stay within project root.

Explicitly blocked subcommands:
  exec — arbitrary command execution inside running containers
  run  — starts a new container with arbitrary command
  cp   — filesystem access across container boundary
"""
from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

# Allowlist — only these docker compose subcommands are permitted.
ALLOWED_SUBCOMMANDS: frozenset[str] = frozenset({
    "ps",
    "logs",
    "up",
    "down",
    "restart",
    "stop",
    "start",
    "pull",
    "build",
    "config",
    "images",
    "version",
    "ls",
})

_BLOCKED_REASON: dict[str, str] = {
    "exec": "exec allows arbitrary command execution inside containers — use exec_on_node for lab nodes",
    "run":  "run starts a container with an arbitrary command — blocked to prevent container escape",
    "cp":   "cp grants filesystem access across the container boundary — blocked",
    "kill": "kill sends arbitrary signals; use 'restart' or 'stop' instead",
}


def _find_project_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


PROJECT_ROOT = _find_project_root()


def _validate_subcommand(raw: str) -> tuple[str | None, str]:
    """Return (subcommand, error_message). error_message is empty on success."""
    parts = shlex.split(raw)
    if not parts:
        return None, "subcommand must not be empty"
    sub = parts[0].lower()
    if sub in _BLOCKED_REASON:
        return None, f"Blocked: docker compose {sub} — {_BLOCKED_REASON[sub]}"
    if sub not in ALLOWED_SUBCOMMANDS:
        allowed = ", ".join(sorted(ALLOWED_SUBCOMMANDS))
        return None, (
            f"docker compose '{sub}' is not in the allowlist. "
            f"Allowed subcommands: {allowed}"
        )
    return sub, ""


def _safe_cwd(service_dir: str) -> tuple[Path | None, str]:
    """Resolve and validate the working directory. Must be within project root."""
    if not service_dir:
        return PROJECT_ROOT, ""
    candidate = Path(service_dir)
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    try:
        resolved = candidate.resolve()
    except Exception as exc:
        return None, f"Cannot resolve service_dir: {exc}"
    # Must stay within project root (no ../../../ escapes)
    try:
        resolved.relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        return None, (
            f"service_dir '{service_dir}' resolves outside project root — forbidden"
        )
    if not resolved.exists():
        return None, f"service_dir '{resolved}' does not exist"
    return resolved, ""


def docker_compose(
    subcommand: str,
    service_dir: str = "",
    timeout: int = 60,
) -> dict:
    """Run a docker compose command in a project service directory.

    Only a curated allowlist of subcommands is accepted (ps, logs, up, down,
    restart, stop, start, pull, build, config, images, version, ls).
    Dangerous subcommands (exec, run, cp) are hard-blocked.

    Args:
        subcommand: docker compose subcommand + flags (e.g. "ps", "logs --tail 50 netbox",
                    "up -d", "down --volumes").
        service_dir: Path to the directory containing docker-compose.yml, relative to
                     the project root (e.g. ".olav/services/netbox"). Leave empty to
                     use the project root.
        timeout: Max seconds to wait for the command (default 60).

    Returns:
        {
          "success": bool,
          "stdout": str,
          "stderr": str,
          "returncode": int,
          "blocked": bool,   # True when the command was rejected by policy
          "reason": str,     # set when blocked=True
        }
    """
    _, err = _validate_subcommand(subcommand)
    if err:
        return {
            "success": False, "stdout": "", "stderr": err,
            "returncode": -1, "blocked": True, "reason": err,
        }

    cwd, err = _safe_cwd(service_dir)
    if err:
        return {
            "success": False, "stdout": "", "stderr": err,
            "returncode": -1, "blocked": True, "reason": err,
        }

    cmd = ["docker", "compose"] + shlex.split(subcommand)

    try:
        result = subprocess.run(
            cmd,           # list form — injection impossible; no shell expansion
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        return {
            "success": result.returncode == 0,
            "stdout": stdout[:8_000] + ("\n…[truncated]" if len(stdout) > 8_000 else ""),
            "stderr": stderr[:2_000] + ("\n…[truncated]" if len(stderr) > 2_000 else ""),
            "returncode": result.returncode,
            "blocked": False,
            "reason": "",
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False, "stdout": "", "blocked": False,
            "stderr": f"docker compose timed out after {timeout}s",
            "returncode": -1, "reason": "",
        }
    except FileNotFoundError:
        return {
            "success": False, "stdout": "", "blocked": False,
            "stderr": "docker not found — is Docker installed and on PATH?",
            "returncode": -1, "reason": "",
        }
    except Exception as exc:
        return {
            "success": False, "stdout": "", "blocked": False,
            "stderr": str(exc), "returncode": -1, "reason": "",
        }


if __name__ == "__main__":
    import json as _json, sys as _sys
    _args = _json.loads(_sys.stdin.read() or "{}")
    result = docker_compose(**_args)
    print(_json.dumps(result, default=str))
