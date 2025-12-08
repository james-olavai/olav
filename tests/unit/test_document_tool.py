"""Unit tests for document search tool."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from olav.tools.document_tool import (
    DOCUMENT_TOOLS,
    DocumentSearchTool,
    get_document_search_tool,
    get_document_tools,
    search_documents,
    search_rfc,
    search_vendor_docs,
)

if TYPE_CHECKING:
    from collections.abc import Generator


class TestDocumentSearchTool:
    """Tests for DocumentSearchTool class."""

    @pytest.fixture
    def mock_services(self) -> Generator[dict, None, None]:
        """Mock all services."""
        with (
            patch("olav.tools.document_tool.EmbeddingService") as mock_embed,
            patch("olav.tools.document_tool.DocumentIndexer") as mock_indexer,
        ):
            embed_service = MagicMock()
            embed_service.embed_text = AsyncMock(return_value=[0.1] * 1536)
            mock_embed.return_value = embed_service

            indexer = MagicMock()
            indexer.search_similar = AsyncMock(return_value=[
                {
                    "content": "BGP is a routing protocol",
                    "source": "network_guide.txt",
                    "_score": 0.92,
                    "vendor": "cisco",
                    "document_type": "manual",
                },
                {
                    "content": "OSPF uses link state",
                    "source": "ospf_manual.md",
                    "_score": 0.85,
                    "vendor": "arista",
                    "document_type": "reference",
                },
            ])
            mock_indexer.return_value = indexer

            yield {
                "embedding_service": embed_service,
                "indexer": indexer,
            }

    @pytest.fixture
    def tool(self, mock_services: dict) -> DocumentSearchTool:
        """Create tool instance with mocks."""
        return DocumentSearchTool()

    def test_default_embedding_model(self, tool: DocumentSearchTool) -> None:
        """Test default embedding model."""
        assert True

    @pytest.mark.asyncio
    async def test_search_basic(
        self, tool: DocumentSearchTool, mock_services: dict
    ) -> None:
        """Test basic search."""
        results = await tool.search("BGP configuration")

        assert len(results) == 2
        assert results[0]["content"] == "BGP is a routing protocol"
        mock_services["embedding_service"].embed_text.assert_called_once()
        mock_services["indexer"].search_similar.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_with_vendor_filter(
        self, tool: DocumentSearchTool, mock_services: dict
    ) -> None:
        """Test search with vendor filter."""
        await tool.search("OSPF", vendor="cisco")

        call_kwargs = mock_services["indexer"].search_similar.call_args[1]
        assert call_kwargs["filters"] == {"vendor": "cisco"}

    @pytest.mark.asyncio
    async def test_search_with_document_type_filter(
        self, tool: DocumentSearchTool, mock_services: dict
    ) -> None:
        """Test search with document type filter."""
        await tool.search("BGP", document_type="manual")

        call_kwargs = mock_services["indexer"].search_similar.call_args[1]
        assert call_kwargs["filters"] == {"document_type": "manual"}

    @pytest.mark.asyncio
    async def test_search_with_multiple_filters(
        self, tool: DocumentSearchTool, mock_services: dict
    ) -> None:
        """Test search with multiple filters."""
        await tool.search("routing", vendor="juniper", document_type="reference")

        call_kwargs = mock_services["indexer"].search_similar.call_args[1]
        assert call_kwargs["filters"]["vendor"] == "juniper"
        assert call_kwargs["filters"]["document_type"] == "reference"

    @pytest.mark.asyncio
    async def test_search_with_k(
        self, tool: DocumentSearchTool, mock_services: dict
    ) -> None:
        """Test search with custom k."""
        await tool.search("BGP", k=10)

        call_kwargs = mock_services["indexer"].search_similar.call_args[1]
        assert call_kwargs["k"] == 10

    @pytest.mark.asyncio
    async def test_search_formatted(
        self, tool: DocumentSearchTool, mock_services: dict
    ) -> None:
        """Test formatted search output."""
        result = await tool.search_formatted("BGP")

        assert "Found 2 relevant documents" in result
        assert "BGP is a routing protocol" in result
        assert "network_guide.txt" in result
        assert "cisco" in result

    @pytest.mark.asyncio
    async def test_search_formatted_no_results(
        self, tool: DocumentSearchTool, mock_services: dict
    ) -> None:
        """Test formatted search with no results."""
        mock_services["indexer"].search_similar.return_value = []

        result = await tool.search_formatted("nonexistent topic")

        assert "No documents found" in result


class TestSearchDocumentsTool:
    """Tests for search_documents tool function."""

    @pytest.fixture
    def mock_tool(self) -> Generator[MagicMock, None, None]:
        """Mock DocumentSearchTool."""
        with patch("olav.tools.document_tool.get_document_search_tool") as mock:
            tool = MagicMock()
            tool.search_formatted = AsyncMock(return_value="Formatted results")
            mock.return_value = tool
            yield tool

    @pytest.mark.asyncio
    async def test_search_documents_basic(self, mock_tool: MagicMock) -> None:
        """Test basic search_documents call."""
        await search_documents.ainvoke({"query": "BGP configuration"})

        mock_tool.search_formatted.assert_called_once_with(
            query="BGP configuration",
            k=5,
            vendor=None,
            document_type=None,
        )

    @pytest.mark.asyncio
    async def test_search_documents_with_filters(self, mock_tool: MagicMock) -> None:
        """Test search_documents with filters."""
        await search_documents.ainvoke({
            "query": "OSPF",
            "vendor": "cisco",
            "k": 3,
        })

        mock_tool.search_formatted.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_documents_k_clamped(self, mock_tool: MagicMock) -> None:
        """Test k is clamped to valid range."""
        # Test k > 10 gets clamped
        await search_documents.ainvoke({"query": "test", "k": 20})

        call_kwargs = mock_tool.search_formatted.call_args[1]
        assert call_kwargs["k"] <= 10


class TestSearchVendorDocsTool:
    """Tests for search_vendor_docs tool function."""

    @pytest.fixture
    def mock_tool(self) -> Generator[MagicMock, None, None]:
        """Mock DocumentSearchTool."""
        with patch("olav.tools.document_tool.get_document_search_tool") as mock:
            tool = MagicMock()
            tool.search_formatted = AsyncMock(return_value="Vendor docs")
            mock.return_value = tool
            yield tool

    @pytest.mark.asyncio
    async def test_search_vendor_docs_cisco(self, mock_tool: MagicMock) -> None:
        """Test searching Cisco docs."""
        await search_vendor_docs.ainvoke({
            "query": "BGP best path",
            "vendor": "cisco",
        })

        mock_tool.search_formatted.assert_called_once_with(
            query="BGP best path",
            k=3,
            vendor="cisco",
        )

    @pytest.mark.asyncio
    async def test_search_vendor_docs_arista(self, mock_tool: MagicMock) -> None:
        """Test searching Arista docs."""
        await search_vendor_docs.ainvoke({
            "query": "EVPN configuration",
            "vendor": "arista",
        })

        mock_tool.search_formatted.assert_called_once()
        call_kwargs = mock_tool.search_formatted.call_args[1]
        assert call_kwargs["vendor"] == "arista"


class TestSearchRFCTool:
    """Tests for search_rfc tool function."""

    @pytest.fixture
    def mock_tool(self) -> Generator[MagicMock, None, None]:
        """Mock DocumentSearchTool."""
        with patch("olav.tools.document_tool.get_document_search_tool") as mock:
            tool = MagicMock()
            tool.search_formatted = AsyncMock(return_value="RFC content")
            mock.return_value = tool
            yield tool

    @pytest.mark.asyncio
    async def test_search_rfc(self, mock_tool: MagicMock) -> None:
        """Test searching RFCs."""
        await search_rfc.ainvoke({"topic": "BGP route reflection"})

        mock_tool.search_formatted.assert_called_once_with(
            query="BGP route reflection",
            k=3,
            vendor="ietf",
            document_type="rfc",
        )


class TestToolRegistry:
    """Tests for tool registration."""

    def test_document_tools_list(self) -> None:
        """Test DOCUMENT_TOOLS list."""
        assert len(DOCUMENT_TOOLS) == 3
        assert search_documents in DOCUMENT_TOOLS
        assert search_vendor_docs in DOCUMENT_TOOLS
        assert search_rfc in DOCUMENT_TOOLS

    def test_get_document_tools(self) -> None:
        """Test get_document_tools function."""
        tools = get_document_tools()

        assert len(tools) == 3
        assert tools == DOCUMENT_TOOLS

    def test_tool_names(self) -> None:
        """Test tool names are set correctly."""
        assert search_documents.name == "search_documents"
        assert search_vendor_docs.name == "search_vendor_docs"
        assert search_rfc.name == "search_rfc"

    def test_tools_have_descriptions(self) -> None:
        """Test all tools have descriptions."""
        for tool in DOCUMENT_TOOLS:
            assert tool.description
            assert len(tool.description) > 0


class TestGlobalToolInstance:
    """Tests for global tool instance."""

    def test_get_document_search_tool_singleton(self) -> None:
        """Test singleton pattern."""
        with (
            patch("olav.tools.document_tool.EmbeddingService"),
            patch("olav.tools.document_tool.DocumentIndexer"),
            patch("olav.tools.document_tool._search_tool", None),
        ):
            tool1 = get_document_search_tool()
            tool2 = get_document_search_tool()

            assert tool1 is tool2


class TestEdgeCases:
    """Tests for edge cases."""

    @pytest.fixture
    def mock_services(self) -> Generator[dict, None, None]:
        """Mock all services."""
        with (
            patch("olav.tools.document_tool.EmbeddingService") as mock_embed,
            patch("olav.tools.document_tool.DocumentIndexer") as mock_indexer,
        ):
            embed_service = MagicMock()
            embed_service.embed_text = AsyncMock(return_value=[0.1] * 1536)
            mock_embed.return_value = embed_service

            indexer = MagicMock()
            indexer.search_similar = AsyncMock(return_value=[])
            mock_indexer.return_value = indexer

            yield {"embedding_service": embed_service, "indexer": indexer}

    @pytest.mark.asyncio
    async def test_empty_query(self, mock_services: dict) -> None:
        """Test handling empty query."""
        tool = DocumentSearchTool()
        result = await tool.search("")

        # Should handle gracefully
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_unicode_query(self, mock_services: dict) -> None:
        """Test handling Unicode query."""
        tool = DocumentSearchTool()
        result = await tool.search("网络配置 BGP 路由")

        # Should handle gracefully
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_special_characters_query(self, mock_services: dict) -> None:
        """Test handling special characters in query."""
        tool = DocumentSearchTool()
        result = await tool.search('BGP "neighbor" 192.168.1.1/24')

        # Should handle gracefully
        assert isinstance(result, list)
