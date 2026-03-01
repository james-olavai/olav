"""Knowledge Base (KB) Engine — Semantic Storage in LanceDB.

This module provides the core KB engine for indexing and searching knowledge
documents (markdown, PDFs) using LanceDB as the unified storage layer for both
long-term agentic memory and KB chunks.

Implements Phase 1 of LANCEDB_MEMORY_SYSTEM_INTEGRATION.md:
  - Migrate ALL KB chunks from DuckDB to LanceDB
  - Delete legacy DuckDB knowledge_chunks code and LangChain VSS integrations
  - Unified hybrid search (vector + BM25) via RRF fusion
  - Local sentence-transformers for zero-cost offline embedding

Architecture:
  - KnowledgeBase: High-level API for index/search KB documents
  - LanceDB table:  'kb_chunks' (separate from 'memory' table)
  - Schema: id, text, vector, source_file, chunk_index, metadata, timestamp, weight
  - Search: hybrid_search() with optional category/scope filters
"""

import hashlib
import json
import logging
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa

from olav.core.memory import (
    DEFAULT_MEMORY_DB,
    LanceDBStore,
    SemanticCache,
    hybrid_search,
    rrf_fusion,
)

logger = logging.getLogger(__name__)

# Knowledge base table name (separate from long-term memory table)
KB_TABLE = "kb_chunks"

# Semantic cache for KB queries (Tier 0, ~98% similarity threshold)
KB_CACHE_TABLE = "kb_query_cache"


class KnowledgeBase:
    """Core Knowledge Base engine — index and search KB documents in LanceDB.

    This unified KB store replaces the legacy DuckDB knowledge_chunks table.
    Documents are split into semantic chunks, embedded, stored in LanceDB,
    and searched via hybrid (vector + BM25) retrieval.

    Schema for KB chunks:
      - id:           UUID, starts with 'kb-'
      - text:         Chunk content (≤1024 chars default)
      - vector:       Embedding vector (384-dim default)
      - source_file:  Path to original document (e.g., 'ccnp_642_832.pdf')
      - chunk_index:  Sequential chunk number within the source
      - category:     Always 'kb' (distinguishes from memory items)
      - metadata:     JSON with file_size, page (for PDF), etc.
      - timestamp:    When indexed
      - weight:       Time-decay weight (1.0 initially, decays over time)

    Attributes:
        store:          LanceDBStore instance
        embedding_dim:  Embedding dimension (default 384)
    """

    def __init__(
        self,
        store: LanceDBStore,
        embedding_dim: int = 384,
    ) -> None:
        """Initialize Knowledge Base.

        Args:
            store:          LanceDBStore instance (shared with memory).
            embedding_dim:  Embedding vector dimension.
        """
        self._store = store
        self._embedding_dim = embedding_dim
        self._embedder = None  # lazy-loaded

    def _ensure_table(self) -> "LanceDBStore.table.LanceTable":
        """Ensure KB table exists with FTS index."""
        if not self._store.table_exists(KB_TABLE):
            self._create_kb_table()
        return self._store.get_table(KB_TABLE)

    def _create_kb_table(self) -> None:
        """Create KB chunks table if it doesn't exist."""
        db = self._store.connect()
        if KB_TABLE not in db.table_names():
            schema = pa.schema(
                [
                    ("id", pa.string()),
                    ("text", pa.string()),
                    ("vector", pa.list_(pa.float32(), self._embedding_dim)),
                    ("source_file", pa.string()),
                    ("chunk_index", pa.int32()),
                    ("category", pa.string()),  # Always 'kb'
                    ("metadata", pa.string()),  # JSON
                    ("timestamp", pa.timestamp("us")),
                    ("weight", pa.float32()),
                ]
            )
            tbl = db.create_table(KB_TABLE, schema=schema)
            logger.info(f"Created KB table: {KB_TABLE}")
            # Create FTS index for BM25
            try:
                tbl.create_fts_index("text", replace=True)
                logger.debug(f"Created FTS index on {KB_TABLE}.text")
            except Exception as e:
                logger.debug(f"FTS index skipped: {e}")

    def _embed(self, text: str) -> list[float] | None:
        """Lazy-load embedder and embed text."""
        if self._embedder is None:
            try:
                from sentence_transformers import SentenceTransformer

                self._embedder = SentenceTransformer("BAAI/bge-small-en-v1.5")
                logger.debug("KB: embedder loaded (BAAI/bge-small-en-v1.5)")
            except Exception as e:
                logger.debug(f"KB: embedder unavailable ({e}), falling back to zero vectors")
                self._embedder = False
        if not self._embedder:
            return None
        try:
            return self._embedder.encode(text, normalize_embeddings=True).tolist()
        except Exception as e:
            logger.warning(f"KB: embedding failed: {e}")
            return None

    def index_document(
        self,
        file_path: Path,
        text_content: str,
        chunk_size: int = 1024,
        chunk_overlap: int = 128,
    ) -> dict:
        """Index a document (Markdown or PDF text) into the KB.

        Splits the text into overlapping semantic chunks, embeds each chunk,
        and stores in LanceDB. Automatically skips duplicate chunks (vector
        similarity).

        Args:
            file_path:       Path to the source document.
            text_content:    Full text extracted from the document.
            chunk_size:      Characters per chunk (default 1024).
            chunk_overlap:   Overlap between chunks (default 128).

        Returns:
            Dict with indexing results: {"status": "success", "chunks": int, "skipped": int}
        """
        if not text_content.strip():
            return {"status": "error", "message": "Empty document"}

        source_file = str(file_path)
        chunks = self._split_chunks(text_content, chunk_size, chunk_overlap)
        if not chunks:
            return {"status": "error", "message": "No chunks created"}

        self._ensure_table()
        tbl = self._store.get_table(KB_TABLE)

        stored = 0
        skipped = 0

        for chunk_index, chunk_text in enumerate(chunks):
            # Embed
            vector = self._embed(chunk_text)
            if vector is None:
                vector = [0.0] * self._embedding_dim

            # Deduplicate: check vector similarity
            try:
                existing = (
                    tbl.search(vector, vector_column_name="vector")
                    .where(f"source_file = '{source_file}'")
                    .limit(1)
                    .to_list()
                )
                if existing:
                    dist = existing[0].get("_distance", 1.0)
                    if dist < 0.05:  # very similar
                        logger.debug(f"KB: skipping duplicate chunk {chunk_index}")
                        skipped += 1
                        continue
            except Exception:
                pass

            # Store chunk
            chunk_id = f"kb-{uuid.uuid4().hex[:8]}"
            try:
                self._store.add_memory(
                    id=chunk_id,
                    text=chunk_text,
                    vector=vector,
                    category="kb",
                    scope="global",
                    metadata={
                        "source_file": source_file,
                        "chunk_index": chunk_index,
                        "file_size": len(text_content),
                    },
                    table_name=KB_TABLE,
                )
                stored += 1
            except Exception as e:
                logger.error(f"KB: failed to store chunk {chunk_index}: {e}")
                skipped += 1

        logger.info(f"KB indexed {source_file}: {stored} chunks stored, {skipped} skipped")
        return {
            "status": "success",
            "source_file": source_file,
            "chunks": stored,
            "skipped": skipped,
        }

    @staticmethod
    def _split_chunks(text: str, chunk_size: int = 1024, overlap: int = 128) -> list[str]:
        """Split text into overlapping chunks."""
        chunks = []
        step = chunk_size - overlap
        for i in range(0, len(text), step):
            chunk = text[i : i + chunk_size]
            if chunk.strip():
                chunks.append(chunk)
        return chunks

    def search(
        self,
        query: str,
        limit: int = 5,
        scope: str = "global",
    ) -> list[dict]:
        """Search KB using hybrid retrieval (vector + BM25).

        Args:
            query:  Natural language search query.
            limit:  Max results (default 5).
            scope:  Scope filter (usually 'global').

        Returns:
            List of KB chunks ranked by relevance.
        """
        if not query.strip():
            return []

        limit = max(1, min(int(limit), 10))

        if not self._store.table_exists(KB_TABLE):
            logger.warning("KB: table does not exist yet")
            return []

        # Embed query
        query_vector = self._embed(query)
        if query_vector is None:
            query_vector = [0.0] * self._embedding_dim

        # Hybrid search via store (vector + BM25)
        try:
            vector_results = self._store.search_by_vector(
                query_vector=query_vector,
                limit=limit * 2,
                category="kb",
                scope=scope,
                table_name=KB_TABLE,
            )
            text_results = self._store.search_by_text(
                query=query,
                limit=limit * 2,
                category="kb",
                scope=scope,
                table_name=KB_TABLE,
            )
            # RRF fusion
            fused = rrf_fusion(
                [vector_results, text_results],
                k=60,
                list_weights=[0.5, 0.5],
            )
            return fused[:limit]
        except Exception as e:
            logger.error(f"KB search failed: {e}")
            return []

    def get_indexed_sources(self) -> list[str]:
        """Get list of indexed source files.

        Returns:
            List of unique source_file paths.
        """
        if not self._store.table_exists(KB_TABLE):
            return []

        try:
            tbl = self._store.get_table(KB_TABLE)
            rows = tbl.search().limit(10000).to_list()
            sources = set()
            for row in rows:
                meta = row.get("metadata")
                if meta:
                    try:
                        if isinstance(meta, str):
                            meta = json.loads(meta)
                        source = meta.get("source_file")
                        if source:
                            sources.add(source)
                    except Exception:
                        pass
            return sorted(list(sources))
        except Exception as e:
            logger.error(f"Failed to get indexed sources: {e}")
            return []

    def delete_source(self, source_file: str) -> dict:
        """Delete all chunks from a specific source file.

        Args:
            source_file: Source file path.

        Returns:
            Dict with deletion status.
        """
        if not self._store.table_exists(KB_TABLE):
            return {"status": "error", "message": "KB table does not exist"}

        try:
            tbl = self._store.get_table(KB_TABLE)
            source_safe = source_file.replace("'", "")
            tbl.delete(f"metadata LIKE '%{source_safe}%'")
            logger.info(f"KB: deleted chunks from {source_file}")
            return {"status": "success", "source_file": source_file}
        except Exception as e:
            logger.error(f"Failed to delete source {source_file}: {e}")
            return {"status": "error", "message": str(e)}


# Singleton instance
_kb_instance: KnowledgeBase | None = None


def get_knowledge_base(store: LanceDBStore | None = None) -> KnowledgeBase:
    """Get or create Knowledge Base singleton."""
    global _kb_instance
    if _kb_instance is None:
        if store is None:
            from olav.core.memory import get_store

            store = get_store()
        _kb_instance = KnowledgeBase(store)
    return _kb_instance


def reset_knowledge_base():
    """Reset KB singleton."""
    global _kb_instance
    _kb_instance = None
