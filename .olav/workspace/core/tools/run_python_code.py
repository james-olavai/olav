"""run_python_code — General-purpose Python sandbox for the core workspace.

Executes arbitrary Python code in an isolated subprocess. The agent writes
code that can use any installed package, run shell commands via subprocess,
read/write files, make HTTP requests, etc.

Self-contained subprocess-based sandbox. No external simulation dependencies.

The agent's code may set `_result` to any JSON-serialisable value; that value
is returned in the `result` field of the response.

Usage example (agent writes this code):
    import subprocess
    out = subprocess.check_output(["docker", "compose", "ps"])
    _result = {"containers": out.decode()}
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Any

from langchain_core.tools import tool


def _execute_code(code: str, timeout: int, cwd: str | None = None) -> dict[str, Any]:
    """Execute Python code in a subprocess and return structured result."""
    # Wrap user code so that _result is serialised to stdout on success
    wrapper = textwrap.dedent(f"""\
        import json as _json
        import sys as _sys

        _result = None

        try:
{textwrap.indent(code, "            ")}
        except Exception as _exc:
            import traceback
            print("__OLAV_ERROR__:" + str(_exc), file=_sys.stderr)
            print(traceback.format_exc(), file=_sys.stderr)
            _sys.exit(1)

        # Emit structured result marker
        try:
            print("__OLAV_RESULT__:" + _json.dumps(_result))
        except (TypeError, ValueError):
            print("__OLAV_RESULT__:" + _json.dumps(str(_result)))
    """)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(wrapper)
        script_path = f.name

    try:
        proc = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd or str(Path.cwd()),
        )
    except subprocess.TimeoutExpired:
        Path(script_path).unlink(missing_ok=True)
        return {
            "status": "error",
            "error": f"code execution timed out after {timeout}s",
            "stdout": "",
            "stderr": "",
            "result": None,
        }
    finally:
        Path(script_path).unlink(missing_ok=True)

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""

    # Extract structured _result from stdout
    result_value = None
    clean_stdout_lines = []
    for line in stdout.splitlines():
        if line.startswith("__OLAV_RESULT__:"):
            try:
                result_value = json.loads(line[len("__OLAV_RESULT__:"):])
            except json.JSONDecodeError:
                result_value = line[len("__OLAV_RESULT__:"):]
        else:
            clean_stdout_lines.append(line)

    clean_stdout = "\n".join(clean_stdout_lines)

    if proc.returncode != 0:
        # Extract clean error from stderr
        error_msg = ""
        for line in stderr.splitlines():
            if line.startswith("__OLAV_ERROR__:"):
                error_msg = line[len("__OLAV_ERROR__:"):]
                break
        if not error_msg:
            error_msg = stderr.strip().split("\n")[-1] if stderr.strip() else "non-zero exit"

        return {
            "status": "error",
            "error": error_msg,
            "stdout": clean_stdout,
            "stderr": stderr,
            "result": None,
        }

    return {
        "status": "success",
        "error": None,
        "stdout": clean_stdout,
        "stderr": stderr,
        "result": result_value,
    }


@tool
def run_python_code(
    code: str,
    timeout: int = 60,
    cwd: str = "",
) -> dict[str, Any]:
    """Execute arbitrary Python code in an isolated subprocess.

    Use this to accomplish any task that requires code: calling APIs,
    managing docker containers, writing files, processing data, installing
    packages, running CLI tools, etc. The code runs in a fresh subprocess
    with access to the full Python standard library and all installed packages.

    The code may set `_result` to any JSON-serialisable value; that value is
    returned in the response `result` field.

    Available in the execution environment:
    - Full Python standard library (subprocess, pathlib, os, json, yaml, etc.)
    - All packages installed in the current Python environment
    - subprocess for shell commands (docker, git, curl, olav CLI, etc.)
    - Network access (httpx, requests) for HTTP calls

    Args:
        code: Python source code to execute. Set `_result` to return structured data.
        timeout: Maximum execution time in seconds (default: 60).
        cwd: Working directory for execution (default: project root).

    Returns:
        dict with keys: status ("success"/"error"), stdout, stderr, result, error
    """
    return _execute_code(code, timeout=timeout, cwd=cwd or None)
