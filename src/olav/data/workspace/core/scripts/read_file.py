#!/usr/bin/env python3
"""read_file — Read a file and return its content for the writer agent."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Safety: limit file size to prevent context explosion
MAX_FILE_SIZE = 64 * 1024  # 64 KB


def read_file(path: str) -> str:
    """Read a file and return its text content.

    Use this to read report files, exported CSVs, or any text file
    that needs to be processed for summary extraction or formatting.

    Args:
        path: File path (absolute or relative to .olav/).
    """
    p = Path(path)

    # Build a list of candidate locations to try.
    # Small models often pass paths like ``/exports/foo.md`` (a leading
    # slash they think looks "right" but is actually absolute and
    # won't resolve under the real fs root).  Treat such paths as
    # cwd-relative if they reference well-known workspace top-dirs.
    _WORKSPACE_PREFIXES = ("/exports/", "/.olav/")

    candidates: list[Path] = []
    if p.is_absolute():
        candidates.append(p)
        # Relativize "/exports/..." → "exports/..." and try under cwd
        for prefix in _WORKSPACE_PREFIXES:
            if path.startswith(prefix):
                rel = path.lstrip("/")
                candidates.append(Path.cwd() / rel)
                break
    else:
        try:
            from olav.core.workspace import resolve_workspace_root
            ws_root = resolve_workspace_root()
            candidates.append(ws_root.parent / path)
        except Exception:  # noqa: BLE001
            pass
        candidates.append(Path.cwd() / path)
        candidates.append(p)

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


if __name__ == "__main__":
    import json as _json, sys as _sys
    _args = _json.loads(_sys.stdin.read() or "{}")
    result = read_file(**_args)
    print(_json.dumps(result, default=str))
