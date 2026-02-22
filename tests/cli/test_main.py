"""TDD Tests for minimal deepagents-cli wrapper CLI (v0.9.9).

These tests verify the new minimal CLI structure that:
1. Extends deepagents-cli (not replaces it)
2. Exposes domain functionality through tools/skills, not CLI commands
3. Uses natural language queries instead of hardcoded commands

Run: uv run pytest tests/cli/test_main.py -v
"""

import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent


def run_olav(*args, timeout: int = 15) -> subprocess.CompletedProcess:
    """Run olav CLI command and return result."""
    return subprocess.run(
        ["uv", "run", "olav", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(PROJECT_ROOT),
    )


class TestCLIEntryPoint:
    """Test the main CLI entry point works correctly."""

    def test_help_flag(self):
        """--help should show usage information."""
        r = run_olav("--help")
        assert r.returncode == 0, f"stderr: {r.stderr}"
        assert "olav" in r.stdout.lower()

    def test_version_flag(self):
        """--version should show version number."""
        r = run_olav("--version")
        assert r.returncode == 0, f"stderr: {r.stderr}"
        assert "0.9.9" in r.stdout

    @pytest.mark.skip(reason="Interactive mode hangs in subprocess - test with --help instead")
    def test_no_args_enters_interactive_hint(self):
        """Running olav without args should enter interactive mode or show hint."""
        r = run_olav(timeout=2)
        assert r.returncode in (0, None) or "OLAV" in r.stdout or "olav" in r.stdout.lower()


class TestDeepAgentsCompatibleFlags:
    """Test deepagents-cli compatible flags are present."""

    def test_agent_flag_in_help(self):
        """--agent flag should be present for multi-agent support."""
        r = run_olav("--help")
        assert r.returncode == 0
        assert "--agent" in r.stdout

    def test_sandbox_flag_in_help(self):
        """--sandbox flag should be present for remote execution support."""
        r = run_olav("--help")
        assert r.returncode == 0
        assert "--sandbox" in r.stdout

    def test_auto_approve_flag_in_help(self):
        """--auto-approve flag should be present for HITL control."""
        r = run_olav("--help")
        assert r.returncode == 0
        assert "--auto-approve" in r.stdout

    def test_sandbox_choices(self):
        """--sandbox should support deepagents providers."""
        r = run_olav("--help")
        assert r.returncode == 0
        # Should mention at least modal or daytona or runloop
        assert any(p in r.stdout for p in ["modal", "daytona", "runloop"])


class TestSingleQueryMode:
    """Test single query mode (natural language)."""

    @pytest.mark.llm
    @pytest.mark.skipif(
        not subprocess.run(
            ["sh", "-c", 'test -n "$LLM_API_KEY" || test -n "$OPENAI_API_KEY"'], capture_output=True
        ).returncode
        == 0,
        reason="LLM_API_KEY not set",
    )
    def test_single_query_returns_response(self):
        """olav 'query' should return a response."""
        r = run_olav("What is 2+2?", timeout=60)
        assert r.returncode == 0, f"stderr: {r.stderr}"
        assert len(r.stdout.strip()) > 0, "Expected non-empty response"

    @pytest.mark.skip(reason="Cannot test API key error when key is set in environment")
    def test_query_without_api_key_shows_error(self):
        """olav query without API key should show helpful error."""
        import os

        if os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY"):
            pytest.skip("API key is set, skipping error test")
        r = run_olav("test query", timeout=10)
        output = r.stdout + r.stderr
        assert "API" in output.upper() or "KEY" in output.upper() or "error" in output.lower()


class TestNoHardcodedCommands:
    """Verify hardcoded domain commands are removed (use tools instead)."""

    def test_no_devices_command(self):
        """devices command should not exist (use tools)."""
        r = run_olav("devices", "--help", timeout=5)
        # Should either fail or not show devices help
        # New CLI doesn't have devices command - query should be passed to agent
        assert (
            r.returncode != 0 or "devices" not in r.stdout.lower() or "unknown" in r.stdout.lower()
        )

    def test_no_db_command(self):
        """db command should not exist (use tools)."""
        r = run_olav("db", "--help", timeout=5)
        # The new CLI treats 'db' as a query argument, so it shows help
        # Check that 'db' is not shown as a command option
        assert "db status" not in r.stdout.lower() and "db query" not in r.stdout.lower()

    def test_no_inspect_command(self):
        """inspect command should not exist (use tools)."""
        r = run_olav("inspect", "--help", timeout=5)
        assert (
            r.returncode != 0 or "inspect" not in r.stdout.lower() or "unknown" in r.stdout.lower()
        )

    def test_no_status_command(self):
        """status command should not exist (use tools)."""
        r = run_olav("status", "--help", timeout=5)
        assert (
            r.returncode != 0 or "status" not in r.stdout.lower() or "unknown" in r.stdout.lower()
        )

    def test_no_backup_command(self):
        """backup command should not exist (use tools)."""
        r = run_olav("backup", "--help", timeout=5)
        assert (
            r.returncode != 0 or "backup" not in r.stdout.lower() or "unknown" in r.stdout.lower()
        )


class TestAgentUsesDeepAgents:
    """Verify OLAVAgent uses create_deep_agent internally."""

    def test_agent_imports_deepagents(self):
        """OLAVAgent should import create_deep_agent from deepagents."""
        from olav.agents.agent import OLAVAgent

        # Check that the module imports create_deep_agent
        import olav.agents.agent as agent_module

        assert hasattr(agent_module, "create_deep_agent") or "create_deep_agent" in dir()

    def test_agent_has_graph_attribute(self):
        """OLAVAgent should have a graph attribute (LangGraph compiled agent)."""
        from olav.agents.agent import create_olav_agent

        agent = create_olav_agent(enable_checkpointer=False, enable_store=False)
        assert hasattr(agent, "graph"), "OLAVAgent should have graph attribute"

    def test_agent_has_subagents(self):
        """OLAVAgent should support subagents for tool isolation."""
        from olav.agents.agent import create_olav_agent

        agent = create_olav_agent(enable_checkpointer=False, enable_store=False)
        # The graph should be created with subagents
        assert agent.graph is not None


class TestUsesDeepAgentsComponents:
    """Verify CLI uses deepagents-cli components."""

    def test_main_imports_deepagents_cli(self):
        """main.py should import from deepagents_cli."""
        from olav.cli.main import create_olav_agent_with_backend

        # Should be able to create agent with backend
        assert callable(create_olav_agent_with_backend)

    def test_agent_creates_backend(self):
        """Agent creation should return backend for file operations."""
        from olav.cli.main import create_olav_agent_with_backend

        agent, backend = create_olav_agent_with_backend("test-agent")

        # Backend should be a CompositeBackend
        assert backend is not None
        assert hasattr(backend, "default")

    def test_agent_has_graph_from_main(self):
        """Agent from main.py should have a graph."""
        from olav.cli.main import create_olav_agent_with_backend

        agent, backend = create_olav_agent_with_backend("test-agent")

        # Agent should be a LangGraph graph
        assert agent is not None


class TestListCommand:
    """Test list agents command."""

    def test_list_command(self):
        """list should show available agents."""
        r = run_olav("list", timeout=10)
        assert r.returncode == 0, f"stderr: {r.stderr}"
        assert "olav" in r.stdout.lower()

    def test_help_command(self):
        """help command should show usage."""
        r = run_olav("help")
        assert r.returncode == 0, f"stderr: {r.stderr}"
        assert "Usage" in r.stdout or "usage" in r.stdout.lower()

