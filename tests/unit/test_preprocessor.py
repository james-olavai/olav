"""
Unit tests for QueryPreprocessor - Fast Path for Network Queries.

Tests cover:
1. Intent classification (diagnostic vs query)
2. Device name extraction
3. Fast path pattern matching
4. Integration with UnifiedClassifier
"""

import pytest

from olav.modes.shared.preprocessor import (
    DIAGNOSTIC_KEYWORDS,
    QUERY_KEYWORDS,
    QueryPreprocessor,
)


class TestIntentClassification:
    """Test intent type classification."""

    @pytest.fixture
    def preprocessor(self):
        return QueryPreprocessor()

    @pytest.mark.parametrize(
        ("query", "expected_intent"),
        [
            # Query intent (Standard Mode)
            ("query R1 BGP status", "query"),
            ("show all interfaces", "query"),
            ("list devices", "query"),
            ("show BGP neighbors on R1", "query"),
            ("get interface status", "query"),
            ("check routing table", "query"),

            # Diagnostic intent (Expert Mode)
            ("why is BGP down between R1 and R2", "diagnostic"),
            ("diagnose spine-1 connectivity issue", "diagnostic"),
            ("analyze high network latency", "diagnostic"),
            ("troubleshoot OSPF neighbor failure", "diagnostic"),
            ("Why is BGP down between R1 and R2", "diagnostic"),
            ("troubleshoot connectivity issue", "diagnostic"),

            # Network terms default to query
            ("R1 BGP", "query"),
            ("spine-1 OSPF", "query"),
        ],
    )
    def test_intent_classification(self, preprocessor, query, expected_intent):
        """Test that intent is correctly classified."""
        result = preprocessor.process(query)
        assert result.intent_type == expected_intent, f"Query: {query}"


class TestDeviceExtraction:
    """Test device name extraction."""

    @pytest.fixture
    def preprocessor(self):
        return QueryPreprocessor()

    @pytest.mark.parametrize(
        ("query", "expected_devices"),
        [
            # English patterns
            ("query R1 BGP status", ["R1"]),
            ("device spine-1 interface", ["spine-1"]),
            ("show BGP on R1", ["R1"]),
            ("device core-rtr interface status", ["core-rtr"]),

            # Multiple devices (future support)
            # ("between R1 and R2", ["R1", "R2"]),

            # No device
            ("list all devices", []),
            ("show all interfaces status", []),
        ],
    )
    def test_device_extraction(self, preprocessor, query, expected_devices):
        """Test that device names are correctly extracted."""
        result = preprocessor.process(query)
        assert set(result.devices) == set(expected_devices), f"Query: {query}"


class TestFastPathMatching:
    """Test fast path regex pattern matching."""

    @pytest.fixture
    def preprocessor(self):
        return QueryPreprocessor()

    @pytest.mark.parametrize(
        ("query", "expected_tool", "expected_table"),
        [
            # BGP queries
            ("query R1 BGP status", "suzieq_query", "bgp"),
            ("show R1 BGP neighbor", "suzieq_query", "bgp"),
            ("show BGP on R1", "suzieq_query", "bgp"),

            # Interface queries
            ("query R1 interface status", "suzieq_query", "interface"),
            ("show all interfaces", "suzieq_query", "interface"),

            # Route queries
            ("check spine-1 routing table", "suzieq_query", "routes"),
            ("query R1 routes", "suzieq_query", "routes"),

            # OSPF queries
            ("query R1 OSPF neighbor", "suzieq_query", "ospf"),

            # Device list (NetBox)
            ("list all devices", "netbox_api_call", None),
            ("show devices", "netbox_api_call", None),

            # VLAN queries
            ("query R1 VLAN", "suzieq_query", "vlan"),

            # LLDP queries
            ("show R1 LLDP neighbor", "suzieq_query", "lldp"),
        ],
    )
    def test_fast_path_matching(self, preprocessor, query, expected_tool, expected_table):
        """Test that fast path patterns match correctly."""
        result = preprocessor.process(query)

        assert result.can_use_fast_path, f"Query should match fast path: {query}"
        assert result.fast_path_match is not None
        assert result.fast_path_match.tool == expected_tool, f"Query: {query}"

        if expected_table:
            assert result.fast_path_match.parameters.get("table") == expected_table

    @pytest.mark.parametrize(
        "query",
        [
            # Diagnostic queries should not use fast path
            "why is R1 BGP down",
            "diagnose connectivity issue",
            "analyze network fault",

            # Complex queries may not match
            "compare R1 and R2 BGP config",
            "calculate interface utilization for all devices",
        ],
    )
    def test_fast_path_not_matching(self, preprocessor, query):
        """Test that diagnostic/complex queries don't use fast path."""
        result = preprocessor.process(query)
        assert not result.can_use_fast_path, f"Query should NOT match fast path: {query}"


class TestHostnameInParameters:
    """Test that hostname is correctly added to parameters."""

    @pytest.fixture
    def preprocessor(self):
        return QueryPreprocessor()

    def test_hostname_in_bgp_query(self, preprocessor):
        """Test hostname extraction in BGP query."""
        result = preprocessor.process("query R1 BGP status")

        assert result.can_use_fast_path
        assert result.fast_path_match.parameters.get("hostname") == "R1"
        assert result.fast_path_match.parameters.get("table") == "bgp"

    def test_no_hostname_in_list_query(self, preprocessor):
        """Test no hostname in device list query."""
        result = preprocessor.process("list all devices")

        assert result.can_use_fast_path
        assert "hostname" not in result.fast_path_match.parameters


class TestPreprocessorIntegration:
    """Test preprocessor integration with classifier."""

    @pytest.mark.asyncio
    async def test_fast_path_in_classifier(self):
        """Test that classifier uses fast path when available."""
        from olav.core.unified_classifier import UnifiedClassifier

        classifier = UnifiedClassifier()

        # This should hit fast path (no LLM call)
        result = await classifier.classify("query R1 BGP status")

        # Check result
        assert result.tool == "suzieq_query"
        assert result.parameters.get("table") == "bgp"

        # Check that it was fast path (LLM time should be 0)
        if hasattr(result, "_fast_path"):
            assert result._fast_path is True
        if hasattr(result, "_llm_time_ms"):
            assert result._llm_time_ms == 0.0

    @pytest.mark.asyncio
    async def test_skip_fast_path_flag(self):
        """Test that skip_fast_path forces LLM classification."""
        from olav.core.unified_classifier import UnifiedClassifier

        classifier = UnifiedClassifier()

        # Force LLM path
        result = await classifier.classify(
            "query R1 BGP status",
            skip_fast_path=True,
        )

        # Should still work, but via LLM
        assert result.tool in ["suzieq_query", "suzieq_schema_search"]

        # LLM time should be > 0 (if attribute exists)
        if hasattr(result, "_llm_time_ms") and hasattr(result, "_fast_path"):
            # If _fast_path is not set, it went through LLM
            assert not getattr(result, "_fast_path", False)


class TestKeywordSets:
    """Test keyword set definitions."""

    def test_diagnostic_keywords_frozenset(self):
        """Ensure diagnostic keywords is immutable."""
        assert isinstance(DIAGNOSTIC_KEYWORDS, frozenset)
        assert "why" in DIAGNOSTIC_KEYWORDS
        assert "diagnose" in DIAGNOSTIC_KEYWORDS

    def test_query_keywords_frozenset(self):
        """Ensure query keywords is immutable."""
        assert isinstance(QUERY_KEYWORDS, frozenset)
        assert "query" in QUERY_KEYWORDS
        assert "show" in QUERY_KEYWORDS

    def test_no_overlap(self):
        """Ensure no overlap between diagnostic and query keywords."""
        overlap = DIAGNOSTIC_KEYWORDS & QUERY_KEYWORDS
        assert len(overlap) == 0, f"Overlapping keywords: {overlap}"
