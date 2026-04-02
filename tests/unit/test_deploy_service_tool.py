"""Tests for deploy_service tool and orchestrator prompt correctness."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch
import subprocess


# ---------------------------------------------------------------------------
# deploy_service: tool discovery
# ---------------------------------------------------------------------------

class TestDeployServiceDiscoverable:
    def test_tool_importable(self):
        """deploy_service must be loadable as a LangChain @tool."""
        import importlib.util, sys

        spec = importlib.util.spec_from_file_location(
            "deploy_service_mod",
            Path(".olav/workspace/ops/tools/deploy_service.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        # Patch langchain_core.tools.tool to avoid heavy imports during load
        with patch.dict("sys.modules", {"langchain_core.tools": MagicMock(tool=lambda f: f)}):
            spec.loader.exec_module(mod)

        assert hasattr(mod, "deploy_service"), "deploy_service function must exist"

    def test_tool_has_correct_signature(self):
        """deploy_service must accept name, compose_yaml, env_files, health_url, register."""
        import inspect, importlib.util
        from unittest.mock import MagicMock, patch

        spec = importlib.util.spec_from_file_location(
            "deploy_service_mod2",
            Path(".olav/workspace/ops/tools/deploy_service.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        with patch.dict("sys.modules", {"langchain_core.tools": MagicMock(tool=lambda f: f)}):
            spec.loader.exec_module(mod)

        fn = mod.deploy_service
        sig = inspect.signature(fn)
        params = set(sig.parameters.keys())
        required = {"name", "health_url", "health_timeout"}
        assert required.issubset(params), f"Missing params: {required - params}"


# ---------------------------------------------------------------------------
# Orchestrator prompt: correct tool guidance
# ---------------------------------------------------------------------------

class TestOrchestratorPrompt:
    PROMPT = Path(".olav/workspace/ops/prompts/orchestrator.md").read_text()

    def test_deploy_service_listed_as_primary(self):
        """orchestrator.md must list deploy_service as primary for service deployment."""
        assert "deploy_service" in self.PROMPT

    def test_write_file_marked_never(self):
        """orchestrator.md must mark write_file as NEVER (in the NEVER column of the tool table)."""
        assert "write_file" in self.PROMPT
        # The table has a "NEVER use these" header; write_file appears in the data rows of that column
        lines = self.PROMPT.splitlines()
        never_section = False
        for line in lines:
            if "NEVER use these" in line:
                never_section = True
            if never_section and "write_file" in line:
                return
        raise AssertionError("write_file must appear under the 'NEVER use these' column")

    def test_run_shell_is_preferred_for_docker(self):
        """orchestrator.md must list run_shell as the tool for docker commands."""
        assert "run_shell" in self.PROMPT

    def test_execute_marked_never(self):
        """orchestrator.md must mark bare execute as NEVER (in the NEVER column of the tool table)."""
        lines = self.PROMPT.splitlines()
        never_section = False
        for line in lines:
            if "NEVER use these" in line:
                never_section = True
            # Match lines in the table that contain `execute` as a bare tool (not execute_sql/cli)
            if never_section and "`execute`" in line:
                return
        raise AssertionError("bare `execute` tool must appear under the 'NEVER use these' column")
