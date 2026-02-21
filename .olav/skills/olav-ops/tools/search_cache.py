"""search_cache — Semantic response cache lookup tool for the Orchestrator.

Returns the best-matching cached response for a natural-language query
using lightweight keyword-overlap similarity (no embedding model required).

Strategy:
  1. Load all valid (non-expired) cache entries from response_cache table.
  2. Score each entry using token-overlap Jaccard similarity vs the input query.
  3. Return the entry above MIN_SIMILARITY_SCORE, else {'found': False}.

This is the Tier-0 semantic companion to the exact-hash bypass in
_stream_response. The exact-hash handles identical queries; this handles
near-identical phrasing (e.g. "list devices" vs "show all devices").

Usage in DeepAgents Orchestrator:
    from .tools.search_cache import search_cache
    agent = create_deep_agent(tools=[..., search_cache])

Prompt hint (add to Orchestrator system prompt):
    Before calling any SubAgent, call search_cache(query=<user_query>).
    If found=True, return the cached_response directly.
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# Minimum Jaccard similarity to return a cache hit (0–1)
MIN_SIMILARITY = 0.55

# Stop-words to exclude from token matching
_STOP_WORDS = {
    "a", "an", "the", "is", "are", "was", "were", "of", "for", "in", "on",
    "to", "and", "or", "all", "me", "us", "i", "we", "you", "please",
    "show", "list", "get", "give", "find", "what", "how", "many", "do",
    "can", "could", "would", "which", "that", "this", "with", "from",
}


def _find_project_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


sys.path.insert(0, str(_find_project_root() / "src"))
sys.path.insert(0, str(_find_project_root()))


def _tokenise(text: str) -> set[str]:
    """Lowercase token set, stop-words removed.

    Args:
        text: Input string to tokenise.

    Returns:
        Set of meaningful tokens.
    """
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return {t for t in tokens if t not in _STOP_WORDS and len(t) > 1}


def _jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard similarity between two token sets.

    Args:
        a: First token set.
        b: Second token set.

    Returns:
        Similarity score 0.0–1.0.
    """
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _load_valid_entries() -> list[dict]:
    """Load non-expired cache entries from DuckDB.

    Returns:
        List of dicts with query_text, response, source_agent, cached_at, snapshot_ts.
    """
    try:
        from olav.core.response_cache import ResponseCache

        cache = ResponseCache()
        import duckdb

        conn = duckdb.connect(str(cache._db_path), read_only=True)
        rows = conn.execute(
            "SELECT query_hash, query_text, response, source_agent, cached_at, snapshot_ts "
            "FROM response_cache"
        ).fetchall()
        conn.close()

        valid = []
        for row in rows:
            validity = (row[0], row[4], row[5], row[3])  # hash, cached_at, snapshot_ts, agent
            if cache._is_valid(validity):
                valid.append(
                    {
                        "query_text": row[1],
                        "response": row[2],
                        "source_agent": row[3],
                    }
                )
        return valid
    except Exception as exc:
        logger.debug("search_cache: could not load entries: %s", exc)
        return []


@tool
def search_cache(query: str) -> dict:
    """Search the response cache for a semantically similar previous answer.

    Call this BEFORE routing to any SubAgent. If found=True, return the
    cached_response directly without calling any SubAgent.

    The search uses keyword-overlap similarity (fast, no LLM call).
    Threshold: 55% — tight enough to avoid false positives on different
    devices (e.g. "BGP on R1" vs "BGP on R2" will NOT match).

    Args:
        query: The user's natural language query.

    Returns:
        {
          "found": True,
          "cached_response": "...",
          "similarity": 0.72,
          "source_agent": "olav-ops"
        }
        OR
        {
          "found": False,
          "similarity": 0.0
        }

    Examples:
        >>> search_cache("list all devices")
        {"found": True, "cached_response": "...", "similarity": 0.88, ...}

        >>> search_cache("show BGP neighbors on R2")
        {"found": False, "similarity": 0.31}
    """
    q_tokens = _tokenise(query)
    if not q_tokens:
        return {"found": False, "similarity": 0.0}

    entries = _load_valid_entries()
    if not entries:
        return {"found": False, "similarity": 0.0}

    best_score = 0.0
    best_entry: dict | None = None

    for entry in entries:
        e_tokens = _tokenise(entry["query_text"])
        score = _jaccard(q_tokens, e_tokens)
        if score > best_score:
            best_score = score
            best_entry = entry

    if best_score >= MIN_SIMILARITY and best_entry is not None:
        logger.debug("search_cache: HIT similarity=%.2f query=%r", best_score, query)
        return {
            "found": True,
            "cached_response": best_entry["response"],
            "similarity": round(best_score, 3),
            "source_agent": best_entry["source_agent"],
        }

    logger.debug("search_cache: MISS best_similarity=%.2f query=%r", best_score, query)
    return {"found": False, "similarity": round(best_score, 3)}
