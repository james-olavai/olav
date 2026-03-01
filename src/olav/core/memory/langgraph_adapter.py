"""LanceDB Store Adapter for LangGraph BaseStore Interface.

This adapter wraps olav.core.memory.LanceDBStore to implement the langgraph.store.base.BaseStore
interface, allowing it to be used directly with DeepAgents.
"""

import logging
from collections.abc import Iterable, Sequence
from typing import Any

from langgraph.store.base import BaseStore

from olav.core.memory import MEMORY_TABLE
from olav.core.memory import LanceDBStore as OCLanceDBStore

logger = logging.getLogger(__name__)


class LangGraphLanceDBStore(BaseStore):
    """Adapter to wrap OLAV's LanceDBStore for LangGraph compatibility.

    This implements the BaseStore interface required by DeepAgents' store parameter.
    """

    def __init__(self, db_path: str | None = None, embedding_dim: int = 384) -> None:
        """Initialize the adapter.

        Args:
            db_path: Optional path to LanceDB database
            embedding_dim: Embedding dimension (default 384 for bge-small)
        """
        self._store = OCLanceDBStore(db_path=db_path, embedding_dim=embedding_dim)
        self._table_name = MEMORY_TABLE

        # Ensure table exists
        if not self._store.table_exists(self._table_name):
            self._store.create_table(self._table_name)

    # pyright: ignore[reportIncompatibleMethodOverride]
    def get(self, namespace: tuple[str, ...], key: str) -> Any | None:
        """Get a value by namespace and key.

        Args:
            namespace: Tuple of strings identifying the namespace
            key: The key to retrieve

        Returns:
            The stored value or None if not found
        """
        # OLAV LanceDB uses different key structure
        # We map namespace to scope
        scope = namespace[0] if namespace else "global"
        memories = self._store.get_memories(scope=scope, limit=100, table_name=self._table_name)
        for mem in memories:
            if mem.get("id") == key:
                return mem
        return None

    # pyright: ignore[reportIncompatibleMethodOverride]
    def put(self, namespace: tuple[str, ...], key: str, value: Any) -> None:
        """Store a value with namespace and key.

        Args:
            namespace: Tuple of strings identifying the namespace
            key: The key to store under
            value: The value to store (must be dict-like with 'text' and optional 'vector')
        """
        import uuid

        scope = namespace[0] if namespace else "global"

        # Extract text and vector from value
        text = value.get("text", str(value))
        vector = value.get("vector")

        memory_id = f"{scope}-{key}-{uuid.uuid4().hex[:8]}"

        self._store.add_memory(
            id=memory_id,
            text=text,
            vector=vector,
            scope=scope,
            metadata=value.get("metadata", {}),
            table_name=self._table_name,
        )

    def delete(self, namespace: tuple[str, ...], key: str) -> None:
        """Delete a value by namespace and key.

        Args:
            namespace: Tuple of strings identifying the namespace
            key: The key to delete
        """
        scope = namespace[0] if namespace else "global"

        # Find and delete the memory
        memories = self._store.get_memories(scope=scope, limit=100, table_name=self._table_name)
        for mem in memories:
            if mem.get("id") == key:
                self._store.delete_memory(key, table_name=self._table_name)
                break

    # pyright: ignore[reportIncompatibleMethodOverride]
    def search(
        self,
        namespace: tuple[str, ...],
        query: str | None = None,
        limit: int = 10,
    ) -> Sequence[Any]:
        """Search for items in a namespace.

        Args:
            namespace: Tuple of strings identifying the namespace
            query: Optional text query
            limit: Maximum number of results

        Returns:
            List of matching items
        """
        scope = namespace[0] if namespace else "global"

        if query:
            results = self._store.hybrid_search(
                store=self._store,
                query=query,
                limit=limit,
                scope=scope,
                table_name=self._table_name,
            )
            return results
        else:
            return self._store.get_memories(scope=scope, limit=limit, table_name=self._table_name)

    # pyright: ignore[reportIncompatibleMethodOverride]
    def list_namespaces(
        self, prefix: str | Iterable[str] | None = None
    ) -> Iterable[tuple[str, ...]]:
        """List all namespaces.

        Args:
            prefix: Optional prefix to filter namespaces

        Returns:
            List of namespace tuples
        """
        # OLAV LanceDB doesn't have namespace enumeration
        # Return default namespace
        if prefix:
            return [("global",)]
        return [("global",)]

    # pyright: ignore[reportIncompatibleMethodOverride]
    def abatch(self, operations: Sequence[tuple[str, tuple[str, ...], str, Any]]) -> Sequence[Any]:
        """Async batch operations.

        Args:
            operations: List of (operation, namespace, key, value) tuples

        Returns:
            List of results
        """
        # Simple sync implementation for now
        results = []
        for op, namespace, key, value in operations:
            if op == "get":
                results.append(self.get(namespace, key))
            elif op == "put":
                self.put(namespace, key, value)
                results.append(None)
            elif op == "delete":
                self.delete(namespace, key)
                results.append(None)
            else:
                results.append(None)
        return results

    # pyright: ignore[reportIncompatibleMethodOverride]
    def batch(self, operations: Sequence[tuple[str, tuple[str, ...], str, Any]]) -> Sequence[Any]:
        """Batch operations (sync version).

        Args:
            operations: List of (operation, namespace, key, value) tuples

        Returns:
            List of results
        """
        return self.abatch(operations)
