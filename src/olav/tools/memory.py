"""olav.tools.memory — Knowledge retrieval from LanceDB (platform-agnostic).

Core memory search logic used by the `olav_recall_memory` workspace tool.
Can be used standalone::

    from olav.tools.memory import search_memory

    results = search_memory("BGP failover procedure")
    for r in results:
        print(r["text"], r["score"])
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def search_memory(
    query: str,
    category: str | None = None,
    scope: str = "global",
    limit: int = 5,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    """Search long-term memory using hybrid vector + BM25 search.

    Args:
        query: Natural language search query.
        category: Filter by category (fact, procedure, decision, etc.).
        scope: Memory scope (default "global").
        limit: Maximum results to return.
        db_path: Optional LanceDB path override.

    Returns:
        List of memory dicts with text, category, score, tags, etc.
        Empty list if no memories found or on error.

    Example::

        from olav.tools.memory import search_memory

        results = search_memory("BGP neighbor flap", category="fact", limit=3)
        for r in results:
            print(f"[{r['category']}] {r['text']} (score={r['score']:.2f})")
    """
    import os

    try:
        from olav.core.memory import get_store, hybrid_search, MEMORY_TABLE
        from olav.core.embedder import embed_text

        store = get_store(db_path=db_path or os.environ.get("OLAV_MEMORY_DB_PATH"))

        if not store.table_exists(MEMORY_TABLE):
            return []

        query_vector = None
        try:
            query_vector = embed_text(query)
        except Exception as e:
            logger.debug("search_memory: embedder unavailable (%s), text-only search", e)

        if query_vector:
            return hybrid_search(
                store=store,
                query=query,
                query_vector=query_vector,
                limit=limit,
                category=category,
                scope=scope,
            )
        else:
            return store.search_by_text(
                query=query,
                limit=limit,
                category=category,
                scope=scope,
            )

    except Exception as exc:
        logger.warning("search_memory failed: %s", exc)
        return []


def store_memory(
    text: str,
    category: str = "fact",
    scope: str = "global",
    tags: list[str] | None = None,
    confidence: float = 1.0,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Explicitly store a durable fact into long-term LanceDB memory.

    Write-side counterpart to :func:`search_memory`. Embeds ``text`` and calls
    ``LanceDBStore.add_memory`` with ``origin="user"`` — distinguishing it from
    ``MemoryCapturePlugin``'s automatic ``origin="agent"`` captures. This is
    OLAV's own semantic memory and is entirely separate from deepagents' native
    AGENTS.md file memory (which OLAV does not touch).

    Args:
        text:       The fact/preference to remember (clear, self-contained).
        category:   fact (default) / decision / preference / etc.
        scope:      Memory scope (default "global").
        tags:       Optional topic/entity tags (list of strings).
        confidence: Reliability 0.0-1.0 (default 1.0 — user-stated facts are trusted).
        db_path:    Optional LanceDB path override.

    Returns:
        Dict from ``add_memory`` (``status`` + ``id``), or ``{"status":"error",...}``.

    Example::

        from olav.tools.memory import store_memory
        store_memory("R2 is scheduled for decommission in Q3", category="decision")
    """
    import json
    import os
    import uuid

    try:
        from olav.core.embedder import embed_text
        from olav.core.memory import MEMORY_TABLE, get_store

        store = get_store(db_path=db_path or os.environ.get("OLAV_MEMORY_DB_PATH"))

        vec = embed_text(text)
        if not vec:
            return {"status": "error", "reason": "embedder unavailable; cannot store memory"}

        mid = f"usr-{uuid.uuid4().hex[:8]}"
        result = store.add_memory(
            id=mid,
            text=text,
            vector=vec,
            category=category,
            scope=scope,
            origin="user",
            confidence=confidence,
            tags=json.dumps(tags or []),
            metadata={"source": "user_explicit"},
            table_name=MEMORY_TABLE,
        )
        if isinstance(result, dict):
            result.setdefault("id", mid)
        return result

    except Exception as exc:
        logger.warning("store_memory failed: %s", exc)
        return {"status": "error", "reason": str(exc)}
