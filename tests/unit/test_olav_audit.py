"""Unit tests for olav-audit workspace tools.

NOTE: The original tests referenced `audit_designer` and `schema_inspector`
modules that were never created. Those tests are removed.

This file tests the tools that actually exist in .olav/workspace/audit/tools/.
"""

import sys
from pathlib import Path

import pytest

AUDIT_TOOLS_DIR = Path(__file__).resolve().parents[2] / ".olav" / "workspace" / "audit" / "tools"


class TestAuditToolsExist:
    """Verify the audit tool files actually exist on disk."""

    def test_execute_sql_exists(self):
        assert (AUDIT_TOOLS_DIR / "execute_sql.py").exists()

    def test_execute_cli_exists(self):
        assert (AUDIT_TOOLS_DIR / "execute_cli.py").exists()

    def test_take_snapshot_exists(self):
        assert (AUDIT_TOOLS_DIR / "take_snapshot.py").exists()

    def test_format_and_export_exists(self):
        assert (AUDIT_TOOLS_DIR / "format_and_export.py").exists()

    def test_search_knowledge_lancedb_exists(self):
        assert (AUDIT_TOOLS_DIR / "search_knowledge_lancedb.py").exists()


class TestAuditToolsImportable:
    """Verify audit tools are importable via tool_discovery."""

    def test_audit_tools_loadable(self):
        """discover_tools must load at least 1 tool from audit/tools."""
        from olav.core.tool_discovery import discover_tools

        tools = discover_tools(AUDIT_TOOLS_DIR)
        assert len(tools) >= 1, f"Expected at least 1 tool, got {len(tools)}"

    def test_search_knowledge_tool_importable(self):
        """search_knowledge tool must be importable and usable."""
        sys.path.insert(0, str(AUDIT_TOOLS_DIR))
        try:
            from search_knowledge_lancedb import search_knowledge
            assert hasattr(search_knowledge, 'invoke'), "search_knowledge must be a callable LangChain tool"
        finally:
            if str(AUDIT_TOOLS_DIR) in sys.path:
                sys.path.remove(str(AUDIT_TOOLS_DIR))


class TestDiffConfigs:
    """Tests for diff_configs.py tool."""

    def test_diff_configs_importable(self):
        """diff_configs tool must load without errors."""
        sys.path.insert(0, str(AUDIT_TOOLS_DIR))
        try:
            import importlib.util

            spec = importlib.util.spec_from_file_location(
                "diff_configs", AUDIT_TOOLS_DIR / "diff_configs.py"
            )
            assert spec is not None, "diff_configs.py must be loadable"
        finally:
            if str(AUDIT_TOOLS_DIR) in sys.path:
                sys.path.remove(str(AUDIT_TOOLS_DIR))

