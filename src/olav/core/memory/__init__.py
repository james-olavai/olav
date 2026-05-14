"""LanceDB Memory Store - Core engine for OLAV Agentic Memory.

This module provides the foundation for LanceDB integration as the semantic/memory
layer (OCM - Olav Central Memory). It implements:
- Hybrid fusion engine (Vector + BM25)
- Categorized memory (Fact, Decision, Preference)
- Scope isolation for multi-tenant support
- Time-decay weights and recency boosts

Following the integration plan in dev_docs/LANCEDB_MEMORY_SYSTEM_INTEGRATION.md
"""

import json
import logging
import math
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import lancedb
import pyarrow as pa

from olav.platform.safety.injection_scanner import scan_content as _scan_content

logger = logging.getLogger(__name__)

# Default LanceDB database path
DEFAULT_MEMORY_DB = ".olav/databases/memory.lance"

# Memory table name
MEMORY_TABLE = "memory"


class EmbeddingDimMismatchError(RuntimeError):
    """Raised when an existing LanceDB table's vector dim doesn't match
    the configured embedder.

    Earlier OLAV versions silently dropped + recreated the table, wiping
    user-curated memory rows.  We now raise instead.  Operator must:

    1. Fix the embedder so its dim matches the stored data, OR
    2. Migrate the data explicitly (re-embed every row), OR
    3. Set ``OLAV_ALLOW_DESTRUCTIVE_DIM_MIGRATION=1`` to opt back in to
       the destructive drop (debug only — destroys ALL rows in the table).

    See ``dev_docs/00 § ISSUE-EMBEDDING-FALLBACK-DIM-MISMATCH-DESTROYS-DATA``.
    """

    def __init__(self, *, table: str, stored_dim: int, embedder_dim: int):
        self.table = table
        self.stored_dim = stored_dim
        self.embedder_dim = embedder_dim
        super().__init__(
            f"Embedding dim mismatch on table {table!r}: "
            f"stored={stored_dim}, embedder={embedder_dim}.  Refusing to "
            f"start to avoid silent data loss.  Fix the embedder config "
            f"(check api.json embedding.fallback) or set "
            f"OLAV_ALLOW_DESTRUCTIVE_DIM_MIGRATION=1 to opt in to the "
            f"old drop-and-recreate behaviour (destroys ALL rows in "
            f"{table!r})."
        )


# Memory categories
class MemoryCategory:
    FACT = "fact"
    DECISION = "decision"
    PREFERENCE = "preference"
    AUDIT = "audit"


class LanceDBStore:
    """LanceDB store for semantic memory and knowledge base.

    This is the core engine for OLAV's agentic memory system, providing:
    - Vector similarity search with embeddings
    - Full-text search (BM25) via LanceDB's built-in FTS
    - Categorized memory (fact, decision, preference, audit)
    - Scope isolation (global, agent-specific)
    - Time-decay weighting

    Attributes:
        db_path: Path to the LanceDB database
        embedding_dim: Dimension of embedding vectors
    """

    def __init__(self, db_path: str | Path | None = None, embedding_dim: int | None = None):
        """Initialize LanceDB store.

        Args:
            db_path: Path to LanceDB database. Defaults to DEFAULT_MEMORY_DB
            embedding_dim: Dimension of embedding vectors. Auto-detected if None.
        """
        self._db_path = Path(db_path) if db_path else self._get_default_db_path()
        if embedding_dim is None:
            embedding_dim = _detect_embedding_dim()
        self._embedding_dim = embedding_dim
        self._db: lancedb.LanceDBConnection | None = None
        # FTS dirty tracking: rebuild index after N writes to keep BM25 fresh
        self._fts_dirty: dict[str, int] = {}
        self._fts_rebuild_threshold: int = self._load_fts_threshold()
        self._ensure_database()
        # Eager connect so dim mismatch is caught at construction time
        # (fail-fast).  Lazy connect made the check fire only when the
        # first query landed — by then the agent had been making
        # decisions on stale memory.  See dev_docs/00 §
        # ISSUE-EMBEDDING-FALLBACK-DIM-MISMATCH-DESTROYS-DATA.
        self.connect()

    @staticmethod
    def _load_fts_threshold() -> int:
        """Read fts_rebuild_every from config (default 20)."""
        try:
            from olav.core.config import get_memory_config

            return get_memory_config().fts_rebuild_every
        except Exception:
            return 20

    def _get_default_db_path(self) -> Path:
        """Get default database path from project root."""
        from olav.core.config import get_paths_config

        paths = get_paths_config()
        db_dir = paths.project_root / paths.databases_dir
        return db_dir / "memory.lance"

    def _ensure_database(self):
        """Ensure database directory exists."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def db_path(self) -> Path:
        """Get database path."""
        return self._db_path

    @property
    def embedding_dim(self) -> int:
        """Get embedding dimension."""
        return self._embedding_dim

    def connect(self) -> lancedb.LanceDBConnection:
        """Connect to LanceDB database.

        Returns:
            LanceDB connection instance
        """
        if self._db is None:
            self._db = lancedb.connect(str(self._db_path))
            logger.info(f"Connected to LanceDB at {self._db_path}")
            # Auto-migrate existing tables with mismatched embedding
            # dimension. Without this, switching embedding backend (e.g.
            # OpenRouter 1536-dim → Ollama nomic-v2 768-dim) leaves a
            # stale 1536-dim schema that silently rejects every memory
            # write with a cryptic FixedSizeList cast error.
            self._check_and_migrate_vector_dim()
        return self._db  # type: ignore[returnValue]

    @staticmethod
    def _extract_table_names(raw: Any) -> list[str]:
        """Coerce a lancedb list-tables response (flat list / paginated
        dict / list-of-tuples) into ``list[str]`` of real table names.

        Filters out non-string entries (page tokens, etc) so callers
        never feed garbage to ``open_table()``.
        """
        if raw is None:
            return []
        if isinstance(raw, dict):
            tables = raw.get("tables") or []
            return [t for t in tables if isinstance(t, str)]
        try:
            seq = list(raw)
        except Exception:
            return []
        # Some versions yield 2-tuples like ``('tables', ['memory'])``,
        # ``('page_token', None)``. Walk the items and keep only the
        # actual table-name list contents.
        if seq and isinstance(seq[0], tuple):
            for k, v in seq:
                if k == "tables" and isinstance(v, (list, tuple)):
                    return [t for t in v if isinstance(t, str)]
            return []
        # Flat list — keep only strings.
        return [t for t in seq if isinstance(t, str)]

    def _check_and_migrate_vector_dim(self) -> None:
        """Scan every table for a vector field whose ``list_size`` doesn't
        match the current embedder's dimension.

        On mismatch: REFUSE to start (raise ``EmbeddingDimMismatchError``).

        Earlier versions silently dropped + recreated the table here, which
        wiped user-curated memory rows whenever the embedding backend
        flapped (e.g. API → local fallback with different dim).  See
        ``dev_docs/00 § ISSUE-EMBEDDING-FALLBACK-DIM-MISMATCH-DESTROYS-DATA``
        — the fix is to never destroy data implicitly.  Operator decides:
        explicit migration, drop, or fix the embedder.

        Set ``OLAV_ALLOW_DESTRUCTIVE_DIM_MIGRATION=1`` to opt in to the
        old drop-and-recreate behaviour (debug only, NOT recommended).
        """
        if self._db is None:
            return
        # lancedb shipped multiple list-table APIs across versions:
        #   * ``table_names()`` (deprecated): some versions return
        #     a flat ``list[str]``, others return a paginated dict
        #     ``{"tables": [...], "page_token": ...}`` cast to list of
        #     2-tuples
        #   * ``list_tables()`` (current): same dual behaviour
        # In either case we want only string table names; tuples like
        # ``('page_token', None)`` blow up downstream
        # ``open_table()`` with a Rust panic on InvalidTableName.
        table_names: list[str] = []
        for accessor in (
            getattr(self._db, "table_names", None),
            getattr(self._db, "list_tables", None),
        ):
            if accessor is None:
                continue
            try:
                raw = accessor()
            except Exception:
                continue
            extracted = self._extract_table_names(raw)
            if extracted:
                table_names = extracted
                break
        import os
        allow_destructive = os.environ.get(
            "OLAV_ALLOW_DESTRUCTIVE_DIM_MIGRATION", ""
        ).strip().lower() in {"1", "true", "yes"}

        for tname in table_names:
            try:
                tbl = self._db.open_table(tname)
                for field in tbl.schema:
                    if field.name == "vector" and hasattr(field.type, "list_size"):
                        if field.type.list_size != self._embedding_dim:
                            stored_dim = field.type.list_size
                            if allow_destructive:
                                # ISSUE-CH8-DEMO-DIRECTIVE-VANISHES-ON-DIM-MIGRATION
                                # (P2, 2026-05-12): make the warning impossible
                                # to miss + tell the operator the exact
                                # recovery commands so demo / directive guides
                                # can be re-imported, otherwise the agent's
                                # compliance silently regresses to baseline.
                                logger.warning(
                                    "═" * 70 + "\n"
                                    "⚠️  EMBEDDING DIM MIGRATION — DESTRUCTIVE  ⚠️\n"
                                    "Table %r: stored=%dd, new embedder=%dd. "
                                    "OLAV_ALLOW_DESTRUCTIVE_DIM_MIGRATION=1 set; "
                                    "dropping and recreating — ALL EXISTING ROWS LOST "
                                    "(directives, query patterns, schema knowledge).\n"
                                    "\n"
                                    "  → To restore the workspace's guide library:\n"
                                    "        olav kb import-guides .olav/workspace\n"
                                    "  → To re-prime schema knowledge (netops):\n"
                                    "        olav --agent netops-init '/netops_init'\n"
                                    "\n"
                                    "If the source data isn't on disk, the memory "
                                    "cannot be recovered.\n"
                                    + "═" * 70,
                                    tname, stored_dim, self._embedding_dim,
                                )
                                self._db.drop_table(tname)
                            else:
                                raise EmbeddingDimMismatchError(
                                    table=tname,
                                    stored_dim=stored_dim,
                                    embedder_dim=self._embedding_dim,
                                )
                        break
            except EmbeddingDimMismatchError:
                raise
            except Exception as exc:
                logger.debug("dim-check skipped for %r: %s", tname, exc)

    def close(self):
        """Close database connection."""
        # LanceDB doesn't require explicit close in current version
        self._db = None

    def _get_schema(self) -> pa.Schema:
        """Get memory table schema.

        Returns:
            PyArrow schema for memory table
        """
        return pa.schema(
            [
                ("id", pa.string()),
                ("text", pa.string()),
                ("vector", pa.list_(pa.float32(), self._embedding_dim)),
                ("category", pa.string()),  # fact, decision, preference, audit
                ("scope", pa.string()),  # global, agent name, or specific scope
                ("metadata", pa.string()),  # JSON string for additional metadata
                ("timestamp", pa.timestamp("us")),
                ("created_at", pa.timestamp("us")),
                ("access_count", pa.int32()),
                ("weight", pa.float32()),  # time-decay weight
                ("origin", pa.string()),  # agent | document | user | audit
                ("confidence", pa.float32()),  # 0.0-1.0 knowledge reliability
                ("tags", pa.string()),  # JSON array of entity/topic tags
            ]
        )

    def get_schema(self, table_name: str = MEMORY_TABLE) -> pa.Schema:
        """Return the actual schema of the live table (or the spec schema if table absent).

        Args:
            table_name: Name of the table

        Returns:
            PyArrow schema
        """
        db = self.connect()
        if table_name in db.table_names():
            return db.open_table(table_name).schema
        return self._get_schema()

    def create_table(self, table_name: str = MEMORY_TABLE) -> lancedb.table.LanceTable:
        """Create memory table if not exists, and register an FTS index on the text column.

        If the table already exists but is missing the new UKS columns
        (origin, confidence, tags), they are added with safe default values
        so that existing data is preserved (C-KB-03 migration).

        Args:
            table_name: Name of the table to create

        Returns:
            LanceDB table instance
        """
        db = self.connect()

        if table_name not in db.table_names():
            schema = self._get_schema()
            tbl = db.create_table(table_name, schema=schema)
            logger.info(f"Created memory table: {table_name}")
            # Create FTS index so search_by_text uses real BM25, not LIKE
            try:
                tbl.create_fts_index("text", replace=True)
                logger.info(f"Created FTS index on '{table_name}'.text")
            except Exception as e:
                logger.debug(f"FTS index creation skipped: {e}")
            return tbl

        tbl = db.open_table(table_name)
        existing_names = {f.name for f in tbl.schema}

        # ── Vector dim migration (existing behaviour) ────────────────────────
        for field in tbl.schema:
            if field.name == "vector" and hasattr(field.type, "list_size"):
                if field.type.list_size != self._embedding_dim:
                    logger.warning(
                        "Memory table '%s' has vector dim %d but embedder is %d — "
                        "dropping and recreating (existing entries will be lost).",
                        table_name,
                        field.type.list_size,
                        self._embedding_dim,
                    )
                    db.drop_table(table_name)
                    return self.create_table(table_name)
                break

        # ── UKS Schema migration (C-KB-03): add missing columns ─────────────
        if "origin" not in existing_names:
            tbl.add_columns({"origin": "'agent'"})
            logger.info(f"Migration: added 'origin' column to '{table_name}' (default='agent')")
        if "confidence" not in existing_names:
            tbl.add_columns({"confidence": "cast(0.5 as float)"})
            logger.info(f"Migration: added 'confidence' column to '{table_name}' (default=0.5)")
        if "tags" not in existing_names:
            tbl.add_columns({"tags": "'[]'"})
            logger.info(f"Migration: added 'tags' column to '{table_name}' (default='[]')")

        return tbl

    def get_table(self, table_name: str = MEMORY_TABLE) -> lancedb.table.LanceTable:
        """Get existing memory table.

        Args:
            table_name: Name of the table

        Returns:
            LanceDB table instance

        Raises:
            ValueError: If table doesn't exist
        """
        db = self.connect()

        if table_name not in db.table_names():
            raise ValueError(f"Table {table_name} does not exist. Create it first.")

        return db.open_table(table_name)

    def get_memory(
        self,
        id: str,
        table_name: str = MEMORY_TABLE,
    ) -> dict | None:
        """Retrieve a single memory entry by ID.

        Args:
            id: Memory ID to look up
            table_name: Table to search

        Returns:
            Dict with memory fields, or None if not found
        """
        try:
            tbl = self.get_table(table_name)
            results = tbl.search().where(f"id = '{id}'").limit(1).to_list()
            if not results:
                return None
            r = results[0]
            return {k: r.get(k) for k in tbl.schema.names}
        except Exception as e:
            logger.debug(f"get_memory({id!r}) failed: {e}")
            return None

    def add_memory(
        self,
        id: str,
        text: str,
        vector: list[float],
        category: str = MemoryCategory.FACT,
        scope: str = "global",
        metadata: dict | None = None,
        table_name: str = MEMORY_TABLE,
        origin: str = "agent",
        confidence: float = 0.5,
        tags: str = "[]",
        weight: float = 1.0,
    ) -> dict:
        """Add a memory entry to the store.

        Args:
            id: Unique identifier for the memory
            text: Text content of the memory
            vector: Embedding vector for the text
            category: Memory category (fact, decision, preference, audit)
            scope: Scope for isolation (global, agent name, etc.)
            metadata: Additional metadata as dict
            table_name: Table to add to
            origin: Knowledge source — "agent" | "document" | "user" | "audit"
            confidence: Reliability score 0.0-1.0 (default 0.5 for agent captures)
            tags: JSON array string of entity/topic tags (default "[]")
            weight: Ranking weight for hybrid recall (1.0 = neutral;
                    >1 boost; <1 suppress).  2026-05-14: used by
                    search_by_text to multiply BM25 score so high-priority
                    usage_guide entries outrank operational_event noise.

        Returns:
            Dict with status and message
        """
        # Vector dim guard — refuse rather than write a malformed row.
        # Earlier code paths trusted callers; a transient embedder
        # fallback (api → local) could feed a wrong-dim vector, then
        # _check_and_migrate_vector_dim would silently drop the table on
        # next start.  Reject upfront — the caller decides how to recover.
        if vector is not None and len(vector) != self._embedding_dim:
            logger.warning(
                "add_memory: rejecting wrong-dim vector for id=%r "
                "(got %d, expected %d).  Caller should fix embedder.",
                id, len(vector), self._embedding_dim,
            )
            return {
                "status": "error",
                "reason": (
                    f"vector dim {len(vector)} != store embedding_dim "
                    f"{self._embedding_dim}; refusing write to avoid "
                    f"corrupting the table"
                ),
            }

        # Injection scan — reject hostile content before writing to memory
        is_clean, match = _scan_content(text)
        if not is_clean:
            logger.warning(
                "InjectionScanner blocked memory write: category=%s pattern=%r snippet=%r",
                match.category,  # type: ignore[union-attr]
                match.matched_pattern,  # type: ignore[union-attr]
                match.matched_text[:60],  # type: ignore[union-attr]
            )
            return {
                "status": "blocked",
                "reason": f"Injection pattern detected: {match.category}",  # type: ignore[union-attr]
            }

        try:
            # Ensure table exists
            if not self.table_exists(table_name):
                self.create_table(table_name)

            tbl = self.get_table(table_name)

            now = datetime.now(UTC)
            metadata_json = json.dumps(metadata) if metadata else "{}"

            # Create record
            record = pa.table(
                [
                    pa.array([id]),
                    pa.array([text]),
                    pa.array([vector]),
                    pa.array([category]),
                    pa.array([scope]),
                    pa.array([metadata_json]),
                    pa.array([now]),
                    pa.array([now]),
                    pa.array([1]),  # access_count
                    pa.array([float(weight)]),  # configurable weight
                    pa.array([origin]),
                    pa.array([confidence], type=pa.float32()),
                    pa.array([tags]),
                ],
                schema=self._get_schema(),
            )

            tbl.add(record)

            # ── FTS index maintenance ───────────────────────────────────────
            # LanceDB FTS is a static index: newly added rows are invisible to
            # BM25 search until the index is rebuilt.  We rebuild lazily every
            # `_fts_rebuild_threshold` writes so BM25 stays fresh without
            # paying the rebuild cost on every single insert.
            self._fts_dirty[table_name] = self._fts_dirty.get(table_name, 0) + 1
            if self._fts_dirty[table_name] >= self._fts_rebuild_threshold:
                try:
                    tbl.create_fts_index("text", replace=True)
                    logger.debug(
                        f"FTS index rebuilt for '{table_name}' after "
                        f"{self._fts_dirty[table_name]} writes."
                    )
                except Exception as _fts_err:
                    logger.debug(f"FTS rebuild skipped: {_fts_err}")
                self._fts_dirty[table_name] = 0

            logger.info(f"Added memory: {id} (category: {category}, scope: {scope})")
            return {"status": "success", "id": id, "message": "Memory added successfully"}

        except Exception as e:
            logger.error(f"Failed to add memory {id}: {e}")
            return {"status": "error", "message": str(e)}

    def search_by_vector(
        self,
        query_vector: list[float],
        limit: int = 10,
        category: str | None = None,
        scope: str | None = None,
        table_name: str = MEMORY_TABLE,
    ) -> list[dict]:
        """Search memories by vector similarity.

        Args:
            query_vector: Query embedding vector
            limit: Maximum number of results
            category: Optional category filter
            scope: Optional scope filter
            table_name: Table to search

        Returns:
            List of matching memories with scores
        """
        try:
            tbl = self.get_table(table_name)

            # Build filter conditions using where()
            # Only apply scope filter for memory table
            where_clauses = []
            if category and table_name == MEMORY_TABLE:
                where_clauses.append(f"category = '{category}'")
            if scope and table_name == MEMORY_TABLE:
                where_clauses.append(f"(scope = 'global' OR scope = '{scope}')")

            where_sql = " AND ".join(where_clauses) if where_clauses else None

            # Execute vector search
            query = tbl.search(query_vector, vector_column_name="vector")

            if where_sql:
                query = query.where(where_sql)

            results = query.limit(limit).to_list()

            # Format results
            memories = []
            for r in results:
                memories.append(
                    {
                        "id": r.get("id"),
                        "text": r.get("text"),
                        "category": r.get("category"),
                        "scope": r.get("scope"),
                        "metadata": r.get("metadata"),
                        "timestamp": r.get("timestamp"),
                        "weight": r.get("weight"),
                        "access_count": r.get("access_count"),
                        "origin": r.get("origin", "agent"),
                        "confidence": r.get("confidence", 0.5),
                        "tags": r.get("tags", "[]"),
                        "score": r.get("_distance"),  # LanceDB provides distance
                        "vector": r.get("vector"),
                    }
                )

            return memories

        except Exception as e:
            logger.debug(f"Vector search failed: {e}")
            return []

    def search_by_text(
        self,
        query: str,
        limit: int = 10,
        category: str | None = None,
        scope: str | None = None,
        table_name: str = MEMORY_TABLE,
    ) -> list[dict]:
        """Search memories by text (full-text search).

        Note: This requires FTS to be enabled on the table.
        For now, falls back to simple text containment.

        Args:
            query: Text query
            limit: Maximum number of results
            category: Optional category filter
            scope: Optional scope filter
            table_name: Table to search

        Returns:
            List of matching memories
        """
        try:
            tbl = self.get_table(table_name)

            # Use LanceDB native FTS (BM25) when an FTS index exists.
            # Falls back to a safe filter search if FTS is unavailable.
            try:
                search_q = tbl.search(query, query_type="fts")
            except Exception:
                # FTS index not built yet — sanitise query to prevent SQL injection
                safe_query = query.replace("'", "")
                search_q = tbl.search().where(f"text LIKE '%{safe_query}%'")

            # Post-filter by category / scope (only for memory table)
            where_clauses = []
            if category and table_name == MEMORY_TABLE:
                where_clauses.append(f"category = '{category}'")
            if scope and table_name == MEMORY_TABLE:
                where_clauses.append(f"(scope = 'global' OR scope = '{scope}')")
            if where_clauses:
                search_q = search_q.where(" AND ".join(where_clauses))

            # 2026-05-14 weight-aware reranking: fetch 3x candidates, then
            # rank by ``_score * weight`` so high-priority usage_guide rows
            # outrank low-priority operational_event rows even when BM25
            # similarity is comparable.  Weight is set at insert time
            # (guide_kb.py from priority field; operational_event_capture
            # writes weight=0.5).
            raw = search_q.limit(limit * 3).to_list()
            for r in raw:
                w = r.get("weight") or 1.0
                s = r.get("_score") or r.get("score") or 1.0
                r["_effective_score"] = float(s) * float(w)
            raw.sort(key=lambda r: r["_effective_score"], reverse=True)
            results = raw[:limit]

            return [
                {
                    "id": r.get("id"),
                    "text": r.get("text"),
                    "category": r.get("category"),
                    "scope": r.get("scope"),
                    "origin": r.get("origin", "agent"),
                    "confidence": r.get("confidence", 0.5),
                    "weight": r.get("weight", 1.0),
                    "tags": r.get("tags", "[]"),
                    "metadata": r.get("metadata"),
                    "timestamp": r.get("timestamp"),
                }
                for r in results
            ]

        except Exception as e:
            logger.error(f"Text search failed: {e}")
            return []

    def get_memories(
        self,
        category: str | None = None,
        scope: str | None = None,
        limit: int = 100,
        table_name: str = MEMORY_TABLE,
    ) -> list[dict]:
        """Get memories with optional filters.

        Args:
            category: Optional category filter
            scope: Optional scope filter
            limit: Maximum number of results
            table_name: Table to query

        Returns:
            List of memories
        """
        try:
            tbl = self.get_table(table_name)

            # Build filter using where() (only for memory table)
            where_clauses = []
            if category and table_name == MEMORY_TABLE:
                where_clauses.append(f"category = '{category}'")
            if scope and table_name == MEMORY_TABLE:
                where_clauses.append(f"(scope = 'global' OR scope = '{scope}')")

            where_sql = " AND ".join(where_clauses) if where_clauses else None

            # Execute query using search().where().limit()
            if where_sql:
                results = tbl.search().where(where_sql).limit(limit).to_list()
            else:
                results = tbl.search().limit(limit).to_list()

            return [
                {
                    "id": r.get("id"),
                    "text": r.get("text"),
                    "category": r.get("category"),
                    "scope": r.get("scope"),
                    "metadata": r.get("metadata"),
                    "timestamp": r.get("timestamp"),
                    "weight": r.get("weight"),
                    "access_count": r.get("access_count"),
                    "origin": r.get("origin", "agent"),
                    "confidence": r.get("confidence", 0.5),
                    "tags": r.get("tags", "[]"),
                    "vector": r.get("vector"),
                }
                for r in results
            ]

        except Exception as e:
            logger.error(f"Failed to get memories: {e}")
            return []

    def delete_memory(
        self,
        id: str,
        table_name: str = MEMORY_TABLE,
    ) -> dict:
        """Delete a memory entry.

        Args:
            id: ID of the memory to delete
            table_name: Table to delete from

        Returns:
            Dict with status
        """
        try:
            tbl = self.get_table(table_name)
            tbl.delete(f"id = '{id}'")
            logger.info(f"Deleted memory: {id}")
            return {"status": "success", "id": id}

        except Exception as e:
            logger.error(f"Failed to delete memory {id}: {e}")
            return {"status": "error", "message": str(e)}

    def update_weight(
        self,
        id: str,
        weight: float,
        table_name: str = MEMORY_TABLE,
    ) -> dict:
        """Update memory weight (for time-decay).

        Args:
            id: ID of the memory
            weight: New weight value
            table_name: Table to update

        Returns:
            Dict with status
        """
        try:
            tbl = self.get_table(table_name)
            tbl.update(where=f"id = '{id}'", values={"weight": weight})
            return {"status": "success", "id": id}

        except Exception as e:
            logger.error(f"Failed to update weight for {id}: {e}")
            return {"status": "error", "message": str(e)}

    def update_memory(
        self,
        id: str,
        table_name: str = MEMORY_TABLE,
        **fields,
    ) -> dict:
        """Update arbitrary fields on a memory entry (for migration / enrichment).

        Only columns present in the schema are accepted; unknown keys are ignored.

        Args:
            id: ID of the memory to update
            table_name: Table to update
            **fields: Field→value pairs to update (e.g. origin="agent", confidence=0.8)

        Returns:
            Dict with status
        """
        try:
            tbl = self.get_table(table_name)
            valid = {f.name for f in tbl.schema}
            values = {k: v for k, v in fields.items() if k in valid}
            if not values:
                return {"status": "noop", "id": id}
            tbl.update(where=f"id = '{id}'", values=values)
            return {"status": "success", "id": id}
        except Exception as e:
            logger.error(f"Failed to update memory {id}: {e}")
            return {"status": "error", "message": str(e)}

    def get_table_names(self) -> list[str]:
        """Get list of table names in the database.

        Returns:
            List of table names
        """
        db = self.connect()
        return db.table_names()  # type: ignore[returnValue]

    def table_exists(self, table_name: str) -> bool:
        """Check if a table exists.

        Args:
            table_name: Name of the table

        Returns:
            True if table exists
        """
        return table_name in self.get_table_names()


# Singleton instance for convenience
_store_instance: LanceDBStore | None = None
_store_db_path: str | Path | None = None
_store_embedding_dim: int | None = None
_store_lock = threading.Lock()


def _detect_embedding_dim() -> int:
    """Return the active embedder's output dimension via probe.

    Delegates to ``embedder.detect_embedding_dim()`` which runs an actual
    embedding probe and caches the result.  All LanceDB tables in the process
    share the same detected dimension.
    """
    try:
        from olav.core.embedder import detect_embedding_dim
        return detect_embedding_dim()
    except Exception:
        return 512


def get_store(
    db_path: str | Path | None = None,
    embedding_dim: int | None = None,
) -> LanceDBStore:
    """Get or create LanceDB store singleton.

    ``embedding_dim`` defaults to the active embedder's output dimension so
    the LanceDB table schema always matches the vectors being written.  Pass
    an explicit value only in tests or when you know the dimension up-front.

    Args:
        db_path: Optional database path override
        embedding_dim: Embedding dimension (auto-detected from embedder if None)

    Returns:
        LanceDBStore instance
    """
    global _store_instance, _store_db_path, _store_embedding_dim

    if embedding_dim is None:
        embedding_dim = _detect_embedding_dim()

    with _store_lock:
        if (
            _store_instance is None
            or db_path != _store_db_path
            or embedding_dim != _store_embedding_dim
        ):
            if db_path is not None:
                _store_db_path = db_path
            _store_embedding_dim = embedding_dim
            _store_instance = LanceDBStore(db_path=db_path, embedding_dim=embedding_dim)

        return _store_instance


def reset_store():
    """Reset the singleton store instance."""
    global _store_instance

    with _store_lock:
        if _store_instance:
            _store_instance.close()
            _store_instance = None


class SemanticCache:
    """Tier-0 in-memory Semantic Cache for hybrid_search() results.

    When a query vector is within `threshold` cosine distance of a previously
    cached query, the stored results are returned immediately — bypassing the
    full vector + BM25 pipeline.  Cache entries are evicted after `ttl_hours`
    hours or when the store exceeds `max_entries` rows.

    In-memory is appropriate here: TTL ≤24h means entries expire before
    typical service restarts, so disk persistence adds overhead with no benefit.
    Class-level shared state ensures all instances (including those created
    just to call invalidate_all()) access the same cache.

    Implements §4 of LANCEDB_MEMORY_SYSTEM_INTEGRATION.md:
        "If a query is 98% similar to a frequent cached request, return the
        cached answer immediately."
    """

    # Shared across all instances — (query_vector, results, timestamp_seconds)
    _entries: list[tuple[list[float], list[dict], float]] = []
    _lock = threading.Lock()

    # LEGACY-KEEP: ARCH-22 C5 — ``store`` / ``table_name`` kwargs retained
    # for compat. The cache has been in-memory since v0.14; the kwargs
    # remain only so that old callers don't hit a TypeError. Round 50
    # added a ``DeprecationWarning`` when callers pass non-default values
    # so the next major can drop the kwargs without surprising anyone.
    _DEFAULT_TABLE_NAME = "query_cache"

    def __init__(
        self,
        store=None,  # LEGACY-KEEP: no-op since v0.14 (ARCH-22 C5)
        threshold: float = 0.02,
        ttl_hours: int = 24,
        max_entries: int = 500,
        table_name: str = _DEFAULT_TABLE_NAME,  # LEGACY-KEEP: no-op since v0.14 (ARCH-22 C5)
    ) -> None:
        if store is not None:
            import warnings
            warnings.warn(
                "SemanticCache(store=...) is deprecated and has been ignored "
                "since v0.14 (cache is process-local). The parameter will be "
                "removed in the next major release — drop the argument.",
                DeprecationWarning,
                stacklevel=2,
            )
        if table_name != self._DEFAULT_TABLE_NAME:
            import warnings
            warnings.warn(
                f"SemanticCache(table_name={table_name!r}) is deprecated — "
                f"the cache is process-local and does not use a DuckDB table. "
                f"The parameter will be removed in the next major release.",
                DeprecationWarning,
                stacklevel=2,
            )
        self._threshold = threshold
        self._ttl_seconds = ttl_hours * 3600
        self._max_entries = max_entries

    @staticmethod
    def _cosine_distance(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        mag_a = math.sqrt(sum(x * x for x in a))
        mag_b = math.sqrt(sum(x * x for x in b))
        if mag_a == 0.0 or mag_b == 0.0:
            return 1.0
        return 1.0 - dot / (mag_a * mag_b)

    def get(
        self,
        query_vector: list[float],
        *,
        recorder=None,
        run_id: str | None = None,
    ) -> list[dict] | None:
        """Return cached results if a very similar query was seen recently.

        Returns None on cache miss or any error (non-fatal).
        """
        try:
            now = time.time()
            best_dist = 1.0
            best_result: list[dict] | None = None
            with SemanticCache._lock:
                for vec, results, ts in SemanticCache._entries:
                    if now - ts > self._ttl_seconds:
                        continue  # expired
                    dist = self._cosine_distance(query_vector, vec)
                    if dist < best_dist:
                        best_dist = dist
                        best_result = results
            if best_dist <= self._threshold and best_result is not None:
                logger.debug("SemanticCache: hit (distance=%.4f)", best_dist)
                if recorder is not None and run_id is not None:
                    recorder.record(
                        event_type="semantic_cache_hit",
                        run_id=run_id,
                        payload={"distance": best_dist},
                    )
                return best_result
        except Exception as e:
            logger.debug(f"SemanticCache.get error (non-fatal): {e}")
        return None

    def put(self, query_vector: list[float], results: list[dict]) -> None:
        """Store search results keyed by query vector."""
        try:
            now = time.time()
            with SemanticCache._lock:
                # Evict expired entries first
                SemanticCache._entries = [
                    (v, r, ts)
                    for v, r, ts in SemanticCache._entries
                    if now - ts <= self._ttl_seconds
                ]
                # Trim to max_entries (drop oldest)
                if len(SemanticCache._entries) >= self._max_entries:
                    SemanticCache._entries = SemanticCache._entries[-(self._max_entries - 1):]
                SemanticCache._entries.append((query_vector, results, now))
        except Exception as e:
            logger.debug(f"SemanticCache.put error (non-fatal): {e}")

    def invalidate_all(self) -> None:
        """Clear the entire in-memory cache."""
        try:
            with SemanticCache._lock:
                SemanticCache._entries.clear()
            logger.debug("SemanticCache: invalidated all entries.")
        except Exception as e:
            logger.debug(f"SemanticCache.invalidate_all error: {e}")


def rrf_fusion(
    result_lists: list[list[dict]],
    k: int = 60,
    apply_weight_boost: bool = True,
    list_weights: list[float] | None = None,
) -> list[dict]:
    """Reciprocal Rank Fusion (RRF) to combine multiple result lists.

    RRF is a simple but effective method for combining rankings from multiple
    retrieval systems without requiring training data.

    The RRF score for a document is calculated as:
        score = sum(1 / (k + rank)) for each list where the document appears

    If ``apply_weight_boost`` is True (default), the RRF score is multiplied by
    the document's stored ``weight`` field (set by time-decay).  This ensures
    that recently-accessed memories with high weight rank above stale ones even
    when the raw semantic similarity is similar — implementing the **recency
    boost** described in the LANCEDB_MEMORY_SYSTEM_INTEGRATION design.

    Args:
        result_lists: List of result lists, each containing dicts with 'id' and optional 'score'
        k: RRF parameter (default 60). Higher values reduce the impact of high ranks.
        apply_weight_boost: Multiply final RRF score by the document weight (default True).
        list_weights: Per-list scaling factors (e.g. [0.7, 0.3] for 70% vector / 30% text).
                      When None every list contributes equally (weight 1.0).

    Returns:
        Combined and reranked list of results

    Example:
        >>> vector_results = [{"id": "a", "score": 0.9}, {"id": "b", "score": 0.8}]
        >>> text_results = [{"id": "b", "score": 0.9}, {"id": "c", "score": 0.8}]
        >>> fused = rrf_fusion([vector_results, text_results])
    """
    if not result_lists:
        return []

    # Build document scores from all lists
    doc_scores: dict[str, float] = {}
    doc_data: dict[str, dict] = {}

    for list_idx, result_list in enumerate(result_lists):
        if not result_list:
            continue

        # Per-list weight scaling (implements vector_weight / text_weight)
        list_w = list_weights[list_idx] if list_weights and list_idx < len(list_weights) else 1.0

        for rank, doc in enumerate(result_list, start=1):
            doc_id = doc.get("id") or doc.get("_id")
            if not doc_id:
                continue

            # Weighted RRF score: list_w / (k + rank)
            rrf_score = list_w / (k + rank)
            doc_scores[doc_id] = doc_scores.get(doc_id, 0.0) + rrf_score

            # Store document data (use first occurrence)
            if doc_id not in doc_data:
                doc_data[doc_id] = doc

    # Apply recency boost: multiply by stored weight (time-decay sets weight=1.0
    # for new memories, decaying toward 0.1 for old ones).
    if apply_weight_boost:
        for doc_id in doc_scores:
            weight = float(doc_data[doc_id].get("weight") or 1.0)
            doc_scores[doc_id] *= weight

    # Sort by final score descending
    sorted_ids = sorted(doc_scores.items(), key=lambda x: x[1], reverse=True)

    # Build final result list
    results = []
    for doc_id, rrf_score in sorted_ids:
        doc = doc_data[doc_id].copy()
        doc["rrf_score"] = rrf_score
        results.append(doc)

    return results


def hybrid_search(
    store: LanceDBStore,
    query: str,
    query_vector: list[float],
    limit: int = 10,
    category: str | None = None,
    scope: str | None = None,
    rrf_k: int = 60,
    vector_weight: float = 0.5,
    text_weight: float = 0.5,
    use_cache: bool = True,
    table_name: str = MEMORY_TABLE,
) -> list[dict]:
    """Perform hybrid search combining vector and text search.

    This function combines vector similarity search with full-text search
    using weighted RRF fusion.  Before running the full search pipeline it
    checks the Tier-0 Semantic Cache — if a ≥98% similar query was executed
    recently the cached results are returned immediately.

    Args:
        store: LanceDBStore instance.
        query: Text query for full-text search (BM25).
        query_vector: Embedding vector for similarity search.
        limit: Maximum number of results.
        category: Optional category filter.
        scope: Optional scope filter.
        rrf_k: RRF parameter for fusion.
        vector_weight: Relative weight for the vector search list (default 0.5).
        text_weight: Relative weight for the BM25 search list (default 0.5).
        use_cache: Enable Tier-0 semantic cache (default True).
        table_name: Table to search (default ``MEMORY_TABLE`` — the unified
            memory store; see dev_docs/43 for the design rationale).

    Returns:
        Combined and reranked list of results.
    """
    # ── Tier-0 Semantic Cache ─────────────────────────────────────────────────
    cache: SemanticCache | None = None
    if use_cache and query_vector:
        try:
            from olav.core.config import get_memory_config

            cfg = get_memory_config()
            cache = SemanticCache(
                store,
                threshold=cfg.cache_similarity_threshold,
                ttl_hours=cfg.cache_ttl_hours,
                max_entries=cfg.cache_max_entries,
            )
        except Exception:
            cache = SemanticCache(store)

        cached = cache.get(query_vector)
        if cached is not None:
            logger.debug("hybrid_search: Tier-0 cache hit — skipping vector+BM25 pipeline")
            return cached[:limit]

    # ── Full hybrid search ────────────────────────────────────────────────────
    vector_results = store.search_by_vector(
        query_vector,
        limit=limit * 2,  # over-fetch to account for post-filter losses
        category=category,
        scope=scope,
        table_name=table_name,
    )

    text_results = store.search_by_text(
        query,
        limit=limit * 2,
        category=category,
        scope=scope,
        table_name=table_name,
    )

    # Weighted RRF fusion — vector_weight and text_weight now actually used
    fused_results = rrf_fusion(
        [vector_results, text_results],
        k=rrf_k,
        list_weights=[vector_weight, text_weight],
    )
    results = fused_results[:limit]

    # Store results in Tier-0 cache for future identical queries
    if cache is not None:
        cache.put(query_vector, results)

    return results


def store_event(
    store: LanceDBStore,
    summary: str,
    device: str | None = None,
    event_type: str | None = None,
    scope: str = "global",
    embedder=None,
    table_name: str = MEMORY_TABLE,
) -> dict:
    """Store a high-level episode summary in LanceDB memory.

    Implements the **Event Memory** component from the OCM design:
    only summarized, high-level anomalies/episodes are stored here, NOT
    raw system logs or raw CLI output.

    Examples of appropriate summaries:
        - "Datacenter-A experienced service degradation from 10:00 to 10:15"
        - "Scheduled maintenance on host-2 completed with 3 warnings"
        - "Disk usage on storage-01 exceeded 90% threshold on 2026-03-01"

    Args:
        store:       LanceDBStore instance.
        summary:     Human-readable episode summary (required).
        device:      Primary device involved (optional, stored in metadata).
        event_type:  Short label, e.g. "degradation", "maintenance", "threshold-breach".
        scope:       Memory scope — usually the agent or global.
        embedder:    Optional SentenceTransformer model. If None, a zero-vector
                     is used (memory will be text-searched only).
        table_name:  Override the default table name.

    Returns:
        Result dict: {"status": "success", "id": "...", "message": "..."}.
    """
    import uuid

    if not store.table_exists(table_name):
        store.create_table(table_name)

    # Embed the summary
    vector: list[float]
    if embedder is not None:
        try:
            vector = embedder.encode(summary, normalize_embeddings=True).tolist()
        except Exception:
            vector = [0.0] * store.embedding_dim
    else:
        vector = [0.0] * store.embedding_dim

    memory_id = f"evt-{uuid.uuid4().hex[:8]}"
    metadata: dict = {"source": "network_event"}
    if device:
        metadata["device"] = device
    if event_type:
        metadata["event_type"] = event_type

    return store.add_memory(
        id=memory_id,
        text=summary,
        vector=vector,
        category=MemoryCategory.AUDIT,
        scope=scope,
        metadata=metadata,
        table_name=table_name,
    )
