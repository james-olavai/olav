"""Controlled skill-script execution for OLAV agents (per ADR-0008).

Replaces the per-tool ``@tool`` wrapper pattern (and the
``run_python_simulation`` import-helpers pattern) with a single
controlled subprocess-runner that the agent invokes against scripts
declared in a skill's ``SKILL.md``.

Why not deepagents' ``FilesystemMiddleware``:
  OLAV deliberately bypasses ``FilesystemMiddleware`` (agent.py:348)
  to avoid free ``execute(command=...)`` shell access for
  sub-agents. ``execute_skill_script`` keeps that policy intact:
  it accepts ``(skill_name, script_name, args_json)`` and refuses
  to execute anything outside the registered skill directory.

Security guarantees:
  * Script path must resolve to a regular file under
    ``<workspace_root>/<skill_path>/scripts/<script_name>``.
  * No shell metacharacter substitution — uses ``subprocess.run``
    with a list argv.
  * Args are passed as JSON on stdin, not in the command line.
  * Stdout / stderr / return code are captured and returned as a
    structured dict (no raw shell escapes leaking back).
  * Timeout enforced (default 120s; max 600s).

Audit:
  Every invocation produces an ``audit_tool_calls`` row via the
  existing langchain tool wrapper hook. The script's stdout-as-dict
  is the structured return value.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MAX_TIMEOUT_SECONDS = 600
_MAX_OUTPUT_BYTES = 1_000_000  # 1 MB cap per stream


def _resolve_workspace_root() -> Path:
    """Find ``.olav/workspace`` — env override first, then cwd-walk."""
    import os

    env = os.environ.get("OLAV_WORKSPACE_ROOT")
    if env:
        p = Path(env).expanduser().resolve()
        if (p / "core").is_dir() or (p / "ops").is_dir():
            return p

    here = Path.cwd().resolve()
    for parent in [here, *here.parents]:
        candidate = parent / ".olav" / "workspace"
        if candidate.is_dir():
            return candidate
    return here / ".olav" / "workspace"


def _resolve_skill_dir(workspace_root: Path, skill_name: str) -> Path | None:
    """Locate ``<workspace_root>/<skill_name>`` or one level deeper.

    OLAV's layout has both ``<workspace>/ops/`` (parent skill) and
    ``<workspace>/ops/lab/`` (sub-skill). Match either.
    """
    direct = workspace_root / skill_name
    if (direct / "SKILL.md").exists():
        return direct

    for parent in workspace_root.iterdir():
        if not parent.is_dir():
            continue
        nested = parent / skill_name
        if (nested / "SKILL.md").exists():
            return nested

    return None


def execute_skill_script(
    skill_name: str,
    script_name: str,
    args: dict[str, Any] | None = None,
    *,
    timeout: int = 120,
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    """Run a script registered with a skill.

    Args:
        skill_name: The skill's ``name`` from its SKILL.md frontmatter
            (e.g. ``"ops-lab"``). Looked up under the workspace root.
        script_name: Filename of the script to run (must end ``.py``).
            Resolved as ``<skill_dir>/scripts/<script_name>``.
        args: Optional structured args. Serialised to JSON and sent
            on the script's stdin. The script is expected to read
            ``sys.stdin``, parse JSON, and emit its result as a JSON
            object on stdout.
        timeout: Maximum subprocess wall-clock seconds (capped at 600).
        workspace_root: Override workspace root; defaults to
            ``OLAV_WORKSPACE_ROOT`` env or repo-walk to ``.olav/workspace``.

    Returns:
        Dict with:
          * ``status``: ``"ok"`` / ``"error"``
          * ``script_path``: absolute resolved path
          * ``returncode``: subprocess exit code
          * ``stdout``: captured stdout (parsed as JSON if possible,
            else raw string)
          * ``stderr``: captured stderr (string; truncated)
          * ``error``: only on failure (validation, timeout, etc.)
    """
    if timeout > _MAX_TIMEOUT_SECONDS:
        timeout = _MAX_TIMEOUT_SECONDS

    if not script_name.endswith(".py"):
        return {
            "status": "error",
            "error": f"script_name must end with .py; got {script_name!r}",
        }
    if "/" in script_name or ".." in script_name:
        return {
            "status": "error",
            "error": f"script_name must be a bare filename (no path components); got {script_name!r}",
        }

    ws_root = Path(workspace_root) if workspace_root else _resolve_workspace_root()
    skill_dir = _resolve_skill_dir(ws_root, skill_name)
    if skill_dir is None:
        return {
            "status": "error",
            "error": f"skill {skill_name!r} not found under {ws_root}",
        }

    scripts_dir = skill_dir / "scripts"
    script_path = scripts_dir / script_name

    try:
        resolved = script_path.resolve(strict=True)
    except FileNotFoundError:
        return {
            "status": "error",
            "error": f"script not found: {script_path}",
            "skill_dir": str(skill_dir),
        }

    if not resolved.is_file():
        return {
            "status": "error",
            "error": f"script path is not a regular file: {resolved}",
        }

    try:
        scripts_dir_resolved = scripts_dir.resolve(strict=True)
    except FileNotFoundError:
        return {
            "status": "error",
            "error": f"skill scripts directory missing: {scripts_dir}",
        }

    try:
        resolved.relative_to(scripts_dir_resolved)
    except ValueError:
        return {
            "status": "error",
            "error": (
                f"script path escapes skill scripts directory "
                f"({resolved} not under {scripts_dir_resolved})"
            ),
        }

    payload = json.dumps(args or {}).encode("utf-8")

    try:
        completed = subprocess.run(
            [sys.executable, str(resolved)],
            input=payload,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "error",
            "error": f"script timed out after {timeout}s",
            "script_path": str(resolved),
            "stdout": (exc.stdout or b"").decode("utf-8", errors="replace")[:_MAX_OUTPUT_BYTES],
            "stderr": (exc.stderr or b"").decode("utf-8", errors="replace")[:_MAX_OUTPUT_BYTES],
        }
    except Exception as exc:
        return {
            "status": "error",
            "error": f"subprocess launch failed: {type(exc).__name__}: {exc}",
            "script_path": str(resolved),
        }

    stdout_text = completed.stdout.decode("utf-8", errors="replace")[:_MAX_OUTPUT_BYTES]
    stderr_text = completed.stderr.decode("utf-8", errors="replace")[:_MAX_OUTPUT_BYTES]

    parsed_stdout: Any = stdout_text
    stripped = stdout_text.strip()
    if stripped:
        try:
            parsed_stdout = json.loads(stripped)
        except json.JSONDecodeError:
            parsed_stdout = stdout_text

    return {
        "status": "ok" if completed.returncode == 0 else "error",
        "script_path": str(resolved),
        "returncode": completed.returncode,
        "stdout": parsed_stdout,
        "stderr": stderr_text,
    }
