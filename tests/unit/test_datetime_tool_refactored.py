"""Unit tests for TimeRangeTool (refactored to BaseTool protocol)."""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unittest.mock import patch

from olav.tools.datetime_tool_refactored import TimeRangeTool
from olav.tools.base import ToolRegistry


class TestTimeRangeTool:
    """Test suite for TimeRangeTool."""
    
    @pytest.fixture(autouse=True)
    def cleanup_registry(self):
        """Clear tool registry before and after each test."""
        from olav.tools.base import ToolRegistry
        if "parse_time_range" in ToolRegistry._tools:
            del ToolRegistry._tools["parse_time_range"]
        yield
        if "parse_time_range" in ToolRegistry._tools:
            del ToolRegistry._tools["parse_time_range"]
    
    @pytest.fixture
    def time_tool(self):
        """Create TimeRangeTool instance."""
        tool = TimeRangeTool()
        ToolRegistry.register(tool)
        return tool
    
    def test_initialization(self, time_tool):
        """Test tool initialization and properties."""
        assert time_tool.name == "parse_time_range"
        assert "natural language" in time_tool.description
        assert "ISO8601" in time_tool.description
    
    @pytest.mark.asyncio
    async def test_execute_missing_text(self, time_tool):
        """Test execute with empty natural_text parameter."""
        result = await time_tool.execute(natural_text="")
        
        assert result.error is not None
        assert "cannot be empty" in result.error.lower()
        assert result.data == []
    
    @pytest.mark.asyncio
    async def test_execute_past_hours(self, time_tool):
        """Test parsing 'past N hours' phrase."""
        result = await time_tool.execute(natural_text="past 2 hours")
        
        assert result.error is None
        assert len(result.data) == 1
        assert "start" in result.data[0]
        assert "end" in result.data[0]
        assert result.data[0]["duration_hours"] == 2.0
        
        assert result.metadata["recognized_pattern"] == "past_2_hours"
        assert result.metadata["natural_text"] == "past 2 hours"
    
    @pytest.mark.asyncio
    async def test_execute_past_days(self, time_tool):
        """Test parsing 'past N days' phrase."""
        result = await time_tool.execute(natural_text="past 3 days")
        
        assert result.error is None
        assert len(result.data) == 1
        assert result.data[0]["duration_hours"] == 72.0
        
        assert result.metadata["recognized_pattern"] == "past_3_days"
    
    @pytest.mark.asyncio
    async def test_execute_yesterday_english(self, time_tool):
        """Test parsing 'yesterday' phrase (English)."""
        result = await time_tool.execute(natural_text="yesterday")
        
        assert result.error is None
        assert len(result.data) == 1
        assert result.data[0]["duration_hours"] == 24.0
        
        assert result.metadata["recognized_pattern"] == "yesterday"
    
    @pytest.mark.asyncio
    async def test_execute_yesterday_chinese(self, time_tool):
        """Test parsing '昨天' phrase (Chinese)."""
        result = await time_tool.execute(natural_text="昨天")
        
        assert result.error is None
        assert len(result.data) == 1
        assert result.data[0]["duration_hours"] == 24.0
        
        assert result.metadata["recognized_pattern"] == "yesterday"
    
    @pytest.mark.asyncio
    async def test_execute_last_night_english(self, time_tool):
        """Test parsing 'last night' phrase (English)."""
        result = await time_tool.execute(natural_text="last night")
        
        assert result.error is None
        assert len(result.data) == 1
        # Previous day 18:00 to current day 06:00
        assert result.data[0]["duration_hours"] == 12.0
        
        assert result.metadata["recognized_pattern"] == "last_night"
    
    @pytest.mark.asyncio
    async def test_execute_last_night_chinese(self, time_tool):
        """Test parsing '昨晚' phrase (Chinese)."""
        result = await time_tool.execute(natural_text="昨晚")
        
        assert result.error is None
        assert len(result.data) == 1
        assert result.data[0]["duration_hours"] == 12.0
        
        assert result.metadata["recognized_pattern"] == "last_night"
    
    @pytest.mark.asyncio
    async def test_execute_unrecognized_fallback(self, time_tool):
        """Test fallback to past 24 hours for unrecognized phrases."""
        result = await time_tool.execute(natural_text="some random text")
        
        assert result.error is None
        # Should fall back to past 24 hours
        assert result.data[0]["duration_hours"] == 24.0
        
        assert result.metadata["recognized_pattern"] == "fallback_24h"
    
    @pytest.mark.asyncio
    async def test_execute_non_utc_format(self, time_tool):
        """Test output without UTC 'Z' suffix."""
        result = await time_tool.execute(
            natural_text="past 1 hour",
            utc_format=False,
        )
        
        assert result.error is None
        # Should not have 'Z' suffix
        assert not result.data[0]["start"].endswith("Z")
        assert not result.data[0]["end"].endswith("Z")
        
        assert result.metadata["utc_format"] is False
    
    @pytest.mark.asyncio
    async def test_execute_past_hours_no_number(self, time_tool):
        """Test 'past hours' without explicit number (should default to 24)."""
        result = await time_tool.execute(natural_text="past hours")
        
        assert result.error is None
        assert result.data[0]["duration_hours"] == 24.0
    
    @pytest.mark.asyncio
    async def test_execute_past_days_no_number(self, time_tool):
        """Test 'past days' without explicit number (should default to 1)."""
        result = await time_tool.execute(natural_text="past days")
        
        assert result.error is None
        assert result.data[0]["duration_hours"] == 24.0


class TestTimeRangeToolRegistration:
    """Test ToolRegistry registration for TimeRangeTool."""
    
    @pytest.fixture(autouse=True)
    def setup_tool(self):
        """Register tool before tests and cleanup after."""
        from olav.tools.base import ToolRegistry
        if "parse_time_range" in ToolRegistry._tools:
            del ToolRegistry._tools["parse_time_range"]
        
        tool = TimeRangeTool()
        ToolRegistry.register(tool)
        yield
        
        if "parse_time_range" in ToolRegistry._tools:
            del ToolRegistry._tools["parse_time_range"]
    
    def test_tool_registered(self):
        """Test that TimeRangeTool is registered."""
        # Tool already registered by conftest.py fixture
        registered = ToolRegistry.list_tools()
        tool_names = [tool.name for tool in registered]
        assert "parse_time_range" in tool_names
    
    def test_get_tool_by_name(self):
        """Test retrieving tool by name from registry."""
        tool = ToolRegistry.get_tool("parse_time_range")
        assert tool is not None
        assert isinstance(tool, TimeRangeTool)


class TestTimeRangeToolEdgeCases:
    """Test edge cases for TimeRangeTool."""
    
    @pytest.fixture(autouse=True)
    def cleanup_registry(self):
        """Clear tool registry before and after each test."""
        from olav.tools.base import ToolRegistry
        if "parse_time_range" in ToolRegistry._tools:
            del ToolRegistry._tools["parse_time_range"]
        yield
        if "parse_time_range" in ToolRegistry._tools:
            del ToolRegistry._tools["parse_time_range"]
    
    @pytest.fixture
    def time_tool(self):
        """Create TimeRangeTool instance."""
        tool = TimeRangeTool()
        ToolRegistry.register(tool)
        return tool
    
    @pytest.mark.asyncio
    async def test_whitespace_only_text(self, time_tool):
        """Test natural_text with only whitespace."""
        result = await time_tool.execute(natural_text="   \t\n  ")
        
        assert result.error is not None
        assert "cannot be empty" in result.error.lower()
    
    @pytest.mark.asyncio
    async def test_timing_metadata_present(self, time_tool):
        """Test that elapsed_ms is always included in metadata."""
        result = await time_tool.execute(natural_text="past 1 hour")
        
        assert "elapsed_ms" in result.metadata
        assert isinstance(result.metadata["elapsed_ms"], int)
        assert result.metadata["elapsed_ms"] >= 0
    
    @pytest.mark.asyncio
    async def test_case_insensitive_parsing(self, time_tool):
        """Test that parsing is case-insensitive."""
        result_lower = await time_tool.execute(natural_text="past 2 hours")
        result_upper = await time_tool.execute(natural_text="PAST 2 HOURS")
        result_mixed = await time_tool.execute(natural_text="PaSt 2 HoUrS")
        
        # All should produce the same duration
        assert result_lower.data[0]["duration_hours"] == result_upper.data[0]["duration_hours"]
        assert result_lower.data[0]["duration_hours"] == result_mixed.data[0]["duration_hours"]
    
    @pytest.mark.asyncio
    async def test_mixed_language_phrases(self, time_tool):
        """Test phrases with mixed English and Chinese."""
        # Should recognize Chinese keyword
        result = await time_tool.execute(natural_text="查询昨天的数据")
        
        assert result.error is None
        assert result.data[0]["duration_hours"] == 24.0
        assert result.metadata["recognized_pattern"] == "yesterday"
