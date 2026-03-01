"""Test Semantic Router - LanceDB-based Agent Intent Matching.

This test verifies the Semantic Router can:
1. Initialize agent intent index from workspace
2. Route queries using semantic matching
3. Fallback to LLM-based routing when threshold not met

TDD: Tests should FAIL until router is properly implemented.
"""

import json
import tempfile
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestSemanticRouter:
    """Test Semantic Router functionality."""

    @pytest.fixture
    def temp_db_path(self):
        """Create a temporary database path with unique ID."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / f"test_lancedb_{uuid.uuid4().hex[:8]}"

    @pytest.fixture
    def mock_agents(self):
        """Mock agent definitions for testing."""
        return [
            {
                "name": "config",
                "description": "Configuration management agent - handles sync, snapshots, config changes",
                "skills": [
                    {
                        "name": "config_sync",
                        "description": "Synchronize device configurations from network",
                    },
                    {
                        "name": "config_snapshot",
                        "description": "Take configuration snapshots for backup",
                    },
                ],
            },
            {
                "name": "ops",
                "description": "Network operations agent - handles routing, topology, probing",
                "skills": [
                    {
                        "name": "routing_analysis",
                        "description": "Analyze routing tables and protocols",
                    },
                ],
            },
            {
                "name": "audit",
                "description": "Audit and compliance agent - analyzes logs and security",
                "skills": [
                    {
                        "name": "log_search",
                        "description": "Search and analyze network logs",
                    },
                ],
            },
        ]

    def test_router_initialization(self, temp_db_path):
        """Test that router can be initialized."""
        from olav.core.router import SemanticRouter

        router = SemanticRouter(db_path=temp_db_path)

        assert router is not None
        assert router.db_path == temp_db_path
        assert router.threshold == 0.85  # Default threshold

    def test_router_custom_threshold(self, temp_db_path):
        """Test router with custom threshold."""
        from olav.core.router import SemanticRouter

        router = SemanticRouter(db_path=temp_db_path, threshold=0.7)

        assert router.threshold == 0.7

    def test_initialize_index_empty(self, temp_db_path):
        """Test initializing index with empty agent list."""
        from olav.core.router import SemanticRouter

        router = SemanticRouter(db_path=temp_db_path)
        result = router.initialize_index([])

        assert result["status"] == "no_data"

    def test_initialize_index_with_agents(self, temp_db_path, mock_agents):
        """Test initializing index with agent definitions."""
        from olav.core.router import SemanticRouter

        # Create router first, then mock the method
        router = SemanticRouter(db_path=temp_db_path)

        # Mock embeddings - need enough vectors for all records (3 agents + 4 skills = 7)
        mock_emb_instance = MagicMock()
        mock_emb_instance.embed_documents.return_value = [[0.1] * 384 for _ in range(7)]
        mock_emb_instance.embed_query.return_value = [0.1] * 384
        router._embeddings = mock_emb_instance

        result = router.initialize_index(mock_agents)

        assert result["status"] == "created"
        assert result["count"] > 0

    def test_route_empty_query(self, temp_db_path):
        """Test routing empty query."""
        from olav.core.router import SemanticRouter

        router = SemanticRouter(db_path=temp_db_path)
        result = router.route("")

        assert result["agent"] is None
        assert result["method"] == "fallback"

    def test_route_without_index(self, temp_db_path):
        """Test routing when index doesn't exist."""
        from olav.core.router import SemanticRouter

        router = SemanticRouter(db_path=temp_db_path)

        # Should fallback to LLM routing
        with patch.object(router, "_fallback_route") as mock_fallback:
            mock_fallback.return_value = {"agent": "olav", "method": "fallback"}

            result = router.route("test query")

            assert result["method"] == "fallback"


class TestSemanticRouterIntegration:
    """Integration tests for semantic router."""

    def test_get_router_singleton(self):
        """Test that get_router returns a singleton."""
        from olav.core.router import get_router, _router_instance

        # Reset global instance
        import olav.core.router as router_module

        router_module._router_instance = None

        router1 = get_router()
        router2 = get_router()

        # Should be the same instance
        assert router1 is router2

    def test_route_query_function(self):
        """Test the route_query convenience function."""
        from olav.core.router import route_query, _router_instance

        # Reset global instance
        import olav.core.router as router_module

        router_module._router_instance = None

        # Mock the router
        with patch("olav.core.router.get_router") as mock_get:
            mock_router = MagicMock()
            mock_router.route.return_value = {"agent": "config", "method": "fallback"}
            mock_get.return_value = mock_router

            result = route_query("sync configs")

            assert "agent" in result
            mock_router.route.assert_called_once()


class TestSemanticRouterEmbedding:
    """Test embedding integration."""

    def test_embedding_loading_local(self):
        """Test that local embedding model can be loaded."""
        from olav.core.config import get_embedding_config

        config = get_embedding_config()

        # Should have local embedding configured
        assert config.mode == "local" or config.mode == "api"


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
