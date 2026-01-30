"""Semantic Memory Manager with Namespace Isolation.

Implements the memory system for the v0.10.x architecture:
- Namespace isolation for different specialists (Global, SQL, CLI, Orchestrator)
- Semantic search using vector embeddings
- User correction support via upsert
- Integration with DuckDB semantic_cache table

Roadmap: Phase 3 - Semantic Memory (Memory Manager)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from olav.core.embeddings import Embedder, get_embedder
from olav.core.unified_database import UnifiedDatabase

logger = logging.getLogger(__name__)


# =============================================================================
# Namespace Definition
# =============================================================================


class Namespace(str, Enum):
    """Memory namespaces for specialist isolation.

    Each specialist has its own memory space to avoid knowledge pollution.
    """

    GLOBAL = "global"  # Orchestrator-level planning
    SQL = "sql"  # SQL Specialist: NL → SQL mappings
    CLI = "cli"  # CLI Specialist: NL → CLI command mappings
    ORCHESTRATOR = "orchestrator"  # Orchestrator: intent → plan mappings


# =============================================================================
# Memory Record
# =============================================================================


@dataclass
class MemoryRecord:
    """A single memory record with embedding.

    Attributes:
        query: User's natural language query
        namespace: Memory namespace (for isolation)
        action: Associated action (SQL, CLI command, plan, etc.)
        embedding: Vector embedding for semantic search
        confidence: Confidence score (0-1)
        metadata: Additional metadata as dict
    """

    query: str
    namespace: Namespace
    action: str
    embedding: list[float]
    confidence: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "query": self.query,
            "namespace": self.namespace.value,
            "action": self.action,
            "embedding": self.embedding,
            "confidence": self.confidence,
            "metadata": json.dumps(self.metadata),
        }


# =============================================================================
# Memory Manager
# =============================================================================


class MemoryManager:
    """Semantic Memory Manager with namespace isolation.

    Manages vector-based memory storage and retrieval for OLAV specialists.
    Each namespace (Global, SQL, CLI, Orchestrator) maintains isolated memories.

    Example:
        ```python
        manager = MemoryManager()

        # Store a memory
        record = MemoryRecord(
            query="R1 interface status",
            namespace=Namespace.SQL,
            action="SELECT * FROM v_interfaces WHERE device='R1'",
            embedding=embedding,
        )
        await manager.store(record)

        # Retrieve similar memories
        results = await manager.retrieve(
            query="Check R1 interfaces",
            namespace=Namespace.SQL,
            top_k=3,
        )
        ```
    """

    def __init__(self, similarity_threshold: float = 0.85, embedder: Embedder | None = None) -> None:
        """Initialize Memory Manager.

        Args:
            similarity_threshold: Minimum similarity for semantic search (0-1)
            embedder: Embedding model (uses default if None)
        """
        self.similarity_threshold = similarity_threshold
        self.embedder = embedder if embedder is not None else get_embedder()

        # Ensure semantic_cache table has namespace column
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Ensure semantic_cache table has id and namespace columns.

        Migration: Add id and namespace columns if they don't exist.
        """
        try:
            with UnifiedDatabase() as db:
                # Check if id column exists
                result = db.conn.execute(
                    """
                    SELECT COUNT(*) FROM information_schema.columns
                    WHERE table_name = 'semantic_cache'
                    AND column_name = 'id'
                """,
                ).fetchone()

                if result[0] == 0:
                    # Add id column (without PRIMARY KEY constraint - DuckDB limitation)
                    logger.info("Adding id column to semantic_cache table")
                    db.conn.execute(
                        """
                        ALTER TABLE commands.main.semantic_cache
                        ADD COLUMN id UUID DEFAULT uuid()
                    """,
                    )
                    logger.info("Schema migration complete: id column added")

                # Check if namespace column exists
                result = db.conn.execute(
                    """
                    SELECT COUNT(*) FROM information_schema.columns
                    WHERE table_name = 'semantic_cache'
                    AND column_name = 'namespace'
                """,
                ).fetchone()

                if result[0] == 0:
                    # Add namespace column
                    logger.info("Adding namespace column to semantic_cache table")
                    db.conn.execute(
                        """
                        ALTER TABLE commands.main.semantic_cache
                        ADD COLUMN namespace VARCHAR DEFAULT 'global'
                    """,
                    )
                    logger.info("Schema migration complete: namespace column added")
        except Exception as e:
            logger.warning(f"Schema migration failed (may already exist): {e}")

    async def store(self, record: MemoryRecord) -> bool:
        """Store a memory record.

        Args:
            record: Memory record to store

        Returns:
            True if successful, False otherwise
        """
        try:
            # Serialize action as JSON
            action_json = json.dumps({"action": record.action})

            with UnifiedDatabase() as db:
                db.conn.execute(
                    """
                    INSERT INTO commands.main.semantic_cache
                    (query_text, query_embedding, action_json, confidence, namespace)
                    VALUES (?, ?, ?, ?, ?)
                """,
                    [
                        record.query,
                        record.embedding,
                        action_json,
                        record.confidence,
                        record.namespace.value,
                    ],
                )
            logger.debug(f"Stored memory in namespace '{record.namespace.value}': {record.query[:50]}...")
            return True
        except Exception as e:
            logger.error(f"Failed to store memory: {e}")
            return False

    async def retrieve(self, query: str, namespace: Namespace, top_k: int = 5) -> list[dict[str, Any]]:
        """Retrieve similar memories from namespace.

        Args:
            query: Query string to search for
            namespace: Memory namespace to search
            top_k: Maximum number of results to return

        Returns:
            List of matching memory records
        """
        try:
            # Generate query embedding
            query_embedding = self.embedder.embed_query(query)
            if not query_embedding:
                return []

            # Search by namespace with vector similarity
            with UnifiedDatabase() as db:
                results = db.conn.execute(
                    f"""
                    SELECT
                        id,
                        query_text,
                        action_json,
                        confidence,
                        array_cosine_similarity(
                            query_embedding::FLOAT[{len(query_embedding)}],
                            ?::FLOAT[{len(query_embedding)}]
                        ) as similarity
                    FROM commands.main.semantic_cache
                    WHERE namespace = ?
                    ORDER BY similarity DESC
                    LIMIT ?
                """,
                    [query_embedding, namespace.value, top_k],
                ).fetchall()

            # Convert to list of dicts
            memories = []
            for row in results:
                similarity = row[4]
                if similarity >= self.similarity_threshold:
                    # Parse action JSON
                    try:
                        action_data = json.loads(row[2])
                        action = action_data.get("action", row[2])
                    except:
                        action = row[2]

                    memories.append(
                        {
                            "id": row[0],
                            "query": row[1],
                            "action": action,
                            "confidence": row[3],
                            "similarity": similarity,
                            "namespace": namespace.value,
                        }
                    )

            logger.debug(f"Retrieved {len(memories)} memories from '{namespace.value}'")
            return memories

        except Exception as e:
            logger.error(f"Failed to retrieve memories: {e}")
            return []

    async def upsert(self, record: MemoryRecord) -> bool:
        """Update or insert a memory record.

        Used for user corrections via /teach command.

        Args:
            record: Memory record to upsert

        Returns:
            True if successful, False otherwise
        """
        try:
            # Serialize action as JSON
            action_json = json.dumps({"action": record.action})

            with UnifiedDatabase() as db:
                # Check if similar query exists
                existing = db.conn.execute(
                    """
                    SELECT id FROM commands.main.semantic_cache
                    WHERE query_text = ? AND namespace = ?
                    LIMIT 1
                """,
                    [record.query, record.namespace.value],
                ).fetchone()

                if existing:
                    # Update existing record
                    memory_id = existing[0]
                    db.conn.execute(
                        """
                        UPDATE commands.main.semantic_cache
                        SET action_json = ?,
                            confidence = ?,
                            query_embedding = ?,
                            last_used = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """,
                        [action_json, record.confidence, record.embedding, memory_id],
                    )
                    logger.info(f"Updated memory ID {memory_id} in '{record.namespace.value}'")
                else:
                    # Insert new record
                    return await self.store(record)

            return True

        except Exception as e:
            logger.error(f"Failed to upsert memory: {e}")
            return False

    async def delete(self, memory_id: int) -> bool:
        """Delete a memory record by ID.

        Args:
            memory_id: ID of memory to delete

        Returns:
            True if successful, False otherwise
        """
        try:
            with UnifiedDatabase() as db:
                db.conn.execute(
                    "DELETE FROM commands.main.semantic_cache WHERE id = ?",
                    [memory_id],
                )
            logger.debug(f"Deleted memory ID {memory_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete memory {memory_id}: {e}")
            return False

    async def clear_namespace(self, namespace: Namespace) -> None:
        """Clear all memories in a namespace.

        Args:
            namespace: Namespace to clear
        """
        try:
            with UnifiedDatabase() as db:
                db.conn.execute(
                    "DELETE FROM commands.main.semantic_cache WHERE namespace = ?",
                    [namespace.value],
                )
            logger.info(f"Cleared all memories in '{namespace.value}' namespace")
        except Exception as e:
            logger.error(f"Failed to clear namespace '{namespace.value}': {e}")

    async def get_stats(self, namespace: Namespace | None = None) -> dict[str, Any]:
        """Get memory statistics.

        Args:
            namespace: Optional namespace filter

        Returns:
            Statistics dictionary
        """
        try:
            with UnifiedDatabase() as db:
                if namespace:
                    count = db.conn.execute(
                        "SELECT COUNT(*) FROM commands.main.semantic_cache WHERE namespace = ?",
                        [namespace.value],
                    ).fetchone()[0]
                    return {
                        "namespace": namespace.value,
                        "total_memories": count,
                    }
                else:
                    # Get stats for all namespaces
                    result = db.conn.execute(
                        """
                        SELECT namespace, COUNT(*) as count
                        FROM commands.main.semantic_cache
                        GROUP BY namespace
                    """
                    ).fetchall()

                    return {
                        "by_namespace": {row[0]: row[1] for row in result},
                        "total": sum(row[1] for row in result),
                    }
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return {"error": str(e)}


# =============================================================================
# Main
# =============================================================================


if __name__ == "__main__":
    import asyncio

    async def test() -> None:
        """Test Memory Manager."""
        manager = MemoryManager()

        # Test store
        record = MemoryRecord(
            query="R1 interface status",
            namespace=Namespace.SQL,
            action="SELECT * FROM v_interfaces WHERE device='R1'",
            embedding=[0.1] * 768,
        )
        await manager.store(record)

        # Test retrieve
        results = await manager.retrieve(query="R1 interfaces", namespace=Namespace.SQL, top_k=1)
        print(f"Retrieved {len(results)} memories")
        for r in results:
            print(f"  - {r['query']}: {r['action']} (similarity: {r['similarity']:.2f})")

        # Test stats
        stats = await manager.get_stats()
        print(f"Stats: {stats}")

    asyncio.run(test())
