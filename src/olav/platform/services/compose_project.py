"""Docker-compose project naming for co-located OLAV deployments.

`deploy_service` writes its compose file to ``<OLAV_HOME>/.olav/services/<name>/``
and runs ``docker compose`` with that as the cwd. Compose then derives the
project name from the **directory basename**, so every deployment on a machine
produces the same project for the same service: two OLAV_HOMEs both get project
``batfish`` and container ``batfish-batfish-1``.

Observed on the test VM (dev_docs/115 §1i): running ``docker compose up -d`` from
``~/olav-test`` restarted the container belonging to ``~/olav`` — ``docker
inspect`` still reported
``com.docker.compose.project.working_dir=/home/olav/olav/.olav/services/batfish``.
One deployment's service lifecycle silently drives another's containers, which on
a demo machine means a test run can disturb the recording environment.

Naming it per deployment fixes that, but must not orphan what is already
running: a container created under the directory-derived project is invisible to
a differently-named project, so ``down`` would miss it and ``up`` would try to
bind host ports it still holds. So the rule is **adaptive**:

* if containers already exist under the directory-derived name **and
  they belong to this deployment** — matched on the compose ``working_dir``
  label — keep the directory-derived name, and nothing about an existing install changes;
* otherwise use ``<derived>-<8 hex of the service dir path>``, which is stable
  per (deployment, service) and distinct across deployments.

Two deployments that both already have containers under the derived name still collide on host
ports, but that surfaces as docker's own port-in-use error rather than as one
deployment silently operating on the other's containers. A loud failure on the
wrong-target case is the point.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

_INVALID = re.compile(r"[^a-z0-9_-]+")
_LEADING = re.compile(r"^[^a-z0-9]+")

# (resolved service dir) -> project name or None. Resolution shells out to
# docker, so it is done once per process.
_CACHE: dict[str, str | None] = {}

_WORKING_DIR_LABEL = "com.docker.compose.project.working_dir"


def default_project_name(service_dir: Path) -> str:
    """The project name docker itself would derive from *service_dir*."""
    name = _LEADING.sub("", _INVALID.sub("", service_dir.name.lower()))
    return name or "default"


def _namespaced(service_dir: Path) -> str:
    digest = hashlib.sha256(str(service_dir).encode("utf-8")).hexdigest()[:8]
    return f"{default_project_name(service_dir)}-{digest}"


def _default_project_is_ours(service_dir: Path, derived: str) -> bool | None:
    """Do the derived project's containers belong to *service_dir*?

    Returns None when docker cannot be consulted — the caller then keeps
    today's behaviour rather than guessing.
    """
    try:
        proc = subprocess.run(
            [
                "docker", "ps", "-a",
                "--filter", f"label=com.docker.compose.project={derived}",
                "--format", "{{.Label \"" + _WORKING_DIR_LABEL + "\"}}",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    dirs = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if not dirs:
        return False  # nothing under the derived name — safe to namespace
    want = str(service_dir)
    return any(d == want for d in dirs)


def compose_project_name(service_dir: Path | str) -> str | None:
    """Project name to pass as ``docker compose -p``, or None to leave it alone.

    None means "docker's default is already correct here" — either this
    deployment owns the derived project, or docker could not be consulted and we
    must not change behaviour on a guess.
    """
    path = Path(service_dir).resolve()
    key = str(path)
    if key in _CACHE:
        return _CACHE[key]

    derived = default_project_name(path)
    owns = _default_project_is_ours(path, derived)
    result = None if owns is None or owns else _namespaced(path)
    _CACHE[key] = result
    return result


def compose_argv(service_dir: Path | str) -> list[str]:
    """``["docker", "compose"]`` plus ``-p <project>`` when namespacing applies."""
    project = compose_project_name(service_dir)
    argv = ["docker", "compose"]
    if project:
        argv += ["-p", project]
    return argv


__all__ = [
    "compose_argv",
    "compose_project_name",
    "default_project_name",
]
