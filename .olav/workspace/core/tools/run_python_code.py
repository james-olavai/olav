"""run_python_code — Pure-computation Python sandbox for the core workspace.

Executes Python code for data processing, analysis, and transformation.
Scope is intentionally limited to computation — for shell commands use
``run_shell``, for file writes use ``write_workspace_file``, for service
deployment use ``deploy_service``.

The agent's code may set `_result` to any JSON-serialisable value; that value
is returned in the `result` field of the response.

Usage example (agent writes this code):
    import json
    data = [{"ip": "10.0.0.1", "prefix": 24}]
    _result = [f"{d['ip']}/{d['prefix']}" for d in data]
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
    """Execute Python code for data computation, analysis, and transformation.

    Use for: parsing structured data, mathematical calculations, format
    conversion, graph algorithms, JSON/YAML manipulation, and any task
    that is purely computational.

    Do NOT use for: shell commands (use run_shell), file writes (use
    write_workspace_file), service deployment (use deploy_service), or
    docker operations (use run_shell).

    The code may set `_result` to any JSON-serialisable value; that value is
    returned in the response `result` field.

    Available in the execution environment:
    - Full Python standard library (json, math, re, itertools, collections, etc.)
    - All packages installed in the current Python environment (networkx, pandas, etc.)

    Args:
        code: Python source code to execute. Set `_result` to return structured data.
        timeout: Maximum execution time in seconds (default: 60).
        cwd: Working directory for execution (default: project root).

    Returns:
        dict with keys: status ("success"/"error"), stdout, stderr, result, error
    """
    return _execute_code(code, timeout=timeout, cwd=cwd or None)
