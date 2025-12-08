"""Unit tests for init_docs.py - Document RAG index initialization."""

import importlib
from unittest.mock import MagicMock, patch

import pytest


class TestInitDocs:
    """Tests for olav-docs index initialization."""

    @pytest.fixture
    def mock_opensearch(self):
        """Create mock OpenSearch client."""
        mock = MagicMock()
        mock.indices.exists.return_value = False
        mock.indices.create.return_value = {"acknowledged": True}
        return mock

    def test_creates_index_when_not_exists(self, mock_opensearch):
        """Test index is created when it doesn't exist."""
        with patch("olav.core.memory.create_opensearch_client", return_value=mock_opensearch):
            # Reload the module to pick up the patched function
            import olav.etl.init_docs as init_docs_module
            importlib.reload(init_docs_module)
            
            init_docs_module.main()

            mock_opensearch.indices.exists.assert_called_once_with(index="olav-docs")
            mock_opensearch.indices.create.assert_called_once()

            # Verify mapping structure
            call_args = mock_opensearch.indices.create.call_args
            mapping = call_args.kwargs["body"] if "body" in call_args.kwargs else call_args[1]["body"]

            # Check kNN settings
            assert mapping["settings"]["index.knn"] is True

            # Check embedding dimension
            assert mapping["mappings"]["properties"]["embedding"]["dimension"] == 1536

    def test_skips_when_index_exists(self, mock_opensearch):
        """Test index creation is skipped when it exists."""
        mock_opensearch.indices.exists.return_value = True
        mock_opensearch.count.return_value = {"count": 100}

        with patch("olav.core.memory.create_opensearch_client", return_value=mock_opensearch):
            import olav.etl.init_docs as init_docs_module
            importlib.reload(init_docs_module)
            
            init_docs_module.main()

            mock_opensearch.indices.exists.assert_called_once()
            mock_opensearch.indices.create.assert_not_called()
            mock_opensearch.count.assert_called_once()

    def test_mapping_has_required_fields(self, mock_opensearch):
        """Test mapping contains all required fields."""
        with patch("olav.core.memory.create_opensearch_client", return_value=mock_opensearch):
            import olav.etl.init_docs as init_docs_module
            importlib.reload(init_docs_module)
            
            init_docs_module.main()

            call_args = mock_opensearch.indices.create.call_args
            mapping = call_args.kwargs["body"] if "body" in call_args.kwargs else call_args[1]["body"]
            props = mapping["mappings"]["properties"]

            # Required fields
            assert "content" in props
            assert "embedding" in props
            assert "metadata" in props
            assert "created_at" in props

            # Metadata subfields
            metadata_props = props["metadata"]["properties"]
            assert "file_path" in metadata_props
            assert "vendor" in metadata_props
            assert "document_type" in metadata_props
            assert "chunk_index" in metadata_props

    def test_knn_vector_config(self, mock_opensearch):
        """Test kNN vector configuration is correct."""
        with patch("olav.core.memory.create_opensearch_client", return_value=mock_opensearch):
            import olav.etl.init_docs as init_docs_module
            importlib.reload(init_docs_module)
            
            init_docs_module.main()

            call_args = mock_opensearch.indices.create.call_args
            mapping = call_args.kwargs["body"] if "body" in call_args.kwargs else call_args[1]["body"]
            embedding = mapping["mappings"]["properties"]["embedding"]

            assert embedding["type"] == "knn_vector"
            assert embedding["dimension"] == 1536
            assert embedding["method"]["name"] == "hnsw"
            assert embedding["method"]["space_type"] == "cosinesimil"
            assert embedding["method"]["engine"] == "nmslib"
