"""execute_skill_script — run a Python script registered with a skill.

Per ADR-0008. Thin LangChain @tool wrapper around
``olav.core.skill_runner.execute_skill_script``. Lives under
``core/tools/`` so every sub-agent inherits it (agent.py prepends
core tools to each sub-agent's surface).

Security:
  * Only resolves scripts under ``<workspace>/<skill>/scripts/``.
  * Refuses path traversal, symlink escape, non-``.py`` extensions.
  * Captures stdout/stderr/return-code; parses stdout as JSON when
    possible.
  * Enforces 600s timeout cap.

This is OLAV's controlled alternative to deepagents'
``FilesystemMiddleware.execute(command=...)`` (which OLAV
deliberately bypasses for sub-agents per agent.py:348). Same
prompt-cost benefit, narrower attack surface.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


def _find_project_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


sys.path.insert(0, str(_find_project_root() / "src"))

from langchain_core.tools import tool

from olav.core.skill_runner import execute_skill_script as _impl


@tool
def execute_skill_script(
    skill_name: str,
    script_name: str,
    args: dict[str, Any] | None = None,
    timeout: int = 120,
) -> dict[str, Any]:
    """Run a Python script registered with a skill.

    Use this to invoke deterministic Python helpers shipped under
    ``<workspace>/<skill>/scripts/<script_name>``. Args go to the
    script via stdin as JSON; the script prints its result as JSON
    on stdout. Output is captured and returned as a structured dict.

    Args:
        skill_name: The skill's directory name (e.g. ``"lab"``,
            ``"auditor"``). Looked up under the workspace root —
            matches direct child or one level deeper (e.g.
            ``ops/lab``).
        script_name: Filename of the script to run, including
            ``.py`` extension. Must be a bare filename (no path
            components).
        args: Optional structured args. Serialised to JSON and sent
            on stdin. Use ``None`` or ``{}`` for argument-less
            scripts.
        timeout: Subprocess wall-clock seconds (capped at 600).

    Returns:
        Dict with ``status`` (``"ok"``/``"error"``), ``returncode``,
        ``stdout`` (parsed JSON or raw string), ``stderr``,
        ``script_path``. On validation failures: ``error`` with
        a clear reason and no subprocess launched.

    Example:
        >>> execute_skill_script(
        ...     skill_name="lab",
        ...     script_name="generate_clab_topology.py",
        ...     args={"nodes": ["R1", "R4"], "lab_name": "cab_demo"},
        ... )
    """
    return _impl(
        skill_name=skill_name,
        script_name=script_name,
        args=args,
        timeout=timeout,
    )
