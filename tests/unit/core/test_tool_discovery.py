"""Unit tests for src/olav/core/tool_discovery.py."""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path


def test_validate_tools_all_valid():
    """Test validate_tools_against_skill with all valid tools."""
    from src.olav.core.tool_discovery import validate_tools_against_skill

    mock_tool = MagicMock()
    mock_tool.name = "tool1"

    skill_config = {"tools": ["tool1"]}

    result = validate_tools_against_skill([mock_tool], skill_config)

    assert result["valid"] is True
    assert result["missing"] is None
    assert result["extra"] is None


def test_validate_tools_with_extra():
    """Test when SKILL has extra tools."""
    from src.olav.core.tool_discovery import validate_tools_against_skill

    mock_tool = MagicMock()
    mock_tool.name = "tool1"

    skill_config = {"tools": ["tool1", "extra_tool"]}

    result = validate_tools_against_skill([mock_tool], skill_config)

    assert result["valid"] is False
    assert "extra_tool" in result["extra"]


def test_validate_tools_empty():
    """Test with empty skill config."""
    from src.olav.core.tool_discovery import validate_tools_against_skill

    result = validate_tools_against_skill([], {})

    assert result["valid"] is True
