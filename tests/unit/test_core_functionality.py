"""Core functionality tests to ensure comprehensive pytest coverage.

Run: pytest tests/unit/test_core_functionality.py -v
"""

import pytest


class TestCoreFunctionality:
    """Core functionality tests for OLAV system."""

    def test_imports_work_correctly(self):
        """Test that core modules can be imported without issues."""
        # Test core module imports
        from olav.core import command_registry
        from olav.core import database
        from olav.core import llm
        from olav.core import tool_discovery
        from olav.core import memory  # olav.core.knowledge was renamed to olav.core.memory

        # Verify modules are properly imported
        assert command_registry is not None
        assert database is not None
        assert llm is not None
        assert tool_discovery is not None
        assert memory is not None

    def test_database_functionality(self):
        """Test basic database functionality."""
        from olav.core.database import OlavDatabase

        # Test basic instantiation
        db = OlavDatabase()
        assert db is not None
        db.close()

    def test_command_registry_functionality(self):
        """Test command registry functionality."""
        from olav.core.command_registry import CommandRegistry

        # Test singleton pattern
        registry1 = CommandRegistry()
        registry2 = CommandRegistry()
        assert registry1 is registry2

    def test_llm_functionality(self):
        """Test basic LLM functionality."""
        from olav.core.llm import LLMFactory

        # Test that the factory exists
        assert LLMFactory is not None

    def test_tool_discovery_functionality(self):
        """Test tool discovery functionality."""
        from olav.core.tool_discovery import discover_tools

        # Test that function exists
        assert discover_tools is not None

    def test_knowledge_modules(self):
        """Test that knowledge memory module is importable."""
        from olav.core.memory import LanceDBStore, MemoryCategory, rrf_fusion

        assert LanceDBStore is not None
        assert MemoryCategory.FACT == "fact"
        assert callable(rrf_fusion)
