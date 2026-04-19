"""read_file — Read a file and return its content for the writer agent."""

import logging
from pathlib import Path

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# Safety: limit file size to prevent context explosion
MAX_FILE_SIZE = 64 * 1024  # 64 KB


@tool
def read_file(path: str) -> str:
    """Read a file and return its text content.

    Use this to read report files, exported CSVs, or any text file
    that needs to be processed for summary extraction or formatting.

    Args:
        path: File path (absolute or relative to .olav/).
    """
    p = Path(path)

    # Try relative to workspace root if not absolute
    if not p.is_absolute():
        from olav.core.workspace import resolve_workspace_root
        try:
            ws_root = resolve_workspace_root()
            candidates = [ws_root.parent / path, Path.cwd() / path, p]
        except Exception:
            candidates = [Path.cwd() / path, p]
    else:
        candidates = [p]

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            size = candidate.stat().st_size
            if size > MAX_FILE_SIZE:
                # Read first + last portions for large files
                text = candidate.read_text(encoding="utf-8", errors="replace")
                first = text[:MAX_FILE_SIZE // 2]
                last = text[-(MAX_FILE_SIZE // 2):]
                return f"{first}\n\n... (truncated {size} bytes) ...\n\n{last}"
            return candidate.read_text(encoding="utf-8", errors="replace")

    return f"File not found: {path}"
