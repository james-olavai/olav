#!/usr/bin/env python3
"""
run_automation — Execute a script from .olav/automations/ with HITL gate.

Call without confirmed=True first → returns preview (safe, no side effects).
Call with confirmed=True after user approval → executes the script.
Only scripts inside .olav/automations/ may be executed via this tool.
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
_AUTOMATIONS_ROOT = PROJECT_ROOT / ".olav" / "automations"


def run_automation(
    path: str,
    confirmed: bool = False,
    args: list[str] | None = None,
    timeout: int = 300,
) -> dict:
    script = PROJECT_ROOT / path

    # Boundary: only scripts inside .olav/automations/
    try:
        script.resolve().relative_to(_AUTOMATIONS_ROOT.resolve())
    except ValueError:
        return {
            "status": "error",
            "error": f"'{path}' is outside .olav/automations/ — only automation scripts may be executed.",
        }

    if not script.exists():
        return {"status": "error", "error": f"Script not found: {path}"}

    suffix = script.suffix
    if suffix == ".py":
        cmd = [sys.executable, str(script)] + (args or [])
    elif suffix == ".sh":
        cmd = ["/bin/bash", str(script)] + (args or [])
    else:
        return {"status": "error", "error": f"Unsupported type '{suffix}'. Only .py and .sh are executable."}

    if not confirmed:
        return {
            "status": "preview",
            "path": path,
            "interpreter": cmd[0],
            "args": args or [],
            "timeout_seconds": timeout,
            "hint": "Use read_file to review the script, then call again with confirmed=True to execute.",
        }

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            timeout=timeout,
        )
        return {
            "status": "ok" if result.returncode == 0 else "failed",
            "returncode": result.returncode,
            "stdout": result.stdout[-4000:] if len(result.stdout) > 4000 else result.stdout,
            "stderr": result.stderr[-2000:] if len(result.stderr) > 2000 else result.stderr,
            "path": path,
        }
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "error": f"Script exceeded {timeout}s timeout", "path": path}
    except Exception as exc:
        return {"status": "error", "error": str(exc), "path": path}


if __name__ == "__main__":
    raw = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    print(json.dumps(run_automation(**raw)))
