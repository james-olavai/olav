"""Unit tests for synchronous indexing tools."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from olav.tools.indexing_tool import (
    INDEXING_TOOLS,
    VALID_EXTENSIONS,
    index_directory,
    index_document,
)


class TestIndexDocumentTool:
    """Tests for index_document tool."""
    
    @patch("olav.tools.indexing_tool.Path")
    def test_file_not_found(self, mock_path_cls: MagicMock) -> None:
        """Test indexing non-existent file returns error."""
        mock_path = MagicMock()
        mock_path.is_absolute.return_value = True
        mock_path.exists.return_value = False
        mock_path_cls.return_value = mock_path
        
        result = index_document.invoke({
            "file_path": "/docs/missing.pdf",
        })
        
        assert result["status"] == "error"
        assert "not found" in result["message"].lower()
        assert result["chunks_indexed"] == 0
    
    @patch("olav.tools.indexing_tool.Path")
    def test_unsupported_format(self, mock_path_cls: MagicMock) -> None:
        """Test indexing unsupported file format returns error."""
        mock_path = MagicMock()
        mock_path.is_absolute.return_value = True
        mock_path.exists.return_value = True
        mock_path.suffix = ".exe"
        mock_path_cls.return_value = mock_path
        
        result = index_document.invoke({
            "file_path": "/docs/program.exe",
        })
        
        assert result["status"] == "error"
        assert "unsupported" in result["message"].lower()
    
    @patch("olav.tools.indexing_tool._run_async")
    @patch("olav.tools.indexing_tool.Path")
    def test_successful_indexing(
        self,
        mock_path_cls: MagicMock,
        mock_run_async: MagicMock,
    ) -> None:
        """Test successful document indexing."""
        mock_path = MagicMock()
        mock_path.is_absolute.return_value = True
        mock_path.exists.return_value = True
        mock_path.suffix = ".pdf"
        mock_path.name = "guide.pdf"
        mock_path_cls.return_value = mock_path
        
        mock_run_async.return_value = {
            "status": "success",
            "message": "Indexed 10 chunks from 'guide.pdf'",
            "file": "/docs/guide.pdf",
            "chunks_indexed": 10,
            "chunks_failed": 0,
            "vendor": None,
            "document_type": None,
        }
        
        result = index_document.invoke({
            "file_path": "/docs/guide.pdf",
        })
        
        assert result["status"] == "success"
        assert result["chunks_indexed"] == 10
        assert "guide.pdf" in result["message"]
    
    @patch("olav.tools.indexing_tool._run_async")
    @patch("olav.tools.indexing_tool.Path")
    def test_with_vendor_metadata(
        self,
        mock_path_cls: MagicMock,
        mock_run_async: MagicMock,
    ) -> None:
        """Test indexing with vendor metadata."""
        mock_path = MagicMock()
        mock_path.is_absolute.return_value = True
        mock_path.exists.return_value = True
        mock_path.suffix = ".md"
        mock_path.name = "config.md"
        mock_path_cls.return_value = mock_path
        
        mock_run_async.return_value = {
            "status": "success",
            "message": "Indexed 5 chunks from 'config.md'",
            "file": "/docs/config.md",
            "chunks_indexed": 5,
            "chunks_failed": 0,
            "vendor": "cisco",
            "document_type": "configuration",
        }
        
        result = index_document.invoke({
            "file_path": "/docs/config.md",
            "vendor": "cisco",
            "document_type": "configuration",
        })
        
        assert result["status"] == "success"
        assert result["vendor"] == "cisco"
        assert result["document_type"] == "configuration"
    
    @patch("olav.tools.indexing_tool._run_async")
    @patch("olav.tools.indexing_tool.Path")
    def test_partial_failure(
        self,
        mock_path_cls: MagicMock,
        mock_run_async: MagicMock,
    ) -> None:
        """Test partial indexing failure."""
        mock_path = MagicMock()
        mock_path.is_absolute.return_value = True
        mock_path.exists.return_value = True
        mock_path.suffix = ".pdf"
        mock_path.name = "large.pdf"
        mock_path_cls.return_value = mock_path
        
        mock_run_async.return_value = {
            "status": "partial",
            "message": "Indexed 8 chunks from 'large.pdf'",
            "file": "/docs/large.pdf",
            "chunks_indexed": 8,
            "chunks_failed": 2,
            "vendor": None,
            "document_type": None,
        }
        
        result = index_document.invoke({
            "file_path": "/docs/large.pdf",
        })
        
        assert result["status"] == "partial"
        assert result["chunks_indexed"] == 8
        assert result["chunks_failed"] == 2


class TestIndexDirectoryTool:
    """Tests for index_directory tool."""
    
    @patch("olav.tools.indexing_tool.Path")
    def test_directory_not_found(self, mock_path_cls: MagicMock) -> None:
        """Test indexing non-existent directory returns error."""
        mock_path = MagicMock()
        mock_path.is_absolute.return_value = True
        mock_path.exists.return_value = False
        mock_path_cls.return_value = mock_path
        
        result = index_directory.invoke({
            "directory_path": "/docs/missing",
        })
        
        assert result["status"] == "error"
        assert "not found" in result["message"].lower()
        assert result["files_processed"] == 0
    
    @patch("olav.tools.indexing_tool.Path")
    def test_not_a_directory(self, mock_path_cls: MagicMock) -> None:
        """Test indexing a file path returns error."""
        mock_path = MagicMock()
        mock_path.is_absolute.return_value = True
        mock_path.exists.return_value = True
        mock_path.is_dir.return_value = False
        mock_path_cls.return_value = mock_path
        
        result = index_directory.invoke({
            "directory_path": "/docs/file.pdf",
        })
        
        assert result["status"] == "error"
        assert "not a directory" in result["message"].lower()
    
    @patch("olav.tools.indexing_tool.Path")
    def test_no_matching_files(self, mock_path_cls: MagicMock) -> None:
        """Test directory with no matching files."""
        mock_path = MagicMock()
        mock_path.is_absolute.return_value = True
        mock_path.exists.return_value = True
        mock_path.is_dir.return_value = True
        mock_path.rglob.return_value = []
        mock_path_cls.return_value = mock_path
        
        result = index_directory.invoke({
            "directory_path": "/docs/empty",
        })
        
        assert result["status"] == "error"
        assert "no matching" in result["message"].lower()
    
    @patch("olav.tools.indexing_tool._run_async")
    @patch("olav.tools.indexing_tool.Path")
    def test_successful_directory_indexing(
        self,
        mock_path_cls: MagicMock,
        mock_run_async: MagicMock,
    ) -> None:
        """Test successful directory indexing."""
        mock_path = MagicMock()
        mock_path.is_absolute.return_value = True
        mock_path.exists.return_value = True
        mock_path.is_dir.return_value = True
        
        # Mock matching files
        mock_file1 = MagicMock()
        mock_file1.suffix = ".pdf"
        mock_file1.is_file.return_value = True
        
        mock_file2 = MagicMock()
        mock_file2.suffix = ".md"
        mock_file2.is_file.return_value = True
        
        mock_path.rglob.return_value = [mock_file1, mock_file2]
        mock_path_cls.return_value = mock_path
        
        mock_run_async.return_value = {
            "status": "success",
            "message": "Indexed 25 chunks from 2 files",
            "directory": "/docs/cisco",
            "files_found": 2,
            "files_processed": 2,
            "total_chunks": 25,
            "chunks_failed": 0,
            "vendor": "cisco",
            "document_type": None,
        }
        
        result = index_directory.invoke({
            "directory_path": "/docs/cisco",
            "vendor": "cisco",
        })
        
        assert result["status"] == "success"
        assert result["files_processed"] == 2
        assert result["total_chunks"] == 25
    
    @patch("olav.tools.indexing_tool._run_async")
    @patch("olav.tools.indexing_tool.Path")
    def test_with_pattern_filter(
        self,
        mock_path_cls: MagicMock,
        mock_run_async: MagicMock,
    ) -> None:
        """Test directory indexing with pattern filter."""
        mock_path = MagicMock()
        mock_path.is_absolute.return_value = True
        mock_path.exists.return_value = True
        mock_path.is_dir.return_value = True
        
        # Only PDF files matching pattern
        mock_file = MagicMock()
        mock_file.suffix = ".pdf"
        mock_file.is_file.return_value = True
        
        mock_path.rglob.return_value = [mock_file]
        mock_path_cls.return_value = mock_path
        
        mock_run_async.return_value = {
            "status": "success",
            "message": "Indexed 15 chunks from 1 files",
            "directory": "/docs",
            "files_found": 1,
            "files_processed": 1,
            "total_chunks": 15,
            "chunks_failed": 0,
            "vendor": None,
            "document_type": None,
        }
        
        result = index_directory.invoke({
            "directory_path": "/docs",
            "pattern": "*.pdf",
        })
        
        assert result["status"] == "success"
        # Verify pattern was used
        mock_path.rglob.assert_called_with("*.pdf")


class TestIndexingToolsExport:
    """Tests for INDEXING_TOOLS export."""
    
    def test_tools_list_contains_expected(self) -> None:
        """Test that INDEXING_TOOLS contains expected tools."""
        tool_names = [t.name for t in INDEXING_TOOLS]
        
        assert "index_document" in tool_names
        assert "index_directory" in tool_names
        assert len(INDEXING_TOOLS) == 2
    
    def test_tools_have_descriptions(self) -> None:
        """Test all tools have descriptions."""
        for tool in INDEXING_TOOLS:
            assert tool.description
            assert len(tool.description) > 20


class TestValidExtensions:
    """Tests for valid file extensions."""
    
    def test_pdf_supported(self) -> None:
        """Test PDF is supported."""
        assert ".pdf" in VALID_EXTENSIONS
    
    def test_markdown_supported(self) -> None:
        """Test Markdown is supported."""
        assert ".md" in VALID_EXTENSIONS
    
    def test_yaml_supported(self) -> None:
        """Test YAML is supported."""
        assert ".yaml" in VALID_EXTENSIONS
        assert ".yml" in VALID_EXTENSIONS
    
    def test_txt_supported(self) -> None:
        """Test plain text is supported."""
        assert ".txt" in VALID_EXTENSIONS
