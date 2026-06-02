#!/usr/bin/env python3
"""
deploy_service — Start a docker-compose service and verify it is healthy.

This tool ONLY handles the lifecycle (up, health-check, logs on failure).
It does NOT write files — use write_workspace_file first.

Workflow:
  1. write_workspace_file(".olav/services/<name>/docker-compose.yml", content)
  2. write_workspace_file(".olav/services/<name>/env/<name>.env", content)
  3. write_workspace_file(".olav/services/<name>/configuration/config.py", content)
     ... (any other files the compose mounts)
  4. deploy_service(name="<name>", health_url="http://localhost:<port>/")
     → starts containers, waits for health, returns logs on failure

On failure: returns {"success": false, "logs": "...", "hint": "..."}
On success: returns {"success": true, "containers": [...]}
"""

import json
import subprocess
import sys
import time
from pathlib import Path


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


def _wait_healthy(service_dir: Path, timeout: int) -> tuple[bool, str]:
    """Wait until all containers are running and none are still starting.

    A container is considered OK if it is running (state) and its health is
    either 'healthy' or '' (no healthcheck defined). Containers in 'unhealthy'
    state are treated as failures only if they have exited; a running container
    that is unhealthy by Docker's healthcheck but still accepting connections is
    not treated as a fatal error — the HTTP health_url probe is the authoritative
    readiness signal.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        rc, out, _ = _run("docker compose ps --format json", service_dir, timeout=15)
        if rc != 0:
            time.sleep(5)
            continue
        try:
            containers = [json.loads(line) for line in out.splitlines() if line.strip()]
        except json.JSONDecodeError:
            time.sleep(5)
            continue
        if not containers:
            time.sleep(5)
            continue
        # All containers must be running (not created/restarting/dead/exited with error)
        states = [c.get("State", "").lower() for c in containers]
        if not all(s in ("running", "exited") for s in states if s):
            time.sleep(5)
            continue
        # Any container that has exited with non-zero is fatal
        for c in containers:
            if c.get("State", "").lower() == "exited":
                exit_code = c.get("ExitCode", 0)
                if exit_code and exit_code != 0:
                    return False, f"container {c.get('Name', '?')} exited with code {exit_code}"
        # Health: only block on "starting" (transient); accept healthy/unhealthy/empty
        healths = [c.get("Health", "").lower() for c in containers]
        if "starting" in healths:
            time.sleep(5)
            continue
        return True, "running"
    return False, f"containers not ready after {timeout}s"


def _check_http(url: str, timeout: int = 10) -> bool:
    try:
        import urllib.request
        req = urllib.request.urlopen(url, timeout=timeout)
        return req.status < 500
    except Exception:
        return False


def deploy_service(
    name: str,
    health_url: str = "",
    health_timeout: int = 300,
) -> dict:
    """Deploy any container-based service (NetBox, Grafana, Prometheus, etc.).

    This is the ENTRY POINT for any "deploy", "install", or "set up" service
    request. Call write_workspace_file first to create all required files, then
    call this tool to start containers and verify health.

    Two-step pattern:
        # Step 1: write docker-compose.yml and ALL supporting files first
        write_workspace_file(".olav/services/<name>/docker-compose.yml", ...)
        write_workspace_file(".olav/services/<name>/env/<name>.env", ...)
        write_workspace_file(".olav/services/<name>/configuration/config.py", ...)
        # (any other files that compose volume-mounts reference)

        # Step 2: start, wait for health, get logs on failure
        deploy_service(name="<name>", health_url="http://localhost:<port>/")

    Returns {"success": true} when healthy, or {"success": false, "logs": "...",
    "hint": "fix guidance"} so you can diagnose, fix a file, and retry.

    Args:
        name:           Service name → files live at .olav/services/<name>/
        health_url:     HTTP URL polled until < 500 (e.g. "http://localhost:8000/")
        health_timeout: Max seconds to wait (default 300). Use 600 for services
                        that run DB migrations on first start (NetBox, GitLab, etc.).

    Returns on success: {"success": true, "containers": [...]}
    Returns on failure: {"success": false, "logs": "...", "hint": "..."}
    """
    service_dir = PROJECT_ROOT / ".olav" / "services" / name

    if not service_dir.exists():
        return {
            "success": False,
            "error": f"Service directory {service_dir} does not exist. "
                     f"Use write_workspace_file to write docker-compose.yml first.",
        }

    compose_file = service_dir / "docker-compose.yml"
    if not compose_file.exists():
        compose_file = service_dir / "docker-compose.yaml"
    if not compose_file.exists():
        return {
            "success": False,
            "error": f"No docker-compose.yml found in {service_dir}. "
                     f"Use write_workspace_file to create it first.",
        }

    # --- Start containers (long timeout: first run may pull images) ---
    rc, out, err = _run("docker compose up -d", service_dir, timeout=300)
    if rc != 0:
        return {
            "success": False,
            "error": err or out,
            "hint": "docker compose up failed. Check compose_yaml syntax and image names.",
        }

    # --- Wait for health ---
    healthy, health_msg = _wait_healthy(service_dir, timeout=health_timeout)

    # --- Wait for HTTP readiness ---
    http_ok = True
    if health_url and healthy:
        deadline = time.time() + health_timeout
        http_ok = False
        while time.time() < deadline:
            if _check_http(health_url):
                http_ok = True
                break
            time.sleep(5)

    # --- Always collect logs ---
    _, logs_out, _ = _run("docker compose logs --tail 80 --no-color", service_dir, timeout=15)
    _, ps_out, _ = _run("docker compose ps --format json", service_dir, timeout=15)
    containers = []
    try:
        containers = [json.loads(line) for line in ps_out.splitlines() if line.strip()]
    except json.JSONDecodeError:
        pass

    if not healthy or (health_url and not http_ok):
        # Build context-aware hints based on log content
        hint_lines = [
            "Read 'logs' to find the root cause. Common fixes:",
            "- Missing config file: use write_workspace_file to create the file at the exact path the volume mount expects, then call deploy_service again",
            "- Missing env var: use write_workspace_file to update the env file, then redeploy",
            "- Port conflict: update docker-compose.yml port mapping, then redeploy",
        ]
        if logs_out and ("AttributeError" in logs_out or "TypeError" in logs_out or "KeyError" in logs_out):
            hint_lines.append(
                "- Python error in config file detected. Use web_search to find the EXACT config file format "
                "for this service (e.g. search 'netbox docker configuration.py REDIS format site:github.com'). "
                "Many services require dict-of-dicts config, not URL strings. "
                "Also try enabling debug mode: add DEBUG=1 or VERBOSE=1 or <SERVICE>_DEBUG=1 to the env file "
                "to get a full Python traceback showing which config key is wrong."
            )
        if logs_out and ("No such file" in logs_out or "FileNotFoundError" in logs_out):
            hint_lines.append(
                "- File not found in container. Check that write_workspace_file paths exactly match "
                "the volume mount paths in docker-compose.yml."
            )
        return {
            "success": False,
            "status": health_msg,
            "containers": [{"name": c.get("Name", ""), "state": c.get("State", ""), "health": c.get("Health", "")} for c in containers],
            "logs": logs_out[-5000:] if logs_out else "",
            "hint": "\n".join(hint_lines),
        }

    return {
        "success": True,
        "status": "healthy",
        "service_dir": str(service_dir.relative_to(PROJECT_ROOT)),
        "containers": [{"name": c.get("Name", ""), "state": c.get("State", ""), "health": c.get("Health", "")} for c in containers],
    }


if __name__ == "__main__":
    import json as _json, sys as _sys
    _args = _json.loads(_sys.stdin.read() or "{}")
    result = deploy_service(**_args)
    print(_json.dumps(result, default=str))
