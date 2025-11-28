"""
Tests for LLM Intent Classifier.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from olav.core.llm_intent_classifier import (
    IntentResult,
    LLMIntentClassifier,
    classify_intent_with_llm,
    get_classifier,
)


class TestIntentResult:
    """Tests for IntentResult model."""

    def test_valid_intent_result(self):
        """Test valid IntentResult creation."""
        result = IntentResult(
            category="suzieq",
            confidence=0.95,
            reasoning="Network query detected",
        )
        assert result.category == "suzieq"
        assert result.confidence == 0.95
        assert result.reasoning == "Network query detected"

    def test_confidence_bounds(self):
        """Test confidence must be between 0 and 1."""
        with pytest.raises(ValueError):
            IntentResult(category="suzieq", confidence=1.5, reasoning="test")

        with pytest.raises(ValueError):
            IntentResult(category="suzieq", confidence=-0.1, reasoning="test")

    def test_valid_categories(self):
        """Test all valid categories."""
        for category in ["suzieq", "netbox", "openconfig", "cli", "netconf"]:
            result = IntentResult(
                category=category,
                confidence=0.8,
                reasoning=f"Test {category}",
            )
            assert result.category == category

    def test_invalid_category(self):
        """Test invalid category raises error."""
        with pytest.raises(ValueError):
            IntentResult(category="invalid", confidence=0.8, reasoning="test")


class TestLLMIntentClassifier:
    """Tests for LLMIntentClassifier."""

    @pytest.fixture
    def mock_llm(self):
        """Create mock LLM."""
        llm = MagicMock()
        structured_llm = AsyncMock()
        llm.with_structured_output.return_value = structured_llm
        return llm, structured_llm

    def test_classifier_init(self, mock_llm):
        """Test classifier initialization."""
        llm, _ = mock_llm
        classifier = LLMIntentClassifier(llm=llm)
        assert classifier._llm == llm
        assert classifier.enable_cache is True

    def test_fallback_prompt(self):
        """Test fallback prompt generation."""
        classifier = LLMIntentClassifier()
        prompt = classifier._get_fallback_prompt()
        assert "suzieq" in prompt
        assert "netbox" in prompt
        assert "openconfig" in prompt

    @pytest.mark.asyncio
    async def test_classify_success(self, mock_llm):
        """Test successful classification."""
        llm, structured_llm = mock_llm
        expected = IntentResult(
            category="suzieq",
            confidence=0.95,
            reasoning="BGP query detected",
        )
        structured_llm.ainvoke.return_value = expected

        classifier = LLMIntentClassifier(llm=llm)
        result = await classifier.classify("查询 R1 BGP 状态")

        assert result.category == "suzieq"
        assert result.confidence == 0.95
        structured_llm.ainvoke.assert_called_once()

    @pytest.mark.asyncio
    async def test_classify_dict_response(self, mock_llm):
        """Test classification with dict response from LLM."""
        llm, structured_llm = mock_llm
        structured_llm.ainvoke.return_value = {
            "category": "netbox",
            "confidence": 0.8,
            "reasoning": "CMDB operation",
        }

        classifier = LLMIntentClassifier(llm=llm)
        result = await classifier.classify("添加设备到 NetBox")

        assert result.category == "netbox"
        assert result.confidence == 0.8

    @pytest.mark.asyncio
    async def test_classify_llm_failure_fallback(self, mock_llm):
        """Test fallback when LLM fails."""
        llm, structured_llm = mock_llm
        structured_llm.ainvoke.side_effect = Exception("LLM error")

        classifier = LLMIntentClassifier(llm=llm)
        result = await classifier.classify("查询接口状态")

        # Should use fallback (default to suzieq)
        assert result.category == "suzieq"
        assert result.confidence == 0.5

    def test_fallback_classify_netbox(self):
        """Test fallback classification for netbox."""
        classifier = LLMIntentClassifier()
        result = classifier._fallback_classify("在 netbox 添加设备")
        assert result.category == "netbox"

    def test_fallback_classify_netconf(self):
        """Test fallback classification for netconf."""
        classifier = LLMIntentClassifier()
        result = classifier._fallback_classify("使用 netconf rpc 获取配置")
        assert result.category == "netconf"

    def test_fallback_classify_openconfig(self):
        """Test fallback classification for openconfig."""
        classifier = LLMIntentClassifier()
        result = classifier._fallback_classify("查询 openconfig yang 路径")
        assert result.category == "openconfig"

    def test_fallback_classify_cli(self):
        """Test fallback classification for cli."""
        classifier = LLMIntentClassifier()
        result = classifier._fallback_classify("通过 ssh 执行命令")
        assert result.category == "cli"

    def test_fallback_classify_default(self):
        """Test fallback classification default."""
        classifier = LLMIntentClassifier()
        result = classifier._fallback_classify("检查网络状态")
        assert result.category == "suzieq"
        assert result.confidence == 0.5


class TestConvenienceFunctions:
    """Tests for convenience functions."""

    def test_get_classifier_singleton(self):
        """Test get_classifier returns singleton."""
        # Reset global
        import olav.core.llm_intent_classifier as module
        module._classifier = None

        c1 = get_classifier()
        c2 = get_classifier()
        assert c1 is c2

    @pytest.mark.asyncio
    async def test_classify_intent_with_llm(self):
        """Test classify_intent_with_llm function."""
        with patch.object(
            LLMIntentClassifier,
            "classify",
            new_callable=AsyncMock,
            return_value=IntentResult(
                category="suzieq",
                confidence=0.9,
                reasoning="Test",
            ),
        ):
            category, confidence = await classify_intent_with_llm("test query")
            assert category == "suzieq"
            assert confidence == 0.9
