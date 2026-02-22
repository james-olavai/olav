"""TDD Tests for new argparse-based CLI (v0.9.9 migration).

These tests define the expected behavior of the new CLI structure
that replaces the Typer-based implementation.

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

    @pytest.mark.skip(reason="Interactive mode hangs in subprocess - test with --help instead")
    def test_no_args_enters_interactive_hint(self):
        """Running olav without args should enter interactive mode or show hint."""
        # Note: Can't test actual interactive mode in subprocess
        # This test verifies the command doesn't crash immediately
        r = run_olav(timeout=2)
        # Should either start interactive (timeout) or show help
        # Return code 0 or timeout is acceptable
        assert r.returncode in (0, None) or "OLAV" in r.stdout or "olav" in r.stdout.lower()


class TestAskCommand:
    """Test single query mode (replaces -m/--msg flag)."""

    @pytest.mark.llm
    @pytest.mark.skipif(
        not subprocess.run(
            ["sh", "-c", 'test -n "$LLM_API_KEY" || test -n "$OPENAI_API_KEY"'], capture_output=True
        ).returncode
        == 0,
        reason="LLM_API_KEY not set",
    )
    def test_ask_with_query(self):
        """olav ask 'query' should return a response."""
        r = run_olav("ask", "What is 2+2?", timeout=60)
        assert r.returncode == 0, f"stderr: {r.stderr}"
        assert len(r.stdout.strip()) > 0, "Expected non-empty response"

    @pytest.mark.skip(reason="Cannot test API key error when key is set in environment")
    def test_ask_without_api_key_shows_error(self):
        """olav ask without API key should show helpful error."""
        import os

        if os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY"):
            pytest.skip("API key is set, skipping error test")
        r = run_olav("ask", "test query", timeout=10)
        # Should fail gracefully with helpful message
        output = r.stdout + r.stderr
        assert "API" in output.upper() or "KEY" in output.upper() or "error" in output.lower()


class TestDevicesCommand:
    """Test network device listing command."""

    def test_devices_command_help(self):
        """devices --help should show usage."""
        r = run_olav("devices", "--help")
        assert r.returncode == 0, f"stderr: {r.stderr}"

    def test_devices_command_no_crash(self):
        """devices should not crash even with empty database."""
        r = run_olav("devices", timeout=10)
        assert r.returncode in (0, 1), f"Unexpected exit code: {r.stderr}"
        assert "Traceback" not in r.stderr


class TestInspectCommand:
    """Test network snapshot command."""

    def test_inspect_command_help(self):
        """inspect --help should show usage."""
        r = run_olav("inspect", "--help")
        assert r.returncode == 0, f"stderr: {r.stderr}"

    @pytest.mark.e2e
    def test_inspect_requires_devices_or_categories(self):
        """inspect should work with --devices or --categories flags."""
        # This test validates the argument parser
        r = run_olav("inspect", "--help")
        assert "--devices" in r.stdout or "-d" in r.stdout
        assert "--categories" in r.stdout or "-c" in r.stdout


class TestDatabaseCommands:
    """Test database-related commands (db subcommands)."""

    def test_db_status_help(self):
        """db status --help should show usage."""
        r = run_olav("db", "status", "--help")
        assert r.returncode == 0, f"stderr: {r.stderr}"

    def test_db_status_command(self):
        """db status should show database information."""
        r = run_olav("db", "status", timeout=10)
        assert r.returncode == 0, f"stderr: {r.stderr}"

    def test_db_schema_command(self):
        """db schema should show database schema."""
        r = run_olav("db", "schema", timeout=10)
        assert r.returncode == 0, f"stderr: {r.stderr}"

    def test_db_query_command(self):
        """db query should execute SQL and return results."""
        r = run_olav("db", "query", "SELECT 1 as test", timeout=10)
        assert r.returncode == 0, f"stderr: {r.stderr}"


@pytest.mark.skip(reason="TaskManager module not implemented - pending v0.9.10")
class TestTaskCommands:
    """Test task scheduling commands."""

    def test_task_help(self):
        """task --help should show subcommands."""
        r = run_olav("task", "--help")
        assert r.returncode == 0, f"stderr: {r.stderr}"

    def test_task_status_command(self):
        """task status should show scheduled tasks."""
        r = run_olav("task", "status", timeout=10)
        assert r.returncode == 0, f"stderr: {r.stderr}"


class TestStatusCommand:
    """Test status command (replaces admin status)."""

    def test_status_command(self):
        """status should show OLAV system status."""
        r = run_olav("status", timeout=10)
        assert r.returncode == 0, f"stderr: {r.stderr}"
        output = r.stdout + r.stderr
        # Should mention some system component
        assert any(word in output.lower() for word in ["skill", "database", "status", "olav"])


class TestBackupRestoreCommands:
    """Test backup and restore commands."""

    def test_backup_help(self):
        """backup --help should show usage."""
        r = run_olav("backup", "--help")
        assert r.returncode == 0, f"stderr: {r.stderr}"

    def test_restore_help(self):
        """restore --help should show usage."""
        r = run_olav("restore", "--help")
        assert r.returncode == 0, f"stderr: {r.stderr}"


class TestSkillsCommand:
    """Test skills listing command."""

    def test_skills_command(self):
        """skills should list available skills."""
        r = run_olav("skills", timeout=10)
        assert r.returncode == 0, f"stderr: {r.stderr}"

    def test_skills_detail_flag(self):
        """skills --detail should show more information."""
        r = run_olav("skills", "--detail", timeout=10)
        assert r.returncode == 0, f"stderr: {r.stderr}"


class TestUtilityCommands:
    """Test utility commands (ls, search, tree)."""

    def test_ls_command(self):
        """ls should list files matching pattern."""
        r = run_olav("ls", "*.toml", timeout=10)
        assert r.returncode == 0, f"stderr: {r.stderr}"
        assert "pyproject.toml" in r.stdout

    def test_search_command(self):
        """search should find pattern in files."""
        r = run_olav("search", "OLAV", "--type", "py", timeout=10)
        assert r.returncode == 0, f"stderr: {r.stderr}"

    def test_tree_command(self):
        """tree should show directory structure."""
        r = run_olav("tree", timeout=10)
        assert r.returncode == 0, f"stderr: {r.stderr}"
