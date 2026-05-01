#!/usr/bin/env python3
"""
stop_service — Stop and optionally remove a docker-compose service.

Mirrors deploy_service: reads docker-compose.yml from .olav/services/<name>/
and runs `docker compose down` (or `stop` to keep containers).
"""

import json
import subprocess
import sys
from pathlib import Path

from langchain_core.tools import tool


def _find_project_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


PROJECT_ROOT = _find_project_root()


def _run(cmd: str, cwd: Path, timeout: int = 60) -> tuple[int, str, str]:
    result = subprocess.run(
        cmd, shell=True, cwd=str(cwd),
        capture_output=True, text=True, timeout=timeout,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


@tool
def stop_service(
    name: str,
    remove: bool = True,
    remove_volumes: bool = False,
) -> dict:
    """Stop a running docker-compose service managed by OLAV.

    Uses `docker compose down` (removes containers) or `docker compose stop`
    (keeps containers for restart). Volumes are preserved by default.

    Args:
        name:            Service name (must match a directory under .olav/services/)
        remove:          If True (default), run `down` to remove containers.
                         If False, run `stop` to pause without removing.
        remove_volumes:  If True, also remove named volumes (destructive — use only
                         when you want to wipe all persistent data). Default False.

    Returns:
        {"success": true, "service": name} on success
        {"success": false, "error": "...", "hint": "..."} on failure
    """
    service_dir = PROJECT_ROOT / ".olav" / "services" / name

    if not service_dir.exists():
        # Check what services exist to give a helpful hint
        services_root = PROJECT_ROOT / ".olav" / "services"
        existing = sorted(p.name for p in services_root.iterdir() if p.is_dir()) if services_root.exists() else []
        return {
            "success": False,
            "error": f"Service directory '{service_dir}' does not exist.",
            "hint": f"Available services: {existing or ['none']}",
        }

    if remove:
        cmd = "docker compose down"
        if remove_volumes:
            cmd += " -v"
        verb = "removed"
    else:
        cmd = "docker compose stop"
        verb = "stopped"

    rc, out, err = _run(cmd, service_dir, timeout=120)
    if rc != 0:
        return {
            "success": False,
            "error": err or out,
            "hint": f"docker compose {'down' if remove else 'stop'} failed. Check that the service is running.",
        }

    return {
        "success": True,
        "service": name,
        "status": verb,
        "output": out or f"Service '{name}' {verb} successfully.",
    }


@tool
def list_services() -> dict:
    """List all OLAV-managed docker-compose services and their running status.

    Returns a summary of each service directory under .olav/services/ with
    container states (running/stopped/missing).

    Returns:
        {"services": [{"name": ..., "status": ..., "containers": [...]}]}
    """
    services_root = PROJECT_ROOT / ".olav" / "services"

    if not services_root.exists():
        return {"services": [], "hint": "No services deployed yet. Use deploy_service to create one."}

    result = []
    for svc_dir in sorted(services_root.iterdir()):
        if not svc_dir.is_dir():
            continue
        has_compose = (svc_dir / "docker-compose.yml").exists() or (svc_dir / "docker-compose.yaml").exists()
        if not has_compose:
            result.append({"name": svc_dir.name, "status": "no compose file", "containers": []})
            continue

        rc, out, _ = _run("docker compose ps --format json", svc_dir, timeout=15)
        containers = []
        if rc == 0 and out:
            try:
                for line in out.splitlines():
                    if line.strip():
                        c = json.loads(line)
                        containers.append({
                            "name": c.get("Name", ""),
                            "state": c.get("State", ""),
                            "health": c.get("Health", ""),
                            "ports": c.get("Publishers", []),
                        })
            except json.JSONDecodeError:
                pass

        status = "stopped"
        if containers:
            states = {c["state"].lower() for c in containers}
            if "running" in states:
                status = "running"
            elif "exited" in states:
                status = "exited"

        result.append({"name": svc_dir.name, "status": status, "containers": containers})

    return {"services": result, "count": len(result)}
