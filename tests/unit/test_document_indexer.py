"""Unit tests for document indexer module."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from olav.etl.document_indexer import (
    DOCS_INDEX_NAME,
    EMBEDDING_DIMENSION,
    DocumentIndexer,
    EmbeddedChunk,
    EmbeddingService,
    RAGIndexer,
)
from olav.etl.document_loader import DocumentChunk

if TYPE_CHECKING:
    from collections.abc import Generator


class TestEmbeddedChunk:
    """Tests for EmbeddedChunk dataclass."""

    def test_auto_doc_id(self) -> None:
        """Test auto-generated doc_id from content hash."""
        chunk = DocumentChunk(
            content="Test content",
            metadata={"source": "test.txt", "chunk_index": 0},
        )
        embedded = EmbeddedChunk(
            chunk=chunk,
            embedding=[0.1] * 10,
        )
        
        assert embedded.doc_id != ""
        assert "test" in embedded.doc_id
        assert "_0_" in embedded.doc_id

    def test_explicit_doc_id(self) -> None:
        """Test explicit doc_id is preserved."""
        chunk = DocumentChunk(
            content="Test",
            metadata={"source": "test.txt"},
        )
        embedded = EmbeddedChunk(
            chunk=chunk,
            embedding=[0.1] * 10,
            doc_id="custom_id",
        )
        
        assert embedded.doc_id == "custom_id"

    def test_consistent_hash(self) -> None:
        """Test doc_id is consistent for same content."""
        chunk1 = DocumentChunk(
            content="Same content",
            metadata={"source": "doc.txt", "chunk_index": 0},
        )
        chunk2 = DocumentChunk(
            content="Same content",
            metadata={"source": "doc.txt", "chunk_index": 0},
        )
        
        embedded1 = EmbeddedChunk(chunk=chunk1, embedding=[0.1])
        embedded2 = EmbeddedChunk(chunk=chunk2, embedding=[0.1])
        
        assert embedded1.doc_id == embedded2.doc_id


class TestEmbeddingService:
    """Tests for EmbeddingService class."""

    @pytest.fixture
    def mock_openai(self) -> Generator[MagicMock, None, None]:
        """Mock OpenAI client."""
        with patch("openai.OpenAI") as mock:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.data = [MagicMock(embedding=[0.1] * EMBEDDING_DIMENSION)]
            mock_client.embeddings.create.return_value = mock_response
            mock.return_value = mock_client
            yield mock_client

    @pytest.fixture
    def service_with_key(self) -> EmbeddingService:
        """Create embedding service with mocked API key."""
        with patch("olav.etl.document_indexer.env_settings") as mock_settings:
            mock_settings.llm_api_key = "test-api-key"
            return EmbeddingService()

    def test_default_model(self, service_with_key: EmbeddingService) -> None:
        """Test default embedding model."""
        assert service_with_key.model == "text-embedding-3-small"

    def test_custom_model(self) -> None:
        """Test custom embedding model."""
        with patch("olav.etl.document_indexer.env_settings") as mock_settings:
            mock_settings.llm_api_key = "test-key"
            service = EmbeddingService(model="text-embedding-ada-002")
        
        assert service.model == "text-embedding-ada-002"

    @pytest.mark.asyncio
    async def test_embed_text(self, mock_openai: MagicMock) -> None:
        """Test embedding single text."""
        with patch("olav.etl.document_indexer.env_settings") as mock_settings:
            mock_settings.llm_api_key = "test-api-key"
            service = EmbeddingService()
            result = await service.embed_text("Test text")
        
        assert len(result) == EMBEDDING_DIMENSION
        mock_openai.embeddings.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_embed_text_no_api_key(self) -> None:
        """Test embedding returns zeros without API key."""
        with patch("olav.etl.document_indexer.env_settings") as mock_settings:
            mock_settings.llm_api_key = ""
            service = EmbeddingService()
            result = await service.embed_text("Test")
        
        assert len(result) == EMBEDDING_DIMENSION
        assert all(v == 0.0 for v in result)

    @pytest.mark.asyncio
    async def test_embed_batch(self, mock_openai: MagicMock) -> None:
        """Test batch embedding."""
        mock_openai.embeddings.create.return_value.data = [
            MagicMock(embedding=[0.1] * EMBEDDING_DIMENSION),
            MagicMock(embedding=[0.2] * EMBEDDING_DIMENSION),
        ]
        
        with patch("olav.etl.document_indexer.env_settings") as mock_settings:
            mock_settings.llm_api_key = "test-api-key"
            service = EmbeddingService()
            results = await service.embed_batch(["Text 1", "Text 2"])
        
        assert len(results) == 2
        assert all(len(r) == EMBEDDING_DIMENSION for r in results)

    @pytest.mark.asyncio
    async def test_embed_batch_empty(self) -> None:
        """Test batch embedding with empty list."""
        with patch("olav.etl.document_indexer.env_settings") as mock_settings:
            mock_settings.llm_api_key = ""  # No API key = zero vectors
            service = EmbeddingService()
            results = await service.embed_batch([])
        
        assert results == []


class TestDocumentIndexer:
    """Tests for DocumentIndexer class."""

    @pytest.fixture
    def mock_opensearch(self) -> Generator[MagicMock, None, None]:
        """Mock OpenSearch client."""
        with patch("olav.etl.document_indexer.OpenSearch") as mock:
            mock_client = MagicMock()
            mock_client.indices.exists.return_value = False
            mock_client.indices.create.return_value = {"acknowledged": True}
            mock_client.indices.stats.return_value = {
                "indices": {
                    DOCS_INDEX_NAME: {
                        "primaries": {
                            "docs": {"count": 100},
                            "store": {"size_in_bytes": 1024000},
                        }
                    }
                }
            }
            mock_client.search.return_value = {
                "hits": {
                    "total": {"value": 1},
                    "hits": [
                        {
                            "_id": "test:0",
                            "_score": 0.9,
                            "_source": {
                                "content": "Test content",
                                "source": "test.txt",
                                "embedding": [0.1] * EMBEDDING_DIMENSION,
                            },
                        }
                    ],
                }
            }
            mock.return_value = mock_client
            yield mock_client

    @pytest.fixture
    def indexer(self, mock_opensearch: MagicMock) -> DocumentIndexer:
        """Create document indexer with mocks."""
        with patch("olav.etl.document_indexer.env_settings") as mock_settings:
            mock_settings.opensearch_url = "http://localhost:9200"
            return DocumentIndexer()

    def test_default_index_name(self, indexer: DocumentIndexer) -> None:
        """Test default index name."""
        assert indexer.index_name == DOCS_INDEX_NAME

    def test_custom_index_name(self, mock_opensearch: MagicMock) -> None:
        """Test custom index name."""
        with patch("olav.etl.document_indexer.env_settings") as mock_settings:
            mock_settings.opensearch_url = "http://localhost:9200"
            indexer = DocumentIndexer(index_name="custom-docs")
        
        assert indexer.index_name == "custom-docs"

    def test_get_index_mapping(self, indexer: DocumentIndexer) -> None:
        """Test index mapping configuration."""
        mapping = indexer.get_index_mapping()
        
        assert "settings" in mapping
        assert "mappings" in mapping
        assert mapping["settings"]["index"]["knn"] is True
        assert mapping["mappings"]["properties"]["embedding"]["type"] == "knn_vector"
        assert mapping["mappings"]["properties"]["embedding"]["dimension"] == EMBEDDING_DIMENSION

    @pytest.mark.asyncio
    async def test_ensure_index_creates_new(
        self, indexer: DocumentIndexer, mock_opensearch: MagicMock
    ) -> None:
        """Test ensuring index creates when not exists."""
        mock_opensearch.indices.exists.return_value = False
        
        result = await indexer.ensure_index()
        
        assert result is True
        mock_opensearch.indices.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_ensure_index_skips_existing(
        self, indexer: DocumentIndexer, mock_opensearch: MagicMock
    ) -> None:
        """Test ensuring index skips when exists."""
        mock_opensearch.indices.exists.return_value = True
        
        result = await indexer.ensure_index()
        
        assert result is True
        mock_opensearch.indices.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_ensure_index_recreate(
        self, indexer: DocumentIndexer, mock_opensearch: MagicMock
    ) -> None:
        """Test recreating existing index."""
        mock_opensearch.indices.exists.return_value = True
        
        result = await indexer.ensure_index(recreate=True)
        
        assert result is True
        mock_opensearch.indices.delete.assert_called_once()
        mock_opensearch.indices.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_index_chunk(
        self, indexer: DocumentIndexer, mock_opensearch: MagicMock
    ) -> None:
        """Test indexing single chunk."""
        chunk = DocumentChunk(
            content="Test content",
            metadata={"source": "test.txt", "chunk_index": 0},
        )
        embedded = EmbeddedChunk(chunk=chunk, embedding=[0.1] * EMBEDDING_DIMENSION)
        
        result = await indexer.index_chunk(embedded)
        
        assert result is True
        mock_opensearch.index.assert_called_once()

    @pytest.mark.asyncio
    async def test_index_chunks_bulk(
        self, indexer: DocumentIndexer, mock_opensearch: MagicMock
    ) -> None:
        """Test bulk indexing chunks."""
        with patch("olav.etl.document_indexer.helpers.bulk") as mock_bulk:
            mock_bulk.return_value = (2, [])
            
            chunks = [
                EmbeddedChunk(
                    chunk=DocumentChunk(
                        content=f"Content {i}",
                        metadata={"source": "doc.txt", "chunk_index": i},
                    ),
                    embedding=[0.1] * EMBEDDING_DIMENSION,
                )
                for i in range(2)
            ]
            
            success, failures = await indexer.index_chunks_bulk(chunks)
        
        assert success == 2
        assert failures == 0

    @pytest.mark.asyncio
    async def test_search_similar(
        self, indexer: DocumentIndexer, mock_opensearch: MagicMock
    ) -> None:
        """Test similarity search."""
        query_embedding = [0.1] * EMBEDDING_DIMENSION
        
        results = await indexer.search_similar(query_embedding, k=5)
        
        assert len(results) == 1
        assert results[0]["content"] == "Test content"
        assert "embedding" not in results[0]  # Embedding should be removed
        mock_opensearch.search.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_similar_with_filters(
        self, indexer: DocumentIndexer, mock_opensearch: MagicMock
    ) -> None:
        """Test similarity search with filters."""
        query_embedding = [0.1] * EMBEDDING_DIMENSION
        
        await indexer.search_similar(
            query_embedding,
            k=5,
            filters={"vendor": "cisco", "document_type": "manual"},
        )
        
        call_body = mock_opensearch.search.call_args[1]["body"]
        assert "bool" in call_body["query"]
        assert "filter" in call_body["query"]["bool"]

    @pytest.mark.asyncio
    async def test_get_stats(
        self, indexer: DocumentIndexer, mock_opensearch: MagicMock
    ) -> None:
        """Test getting index statistics."""
        stats = await indexer.get_stats()
        
        assert stats["doc_count"] == 100
        assert stats["index_name"] == DOCS_INDEX_NAME


class TestRAGIndexer:
    """Tests for RAGIndexer high-level pipeline."""

    @pytest.fixture
    def mock_services(self) -> Generator[dict, None, None]:
        """Mock all services."""
        with (
            patch("olav.etl.document_indexer.OpenSearch"),
            patch("olav.etl.document_indexer.env_settings") as mock_settings,
        ):
            mock_settings.opensearch_url = "http://localhost:9200"
            mock_settings.llm_api_key = ""  # No API key = zero vectors
            yield {"settings": mock_settings}

    def test_init_default(self, mock_services: dict) -> None:
        """Test default initialization."""
        indexer = RAGIndexer()
        
        assert indexer.chunk_size == 1000
        assert indexer.chunk_overlap == 200

    def test_init_custom(self, mock_services: dict) -> None:
        """Test custom initialization."""
        indexer = RAGIndexer(chunk_size=500, chunk_overlap=100)
        
        assert indexer.chunk_size == 500
        assert indexer.chunk_overlap == 100


class TestEmbeddingDimension:
    """Tests for embedding dimension constant."""

    def test_dimension_value(self) -> None:
        """Test embedding dimension is correct for OpenAI."""
        assert EMBEDDING_DIMENSION == 1536

    def test_docs_index_name(self) -> None:
        """Test docs index name constant."""
        assert DOCS_INDEX_NAME == "olav-docs"
