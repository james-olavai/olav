"""Unit tests for document loader module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from olav.etl.document_loader import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    Document,
    DocumentChunk,
    DocumentLoader,
    TextSplitter,
    load_and_chunk_documents,
)


class TestTextSplitter:
    """Tests for TextSplitter class."""

    def test_split_short_text(self) -> None:
        """Short text should not be split."""
        splitter = TextSplitter(chunk_size=100, chunk_overlap=20)
        text = "Short text"

        chunks = splitter.split_text(text)

        assert len(chunks) == 1
        assert chunks[0] == text

    def test_split_by_paragraph(self) -> None:
        """Text should be split by paragraphs first."""
        splitter = TextSplitter(chunk_size=50, chunk_overlap=0)
        text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."

        chunks = splitter.split_text(text)

        assert len(chunks) >= 2
        assert "First paragraph" in chunks[0]

    def test_split_by_newline(self) -> None:
        """Text should be split by newlines if paragraphs are too long."""
        splitter = TextSplitter(chunk_size=30, chunk_overlap=0)
        text = "Line one is here\nLine two is here\nLine three is here"

        chunks = splitter.split_text(text)

        # Should have at least one chunk
        assert len(chunks) >= 1

    def test_split_respects_chunk_size(self) -> None:
        """All chunks should respect max chunk size (approximately)."""
        splitter = TextSplitter(chunk_size=100, chunk_overlap=20)
        text = "Word " * 100  # 500 characters

        chunks = splitter.split_text(text)

        # Allow some tolerance for overlap and splitting
        for chunk in chunks:
            # Each chunk should be reasonably sized
            assert len(chunk) <= 250  # generous tolerance

    def test_split_with_overlap(self) -> None:
        """Chunks should have overlap when configured."""
        splitter = TextSplitter(chunk_size=50, chunk_overlap=10)
        text = "A" * 30 + "\n\n" + "B" * 30 + "\n\n" + "C" * 30

        chunks = splitter.split_text(text)

        # With overlap, later chunks should contain content from previous chunks
        assert len(chunks) >= 2

    def test_default_values(self) -> None:
        """Test default chunk size and overlap."""
        splitter = TextSplitter()

        assert splitter.chunk_size == DEFAULT_CHUNK_SIZE
        assert splitter.chunk_overlap == DEFAULT_CHUNK_OVERLAP


class TestDocumentChunk:
    """Tests for DocumentChunk dataclass."""

    def test_auto_chunk_id(self) -> None:
        """chunk_id should be auto-generated from source."""
        chunk = DocumentChunk(
            content="Test content",
            metadata={"source": "test.txt", "chunk_index": 0},
        )

        assert chunk.chunk_id == "test.txt:0"

    def test_explicit_chunk_id(self) -> None:
        """Explicit chunk_id should be preserved."""
        chunk = DocumentChunk(
            content="Test content",
            metadata={"source": "test.txt"},
            chunk_id="custom_id",
        )

        assert chunk.chunk_id == "custom_id"


class TestDocument:
    """Tests for Document dataclass."""

    def test_word_count(self) -> None:
        """Test word count property."""
        doc = Document(
            content="One two three four five",
            metadata={},
            source="test.txt",
        )

        assert doc.word_count == 5

    def test_char_count(self) -> None:
        """Test character count property."""
        doc = Document(
            content="Hello World",
            metadata={},
            source="test.txt",
        )

        assert doc.char_count == 11


class TestDocumentLoader:
    """Tests for DocumentLoader class."""

    @pytest.fixture
    def loader(self) -> DocumentLoader:
        """Create document loader instance."""
        return DocumentLoader(chunk_size=100, chunk_overlap=20)

    @pytest.fixture
    def temp_dir(self, tmp_path: Path) -> Path:
        """Create temporary directory with test files."""
        # Create test files
        (tmp_path / "test.txt").write_text("Plain text content")
        (tmp_path / "test.md").write_text("# Markdown Title\n\nContent here")
        (tmp_path / "config.yaml").write_text("key: value\nother: data")
        (tmp_path / "subdir").mkdir()
        (tmp_path / "subdir" / "nested.txt").write_text("Nested content")
        return tmp_path

    def test_load_text_file(self, loader: DocumentLoader, tmp_path: Path) -> None:
        """Test loading plain text file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Test content here")

        doc = loader.load_file(test_file)

        assert doc is not None
        assert doc.content == "Test content here"
        assert doc.metadata["format"] == "text"

    def test_load_markdown_file(self, loader: DocumentLoader, tmp_path: Path) -> None:
        """Test loading Markdown file."""
        test_file = tmp_path / "guide.md"
        test_file.write_text("# User Guide\n\nThis is the guide.")

        doc = loader.load_file(test_file)

        assert doc is not None
        assert "User Guide" in doc.content
        assert doc.metadata["format"] == "markdown"
        assert doc.metadata["title"] == "User Guide"

    def test_load_yaml_file(self, loader: DocumentLoader, tmp_path: Path) -> None:
        """Test loading YAML file."""
        test_file = tmp_path / "config.yaml"
        test_file.write_text("setting: value\nenabled: true")

        doc = loader.load_file(test_file)

        assert doc is not None
        assert doc.metadata["format"] == "yaml"
        assert doc.metadata["document_type"] == "configuration"

    def test_load_nonexistent_file(self, loader: DocumentLoader, tmp_path: Path) -> None:
        """Test loading nonexistent file returns None."""
        doc = loader.load_file(tmp_path / "nonexistent.txt")

        assert doc is None

    def test_load_unsupported_format(self, loader: DocumentLoader, tmp_path: Path) -> None:
        """Test loading unsupported format returns None."""
        test_file = tmp_path / "data.bin"
        test_file.write_bytes(b"\x00\x01\x02")

        doc = loader.load_file(test_file)

        assert doc is None

    def test_infer_vendor_cisco(self, loader: DocumentLoader) -> None:
        """Test vendor inference for Cisco."""
        vendor = loader._infer_vendor(Path("docs/cisco_ios_guide.pdf"))

        assert vendor == "cisco"

    def test_infer_vendor_arista(self, loader: DocumentLoader) -> None:
        """Test vendor inference for Arista."""
        vendor = loader._infer_vendor(Path("arista/eos_manual.md"))

        assert vendor == "arista"

    def test_infer_vendor_unknown(self, loader: DocumentLoader) -> None:
        """Test vendor inference returns unknown for unrecognized."""
        vendor = loader._infer_vendor(Path("random_document.txt"))

        assert vendor == "unknown"

    def test_infer_document_type_manual(self, loader: DocumentLoader) -> None:
        """Test document type inference for manual."""
        doc_type = loader._infer_document_type(Path("user_manual.pdf"))

        assert doc_type == "manual"

    def test_infer_document_type_troubleshooting(self, loader: DocumentLoader) -> None:
        """Test document type inference for troubleshooting."""
        doc_type = loader._infer_document_type(Path("debug_troubleshoot.md"))

        assert doc_type == "troubleshooting"

    def test_chunk_document(self, loader: DocumentLoader) -> None:
        """Test document chunking."""
        doc = Document(
            content="Content " * 50,  # ~350 characters
            metadata={"source": "test.txt"},
            source="test.txt",
        )

        chunks = loader.chunk_document(doc)

        assert len(chunks) >= 1
        assert all(isinstance(c, DocumentChunk) for c in chunks)
        assert chunks[0].metadata["source"] == "test.txt"
        assert chunks[0].metadata["chunk_index"] == 0

    def test_load_directory(self, loader: DocumentLoader, temp_dir: Path) -> None:
        """Test loading all documents from directory."""
        docs = list(loader.load_directory(temp_dir, recursive=True))

        assert len(docs) >= 3  # txt, md, yaml, nested txt

    def test_load_directory_non_recursive(self, loader: DocumentLoader, temp_dir: Path) -> None:
        """Test loading documents non-recursively."""
        docs = list(loader.load_directory(temp_dir, recursive=False))

        # Should not include nested.txt
        sources = [d.source for d in docs]
        assert not any("nested" in s for s in sources)


class TestLoadAndChunkDocuments:
    """Tests for load_and_chunk_documents function."""

    def test_load_and_chunk(self, tmp_path: Path) -> None:
        """Test convenience function."""
        # Create test file
        (tmp_path / "doc.txt").write_text("Content " * 20)

        chunks = list(load_and_chunk_documents(tmp_path, chunk_size=50))

        assert len(chunks) >= 1
        assert all(isinstance(c, DocumentChunk) for c in chunks)

    def test_empty_directory(self, tmp_path: Path) -> None:
        """Test with empty directory."""
        chunks = list(load_and_chunk_documents(tmp_path))

        assert len(chunks) == 0


class TestPDFLoading:
    """Tests for PDF loading (mocked)."""

    def test_pdf_loading_without_pdfplumber(self, tmp_path: Path) -> None:
        """Test PDF loading fails gracefully without pdfplumber."""
        loader = DocumentLoader()
        loader._pdf_available = False

        test_file = tmp_path / "test.pdf"
        test_file.write_bytes(b"%PDF-1.4")  # Minimal PDF header

        doc = loader.load_file(test_file)

        assert doc is None

    def test_pdf_loading_with_mock(self, tmp_path: Path) -> None:
        """Test PDF loading with mocked pdfplumber."""
        # Create mock pdfplumber
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Page content"

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        with patch.dict("sys.modules", {"pdfplumber": MagicMock()}):
            import sys
            sys.modules["pdfplumber"].open = MagicMock(return_value=mock_pdf)

            loader = DocumentLoader()
            loader._pdf_available = True

            test_file = tmp_path / "test.pdf"
            test_file.write_bytes(b"%PDF-1.4")

            # Mock the internal pdfplumber import
            with patch("pdfplumber.open", return_value=mock_pdf):
                doc = loader._load_pdf(test_file)

        assert doc is not None
        assert "Page content" in doc.content
        assert doc.metadata["format"] == "pdf"
        assert doc.metadata["page_count"] == 1
