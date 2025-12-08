"""E2E Tests for Debug Mode - Verify instrumentation works.

Tests that Debug Mode correctly captures:
- LLM calls (prompt, response, tokens)
- Tool calls (input, output, duration)
- Graph states (node transitions)
- Time breakdown

Usage:
    uv run pytest tests/e2e/test_debug_mode.py -v
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

import pytest

# Windows async compatibility
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def _check_dependencies() -> bool:
    """Check if required dependencies are available."""
    import importlib.util
    return importlib.util.find_spec("olav.modes.shared.debug") is not None


pytestmark = pytest.mark.skipif(
    not _check_dependencies(),
    reason="Debug Mode dependencies not available"
)


class TestDebugOutput:
    """Tests for DebugOutput data structure."""

    def test_debug_output_creation(self):
        """Test DebugOutput can be created."""
        from olav.modes.shared.debug import DebugOutput

        output = DebugOutput(
            query="test query",
            mode="standard",
        )

        assert output.query == "test query"
        assert output.mode == "standard"
        assert output.llm_calls == []
        assert output.tool_calls == []

    def test_add_llm_call(self):
        """Test adding LLM call updates totals."""
        from olav.modes.shared.debug import DebugOutput, LLMCallDetail

        output = DebugOutput()

        call = LLMCallDetail(
            call_id="llm-001",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
        )

        output.add_llm_call(call)

        assert len(output.llm_calls) == 1
        assert output.total_prompt_tokens == 100
        assert output.total_completion_tokens == 50
        assert output.total_tokens == 150

    def test_add_tool_call(self):
        """Test adding tool call."""
        from olav.modes.shared.debug import DebugOutput, ToolCallDetail

        output = DebugOutput()

        call = ToolCallDetail(
            tool_name="suzieq_query",
            input_args={"table": "bgp"},
            output="[...]",
            duration_ms=100.5,
        )

        output.add_tool_call(call)

        assert len(output.tool_calls) == 1
        assert output.tool_calls[0].tool_name == "suzieq_query"

    def test_add_graph_state(self):
        """Test adding graph states and transitions."""
        from olav.modes.shared.debug import DebugOutput

        output = DebugOutput()

        output.add_graph_state("classify", {"intent": "query"})
        output.add_graph_state("execute", {"tool": "suzieq"})
        output.add_graph_state("format", {"answer": "..."})

        assert len(output.graph_states) == 3
        assert len(output.transitions) == 2
        assert "classify -> execute" in output.transitions
        assert "execute -> format" in output.transitions

    def test_to_json(self):
        """Test JSON serialization."""
        from olav.modes.shared.debug import DebugOutput

        output = DebugOutput(
            query="test",
            mode="standard",
            duration_ms=1000.0,
        )

        json_str = output.to_json()

        # Should be valid JSON
        parsed = json.loads(json_str)
        assert parsed["query"] == "test"
        assert parsed["mode"] == "standard"

    def test_save_to_file(self):
        """Test saving to file."""
        from olav.modes.shared.debug import DebugOutput

        output = DebugOutput(
            query="test",
            mode="standard",
        )

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            temp_path = Path(f.name)

        try:
            output.save(temp_path)

            # File should exist and contain valid JSON
            assert temp_path.exists()
            content = json.loads(temp_path.read_text())
            assert content["query"] == "test"
        finally:
            temp_path.unlink(missing_ok=True)

    def test_summary(self):
        """Test human-readable summary."""
        from olav.modes.shared.debug import (
            DebugOutput,
            LLMCallDetail,
            ToolCallDetail,
        )

        output = DebugOutput(
            query="test query",
            mode="standard",
            duration_ms=1500.0,
        )

        output.add_llm_call(LLMCallDetail(
            call_id="llm-001",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            duration_ms=800.0,
        ))

        output.add_tool_call(ToolCallDetail(
            tool_name="suzieq_query",
            duration_ms=500.0,
        ))

        summary = output.summary()

        assert "test query" in summary
        assert "standard" in summary
        assert "1500" in summary  # duration
        assert "LLM Calls: 1" in summary
        assert "Tool Calls: 1" in summary


class TestDebugContext:
    """Tests for DebugContext manager."""

    def test_context_disabled(self):
        """Test context when disabled."""
        from olav.modes.shared.debug import DebugContext

        with DebugContext(enabled=False) as ctx:
            ctx.log_llm_call("prompt", "response", 100, 50, 500.0)
            ctx.log_tool_call("tool", {}, "output", 100.0)

        # Should not record anything when disabled
        assert len(ctx.output.llm_calls) == 0
        assert len(ctx.output.tool_calls) == 0

    def test_context_enabled(self):
        """Test context when enabled."""
        from olav.modes.shared.debug import DebugContext

        with DebugContext(enabled=True, query="test", mode="standard") as ctx:
            ctx.log_llm_call("prompt", "response", 100, 50, 500.0)
            ctx.log_tool_call("tool", {"arg": "value"}, "output", 100.0)
            ctx.log_graph_state("node1", {"key": "value"})

        # Should record when enabled
        assert len(ctx.output.llm_calls) == 1
        assert len(ctx.output.tool_calls) == 1
        assert len(ctx.output.graph_states) == 1
        assert ctx.output.duration_ms > 0

    @pytest.mark.asyncio
    async def test_async_context(self):
        """Test async context manager."""
        from olav.modes.shared.debug import DebugContext

        async with DebugContext(enabled=True, query="async test") as ctx:
            ctx.log_llm_call("prompt", "response", 100, 50, 500.0)

        assert len(ctx.output.llm_calls) == 1
        assert ctx.output.query == "async test"

    def test_step_timing(self):
        """Test step timing."""
        import time

        from olav.modes.shared.debug import DebugContext

        with DebugContext(enabled=True) as ctx:
            ctx.start_step("step1")
            time.sleep(0.01)  # 10ms
            ctx.end_step("step1")

            ctx.start_step("step2")
            time.sleep(0.02)  # 20ms
            ctx.end_step("step2")

        # Should record step times
        assert "step1" in ctx.output.time_breakdown
        assert "step2" in ctx.output.time_breakdown
        assert ctx.output.time_breakdown["step1"] >= 10  # At least 10ms
        assert ctx.output.time_breakdown["step2"] >= 20  # At least 20ms

    def test_save_on_exit(self):
        """Test automatic save on context exit."""
        from olav.modes.shared.debug import DebugContext

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            temp_path = Path(f.name)

        try:
            with DebugContext(
                enabled=True,
                query="auto save test",
                output_path=temp_path,
            ) as ctx:
                ctx.log_llm_call("prompt", "response", 100, 50, 500.0)

            # File should be saved automatically
            assert temp_path.exists()
            content = json.loads(temp_path.read_text())
            assert content["query"] == "auto save test"
            assert len(content["llm_calls"]) == 1
        finally:
            temp_path.unlink(missing_ok=True)


class TestGlobalDebugContext:
    """Tests for global debug context management."""

    def test_get_set_context(self):
        """Test get/set global context."""
        from olav.modes.shared.debug import (
            DebugContext,
            get_debug_context,
            set_debug_context,
        )

        # Initially None
        assert get_debug_context() is None

        # Set context
        ctx = DebugContext(enabled=True)
        set_debug_context(ctx)

        assert get_debug_context() is ctx

        # Clean up
        set_debug_context(None)
        assert get_debug_context() is None


class TestThinkingModeCapture:
    """Tests for capturing Ollama thinking mode content."""

    def test_thinking_content_captured(self):
        """Test thinking content is captured."""
        from olav.modes.shared.debug import DebugContext

        with DebugContext(enabled=True) as ctx:
            ctx.log_llm_call(
                prompt="What is 2+2?",
                response="4",
                prompt_tokens=10,
                completion_tokens=5,
                duration_ms=100.0,
                model="qwen2.5:32b",
                thinking_content="Let me think... 2+2 equals 4.",
            )

        assert len(ctx.output.llm_calls) == 1
        call = ctx.output.llm_calls[0]

        assert call.thinking_content == "Let me think... 2+2 equals 4."
        assert call.thinking_tokens > 0
        assert call.model == "qwen2.5:32b"


# ============================================
# Integration Test
# ============================================
class TestDebugModeIntegration:
    """Integration tests with Standard Mode."""

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_debug_with_standard_mode(self):
        """Test Debug Mode captures Standard Mode execution."""
        try:
            from olav.modes.shared.debug import DebugContext, set_debug_context
            from olav.modes.standard import run_standard_mode
            from olav.tools.base import ToolRegistry
        except ImportError:
            pytest.skip("Standard Mode not available")

        registry = ToolRegistry()

        with DebugContext(
            enabled=True,
            query="查询 R1 BGP 状态",
            mode="standard",
        ) as ctx:
            set_debug_context(ctx)

            await run_standard_mode(
                query="查询 R1 BGP 状态",
                tool_registry=registry,
                yolo_mode=True,
            )

            set_debug_context(None)

        # Should capture execution details
        print("\n" + ctx.output.summary())

        # Duration should be recorded
        assert ctx.output.duration_ms > 0
