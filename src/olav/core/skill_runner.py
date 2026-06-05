"""Controlled skill-script execution for OLAV agents (per ADR-0008).

Replaces the per-tool ``@tool`` wrapper pattern with a single
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
    with a list argv in both modes.
  * Args passed as JSON stdin (OLAV native) or ``--key value`` CLI
    pairs (``argv: true`` in SKILL.md, for argparse-based scripts).
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

try:
    from olav.core.config import get_execution_config as _get_exec_cfg
    _exec_cfg = _get_exec_cfg()
    _MAX_TIMEOUT_SECONDS = _exec_cfg.max_skill_timeout_seconds
    _MAX_OUTPUT_BYTES = _exec_cfg.max_skill_output_bytes
except Exception:
    _MAX_TIMEOUT_SECONDS = 600
    _MAX_OUTPUT_BYTES = 524_288  # 512 KB cap per stream (ARCH-20: fits within large-tier context share)


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
    """Locate a skill directory by name.

    Accepts several name shapes so small LLMs that misremember the
    canonical form still hit the right target:

      * ``<workspace>/<skill_name>`` — direct dir match
      * ``<workspace>/<parent>/<skill_name>`` — one level deep
        (parent / sub-skill layout, e.g. ``ops/lab``)
      * ``<workspace>/<parent>/<skill_name>`` where the SKILL.md
        ``name:`` frontmatter field matches ``skill_name`` (handles
        ``audit-author`` → ``author/`` after rev 259 Run/Author split)
      * ``<skill_name>`` as the last hyphen-separated token of a
        SKILL.md name (e.g. ``audit-runner`` → ``runner/``)

    Returns the first match or ``None``.
    """
    # 1. Direct directory match (legacy behaviour).
    direct = workspace_root / skill_name
    if (direct / "SKILL.md").exists():
        return direct

    # Build an alias map by scanning all SKILL.md files once.
    # Key = candidate skill_name. Value = resolved directory.
    aliases: dict[str, Path] = {}
    for parent in workspace_root.iterdir():
        if not parent.is_dir() or parent.name.startswith("_"):
            # Skip `_legacy_*` / `_experiment_*` backup trees so retired
            # sub-agents aren't accidentally resolvable.
            continue
        # 2a. Direct nested layout (legacy).
        if (parent / skill_name / "SKILL.md").exists():
            return parent / skill_name
        # 2b. Scan SKILL.md frontmatter for `name:` aliases.
        for skill_md in parent.rglob("SKILL.md"):
            if any(seg.startswith("_") for seg in skill_md.relative_to(parent).parts):
                continue
            try:
                text = skill_md.read_text(encoding="utf-8")
            except Exception:
                continue
            if not text.startswith("---"):
                continue
            # Cheap name extraction; full YAML parse not worth the
            # dependency in this hot path.
            for line in text.split("\n", 30):
                s = line.strip()
                if s.startswith("name:"):
                    name_val = s.split(":", 1)[1].strip().strip('"\'')
                    if name_val:
                        aliases.setdefault(name_val, skill_md.parent)
                        # Also register the last hyphen-token (e.g.
                        # ``audit-author`` → ``author``) so a small
                        # LLM passing the bare role name still hits.
                        if "-" in name_val:
                            tail = name_val.rsplit("-", 1)[-1]
                            aliases.setdefault(tail, skill_md.parent)
                    break

    return aliases.get(skill_name)


def _read_script_metadata(skill_dir: Path, script_name: str) -> dict:
    """Return the SKILL.md ``scripts:`` entry for *script_name*, or ``{}``."""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return {}
    try:
        import yaml  # soft dep — already required by the workspace loader

        text = skill_md.read_text(encoding="utf-8")
        if not text.startswith("---"):
            return {}
        front = text.split("---", 2)[1]
        meta = yaml.safe_load(front) or {}
        for entry in meta.get("scripts", []):
            if isinstance(entry, dict) and entry.get("file") == script_name:
                return entry
    except Exception as exc:
        logger.debug("Could not read script metadata from %s: %s", skill_md, exc)
    return {}


def _build_argv_args(args: dict) -> list[str]:
    """Convert *args* dict to ``--key value`` CLI pairs.

    Complex values (list, dict) are JSON-serialised so the receiving
    script can ``json.loads(value)`` if needed.  Bool values become
    the strings ``"true"`` / ``"false"``.
    """
    result: list[str] = []
    for k, v in args.items():
        result.append(f"--{k}")
        if isinstance(v, (dict, list)):
            result.append(json.dumps(v))
        elif isinstance(v, bool):
            result.append("true" if v else "false")
        else:
            result.append(str(v))
    return result


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
        args: Optional structured args. By default serialised to JSON
            and sent on the script's stdin (OLAV native convention).
            If the SKILL.md entry carries ``argv: true``, args are
            instead passed as ``--key value`` CLI pairs so the script
            can use ``argparse`` (third-party / deepagents-native style).
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

    # Determine arg-passing convention from the SKILL.md scripts entry.
    # argv: true  → --key value CLI pairs (argparse / deepagents-native).
    # default     → JSON on stdin (OLAV convention, structured + safe).
    script_meta = _read_script_metadata(skill_dir, script_name)
    argv_mode: bool = bool(script_meta.get("argv", False))

    if argv_mode:
        cmd = [sys.executable, str(resolved)] + _build_argv_args(args or {})
        stdin_payload: bytes | None = None
    else:
        cmd = [sys.executable, str(resolved)]
        stdin_payload = json.dumps(args or {}).encode("utf-8")

    try:
        completed = subprocess.run(
            cmd,
            input=stdin_payload,
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
