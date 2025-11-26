"""Tests for StrategyExecutor."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from olav.strategies.executor import (
    ExecutionResult,
    StrategyExecutor,
    execute_with_strategy_selection,
)
from olav.strategies.selector import StrategyDecision


@pytest.fixture
def mock_llm():
    """Create a mock LLM."""
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock(content="mock response"))
    return llm


@pytest.fixture
def mock_fast_path():
    """Create a mock FastPathStrategy."""
    with patch("olav.strategies.executor.FastPathStrategy") as mock:
        instance = MagicMock()
        instance.execute = AsyncMock(return_value={
            "success": True,
            "answer": "BGP has 2 established peers",
            "tool_output": {"tool_name": "suzieq_query"},
            "metadata": {"execution_time_ms": 150, "confidence": 0.95},
        })
        mock.return_value = instance
        yield mock


@pytest.fixture
def mock_deep_path():
    """Create a mock DeepPathStrategy."""
    with patch("olav.strategies.executor.DeepPathStrategy") as mock:
        instance = MagicMock()
        instance.execute = AsyncMock(return_value={
            "success": True,
            "conclusion": "BGP is down due to misconfigured peer IP",
            "reasoning_trace": [
                {"step": 1, "tool": "suzieq_query", "interpretation": "BGP not established"},
                {"step": 2, "tool": "netconf_tool", "interpretation": "Wrong peer IP"},
            ],
            "hypotheses_tested": [{"description": "Wrong peer IP", "confidence": 0.9}],
            "confidence": 0.92,
            "metadata": {"iterations": 2},
        })
        mock.return_value = instance
        yield mock


@pytest.fixture
def mock_batch_path():
    """Create a mock BatchPathStrategy."""
    with patch("olav.strategies.executor.BatchPathStrategy") as mock:
        instance = MagicMock()
        summary = MagicMock()
        summary.summary_text = "3/5 devices passed"
        summary.total_devices = 5
        summary.passed = 3
        summary.failed = 2
        
        result = MagicMock()
        result.config_name = "bgp_audit"
        result.summary = summary
        result.violations = ["Device R3: BGP peer count < 2"]
        
        instance.execute = AsyncMock(return_value=result)
        mock.return_value = instance
        yield mock


class TestExecutionResult:
    """Tests for ExecutionResult model."""

    def test_success_result(self):
        """Test successful execution result."""
        result = ExecutionResult(
            success=True,
            strategy_used="fast_path",
            answer="BGP has 2 peers",
        )
        assert result.success is True
        assert result.strategy_used == "fast_path"
        assert result.answer == "BGP has 2 peers"
        assert result.fallback_required is False

    def test_failure_result_with_fallback(self):
        """Test failed result with fallback suggestion."""
        result = ExecutionResult(
            success=False,
            strategy_used="fast_path",
            error="Low confidence",
            fallback_required=True,
            fallback_strategy="deep_path",
        )
        assert result.success is False
        assert result.fallback_required is True
        assert result.fallback_strategy == "deep_path"

    def test_result_with_reasoning_trace(self):
        """Test result with reasoning trace (deep path)."""
        result = ExecutionResult(
            success=True,
            strategy_used="deep_path",
            answer="Root cause identified",
            reasoning_trace=[
                {"step": 1, "tool": "suzieq_query", "interpretation": "BGP down"},
            ],
        )
        assert len(result.reasoning_trace) == 1
        assert result.reasoning_trace[0]["tool"] == "suzieq_query"


class TestStrategyExecutor:
    """Tests for StrategyExecutor."""

    @pytest.mark.asyncio
    async def test_execute_fast_path_success(self, mock_llm, mock_fast_path, mock_deep_path, mock_batch_path):
        """Test successful fast path execution."""
        executor = StrategyExecutor(llm=mock_llm)
        decision = StrategyDecision(
            strategy="fast_path",
            confidence=0.95,
            reasoning="Simple query",
        )

        result = await executor.execute(
            user_query="查询 R1 BGP 状态",
            decision=decision,
        )

        assert result.success is True
        assert result.strategy_used == "fast_path"
        assert "BGP" in result.answer

    @pytest.mark.asyncio
    async def test_execute_deep_path_success(self, mock_llm, mock_fast_path, mock_deep_path, mock_batch_path):
        """Test successful deep path execution."""
        executor = StrategyExecutor(llm=mock_llm)
        decision = StrategyDecision(
            strategy="deep_path",
            confidence=0.85,
            reasoning="Diagnostic query",
        )

        result = await executor.execute(
            user_query="为什么 R1 BGP 无法建立？",
            decision=decision,
        )

        assert result.success is True
        assert result.strategy_used == "deep_path"
        assert result.reasoning_trace is not None
        assert len(result.reasoning_trace) == 2

    @pytest.mark.asyncio
    async def test_execute_batch_path_success(self, mock_llm, mock_fast_path, mock_deep_path, mock_batch_path):
        """Test successful batch path execution."""
        executor = StrategyExecutor(llm=mock_llm)
        decision = StrategyDecision(
            strategy="batch_path",
            confidence=0.9,
            reasoning="Batch audit query",
        )

        result = await executor.execute(
            user_query="审计所有路由器 BGP",
            decision=decision,
            batch_config_path="config/inspections/bgp_audit.yaml",
        )

        assert result.success is True
        assert result.strategy_used == "batch_path"
        assert "violations" in result.metadata

    @pytest.mark.asyncio
    async def test_auto_fallback_on_failure(self, mock_llm, mock_deep_path, mock_batch_path):
        """Test automatic fallback when primary strategy fails."""
        with patch("olav.strategies.executor.FastPathStrategy") as mock_fast:
            # Fast path fails
            fast_instance = MagicMock()
            fast_instance.execute = AsyncMock(return_value={
                "success": False,
                "reason": "low_confidence",
                "fallback_required": True,
            })
            mock_fast.return_value = fast_instance

            executor = StrategyExecutor(llm=mock_llm, auto_fallback=True)
            decision = StrategyDecision(
                strategy="fast_path",
                confidence=0.6,
                reasoning="Uncertain query",
                fallback="deep_path",
            )

            result = await executor.execute(
                user_query="分析 R1 网络问题",
                decision=decision,
            )

            # Should fallback to deep path
            assert result.success is True
            assert result.strategy_used == "deep_path"
            assert result.metadata.get("fallback_from") == "fast_path"

    @pytest.mark.asyncio
    async def test_batch_path_requires_config(self, mock_llm, mock_fast_path, mock_deep_path, mock_batch_path):
        """Test that batch path requires config path and falls back."""
        executor = StrategyExecutor(llm=mock_llm, auto_fallback=True)
        decision = StrategyDecision(
            strategy="batch_path",
            confidence=0.9,
            reasoning="Batch query",
            fallback="fast_path",
        )

        result = await executor.execute(
            user_query="审计所有设备",
            decision=decision,
            # No batch_config_path provided
        )

        # With auto_fallback=True, should fallback to fast_path
        assert result.success is True
        assert result.strategy_used == "fast_path"
        assert result.metadata.get("fallback_from") == "batch_path"

    @pytest.mark.asyncio
    async def test_batch_path_no_fallback(self, mock_llm, mock_fast_path, mock_deep_path, mock_batch_path):
        """Test that batch path without config fails when auto_fallback is disabled."""
        executor = StrategyExecutor(llm=mock_llm, auto_fallback=False)
        decision = StrategyDecision(
            strategy="batch_path",
            confidence=0.9,
            reasoning="Batch query",
            fallback="fast_path",
        )

        result = await executor.execute(
            user_query="审计所有设备",
            decision=decision,
        )

        # Without auto_fallback, should fail
        assert result.success is False
        assert result.error == "Batch path requires config_path"
        assert result.fallback_required is True


class TestExecuteWithStrategySelection:
    """Tests for execute_with_strategy_selection convenience function."""

    @pytest.mark.asyncio
    async def test_simple_query_uses_fast_path(self, mock_llm, mock_fast_path, mock_deep_path, mock_batch_path):
        """Test that simple queries use fast path."""
        with patch("olav.strategies.executor.StrategySelector") as mock_selector:
            selector_instance = MagicMock()
            selector_instance.select = AsyncMock(return_value=StrategyDecision(
                strategy="fast_path",
                confidence=0.9,
                reasoning="Simple status query",
            ))
            mock_selector.return_value = selector_instance

            result = await execute_with_strategy_selection(
                user_query="查询 R1 接口状态",
                llm=mock_llm,
            )

            assert result.success is True
            assert result.metadata["selection"]["strategy"] == "fast_path"

    @pytest.mark.asyncio
    async def test_diagnostic_query_uses_deep_path(self, mock_llm, mock_fast_path, mock_deep_path, mock_batch_path):
        """Test that diagnostic queries use deep path."""
        with patch("olav.strategies.executor.StrategySelector") as mock_selector:
            selector_instance = MagicMock()
            selector_instance.select = AsyncMock(return_value=StrategyDecision(
                strategy="deep_path",
                confidence=0.88,
                reasoning="Why question requires reasoning",
            ))
            mock_selector.return_value = selector_instance

            result = await execute_with_strategy_selection(
                user_query="为什么 OSPF 邻居不起来？",
                llm=mock_llm,
            )

            assert result.success is True
            assert result.metadata["selection"]["strategy"] == "deep_path"

    @pytest.mark.asyncio
    async def test_batch_query_uses_batch_path(self, mock_llm, mock_fast_path, mock_deep_path, mock_batch_path):
        """Test that batch queries use batch path."""
        with patch("olav.strategies.executor.StrategySelector") as mock_selector:
            selector_instance = MagicMock()
            selector_instance.select = AsyncMock(return_value=StrategyDecision(
                strategy="batch_path",
                confidence=0.92,
                reasoning="Multi-device audit",
            ))
            mock_selector.return_value = selector_instance

            result = await execute_with_strategy_selection(
                user_query="批量检查所有路由器 BGP",
                llm=mock_llm,
                batch_config_path="config/inspections/bgp_check.yaml",
            )

            assert result.success is True
            assert result.metadata["selection"]["strategy"] == "batch_path"
