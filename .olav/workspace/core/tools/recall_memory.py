"""Recall Memory Tool — Explicit long-term memory retrieval for agents.

Agents use this to actively query their past experience: historical decisions,
network events, preferences, and recorded failures/successes.

This complements the Auto-Recall middleware (which injects memories automatically).
Use this tool when you explicitly need to:
  - Recall a past decision or preference
  - Look up historical network events for a specific device
  - Retrieve past troubleshooting findings before starting a new diagnosis
"""

import logging
import sys
from pathlib import Path

def _find_project_root():
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()

sys.path.insert(0, str(_find_project_root() / "src"))

import json
from langchain_core.tools import tool

from olav.core.memory import get_store, hybrid_search, MEMORY_TABLE

logger = logging.getLogger(__name__)


def _embed_query(text: str) -> "list[float] | None":
    """Embed a query string using the same embedder as kb_import (olav.core.embedder.embed_text)."""
    try:
        from olav.core.embedder import embed_text
        return embed_text(text)
    except Exception as e:
        logger.debug(f"recall_memory: embed_query failed ({e})")
        return None


_RECALL_MEMORY_FALLBACK_TOP_K = 3  # ARCH-16: conservative small-model-safe default


def _resolve_recall_limit(explicit: int | None) -> int:
    """Resolve ``limit`` for recall_memory respecting tier defaults.

    Priority: explicit caller value (clamped to 1..10) > tier default from
    ``TIER_DEFAULTS[<tier>]["recall_top_k"]`` > fallback. Keeps the hard
    ceiling of 10 even for large tier so a buggy caller can't blow the
    context budget via huge ``limit=`` values.
    """
    if explicit is not None:
        return max(1, min(int(explicit), 10))
    try:
        from olav.core.config import get_llm_config, tier_default
        tier = get_llm_config().model_tier
        resolved = tier_default(tier, "recall_top_k", _RECALL_MEMORY_FALLBACK_TOP_K)
        return max(1, min(int(resolved), 10))
    except Exception:  # noqa: BLE001
        return _RECALL_MEMORY_FALLBACK_TOP_K


@tool
def recall_memory(
    query: str,
    category: str | None = None,
    scope: str | None = None,
    limit: int | None = None,
) -> str:
    """Query long-term memory for past experiences, decisions, and network events.

    Hybrid semantic search (vector + BM25 + recency). Use natural language.
    Call once at the start of an investigation or change plan.
    Full usage: tool_help('recall_memory').

    Args:
        query:    Natural language query ("BGP failures on R1", "OSPF MTU issue").
        category: Optional — fact / decision / preference / expert_knowledge /
                  usage_guide / format_guide / audit. None = all categories.
        scope:    Optional scope filter. None = all scopes (recommended).
        limit:    Max results. Omit = tier default (small=1, medium=2, large=3).

    Returns:
        Formatted memory entries with timestamps, or "No relevant memories found".
    """
    if not query or not query.strip():
        return "Error: query must not be empty."

    limit = _resolve_recall_limit(limit)

    import concurrent.futures as _cf
    import functools

    def _search() -> str:
        return _recall_memory_inner(query=query, category=category, scope=scope, limit=limit)

    try:
        with _cf.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_search)
            return future.result(timeout=15)
    except _cf.TimeoutError:
        logger.warning("recall_memory: timed out after 15s — continuing without memory")
        return "Memory recall skipped (timeout)."
    except Exception as e:
        logger.error(f"recall_memory failed: {e}")
        return f"Memory recall failed: {e}"


def _recall_memory_inner(
    query: str,
    category: str | None,
    scope: str,
    limit: int,
) -> str:
    """Core memory search logic — called inside a thread by recall_memory."""
    try:
        # Let get_store auto-detect embedding_dim from the configured embedder
        # (was hardcoded 768 — broke against 2048-dim tables and tripped the
        # P0 dim-safety guard.  See dev_docs/00 §
        # ISSUE-EMBEDDING-FALLBACK-DIM-MISMATCH-DESTROYS-DATA).
        store = get_store()

        if not store.table_exists(MEMORY_TABLE):
            return "No long-term memories stored yet."

        # Embed query
        query_vector = _embed_query(query)

        if query_vector:
            results = hybrid_search(
                store=store,
                query=query,
                query_vector=query_vector,
                limit=limit,
                category=category,
                scope=scope,
            )
        else:
            results = store.search_by_text(
                query=query,
                limit=limit,
                category=category,
                scope=scope,
            )

        if not results:
            return (
                f"No relevant memories found for: '{query}'\n"
                "Tip: Try a broader query, or check if this is a new topic with no prior experience."
            )

        lines = [f"🧠 **Long-term memory recall** for: '{query}'\n"]
        for i, r in enumerate(results, 1):
            text = r.get("text", "")
            cat = r.get("category", "unknown")
            ts = r.get("timestamp")
            weight = r.get("weight")
            score = r.get("rrf_score", r.get("score"))

            date_str = ""
            if ts:
                try:
                    date_str = f" [{str(ts)[:10]}]"
                except Exception:
                    pass

            weight_str = f" weight={weight:.2f}" if weight else ""
            score_str = f" score={score:.3f}" if isinstance(score, float) else ""

            # Parse metadata for extra context
            meta_raw = r.get("metadata", "{}")
            try:
                meta = json.loads(meta_raw) if isinstance(meta_raw, str) else (meta_raw or {})
            except Exception:
                meta = {}

            device = meta.get("device", "")
            event_type = meta.get("event_type", "")
            source = meta.get("source", "")

            extra = " | ".join(filter(None, [
                f"device={device}" if device else "",
                f"type={event_type}" if event_type else "",
                f"via={source}" if source and source not in ("auto_capture", "network_event") else "",
            ]))

            lines.append(
                f"**[{i}]** [{cat.upper()}]{date_str}{weight_str}{score_str}\n"
                f"  {text[:300]}{'...' if len(text) > 300 else ''}"
                + (f"\n  _({extra})_" if extra else "")
            )

        return "\n\n".join(lines)

    except Exception as e:
        logger.error(f"recall_memory failed: {e}")
        return f"Memory recall failed: {e}"


if __name__ == "__main__":
    data = json.loads(sys.stdin.read())
    print(json.dumps(recall_memory.invoke(data), ensure_ascii=False))
