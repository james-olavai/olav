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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import lancedb
import pyarrow as pa

logger = logging.getLogger(__name__)

# Default LanceDB database path
DEFAULT_MEMORY_DB = ".olav/databases/memory.lance"

# Memory table name
MEMORY_TABLE = "memory"

# Semantic cache table name (Tier-0 cache)
CACHE_TABLE = "query_cache"


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

    def __init__(self, db_path: str | Path | None = None, embedding_dim: int = 384):
        """Initialize LanceDB store.

        Args:
            db_path: Path to LanceDB database. Defaults to DEFAULT_MEMORY_DB
            embedding_dim: Dimension of embedding vectors. Default 384 (bge-small)
        """
        self._db_path = Path(db_path) if db_path else self._get_default_db_path()
        self._embedding_dim = embedding_dim
        self._db: lancedb.LanceDBConnection | None = None
        # FTS dirty tracking: rebuild index after N writes to keep BM25 fresh
        self._fts_dirty: dict[str, int] = {}
        self._fts_rebuild_threshold: int = self._load_fts_threshold()
        self._ensure_database()

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
        return self._db  # type: ignore[returnValue]

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
            ]
        )

    def create_table(self, table_name: str = MEMORY_TABLE) -> lancedb.table.LanceTable:
        """Create memory table if not exists, and register an FTS index on the text column.

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

        return db.open_table(table_name)

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

    def add_memory(
        self,
        id: str,
        text: str,
        vector: list[float],
        category: str = MemoryCategory.FACT,
        scope: str = "global",
        metadata: dict | None = None,
        table_name: str = MEMORY_TABLE,
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

        Returns:
            Dict with status and message
        """
        try:
            # Ensure table exists
            if not self.table_exists(table_name):
                self.create_table(table_name)

            tbl = self.get_table(table_name)

            now = datetime.now()
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
                    pa.array([1.0]),  # initial weight
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
            where_clauses = []
            if category:
                where_clauses.append(f"category = '{category}'")
            if scope:
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
                        "score": r.get("_distance"),  # LanceDB provides distance
                    }
                )

            return memories

        except Exception as e:
            logger.error(f"Vector search failed: {e}")
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

            # Post-filter by category / scope
            where_clauses = []
            if category:
                where_clauses.append(f"category = '{category}'")
            if scope:
                where_clauses.append(f"(scope = 'global' OR scope = '{scope}')")
            if where_clauses:
                search_q = search_q.where(" AND ".join(where_clauses))

            results = search_q.limit(limit).to_list()

            return [
                {
                    "id": r.get("id"),
                    "text": r.get("text"),
                    "category": r.get("category"),
                    "scope": r.get("scope"),
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

            # Build filter using where()
            where_clauses = []
            if category:
                where_clauses.append(f"category = '{category}'")
            if scope:
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


def get_store(
    db_path: str | Path | None = None,
    embedding_dim: int = 384,
) -> LanceDBStore:
    """Get or create LanceDB store singleton.

    Args:
        db_path: Optional database path override
        embedding_dim: Embedding dimension

    Returns:
        LanceDBStore instance
    """
    global _store_instance, _store_db_path

    # Create new instance if path or embedding_dim differs
    if _store_instance is None or db_path != _store_db_path:
        if db_path is not None:
            _store_db_path = db_path
        _store_instance = LanceDBStore(db_path=db_path, embedding_dim=embedding_dim)

    return _store_instance


def reset_store():
    """Reset the singleton store instance."""
    global _store_instance

    if _store_instance:
        _store_instance.close()
        _store_instance = None


def _get_cache_schema(embedding_dim: int) -> pa.Schema:
    """PyArrow schema for the semantic cache table."""
    return pa.schema(
        [
            ("id", pa.string()),
            ("query_vector", pa.list_(pa.float32(), embedding_dim)),
            ("result_json", pa.string()),
            ("created_at", pa.timestamp("us")),
        ]
    )


class SemanticCache:
    """Tier-0 Semantic Cache for hybrid_search() results.

    When a query vector is within `threshold` cosine distance of a previously
    cached query, the stored results are returned immediately — bypassing the
    full vector + BM25 pipeline.  Cache entries are evicted after `ttl_hours`
    hours or when the table exceeds `max_entries` rows.

    Implements §4 of LANCEDB_MEMORY_SYSTEM_INTEGRATION.md:
        "If a query is 98% similar to a frequent cached request, return the
        cached answer immediately."
    """

    def __init__(
        self,
        store: "LanceDBStore",
        threshold: float = 0.02,
        ttl_hours: int = 24,
        max_entries: int = 500,
    ) -> None:
        self._store = store
        self._threshold = threshold
        self._ttl_hours = ttl_hours
        self._max_entries = max_entries

    def _ensure_table(self) -> "lancedb.table.LanceTable":
        db = self._store.connect()
        if CACHE_TABLE not in db.table_names():
            schema = _get_cache_schema(self._store.embedding_dim)
            tbl = db.create_table(CACHE_TABLE, schema=schema)
            logger.debug(f"Created semantic cache table: {CACHE_TABLE}")
            return tbl
        return db.open_table(CACHE_TABLE)

    def get(self, query_vector: list[float]) -> list[dict] | None:
        """Return cached results if a very similar query was seen recently.

        Returns None on cache miss or any error (non-fatal).
        """
        try:
            tbl = self._ensure_table()
            if tbl.count_rows() == 0:
                return None

            hits = (
                tbl.search(query_vector, vector_column_name="query_vector")
                .limit(1)
                .to_list()
            )
            if not hits:
                return None

            hit = hits[0]
            if hit.get("_distance", 1.0) > self._threshold:
                return None  # not similar enough

            # TTL check
            created_at = hit.get("created_at")
            if created_at is not None:
                if isinstance(created_at, datetime):
                    if created_at.tzinfo is None:
                        created_at = created_at.replace(tzinfo=timezone.utc)
                    age_hours = (datetime.now(timezone.utc) - created_at).total_seconds() / 3600
                    if age_hours > self._ttl_hours:
                        return None  # expired

            logger.debug("SemanticCache: hit (distance=%.4f)", hit["_distance"])
            return json.loads(hit["result_json"])

        except Exception as e:
            logger.debug(f"SemanticCache.get error (non-fatal): {e}")
            return None

    def put(self, query_vector: list[float], results: list[dict]) -> None:
        """Store search results keyed by query vector."""
        try:
            import uuid

            tbl = self._ensure_table()
            entry_id = f"cache-{uuid.uuid4().hex[:8]}"
            record = pa.table(
                [
                    pa.array([entry_id]),
                    pa.array([query_vector]),
                    pa.array([json.dumps(results, default=str)]),
                    pa.array([datetime.now()]),
                ],
                schema=_get_cache_schema(self._store.embedding_dim),
            )
            tbl.add(record)

            # Evict oldest entries when over capacity
            try:
                count = tbl.count_rows()
                if count > self._max_entries:
                    overflow = count - self._max_entries
                    oldest = (
                        tbl.search()
                        .limit(overflow)
                        .to_list()
                    )
                    for row in oldest:
                        if row.get("id"):
                            tbl.delete(f"id = '{row['id']}'")
            except Exception:
                pass  # eviction failure is non-fatal

        except Exception as e:
            logger.debug(f"SemanticCache.put error (non-fatal): {e}")

    def invalidate_all(self) -> None:
        """Drop the entire cache table."""
        try:
            db = self._store.connect()
            if CACHE_TABLE in db.table_names():
                db.drop_table(CACHE_TABLE)
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
        list_w = (
            list_weights[list_idx]
            if list_weights and list_idx < len(list_weights)
            else 1.0
        )

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
    )

    text_results = store.search_by_text(
        query,
        limit=limit * 2,
        category=category,
        scope=scope,
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


def store_network_event(
    store: LanceDBStore,
    summary: str,
    device: str | None = None,
    event_type: str | None = None,
    scope: str = "global",
    embedder=None,
    table_name: str = MEMORY_TABLE,
) -> dict:
    """Store a high-level network episode summary in LanceDB memory.

    Implements the **Network Event Memory** component from the OCM design:
    only summarized, high-level anomalies/episodes are stored here, NOT
    raw system logs or raw CLI output.

    Examples of appropriate summaries:
        - "Datacenter-A experienced BGP flaps from 10:00 to 10:15"
        - "OSPF adjacency dropped between R1 and R2 due to MTU mismatch"
        - "Interface Gi0/1 on Core-SW bounced 3 times in 2026-03-01"

    Args:
        store:       LanceDBStore instance.
        summary:     Human-readable episode summary (required).
        device:      Primary device involved (optional, stored in metadata).
        event_type:  Short label, e.g. "bgp-flap", "ospf-drop", "interface-bounce".
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
