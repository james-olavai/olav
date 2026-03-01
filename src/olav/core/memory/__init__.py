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
from datetime import datetime
from pathlib import Path
from typing import Any

import lancedb
import pyarrow as pa

logger = logging.getLogger(__name__)

# Default LanceDB database path
DEFAULT_MEMORY_DB = ".olav/databases/memory.lance"

# Memory table name
MEMORY_TABLE = "memory"


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
        self._ensure_database()

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
        """Create memory table if not exists.

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

            # Build filter using where()
            where_clauses = [f"text LIKE '%{query}%'"]
            if category:
                where_clauses.append(f"category = '{category}'")
            if scope:
                where_clauses.append(f"(scope = 'global' OR scope = '{scope}')")

            where_sql = " AND ".join(where_clauses)

            # Execute search - use search without vector for text-only
            results = tbl.search().where(where_sql).limit(limit).to_list()

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


def rrf_fusion(
    result_lists: list[list[dict]],
    k: int = 60,
) -> list[dict]:
    """Reciprocal Rank Fusion (RRF) to combine multiple result lists.

    RRF is a simple but effective method for combining rankings from multiple
    retrieval systems without requiring training data.

    The RRF score for a document is calculated as:
        score = sum(1 / (k + rank)) for each list where the document appears

    Args:
        result_lists: List of result lists, each containing dicts with 'id' and optional 'score'
        k: RRF parameter (default 60). Higher values reduce the impact of high ranks.

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

    for result_list in result_lists:
        if not result_list:
            continue

        for rank, doc in enumerate(result_list, start=1):
            doc_id = doc.get("id") or doc.get("_id")
            if not doc_id:
                continue

            # Add RRF score
            rrf_score = 1.0 / (k + rank)
            doc_scores[doc_id] = doc_scores.get(doc_id, 0.0) + rrf_score

            # Store document data (use first occurrence)
            if doc_id not in doc_data:
                doc_data[doc_id] = doc

    # Sort by RRF score descending
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
) -> list[dict]:
    """Perform hybrid search combining vector and text search.

    This function combines vector similarity search with full-text search
    using RRF fusion to get the best of both approaches.

    Args:
        store: LanceDBStore instance
        query: Text query for full-text search
        query_vector: Embedding vector for similarity search
        limit: Maximum number of results
        category: Optional category filter
        scope: Optional scope filter
        rrf_k: RRF parameter for fusion
        vector_weight: Weight for vector search results (for future weighted fusion)
        text_weight: Weight for text search results

    Returns:
        Combined and reranked list of results
    """
    # Execute both searches in parallel
    vector_results = store.search_by_vector(
        query_vector,
        limit=limit * 2,  # Get more to account for filtering
        category=category,
        scope=scope,
    )

    text_results = store.search_by_text(
        query,
        limit=limit * 2,
        category=category,
        scope=scope,
    )

    # Apply RRF fusion
    fused_results = rrf_fusion([vector_results, text_results], k=rrf_k)

    return fused_results[:limit]
