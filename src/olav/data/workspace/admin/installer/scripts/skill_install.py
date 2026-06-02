#!/usr/bin/env python3
"""skill_install.py — Install an OLAV skill pack from a path or URL."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _find_olav_bin() -> str:
    """Locate the olav CLI executable."""
    venv_bin = Path(sys.executable).parent / "olav"
    if venv_bin.exists():
        return str(venv_bin)
    return "olav"


def skill_install(source: str, force: bool = False) -> str:
    """Install an OLAV skill pack from a local directory path or Git URL.

    Args:
        source: Path to a skill pack directory, or a Git URL (https://... or git@...).
        force: If True, overwrite an already-installed skill with the same name.

    Returns:
        stdout + stderr from `olav skill install`, or an error message.
    """
    cmd = [_find_olav_bin(), "skill", "install", source]
    if force:
        cmd.append("--force")
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120
        )
        out = (result.stdout + result.stderr).strip()
        return out if out else f"Exit code {result.returncode} (no output)"
    except FileNotFoundError:
        return "Error: `olav` CLI not found. Run from inside the OLAV virtual environment."
    except subprocess.TimeoutExpired:
        return "Error: skill install timed out after 120 s."


if __name__ == "__main__":
    import json as _json, sys as _sys
    _args = _json.loads(_sys.stdin.read() or "{}")
    result = skill_install(**_args)
    print(_json.dumps(result, default=str))
