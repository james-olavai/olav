"""
Unit tests for StrategySelector.

Tests rule-based selection, LLM fallback, and confidence scoring.
"""

import pytest
from typing import Dict, Any
from unittest.mock import AsyncMock, MagicMock

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage

from olav.strategies.selector import (
    StrategySelector,
    StrategyDecision,
    create_strategy_selector
)
from olav.strategies.fast_path import FastPathStrategy
from olav.strategies.deep_path import DeepPathStrategy
from olav.strategies.batch_path import BatchPathStrategy


# Test fixtures

@pytest.fixture
def mock_llm():
    """Create mock LLM for strategy classification."""
    llm = MagicMock(spec=BaseChatModel)
    
    # Default ainvoke returns fast_path decision
    async def ainvoke(messages):
        return AIMessage(content="""{
            "strategy": "fast_path",
            "confidence": 0.85,
            "reasoning": "Simple status query",
            "fallback": "deep_path"
        }""")
    
    llm.ainvoke = AsyncMock(side_effect=ainvoke)
    
    return llm


@pytest.fixture
def selector_with_llm(mock_llm):
    """Create StrategySelector with LLM."""
    return StrategySelector(llm=mock_llm, use_llm_fallback=True)


@pytest.fixture
def selector_no_llm():
    """Create StrategySelector without LLM."""
    return StrategySelector(llm=None, use_llm_fallback=False)


# Initialization tests

def test_selector_initialization_with_llm(mock_llm):
    """Test StrategySelector initializes with LLM."""
    selector = StrategySelector(llm=mock_llm, use_llm_fallback=True)
    
    assert selector.llm == mock_llm
    assert selector.use_llm_fallback is True
    assert selector.confidence_threshold == 0.8


def test_selector_initialization_no_llm():
    """Test StrategySelector initializes without LLM."""
    selector = StrategySelector(llm=None, use_llm_fallback=False)
    
    assert selector.llm is None
    assert selector.use_llm_fallback is False


def test_factory_function(mock_llm):
    """Test create_strategy_selector factory."""
    selector = create_strategy_selector(llm=mock_llm, use_llm_fallback=True)
    
    assert isinstance(selector, StrategySelector)
    assert selector.use_llm_fallback is True


# Rule-based selection tests - Batch Path

def test_rule_batch_chinese_keywords(selector_no_llm):
    """Test batch path selection with Chinese keywords."""
    decision = selector_no_llm._rule_based_selection("批量检查所有路由器的 BGP 状态")
    
    assert decision.strategy == "batch_path"
    assert decision.confidence >= 0.7
    assert "batch" in decision.reasoning.lower()
    assert decision.fallback == "fast_path"


def test_rule_batch_english_keywords(selector_no_llm):
    """Test batch path selection with English keywords."""
    decision = selector_no_llm._rule_based_selection("Audit all devices for compliance")
    
    assert decision.strategy == "batch_path"
    assert decision.confidence >= 0.7


def test_rule_batch_health_check(selector_no_llm):
    """Test batch path for health check queries."""
    decision = selector_no_llm._rule_based_selection("健康检查所有交换机")
    
    assert decision.strategy == "batch_path"
    assert decision.confidence >= 0.7


def test_rule_batch_multiple_keywords(selector_no_llm):
    """Test batch path with multiple batch keywords (higher confidence)."""
    decision = selector_no_llm._rule_based_selection(
        "批量审计所有设备的合规性检查"
    )
    
    assert decision.strategy == "batch_path"
    assert decision.confidence >= 0.8  # Multiple keywords = higher confidence


# Rule-based selection tests - Deep Path

def test_rule_deep_why_question(selector_no_llm):
    """Test deep path selection for 'why' questions."""
    decision = selector_no_llm._rule_based_selection("为什么 R1 无法建立 BGP 邻居？")
    
    assert decision.strategy == "deep_path"
    assert decision.confidence >= 0.7
    assert "diagnostic" in decision.reasoning.lower()
    assert decision.fallback == "fast_path"


def test_rule_deep_troubleshoot(selector_no_llm):
    """Test deep path for troubleshooting queries."""
    decision = selector_no_llm._rule_based_selection("Troubleshoot packet loss on interface")
    
    assert decision.strategy == "deep_path"
    assert decision.confidence >= 0.7


def test_rule_deep_diagnose(selector_no_llm):
    """Test deep path for diagnostic queries."""
    decision = selector_no_llm._rule_based_selection("诊断路由异常问题")
    
    assert decision.strategy == "deep_path"
    assert decision.confidence >= 0.7


def test_rule_deep_root_cause(selector_no_llm):
    """Test deep path for root cause analysis."""
    decision = selector_no_llm._rule_based_selection("Analyze root cause of network outage")
    
    assert decision.strategy == "deep_path"
    assert decision.confidence >= 0.7


# Rule-based selection tests - Fast Path

def test_rule_fast_simple_query(selector_no_llm):
    """Test fast path for simple status queries."""
    decision = selector_no_llm._rule_based_selection("查询 R1 的 BGP 状态")
    
    assert decision.strategy == "fast_path"
    assert decision.confidence >= 0.6
    assert decision.fallback == "deep_path"


def test_rule_fast_show_command(selector_no_llm):
    """Test fast path for show commands."""
    decision = selector_no_llm._rule_based_selection("Show interfaces on Switch-A")
    
    assert decision.strategy == "fast_path"
    assert decision.confidence >= 0.6


def test_rule_fast_list_query(selector_no_llm):
    """Test fast path for list queries."""
    decision = selector_no_llm._rule_based_selection("列出所有 VLAN")
    
    assert decision.strategy == "fast_path"
    assert decision.confidence >= 0.6


def test_rule_fast_get_query(selector_no_llm):
    """Test fast path for get/retrieve queries."""
    decision = selector_no_llm._rule_based_selection("获取设备配置")
    
    assert decision.strategy == "fast_path"
    assert decision.confidence >= 0.6


def test_rule_fast_ambiguous_low_confidence(selector_no_llm):
    """Test fast path default with low confidence for ambiguous queries."""
    decision = selector_no_llm._rule_based_selection("网络情况如何？")
    
    assert decision.strategy == "fast_path"
    assert decision.confidence < 0.7  # Low confidence for ambiguous query
    assert decision.fallback == "deep_path"


# Priority tests (batch > deep > fast)

def test_rule_priority_batch_over_deep(selector_no_llm):
    """Test batch path has priority over deep path."""
    # Query contains both batch and diagnostic keywords
    decision = selector_no_llm._rule_based_selection("批量诊断所有路由器")
    
    # Batch should win (higher priority)
    assert decision.strategy == "batch_path"


def test_rule_priority_deep_over_fast(selector_no_llm):
    """Test deep path has priority over fast path."""
    # Query contains both diagnostic and show keywords
    decision = selector_no_llm._rule_based_selection("为什么显示这个状态？")
    
    # Deep should win (higher priority)
    assert decision.strategy == "deep_path"


# LLM-based selection tests

@pytest.mark.asyncio
async def test_llm_selection_high_confidence_skips_llm(selector_with_llm):
    """Test high confidence rule selection skips LLM."""
    decision = await selector_with_llm.select("批量检查所有设备")
    
    # Should use rule-based only (high confidence)
    assert decision.strategy == "batch_path"
    
    # LLM should not be called
    assert selector_with_llm.llm.ainvoke.call_count == 0


@pytest.mark.asyncio
async def test_llm_selection_low_confidence_uses_llm(selector_with_llm):
    """Test low confidence triggers LLM classification."""
    # Mock LLM to return deep_path
    async def deep_response(messages):
        return AIMessage(content="""{
            "strategy": "deep_path",
            "confidence": 0.9,
            "reasoning": "Complex analysis required",
            "fallback": "fast_path"
        }""")
    
    selector_with_llm.llm.ainvoke = AsyncMock(side_effect=deep_response)
    
    # Ambiguous query with low rule confidence
    decision = await selector_with_llm.select("网络有问题")
    
    # Should use LLM classification
    assert selector_with_llm.llm.ainvoke.call_count == 1
    assert decision.strategy == "deep_path"
    assert decision.confidence == 0.9


@pytest.mark.asyncio
async def test_llm_selection_parse_error_fallback(selector_with_llm):
    """Test LLM parse error falls back to rule decision."""
    # Mock LLM to return invalid JSON
    async def invalid_response(messages):
        return AIMessage(content="This is not valid JSON")
    
    selector_with_llm.llm.ainvoke = AsyncMock(side_effect=invalid_response)
    
    decision = await selector_with_llm.select("网络状态如何")
    
    # Should fall back to rule-based decision
    assert decision.strategy == "fast_path"


@pytest.mark.asyncio
async def test_llm_selection_disabled(selector_no_llm):
    """Test LLM disabled returns rule decision even with low confidence."""
    decision = await selector_no_llm.select("网络问题")
    
    # Should use rule-based only (no LLM available)
    assert decision.strategy == "fast_path"
    assert decision.confidence < 0.8  # Low confidence but no LLM


# Synchronous selection tests

def test_select_sync(selector_no_llm):
    """Test synchronous selection method."""
    decision = selector_no_llm.select_sync("查询 BGP 状态")
    
    assert isinstance(decision, StrategyDecision)
    assert decision.strategy == "fast_path"


# Strategy class mapping tests

def test_get_strategy_class_fast():
    """Test getting FastPathStrategy class."""
    cls = StrategySelector.get_strategy_class("fast_path")
    
    assert cls == FastPathStrategy


def test_get_strategy_class_deep():
    """Test getting DeepPathStrategy class."""
    cls = StrategySelector.get_strategy_class("deep_path")
    
    assert cls == DeepPathStrategy


def test_get_strategy_class_batch():
    """Test getting BatchPathStrategy class."""
    cls = StrategySelector.get_strategy_class("batch_path")
    
    assert cls == BatchPathStrategy


# Integration tests

@pytest.mark.asyncio
async def test_full_selection_flow_batch(selector_with_llm):
    """Test complete selection flow for batch query."""
    query = "批量审计所有路由器 BGP 配置"
    decision = await selector_with_llm.select(query)
    
    # Should select batch path with high confidence
    assert decision.strategy == "batch_path"
    assert decision.confidence >= 0.7
    assert decision.fallback is not None
    
    # Get strategy class
    strategy_cls = StrategySelector.get_strategy_class(decision.strategy)
    assert strategy_cls == BatchPathStrategy


@pytest.mark.asyncio
async def test_full_selection_flow_deep(selector_with_llm):
    """Test complete selection flow for diagnostic query."""
    query = "为什么 R1 BGP 邻居无法建立？"
    decision = await selector_with_llm.select(query)
    
    # Should select deep path (rule-based has high confidence for "why" questions)
    assert decision.strategy == "deep_path"
    assert decision.confidence >= 0.7
    
    # Get strategy class
    strategy_cls = StrategySelector.get_strategy_class(decision.strategy)
    assert strategy_cls == DeepPathStrategy
    
    # LLM should not be called (high rule confidence)
    assert selector_with_llm.llm.ainvoke.call_count == 0


@pytest.mark.asyncio
async def test_full_selection_flow_fast(selector_with_llm):
    """Test complete selection flow for simple query."""
    query = "查询 R1 接口状态"
    decision = await selector_with_llm.select(query)
    
    # Should select fast path
    assert decision.strategy == "fast_path"
    assert decision.confidence >= 0.6
    
    # Get strategy class
    strategy_cls = StrategySelector.get_strategy_class(decision.strategy)
    assert strategy_cls == FastPathStrategy


# Edge case tests

def test_empty_query(selector_no_llm):
    """Test selection with empty query."""
    decision = selector_no_llm._rule_based_selection("")
    
    # Should default to fast path with low confidence
    assert decision.strategy == "fast_path"
    assert decision.confidence < 0.7


def test_very_long_query(selector_no_llm):
    """Test selection with very long query."""
    long_query = "查询 " + "BGP " * 100 + "状态"
    decision = selector_no_llm._rule_based_selection(long_query)
    
    # Should still work
    assert decision.strategy == "fast_path"


def test_mixed_language_query(selector_no_llm):
    """Test selection with mixed Chinese and English."""
    decision = selector_no_llm._rule_based_selection("批量 audit all routers")
    
    # Should detect batch keywords in both languages
    assert decision.strategy == "batch_path"


def test_case_insensitive_matching(selector_no_llm):
    """Test keyword matching is case-insensitive."""
    decision1 = selector_no_llm._rule_based_selection("TROUBLESHOOT network issue")
    decision2 = selector_no_llm._rule_based_selection("troubleshoot network issue")
    
    assert decision1.strategy == decision2.strategy == "deep_path"
