"""Memory Middleware for DeepAgents Integration.

This module provides the MemoryMiddleware class that integrates LanceDB memory
with the DeepAgents loop:

- **Auto-Recall (Pre-processor)**: Injects relevant historical context into the prompt
  before the agent starts thinking.
- **Auto-Capture (Post-processor)**: Summarizes the conversation and extracts key
  takeaways (decisions/facts/audits) into LanceDB after successful task execution.

Following the architecture in dev_docs/LANCEDB_MEMORY_SYSTEM_INTEGRATION.md
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Default embedding dimension
DEFAULT_EMBEDDING_DIM = 384


class MemoryMiddleware:
    """Memory middleware for DeepAgents integration.

    This middleware provides:
    1. Auto-Recall: Before agent execution, inject relevant memories
    2. Auto-Capture: After agent execution, store new learnings

    Usage:
        middleware = MemoryMiddleware(agent_name="RoutingAgent")

        # Pre-execution: Get context
        context = middleware.recall(query="BGP neighbor down")

        # Post-execution: Store learnings
        middleware.capture(
            task_result="BGP neighbor recovered",
            category="fact"
        )
    """

    def __init__(
        self,
        agent_name: str = "global",
        embedding_dim: int = DEFAULT_EMBEDDING_DIM,
        db_path: str | Path | None = None,
    ):
        """Initialize MemoryMiddleware.

        Args:
            agent_name: Name of the agent using this middleware
            embedding_dim: Dimension of embedding vectors
            db_path: Optional path to LanceDB database
        """
        self.agent_name = agent_name
        self.embedding_dim = embedding_dim
        self._db_path = db_path
        self._store = None

    def _get_store(self):
        """Get or create the LanceDB store."""
        if self._store is None:
            # Import here to avoid circular imports
            from olav.core.memory import (
                MEMORY_TABLE,
                LanceDBStore,
                get_store,
            )

            if self._db_path:
                self._store = LanceDBStore(db_path=self._db_path, embedding_dim=self.embedding_dim)
            else:
                self._store = get_store(embedding_dim=self.embedding_dim)

            # Ensure table exists
            if not self._store.table_exists(MEMORY_TABLE):
                self._store.create_table(MEMORY_TABLE)

        return self._store

    def recall(
        self,
        query: str,
        query_vector: list[float] | None = None,
        limit: int = 5,
    ) -> str:
        """Recall relevant memories before agent execution.

        This method searches the memory store for relevant information
        and returns it as a context string to be injected into
        the agent's prompt.

        Args:
            query: Natural language query describing the task
            query_vector: Optional pre-computed embedding vector
            limit: Maximum number of memories to recall

        Returns:
            Context string with relevant memories, or empty string if none found
        """
        try:
            store = self._get_store()

            # If no query vector provided, try to generate one
            if query_vector is None:
                try:
                    from olav.core.knowledge.embedding_gateway import EmbeddingGateway

                    gateway = EmbeddingGateway()
                    query_vector = gateway.embed_text(query)

                    # Ensure vector matches expected dimension
                    if len(query_vector) < self.embedding_dim:
                        query_vector = query_vector + [0.0] * (
                            self.embedding_dim - len(query_vector)
                        )
                    elif len(query_vector) > self.embedding_dim:
                        query_vector = query_vector[: self.embedding_dim]

                except Exception as e:
                    logger.warning(f"Failed to get embeddings for recall: {e}")
                    return ""

            # Search with hybrid approach
            from olav.core.memory import MEMORY_TABLE, hybrid_search

            results = hybrid_search(
                store=store,
                query=query,
                query_vector=query_vector,
                limit=limit,
                scope=self.agent_name,
                table_name=MEMORY_TABLE,
            )

            if not results:
                return ""

            # Build context string
            context_parts = ["Relevant memories from past experience:"]

            for i, result in enumerate(results, 1):
                text = result.get("text", "")
                category = result.get("category", "unknown")

                # Truncate long texts
                if len(text) > 200:
                    text = text[:200] + "..."

                context_parts.append(f"{i}. [{category}] {text}")

            return "\n".join(context_parts)

        except Exception as e:
            logger.error(f"Recall failed: {e}")
            return ""

    def capture(
        self,
        text: str,
        category: str = "fact",
        metadata: dict | None = None,
        query_vector: list[float] | None = None,
    ) -> dict:
        """Capture a memory after agent execution.

        This method stores new learnings from agent execution
        into the memory store.

        Args:
            text: The memory text to store
            category: Category (fact, decision, preference, audit)
            metadata: Additional metadata
            query_vector: Optional pre-computed embedding vector

        Returns:
            Dict with status and message
        """
        try:
            import uuid

            store = self._get_store()

            # Generate ID
            memory_id = f"{self.agent_name}-{uuid.uuid4().hex[:8]}"

            # If no query vector provided, try to generate one
            if query_vector is None:
                try:
                    from olav.core.knowledge.embedding_gateway import EmbeddingGateway

                    gateway = EmbeddingGateway()
                    query_vector = gateway.embed_text(text)

                    # Ensure vector matches expected dimension
                    if len(query_vector) < self.embedding_dim:
                        query_vector = query_vector + [0.0] * (
                            self.embedding_dim - len(query_vector)
                        )
                    elif len(query_vector) > self.embedding_dim:
                        query_vector = query_vector[: self.embedding_dim]

                except Exception as e:
                    logger.warning(f"Failed to get embeddings for capture: {e}")
                    # Use random vector as fallback
                    import random

                    query_vector = [random.random() for _ in range(self.embedding_dim)]

            # Add metadata
            capture_metadata = metadata or {}
            capture_metadata["source"] = "auto-capture"
            capture_metadata["agent"] = self.agent_name

            # Store memory
            from olav.core.memory import MemoryCategory

            # Convert string category to MemoryCategory
            if category == "fact":
                cat = MemoryCategory.FACT
            elif category == "decision":
                cat = MemoryCategory.DECISION
            elif category == "preference":
                cat = MemoryCategory.PREFERENCE
            elif category == "audit":
                cat = MemoryCategory.AUDIT
            else:
                cat = MemoryCategory.FACT

            result = store.add_memory(
                id=memory_id,
                text=text,
                vector=query_vector,
                category=cat,
                scope=self.agent_name,
                metadata=capture_metadata,
            )

            logger.info(f"Captured memory: {memory_id} ({category})")
            return result

        except Exception as e:
            logger.error(f"Capture failed: {e}")
            return {"status": "error", "message": str(e)}

    def capture_from_result(
        self,
        task_query: str,
        task_result: str,
        category: str = "fact",
    ) -> dict:
        """Capture a learning from task result.

        This is a convenience method that generates both the text
        and vector from the task query and result.

        Args:
            task_query: The original query/task
            task_result: The result/output from the task
            category: Category to assign

        Returns:
            Dict with status and message
        """
        # Combine query and result for richer context
        combined_text = f"Task: {task_query}\nResult: {task_result}"

        return self.capture(
            text=combined_text,
            category=category,
            metadata={"task_query": task_query},
        )

    def get_agent_memories(
        self,
        category: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Get all memories for this agent.

        Args:
            category: Optional category filter
            limit: Maximum number of results

        Returns:
            List of memory dicts
        """
        store = self._get_store()
        from olav.core.memory import MEMORY_TABLE

        return store.get_memories(
            category=category,
            scope=self.agent_name,
            limit=limit,
            table_name=MEMORY_TABLE,
        )

    def clear_agent_memories(self) -> dict:
        """Clear all memories for this agent.

        Returns:
            Dict with status
        """
        try:
            memories = self.get_agent_memories()
            store = self._get_store()
            from olav.core.memory import MEMORY_TABLE

            for memory in memories:
                store.delete_memory(memory["id"], table_name=MEMORY_TABLE)

            return {"status": "success", "deleted": len(memories)}

        except Exception as e:
            logger.error(f"Clear failed: {e}")
            return {"status": "error", "message": str(e)}
