"""Core Utilities for OLAV.

Provides shared logic for text processing and other common tasks.
"""

import logging
import re
from typing import Any

from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)


class TextProcessor:
    """Consolidated text processing utility.

    Provides semantic chunking and text cleaning for knowledge base tasks.
    """

    def __init__(self, chunk_size: int = 1024, chunk_overlap: int = 128) -> None:
        """Initialize text processor.

        Args:
            chunk_size: Characters per chunk
            chunk_overlap: Overlap between chunks
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size, chunk_overlap=chunk_overlap, separators=["\n\n", "\n", " ", ""]
        )

    def split_into_chunks(self, text: str) -> list[str]:
        """Split text into semantic chunks."""
        return self.splitter.split_text(text)

    def clean_text(self, text: str) -> str:
        """Remove common noise from extracted text."""
        # Remove page markers: === PAGE 1 ===
        text = re.sub(r"=== PAGE \d+ ===", "", text)
        # Remove excessive whitespace
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def build_chunk_metadata(
        self,
        chunk_content: str,
        chunk_index: int,
        total_chunks: int,
        source_file: str,
        extra_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build standard metadata for a search chunk."""
        metadata = {
            "chunk_index": chunk_index,
            "total_chunks": total_chunks,
            "source_file": source_file,
            "char_count": len(chunk_content),
        }
        if extra_metadata:
            metadata.update(extra_metadata)
        return metadata


def create_olav_directories(base_path: Any) -> dict:
    """Create the .olav/ directory structure.

    Args:
        base_path: The base path where .olav/ should be created

    Returns:
        Dict with creation status for each directory
    """
    from pathlib import Path

    base_path = Path(base_path)
    results = {}
    olav_path = base_path / ".olav"

    # Create main .olav directory
    try:
        olav_path.mkdir(parents=True, exist_ok=True)
        results["olav_root"] = {"status": "created", "path": str(olav_path)}
        logger.info(f"Created .olav/ directory at {olav_path}")
    except Exception as e:
        results["olav_root"] = {"status": "error", "error": str(e)}
        logger.error(f"Failed to create .olav/: {e}")
        return results

    subdirs = [
        "config",
        "databases",
        "logs",
        "logs/users",
        "cache",
        "workspace",
        "exports",
        "exports/snapshots",
        "exports/snapshots/latest",
        "exports/snapshots/latest/raw",
        "exports/audit_reports",
        "knowledge",
    ]

    for subdir in subdirs:
        dir_path = olav_path / subdir
        try:
            dir_path.mkdir(parents=True, exist_ok=True)
            results[subdir] = {"status": "created", "path": str(dir_path)}
        except Exception as e:
            results[subdir] = {"status": "error", "error": str(e)}
            logger.error(f"Failed to create {subdir}: {e}")

    return results
