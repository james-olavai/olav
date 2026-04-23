"""Unified Knowledge Store — File Sync Module.

Provides differential sync between a markdown vault directory and LanceDB,
plus single-file import for arbitrary formats.

Functions:
    sync_from_files()   Diff-sync a directory: insert/update/delete.
    kb_import()         Import a single markdown (or other) file.
    _embed()            Internal embedding helper (mockable in tests).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from olav.core.memory import LanceDBStore

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Embedding helper (thin wrapper so tests can patch it)
# ─────────────────────────────────────────────────────────────────────────────


def _embed(text: str) -> list[float] | None:
    """Embed text via the configured embedder (mockable in tests)."""
    try:
        from olav.core.embedder import embed_text
        return embed_text(text)
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Markdown helpers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_yaml_value(v: str):
    """Parse a YAML scalar/list value (simple subset, no full YAML parser needed)."""
    v = v.strip()
    if v.startswith("[") and v.endswith("]"):
        # Try JSON first (handles ["a", "b"])
        try:
            return json.loads(v)
        except Exception as e:
            logger.debug("YAML value JSON parse failed, falling back to inline-list: %s", e)
        # YAML inline list: [a, b, c] — items without quotes
        inner = v[1:-1].strip()
        if not inner:
            return []
        return [item.strip().strip('"\'') for item in inner.split(",") if item.strip()]
    # Boolean/numeric coercion (keep as string for our purposes)
    return v


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split YAML frontmatter from body. Returns (meta_dict, body_text)."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text

    body = text[m.end():]
    meta: dict = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            k = k.strip()
            v = v.strip()
            meta[k] = _parse_yaml_value(v)
    return meta, body


def _file_hash(path: Path) -> str:
    """MD5 hash of file contents (used as change detection)."""
    return hashlib.md5(path.read_bytes()).hexdigest()


def _id_for_file(path: Path, origin: str) -> str:
    """Generate a deterministic memory ID from a file path."""
    prefix = {"user": "usr", "document": "doc"}.get(origin, "usr")
    short = hashlib.md5(str(path).encode()).hexdigest()[:8]
    return f"{prefix}-{short}"


def _smart_chunk(text: str, chunk_size: int = 1500) -> list[str]:
    """Split text into chunks, preferring section boundaries."""
    if len(text) < chunk_size:
        return [text]

    # Try to split on ## headings
    sections = re.split(r"\n(?=## )", text)
    chunks: list[str] = []
    for sec in sections:
        if len(sec) <= chunk_size:
            chunks.append(sec)
        else:
            # Split on double newlines
            paras = sec.split("\n\n")
            current = ""
            for para in paras:
                if len(current) + len(para) + 2 <= chunk_size:
                    current = (current + "\n\n" + para).lstrip("\n")
                else:
                    if current:
                        chunks.append(current)
                    current = para
            if current:
                chunks.append(current)
    return [c for c in chunks if c.strip()]


# ─────────────────────────────────────────────────────────────────────────────
# Sync state tracking (stored in a JSON sidecar per directory)
# ─────────────────────────────────────────────────────────────────────────────

def _state_path(kb_dir: Path) -> Path:
    return kb_dir / ".olav_sync_state.json"


def _load_state(kb_dir: Path) -> dict[str, dict]:
    """Load previous sync state: {rel_path: {hash, ids: [mem_id,...]}}."""
    sp = _state_path(kb_dir)
    if sp.exists():
        try:
            return json.loads(sp.read_text())
        except Exception as e:
            logger.debug("sync state load failed: %s", e)
    return {}


def _save_state(kb_dir: Path, state: dict) -> None:
    sp = _state_path(kb_dir)
    sp.write_text(json.dumps(state, indent=2))


# ─────────────────────────────────────────────────────────────────────────────
# sync_from_files
# ─────────────────────────────────────────────────────────────────────────────

def sync_from_files(
    store: "LanceDBStore",
    kb_dir: Path,
    origin: str = "user",
    dry_run: bool = False,
    chunk_size: int = 1500,
) -> dict:
    """Differential sync between a markdown directory and LanceDB.

    - New files → INSERT.
    - Changed files (hash mismatch) → DELETE old chunks + INSERT new.
    - Deleted files → DELETE from LanceDB.
    - Unchanged files → skip.

    Args:
        store:      LanceDBStore instance.
        kb_dir:     Directory containing .md / .txt files.
        origin:     origin value written to all synced entries.
        dry_run:    If True, compute diff but do not modify LanceDB.
        chunk_size: Maximum characters per chunk.

    Returns:
        {"inserted": int, "updated": int, "deleted": int, "skipped": int,
         "errors": int, "dry_run": bool}
    """
    from olav.core.memory import MEMORY_TABLE

    kb_dir = Path(kb_dir)
    if not kb_dir.exists():
        return {"inserted": 0, "updated": 0, "deleted": 0,
                "skipped": 0, "errors": 0, "dry_run": dry_run}

    if not store.table_exists(MEMORY_TABLE):
        if not dry_run:
            store.create_table()

    prev_state = _load_state(kb_dir)
    new_state: dict[str, dict] = {}

    inserted = updated = deleted = skipped = errors = 0

    # Walk all markdown files
    current_files: dict[str, Path] = {}
    for ext in ("*.md", "*.txt"):
        for p in kb_dir.rglob(ext):
            if p.name.startswith("."):
                continue
            rel = str(p.relative_to(kb_dir))
            current_files[rel] = p

    # Process each current file
    for rel, path in current_files.items():
        fhash = _file_hash(path)
        prev = prev_state.get(rel, {})

        if prev.get("hash") == fhash:
            # Unchanged
            new_state[rel] = prev
            skipped += 1
            continue

        is_update = rel in prev_state

        if dry_run:
            if is_update:
                updated += 1
            else:
                inserted += 1
            continue

        # Delete old chunks if updating
        if is_update:
            for old_id in prev.get("ids", []):
                store.delete_memory(old_id)

        # Parse and chunk
        try:
            raw_text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            logger.warning(f"sync: read error {path}: {e}")
            errors += 1
            continue

        meta, body = _parse_frontmatter(raw_text)
        tags_raw = meta.get("tags", [])
        if isinstance(tags_raw, list):
            tags = tags_raw
        elif isinstance(tags_raw, str):
            try:
                tags = json.loads(tags_raw)
            except Exception:
                tags = [tags_raw] if tags_raw else []
        else:
            tags = []

        file_origin = meta.get("origin", origin)
        confidence = float(meta.get("confidence", 1.0 if file_origin in ("user", "document") else 0.8))
        chunks = _smart_chunk(body.strip(), chunk_size=chunk_size)

        if not chunks or not any(c.strip() for c in chunks):
            logger.debug(f"sync: skipping empty file {path}")
            skipped += 1
            continue

        new_ids: list[str] = []
        for i, chunk_text in enumerate(chunks):
            if not chunk_text.strip():
                continue
            mem_id = f"{_id_for_file(path, file_origin)}-{i}"
            vector = _embed(chunk_text)
            if vector is None:
                vector = [0.0] * store.embedding_dim

            result = store.add_memory(
                id=mem_id,
                text=chunk_text,
                vector=vector,
                category=meta.get("category", "fact"),
                scope=meta.get("scope", "global"),
                origin=file_origin,
                confidence=confidence,
                tags=json.dumps(tags),
                metadata={"source_file": str(path), "chunk_index": i},
            )
            if result.get("status") not in ("blocked",):
                new_ids.append(mem_id)

        new_state[rel] = {"hash": fhash, "ids": new_ids}
        if is_update:
            updated += 1
        else:
            inserted += 1

    # Handle deleted files
    for rel, prev in prev_state.items():
        if rel not in current_files:
            if not dry_run:
                for old_id in prev.get("ids", []):
                    store.delete_memory(old_id)
                deleted += 1
            else:
                deleted += 1

    if not dry_run:
        _save_state(kb_dir, new_state)

    summary = {
        "inserted": inserted,
        "updated": updated,
        "deleted": deleted,
        "skipped": skipped,
        "errors": errors,
        "dry_run": dry_run,
    }
    logger.info(f"sync_from_files: {summary} ← {kb_dir}")
    return summary


# ─────────────────────────────────────────────────────────────────────────────
# kb_import — single file import
# ─────────────────────────────────────────────────────────────────────────────

def kb_import(
    store: "LanceDBStore",
    file_path: Path | str,
    *,
    origin: str = "document",
    confidence: float = 1.0,
    chunk_size: int = 1500,
) -> dict:
    """Import a single file into the knowledge store.

    Supports .md and .txt natively. Other formats require markitdown.

    Args:
        store:      LanceDBStore instance.
        file_path:  Path to file.
        origin:     Origin tag for the imported entries.
        confidence: Confidence value (default 1.0 for imported documents).
        chunk_size: Maximum characters per chunk.

    Returns:
        {"status": "success"|"error", "file": str, "chunks": int, "message": str|None}
    """
    from olav.core.memory import MEMORY_TABLE

    path = Path(file_path)
    if not path.exists():
        return {"status": "error", "file": str(path), "message": f"File not found: {path}"}

    # Read content
    suffix = path.suffix.lower()
    if suffix in (".md", ".txt"):
        try:
            raw_text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return {"status": "error", "file": str(path), "message": str(e)}
    else:
        try:
            from markitdown import MarkItDown  # type: ignore
            mid = MarkItDown()
            result = mid.convert(str(path))
            raw_text = result.text_content
        except ImportError:
            return {
                "status": "error",
                "file": str(path),
                "message": f"markitdown not installed; cannot import {suffix} files",
            }
        except Exception as e:
            return {"status": "error", "file": str(path), "message": str(e)}

    # Parse frontmatter (if .md)
    meta: dict = {}
    body = raw_text
    if suffix == ".md":
        meta, body = _parse_frontmatter(raw_text)

    if not body.strip():
        return {"status": "error", "file": str(path), "message": "Empty content"}

    # Extract tags from frontmatter
    tags_raw = meta.get("tags", [])
    if isinstance(tags_raw, list):
        tags = tags_raw
    elif isinstance(tags_raw, str):
        try:
            tags = json.loads(tags_raw)
        except Exception:
            tags = [tags_raw] if tags_raw else []
    else:
        tags = []

    file_origin = meta.get("origin", origin)
    file_confidence = float(meta.get("confidence", confidence))

    if not store.table_exists(MEMORY_TABLE):
        store.create_table()

    chunks = _smart_chunk(body.strip(), chunk_size=chunk_size)
    stored = 0

    for i, chunk_text in enumerate(chunks):
        if not chunk_text.strip():
            continue
        mem_id = f"doc-{uuid.uuid4().hex[:8]}"
        vector = _embed(chunk_text)
        if vector is None:
            vector = [0.0] * store.embedding_dim

        result = store.add_memory(
            id=mem_id,
            text=chunk_text,
            vector=vector,
            category=meta.get("category", "fact"),
            scope=meta.get("scope", "global"),
            origin=file_origin,
            confidence=file_confidence,
            tags=json.dumps(tags),
            metadata={
                "source_file": str(path),
                "chunk_index": i,
                "total_chunks": len(chunks),
            },
        )
        if result.get("status") not in ("blocked",):
            stored += 1

    # Force FTS index rebuild so the newly inserted chunks are visible to
    # text search immediately (LanceDB FTS is static; stale until rebuilt).
    if stored > 0:
        try:
            tbl = store.get_table(MEMORY_TABLE)
            tbl.create_fts_index("text", replace=True)
        except Exception as _e:
            logger.debug(f"kb_import: FTS rebuild skipped: {_e}")

    return {"status": "success", "file": str(path), "chunks": stored}
