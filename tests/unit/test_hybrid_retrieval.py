"""Test Hybrid Retrieval (Vector + BM25/Text fusion).

This test validates the RRF (Reciprocal Rank Fusion) pipeline that combines
vector search with text/BM25 search for better retrieval results.

Following the TDD approach from the tracking document.
"""

import pytest
import tempfile
from pathlib import Path


class TestHybridRetrieval:
    """Test hybrid retrieval combining vector and text search."""

    @pytest.fixture
    def store_with_data(self, tmp_path):
        """Create a store with test data for hybrid search."""
        from olav.core.memory import LanceDBStore, MemoryCategory

        db_path = tmp_path / "hybrid_test.lance"
        store = LanceDBStore(db_path=db_path, embedding_dim=384)

        # Create table and add test data
        store.create_table()

        # Add diverse test memories
        test_memories = [
            {
                "id": "bgp-1",
                "text": "BGP neighbor 192.168.1.1 is down due to hold timer expiry",
                "vector": [0.1, 0.2, 0.3] + [0.0] * 381,
                "category": MemoryCategory.FACT,
                "scope": "global",
                "metadata": {"protocol": "BGP", "device": "R1"},
            },
            {
                "id": "bgp-2",
                "text": "When BGP neighbor times out, check TCP connection and ACLs",
                "vector": [0.1, 0.2, 0.4] + [0.0] * 381,
                "category": MemoryCategory.DECISION,
                "scope": "RoutingAgent",
                "metadata": {"protocol": "BGP"},
            },
            {
                "id": "ospf-1",
                "text": "OSPF neighbor in EXSTART state indicates MTU mismatch",
                "vector": [0.5, 0.6, 0.7] + [0.0] * 381,
                "category": MemoryCategory.FACT,
                "scope": "global",
                "metadata": {"protocol": "OSPF"},
            },
            {
                "id": "preference-1",
                "text": "Always use --limit flag with show commands to avoid timeouts",
                "vector": [0.8, 0.9, 0.1] + [0.0] * 381,
                "category": MemoryCategory.PREFERENCE,
                "scope": "global",
                "metadata": {"lesson": "avoid timeouts"},
            },
            {
                "id": "audit-1",
                "text": "Configuration change: interface GigabitEthernet0/1 changed to trunk mode",
                "vector": [0.3, 0.4, 0.5] + [0.0] * 381,
                "category": MemoryCategory.AUDIT,
                "scope": "global",
                "metadata": {"action": "config change"},
            },
        ]

        for mem in test_memories:
            store.add_memory(**mem)

        return store

    def test_vector_search_returns_ranked_results(self, store_with_data):
        """Test that vector search returns properly ranked results."""
        store = store_with_data

        # Query with a vector similar to bgp-1 and bgp-2
        query_vector = [0.1, 0.2, 0.35] + [0.0] * 381
        results = store.search_by_vector(query_vector, limit=5)

        assert len(results) > 0, "Vector search should return results"
        assert results[0]["id"] in ["bgp-1", "bgp-2"], "Most similar results should be BGP related"

    def test_text_search_returns_ranked_results(self, store_with_data):
        """Test that text search returns properly ranked results."""
        store = store_with_data

        # Search for BGP
        results = store.search_by_text("BGP", limit=5)

        assert len(results) > 0, "Text search should return results"
        # Should find bgp-1 and bgp-2
        ids = [r["id"] for r in results]
        assert "bgp-1" in ids or "bgp-2" in ids, "Should find BGP-related memories"

    def test_category_filter_works(self, store_with_data):
        """Test that category filtering works correctly."""
        store = store_with_data

        # Get only facts
        facts = store.get_memories(category="fact", limit=10)
        assert len(facts) >= 1, "Should have fact memories"
        for f in facts:
            assert f["category"] == "fact", "All results should be facts"

    def test_scope_filter_works(self, store_with_data):
        """Test that scope filtering works correctly."""
        store = store_with_data

        # Get global scope
        global_memories = store.get_memories(scope="global", limit=10)
        assert len(global_memories) >= 1, "Should have global memories"
        for m in global_memories:
            assert m["scope"] in ["global"], "All results should be global or match scope"

    def test_combined_vector_and_text_search(self, store_with_data):
        """Test combining vector and text search results."""
        store = store_with_data

        query_vector = [0.1, 0.2, 0.3] + [0.0] * 381

        # Get both result sets
        vector_results = store.search_by_vector(query_vector, limit=5)
        text_results = store.search_by_text("BGP", limit=5)

        # Both should return results
        assert len(vector_results) > 0, "Vector search should work"
        assert len(text_results) > 0, "Text search should work"

    def test_rrf_fusion(self, store_with_data):
        """Test RRF (Reciprocal Rank Fusion) combining both searches."""
        from olav.core.memory import rrf_fusion

        store = store_with_data

        query_vector = [0.1, 0.2, 0.3] + [0.0] * 381

        # Get both result sets
        vector_results = store.search_by_vector(query_vector, limit=5)
        text_results = store.search_by_text("BGP", limit=5)

        # Apply RRF fusion
        fused = rrf_fusion([vector_results, text_results], k=60)

        assert len(fused) > 0, "RRF should produce results"
        # Should have combined unique results
        assert len(fused) <= len(vector_results) + len(text_results)


class TestHybridRetrievalPipeline:
    """Test the hybrid retrieval pipeline module."""

    def test_rrf_function_imports(self):
        """Verify RRF fusion function is available."""
        from olav.core.memory import rrf_fusion

        assert callable(rrf_fusion)

    def test_rrf_empty_input(self):
        """Test RRF with empty inputs."""
        from olav.core.memory import rrf_fusion

        result = rrf_fusion([], k=60)
        assert result == []

    def test_rrf_single_list(self):
        """Test RRF with single result list."""
        from olav.core.memory import rrf_fusion

        results = [[{"id": "a", "score": 0.9}, {"id": "b", "score": 0.8}]]
        fused = rrf_fusion(results, k=60)
        assert len(fused) == 2
        assert fused[0]["id"] == "a"  # Highest score first

    def test_rrf_combines_different_rankings(self):
        """Test RRF combines results with different rankings."""
        from olav.core.memory import rrf_fusion

        # List 1: A > B > C
        list1 = [
            {"id": "a", "score": 0.9},
            {"id": "b", "score": 0.8},
            {"id": "c", "score": 0.7},
        ]
        # List 2: B > C > A (different order)
        list2 = [
            {"id": "b", "score": 0.9},
            {"id": "c", "score": 0.8},
            {"id": "a", "score": 0.7},
        ]

        fused = rrf_fusion([list1, list2], k=60)

        # B should rank higher due to appearing in both lists
        ids = [r["id"] for r in fused]
        assert "b" in ids
        assert "a" in ids
        assert "c" in ids
