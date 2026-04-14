"""Safe execution of shell-type slash commands.

Design reference: dev_docs/slash_command_auto_registration.md §8.2, §3.3, §11

Rules enforced here:
- ``shell=True`` is NEVER used — argv-style exec only.
- Commands with ``approval="required"`` must be confirmed by the user before
  execution (HITL gate).
- ``timeout`` is mandatory for shell commands declared in MANIFEST (enforced
  upstream in the spec); this runner also applies it at the subprocess level.
- ``cwd_policy`` resolves the working directory deterministically.
- Only environment variables on ``env_allowlist`` are forwarded to the child
  process (plus a minimal safe set: PATH, HOME, LANG, LC_ALL).
"""

from __future__ import annotations

import asyncio
import os
import shlex
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from olav.cli.commands.registry import SlashCommandSpec

# Minimum environment variables always forwarded to child processes.
_ALWAYS_FORWARD: frozenset[str] = frozenset({"PATH", "HOME", "LANG", "LC_ALL", "TERM"})

# Default timeout for shell commands that declare no explicit timeout.
_DEFAULT_TIMEOUT: int = 300  # 5 minutes


# ── approval gate ─────────────────────────────────────────────────────────────


def _prompt_approval(spec: SlashCommandSpec, args: str) -> bool:
    """Synchronous HITL approval prompt.

    Returns ``True`` if the user approves execution, ``False`` otherwise.
    Prints a summary of what will be executed before asking.
    """
    print()
    print("⚠️  Approval required before executing:")
    print(f"   Command : /{spec.name}")
    print(f"   Script  : {spec.script}")
    if args:
        print(f"   Args    : {args}")
    print()
    try:
        answer = input("Proceed? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = "n"
    return answer in ("y", "yes")


# ── cwd resolution ────────────────────────────────────────────────────────────


def _resolve_cwd(spec: SlashCommandSpec, project_root: Path) -> Path:
    """Return the working directory for the child process."""
    policy = spec.cwd_policy
    if policy == "workspace_dir":
        return project_root / ".olav" / "workspace"
    if policy == "script_dir" and spec.script:
        return (project_root / spec.script).resolve().parent
    # default: project_root
    return project_root


# ── env filtering ─────────────────────────────────────────────────────────────


def _filtered_env(spec: SlashCommandSpec) -> dict[str, str]:
    """Return a minimal environment dict for the child process."""
    allowed = set(_ALWAYS_FORWARD) | set(spec.env_allowlist)
    return {k: v for k, v in os.environ.items() if k in allowed}


# ── runner ────────────────────────────────────────────────────────────────────


async def run_shell_command(
    spec: SlashCommandSpec,
    args: str,
    project_root: Path,
    *,
    auto_approve: bool = False,
) -> str:
    """Execute a shell-type slash command safely.

    Parameters
    ----------
    spec:
        The :class:`~olav.cli.commands.registry.SlashCommandSpec` for the
        command.  Must have ``kind="shell"`` and a ``script`` field.
    args:
        Raw argument string from the CLI (will be split with ``shlex.split``).
    project_root:
        Repository root used for CWD resolution and script path expansion.
    auto_approve:
        If ``True``, skip the HITL approval prompt (used in non-interactive /
        test contexts where ``--auto-approve`` was passed).

    Returns
    -------
    str
        Combined stdout output from the process.

    Raises
    ------
    ValueError
        If the script path is missing or the spec kind is not ``"shell"``.
    PermissionError
        If the script file is not executable.
    RuntimeError
        If the user declines approval.
    asyncio.TimeoutError
        If the process exceeds ``spec.timeout``.
    """
    if spec.kind != "shell":
        raise ValueError(f"run_shell_command() requires kind='shell', got '{spec.kind}'")
    if not spec.script:
        raise ValueError(f"SlashCommandSpec '{spec.name}' has no script path set")

    script_path = (project_root / spec.script).resolve()
    if not script_path.exists():
        return f"❌ Script not found: {script_path}"
    # Python scripts are invoked via sys.executable — no +x bit required.
    if script_path.suffix != ".py" and not os.access(script_path, os.X_OK):
        return f"❌ Script is not executable: {script_path}\nRun: chmod +x {script_path}"

    # ── approval gate ─────────────────────────────────────────────────────────
    if spec.approval == "required" and not auto_approve:
        if not _prompt_approval(spec, args):
            return "❌ Execution cancelled by user."

    # ── build argv ────────────────────────────────────────────────────────────
    try:
        extra_args = shlex.split(args) if args.strip() else []
    except ValueError as exc:
        return f"❌ Argument parse error: {exc}"

    # For Python scripts, use the current interpreter (venv-aware) instead of
    # relying on the shebang which may resolve to the system python.
    import sys

    if script_path.suffix == ".py":
        argv = [sys.executable, str(script_path)] + extra_args
    else:
        argv = [str(script_path)] + extra_args

    # ── resolve cwd & env ─────────────────────────────────────────────────────
    cwd = _resolve_cwd(spec, project_root)
    env = _filtered_env(spec)
    timeout = spec.timeout if spec.timeout is not None else _DEFAULT_TIMEOUT

    # ── execute ───────────────────────────────────────────────────────────────
    t0 = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(cwd),
            env=env,
        )
        try:
            stdout_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=float(timeout))
        except TimeoutError:
            proc.kill()
            await proc.communicate()
            elapsed = time.monotonic() - t0
            return f"❌ Script '{spec.name}' timed out after {elapsed:.1f}s (limit: {timeout}s)."

        elapsed = time.monotonic() - t0
        output = stdout_bytes.decode(errors="replace").rstrip()
        rc = proc.returncode

        if rc != 0:
            return (
                f"❌ Script '{spec.name}' exited with code {rc} "
                f"(elapsed: {elapsed:.1f}s).\n\n{output}"
            )
        return output or f"✓ Script '{spec.name}' completed in {elapsed:.1f}s."

    except FileNotFoundError:
        return f"❌ Could not execute script: {script_path}"
