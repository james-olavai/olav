"""Tests for core/tools/run_python_code — general-purpose Python sandbox.

The tool must:
- Execute arbitrary Python code in a subprocess (isolated)
- Return stdout + structured _result if set
- Enforce a timeout
- Work with stdlib, pathlib, json, subprocess
- Not require LLMExperimentSandbox (deleted in core cleanup)
"""
from __future__ import annotations

import sys
from pathlib import Path

_TOOL_PATH = Path(__file__).resolve().parents[2] / ".olav" / "workspace" / "core" / "tools" / "run_python_code.py"


def _import_tool():
    import importlib.util
    import pytest
    if not _TOOL_PATH.exists():
        pytest.fail(f"run_python_code.py not found at {_TOOL_PATH}")
    spec = importlib.util.spec_from_file_location("run_python_code", _TOOL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestRunPythonCode:
    def test_simple_print_captured(self):
        mod = _import_tool()
        result = mod.run_python_code.invoke({"code": "print('hello world')"})
        assert "hello world" in result["stdout"]
        assert result["status"] == "success"

    def test_result_variable_returned(self):
        mod = _import_tool()
        result = mod.run_python_code.invoke({"code": "_result = {'answer': 42}"})
        assert result["result"] == {"answer": 42}
        assert result["status"] == "success"

    def test_subprocess_call_works(self):
        """Agent can run shell commands from within Python code."""
        mod = _import_tool()
        result = mod.run_python_code.invoke({
            "code": "import subprocess; out = subprocess.check_output(['echo', 'from-subprocess']); _result = out.decode().strip()"
        })
        assert result["status"] == "success"
        assert result["result"] == "from-subprocess"

    def test_syntax_error_returns_error_status(self):
        mod = _import_tool()
        result = mod.run_python_code.invoke({"code": "def ("})
        assert result["status"] == "error"
        assert result["error"] is not None

    def test_runtime_error_returns_error_status(self):
        mod = _import_tool()
        result = mod.run_python_code.invoke({"code": "raise ValueError('intentional')"})
        assert result["status"] == "error"
        assert "intentional" in (result["error"] or "") or "intentional" in (result["stderr"] or "")

    def test_timeout_enforced(self):
        mod = _import_tool()
        result = mod.run_python_code.invoke({
            "code": "import time; time.sleep(999)",
            "timeout": 2,
        })
        assert result["status"] == "error"
        assert "timeout" in result["error"].lower() or "timed out" in result["error"].lower()

    def test_pathlib_available(self):
        mod = _import_tool()
        result = mod.run_python_code.invoke({
            "code": "from pathlib import Path; _result = str(Path('.').resolve())"
        })
        assert result["status"] == "success"
        assert isinstance(result["result"], str)

    def test_json_yaml_available(self):
        mod = _import_tool()
        result = mod.run_python_code.invoke({
            "code": "import json, yaml; _result = json.loads('{\"k\": 1}')"
        })
        assert result["status"] == "success"
        assert result["result"] == {"k": 1}

    def test_no_llm_experiment_sandbox_dependency(self):
        """Tool must NOT import from olav.core.simulation (deleted module)."""
        content = _TOOL_PATH.read_text()
        assert "LLMExperimentSandbox" not in content
        assert "olav.core.simulation" not in content

    def test_is_langchain_tool(self):
        """run_python_code must be decorated with @tool for agent discovery."""
        mod = _import_tool()
        from langchain_core.tools import BaseTool
        # The @tool decorator makes it either a StructuredTool or BaseTool subclass
        assert hasattr(mod.run_python_code, "invoke"), "Must be a LangChain tool with .invoke()"
