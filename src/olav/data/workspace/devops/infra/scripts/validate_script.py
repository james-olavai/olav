#!/usr/bin/env python3
"""
validate_script — Syntax-check a script before HITL execution.

Runs py_compile for .py files; bash -n for .sh files.
Optionally runs ruff (E, F rules) if available.
Call this after write_automation and before run_automation.
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


def validate_script(path: str) -> dict:
    script = PROJECT_ROOT / path
    if not script.exists():
        return {"status": "error", "error": f"Script not found: {path}"}

    suffix = script.suffix
    checks = []

    if suffix == ".py":
        r = subprocess.run(
            [sys.executable, "-m", "py_compile", str(script)],
            capture_output=True,
            text=True,
        )
        checks.append({"check": "py_compile", "passed": r.returncode == 0, "output": r.stderr.strip()})

        ruff = subprocess.run(
            ["ruff", "check", "--select", "E,F", str(script)],
            capture_output=True,
            text=True,
        )
        if ruff.returncode != 127:  # 127 = command not found
            checks.append({
                "check": "ruff",
                "passed": ruff.returncode == 0,
                "output": ruff.stdout.strip()[:1000],
            })

    elif suffix == ".sh":
        r = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
        checks.append({"check": "bash_syntax", "passed": r.returncode == 0, "output": r.stderr.strip()})

    else:
        return {"status": "skipped", "reason": f"No validator for '{suffix}' files", "path": path}

    passed = all(c["passed"] for c in checks)
    return {"status": "pass" if passed else "fail", "path": path, "checks": checks}


if __name__ == "__main__":
    args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    print(json.dumps(validate_script(**args)))
