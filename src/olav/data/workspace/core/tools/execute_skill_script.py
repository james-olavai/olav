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
from pydantic import BaseModel, Field, model_validator

from olav.core.skill_runner import execute_skill_script as _impl


class _ExecuteSkillScriptArgs(BaseModel):
    """Call-shape coercion, not a prompt rule (CLAUDE.md tool-arch: fix
    construction errors at the Pydantic layer). 2026-07-25 live e2e finding:
    a small model repeatedly nested skill_name/script_name INSIDE script_args
    instead of at the top level — structurally rejected before this fix,
    tripping the loop-breaker after 6 identical failures. Pull them out of
    script_args when missing at the top, before required-field validation."""

    skill_name: str = Field(description="Your own skill's directory name.")
    script_name: str = Field(description="Filename of the script to run.")
    script_args: dict[str, Any] | None = Field(default=None)
    timeout: int = Field(default=120)

    @model_validator(mode="before")
    @classmethod
    def _pull_nested_names(cls, data):
        if isinstance(data, dict) and isinstance(data.get("script_args"), dict):
            inner = data["script_args"]
            for key in ("skill_name", "script_name"):
                if not data.get(key) and key in inner:
                    data[key] = inner.pop(key)
        return data


@tool(args_schema=_ExecuteSkillScriptArgs)
def execute_skill_script(
    skill_name: str,
    script_name: str,
    script_args: dict[str, Any] | None = None,
    timeout: int = 120,
) -> dict[str, Any]:
    """Run a Python script registered with a skill.

    Use this to invoke deterministic Python helpers shipped under
    ``<workspace>/<skill>/scripts/<script_name>``. Args go to the
    script via stdin as JSON; the script prints its result as JSON
    on stdout. Output is captured and returned as a structured dict.

    Args:
        skill_name: **YOUR OWN skill's directory name** — the agent
            whose scripts you are running is almost always yourself
            (e.g. an ``api-query`` agent passes ``"api-query"``). Do
            NOT copy the example value below. Looked up under the
            workspace root — matches a direct child or one level
            deeper (e.g. ``netops/lab``).
        script_name: Filename of the script to run, including
            ``.py`` extension. Must be a bare filename (no path
            components).
        script_args: Optional structured args (dict). Serialised to JSON
            and sent on stdin. Use ``None`` or ``{}`` for argument-less
            scripts. (Named ``script_args`` rather than ``args`` to
            avoid collision with LangChain's tool-schema ``args``
            reserved key.)
        timeout: Subprocess wall-clock seconds (capped at 600).

    Returns:
        Dict with ``status`` (``"ok"``/``"error"``), ``returncode``,
        ``stdout`` (parsed JSON or raw string), ``stderr``,
        ``script_path``. On validation failures: ``error`` with
        a clear reason and no subprocess launched.

    Example (replace ``<your-skill>`` with your own skill name):
        >>> execute_skill_script(
        ...     skill_name="<your-skill>",
        ...     script_name="some_script.py",
        ...     script_args={"key": "value"},
        ... )
    """
    return _impl(
        skill_name=skill_name,
        script_name=script_name,
        args=script_args,
        timeout=timeout,
    )
