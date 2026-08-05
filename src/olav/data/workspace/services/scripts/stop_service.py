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


def _find_project_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


PROJECT_ROOT = _find_project_root()


def _compose_prefix(cwd: Path) -> str:
    """``docker compose`` plus ``-p <project>`` when this deployment needs one.

    Without it the project name comes from the directory basename, so two
    OLAV_HOMEs on one machine share it and one deployment's service commands
    drive the other's containers (dev_docs/115 §1i). Falls back to the bare
    command whenever the platform helper is unavailable or the directory-derived name is
    already correct here.
    """
    try:
        from olav.platform.services.compose_project import compose_project_name

        project = compose_project_name(cwd)
    except Exception:
        project = None
    return f"docker compose -p {project}" if project else "docker compose"


def _run(cmd: str, cwd: Path, timeout: int = 60) -> tuple[int, str, str]:
    result = subprocess.run(
        cmd, shell=True, cwd=str(cwd),
        capture_output=True, text=True, timeout=timeout,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def stop_service(
    name: str,
    remove: bool = True,
    remove_volumes: bool = False,
    confirmed: bool = False,
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
    # HITL gate: stopping/removing a service may disrupt running workloads
    if not confirmed:
        action_desc = "docker compose down" if remove else "docker compose stop"
        if remove and remove_volumes:
            action_desc += " --volumes (⚠️ deletes persistent data)"
        return {
            "status": "preview",
            "action": f"stop_service(name={name!r}, remove={remove}, remove_volumes={remove_volumes})",
            "command": action_desc,
            "service_dir": str(PROJECT_ROOT / ".olav" / "services" / name),
            "requires_confirmation": True,
            "message": (
                f"About to stop service '{name}': {action_desc}\n"
                + ("⚠️  This will delete all persistent volume data.\n" if remove_volumes else "")
                + "Call again with confirmed=True to execute."
            ),
        }

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

    compose = _compose_prefix(service_dir)
    if remove:
        cmd = f"{compose} down"
        if remove_volumes:
            cmd += " -v"
        verb = "removed"
    else:
        cmd = f"{compose} stop"
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

        rc, out, _ = _run(f"{_compose_prefix(svc_dir)} ps --format json", svc_dir, timeout=15)
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


if __name__ == "__main__":
    import json as _json, sys as _sys
    _args = _json.loads(_sys.stdin.read() or "{}")
    action = _args.pop("action", "stop")
    fn = {"stop": stop_service, "list": list_services}.get(action, stop_service)
    result = fn(**_args)
    print(_json.dumps(result, default=str))
