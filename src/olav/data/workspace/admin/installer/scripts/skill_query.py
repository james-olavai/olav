#!/usr/bin/env python3
"""skill_query.py — Query installed OLAV skill packs (list all or inspect one)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _find_olav_bin() -> str:
    venv_bin = Path(sys.executable).parent / "olav"
    if venv_bin.exists():
        return str(venv_bin)
    return "olav"


def skill_query(name: str = "") -> str:
    """List all installed OLAV skill packs, or inspect a specific one.

    Args:
        name: Skill pack name for detailed status (e.g. "netops", "ent").
              Leave empty to list all installed skill packs.

    Returns:
        Table of installed skills (no name), or detailed status for the named skill.
    """
    try:
        if name:
            cmd = [_find_olav_bin(), "skill", "status", name]
            timeout = 30
            empty_msg = f"No status output for skill '{name}'."
        else:
            cmd = [_find_olav_bin(), "skill", "list"]
            timeout = 30
            empty_msg = "No skill packs installed."

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = (result.stdout + result.stderr).strip()
        return out if out else empty_msg
    except FileNotFoundError:
        return "Error: `olav` CLI not found. Run from inside the OLAV virtual environment."
    except subprocess.TimeoutExpired:
        return "Error: skill query timed out."


if __name__ == "__main__":
    import json as _json, sys as _sys
    _args = _json.loads(_sys.stdin.read() or "{}")
    result = skill_query(**_args)
    print(_json.dumps(result, default=str))
