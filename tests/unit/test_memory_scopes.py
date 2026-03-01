"""Test Memory Scope Isolation.

This test validates that memory scope isolation works correctly:
- Agent A cannot read Agent B's private memory
- Global memories are accessible to all agents
- Scope filtering at query time works correctly

Following the TDD approach from the tracking document.
"""

import pytest
import tempfile
from pathlib import Path


class TestMemoryScopes:
    """Test memory scope isolation functionality."""

    @pytest.fixture
    def store_with_scoped_memories(self, tmp_path):
        """Create a store with different scope memories."""
        from olav.core.memory import LanceDBStore

        db_path = tmp_path / "scopes_test.lance"
        store = LanceDBStore(db_path=db_path, embedding_dim=384)
        store.create_table()

        # Add global memories
        store.add_memory(
            id="global-1",
            text="Global knowledge: BGP uses port 179",
            vector=[0.1] * 384,
            category="fact",
            scope="global",
        )
        store.add_memory(
            id="global-2",
            text="Global preference: always save config before reboot",
            vector=[0.1] * 384,
            category="preference",
            scope="global",
        )

        # Add Agent-specific memories
        store.add_memory(
            id="routing-1",
            text="RoutingAgent learned: BGP neighbors in EXSTART need MTU check",
            vector=[0.2] * 384,
            category="fact",
            scope="RoutingAgent",
        )
        store.add_memory(
            id="routing-2",
            text="RoutingAgent preference: use 'show bgp summary' first",
            vector=[0.2] * 384,
            category="preference",
            scope="RoutingAgent",
        )

        store.add_memory(
            id="config-1",
            text="ConfigAgent learned: Cisco devices need 'write mem'",
            vector=[0.3] * 384,
            category="fact",
            scope="ConfigAgent",
        )
        store.add_memory(
            id="config-2",
            text="ConfigAgent preference: backup before changes",
            vector=[0.3] * 384,
            category="preference",
            scope="ConfigAgent",
        )

        return store

    def test_global_scope_includes_global_only(self, store_with_scoped_memories):
        """Test that querying with 'global' scope returns only global memories."""
        store = store_with_scoped_memories

        results = store.get_memories(scope="global")

        # Should return global memories
        assert len(results) >= 2, "Should have global memories"
        scopes = set(r["scope"] for r in results)
        assert "global" in scopes, "Should include global scope"

    def test_agent_scope_includes_global_and_agent(self, store_with_scoped_memories):
        """Test that querying with agent scope returns global + agent memories."""
        store = store_with_scoped_memories

        # Query as RoutingAgent
        routing_results = store.get_memories(scope="RoutingAgent")

        # Should include both global and RoutingAgent
        scopes = set(r["scope"] for r in routing_results)
        assert "global" in scopes, "Should include global memories"
        assert "RoutingAgent" in scopes, "Should include RoutingAgent memories"

    def test_different_agents_have_isolated_memory(self, store_with_scoped_memories):
        """Test that Agent A cannot see Agent B's private memories."""
        store = store_with_scoped_memories

        # Query as RoutingAgent
        routing_results = store.get_memories(scope="RoutingAgent")
        routing_ids = {r["id"] for r in routing_results}

        # Query as ConfigAgent
        config_results = store.get_memories(scope="ConfigAgent")
        config_ids = {r["id"] for r in config_results}

        # Verify isolation
        # RoutingAgent should NOT see ConfigAgent's private memories
        assert "config-1" not in routing_ids, "RoutingAgent should not see ConfigAgent private"
        assert "config-2" not in routing_ids, "RoutingAgent should not see ConfigAgent preference"

        # ConfigAgent should NOT see RoutingAgent's private memories
        assert "routing-1" not in config_ids, "ConfigAgent should not see RoutingAgent private"
        assert "routing-2" not in config_ids, "ConfigAgent should not see RoutingAgent preference"

        # Both should see global
        assert "global-1" in routing_ids, "Both should see global-1"
        assert "global-1" in config_ids, "Both should see global-1"

    def test_category_filtering_with_scope(self, store_with_scoped_memories):
        """Test filtering by category AND scope together."""
        store = store_with_scoped_memories

        # Get only facts for RoutingAgent
        facts = store.get_memories(scope="RoutingAgent", category="fact")

        # Should have RoutingAgent fact
        assert len(facts) >= 1
        for f in facts:
            assert f["category"] == "fact"
            assert f["scope"] in ["global", "RoutingAgent"]

    def test_scope_isolation_in_vector_search(self, store_with_scoped_memories):
        """Test that vector search respects scope isolation."""
        store = store_with_scoped_memories

        # Search with RoutingAgent scope
        query_vector = [0.2] * 384  # Similar to RoutingAgent vectors
        results = store.search_by_vector(query_vector, limit=10, scope="RoutingAgent")

        # Should not return ConfigAgent private memories
        ids = {r["id"] for r in results}
        assert "config-1" not in ids, "Should not see ConfigAgent memory"
        assert "config-2" not in ids, "Should not see ConfigAgent preference"

    def test_scope_isolation_in_text_search(self, store_with_scoped_memories):
        """Test that text search respects scope isolation."""
        store = store_with_scoped_memories

        # Search with RoutingAgent scope
        results = store.search_by_text("BGP", limit=10, scope="RoutingAgent")

        # Should only return global memories (no agent-specific for BGP)
        for r in results:
            assert r["scope"] in ["global", "RoutingAgent"]


class TestMemoryCategories:
    """Test memory categorization (Fact/Decision/Preference/Audit)."""

    @pytest.fixture
    def store_with_categories(self, tmp_path):
        """Create a store with different category memories."""
        from olav.core.memory import LanceDBStore, MemoryCategory

        db_path = tmp_path / "categories_test.lance"
        store = LanceDBStore(db_path=db_path, embedding_dim=384)
        store.create_table()

        # Add different categories
        store.add_memory(
            id="fact-1",
            text="BGP neighbor 192.168.1.1 is down",
            vector=[0.1] * 384,
            category=MemoryCategory.FACT,
            scope="global",
        )
        store.add_memory(
            id="decision-1",
            text="Decision: restart BGP process to recover",
            vector=[0.2] * 384,
            category=MemoryCategory.DECISION,
            scope="global",
        )
        store.add_memory(
            id="preference-1",
            text="Preference: use --limit with show commands",
            vector=[0.3] * 384,
            category=MemoryCategory.PREFERENCE,
            scope="global",
        )
        store.add_memory(
            id="audit-1",
            text="Audit: interface GigabitEthernet0/1 changed to trunk",
            vector=[0.4] * 384,
            category=MemoryCategory.AUDIT,
            scope="global",
        )

        return store

    def test_get_memories_by_category(self, store_with_categories):
        """Test filtering memories by category."""
        store = store_with_categories

        facts = store.get_memories(category="fact")
        decisions = store.get_memories(category="decision")
        preferences = store.get_memories(category="preference")
        audits = store.get_memories(category="audit")

        assert len(facts) >= 1
        assert len(decisions) >= 1
        assert len(preferences) >= 1
        assert len(audits) >= 1

        for f in facts:
            assert f["category"] == "fact"
        for d in decisions:
            assert d["category"] == "decision"

    def test_search_by_category(self, store_with_categories):
        """Test vector search with category filter."""
        store = store_with_categories

        # Search for facts only
        results = store.search_by_vector([0.1] * 384, limit=10, category="fact")

        for r in results:
            assert r["category"] == "fact"


class TestMemoryWeightDecay:
    """Test time-decay weight functionality."""

    @pytest.fixture
    def store_with_weights(self, tmp_path):
        """Create a store with different weight memories."""
        from olav.core.memory import LanceDBStore

        db_path = tmp_path / "weights_test.lance"
        store = LanceDBStore(db_path=db_path, embedding_dim=384)
        store.create_table()

        store.add_memory(
            id="weight-1",
            text="Recent important memory",
            vector=[0.1] * 384,
            category="fact",
            scope="global",
        )

        return store

    def test_update_weight(self, store_with_weights):
        """Test updating memory weight."""
        store = store_with_weights

        # Update weight
        result = store.update_weight("weight-1", weight=5.0)
        assert result["status"] == "success"

        # Verify weight was updated
        memories = store.get_memories()
        assert memories[0]["weight"] == 5.0

    def test_weight_in_search_results(self, store_with_weights):
        """Test that weight is included in search results."""
        store = store_with_weights

        results = store.search_by_vector([0.1] * 384, limit=5)

        assert len(results) > 0
        assert "weight" in results[0]
