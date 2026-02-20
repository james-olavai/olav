"""Generic Text Processing Framework

Provides reusable text splitting and chunking capabilities.
"""

import logging
import re
from typing import Any

from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)


class TextProcessor:
    """Generic text chunking interface for knowledge processing.
    
    This is pure algorithm logic - no business domain knowledge.
    """

    def __init__(self, chunk_size: int = 1024, chunk_overlap: int = 128):
        """Initialize text processor.
        
        Args:
            chunk_size: Characters per chunk
            chunk_overlap: Overlap between chunks
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", " ", ""]
        )
    
    def split_into_chunks(self, text: str) -> list[str]:
        """Split text into semantic chunks.
        
        Args:
            text: Raw text to split
        
        Returns:
            List of text chunks
        """
        return self.splitter.split_text(text)
    
    def build_chunk_metadata(
        self,
        chunk_content: str,
        chunk_index: int,
        total_chunks: int,
        source_file: str,
        extra_metadata: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Build metadata dict for a chunk.
        
        Args:
            chunk_content: The actual chunk text
            chunk_index: 1-based chunk number
            total_chunks: Total chunks from same source
            source_file: Source filename
            extra_metadata: Additional metadata to include
        
        Returns:
            Metadata dict with standard fields
        """
        metadata = {
            'chunk_index': chunk_index,
            'total_chunks': total_chunks,
            'source_file': source_file,
            'char_count': len(chunk_content),
        }
        
        if extra_metadata:
            metadata.update(extra_metadata)
        
        return metadata
    
    def extract_page_number_from_text(self, text: str) -> int | None:
        """Extract page number from text markers (e.g., from PDF extraction).
        
        Args:
            text: Text possibly containing page markers
        
        Returns:
            Page number if found, else None
        """
        match = re.search(r'=== PAGE (\d+) ===', text)
        return int(match.group(1)) if match else None
    
    def clean_text(self, text: str) -> str:
        """Remove common noise from extracted text.
        
        Args:
            text: Raw text
        
        Returns:
            Cleaned text
        """
        # Remove page markers
        text = re.sub(r'=== PAGE \d+ ===', '', text)
        
        # Remove excessive whitespace
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = text.strip()
        
        return text
