"""Bench-state reset — make consecutive bench runs comparable.

Between bench runs, the demo workspace's LanceDB memory store
accumulates ``query_pattern`` rows from prior agent runs.  These
crowd into ``AutoRecallMiddleware``'s diversifier output and bias
small-model exploration paths in non-deterministic ways
(R84 platform_kb refactor's bench saw Q2 +113% / Q3 +167% vs
postfix despite byte-for-byte equivalent code — the only difference
was 163 accumulated query_pattern rows).

This module provides :func:`reset_volatile_categories` — drop the
"learned" / volatile memory categories while preserving the
deterministic ones (usage_guide, schema_knowledge, value_distribution)
that ``/netops_init`` re-primes idempotently.

Default volatile set: ``("query_pattern",)``.  Callers can opt in
to also clearing ``fact`` / ``decision`` (post-conversation
extraction artefacts) when stricter isolation is needed.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

logger = logging.getLogger(__name__)

# What gets cleared by default — narrow on purpose, only the
# unambiguously-bench-noise category.  Other "volatile" categories
# can leak between sessions intentionally (a captured fact may
# be the answer to the next query) so they're opt-in.
DEFAULT_VOLATILE_CATEGORIES: tuple[str, ...] = ("query_pattern",)

# Categories the helper protects regardless of the caller's request —
# clearing these would break the next agent run (no schema, no
# guides) and the bench would measure cold-start, not behaviour.
# Listed so a future contributor doesn't accidentally widen the
# default set in a way that destroys ingest-time work.
PRESERVED_CATEGORIES: frozenset[str] = frozenset({
    "usage_guide",
    "schema_knowledge",
    "value_distribution",
})


def _count_by_category(store: Any) -> dict[str, int]:
    """Return ``{category: row_count}`` across the memory table."""
    counts: dict[str, int] = {}
    try:
        memories = store.get_memories(limit=100_000)
    except Exception as exc:  # noqa: BLE001
        logger.warning("bench_reset: get_memories failed: %s", exc)
        return counts
    for m in memories:
        cat = m.get("category", "")
        counts[cat] = counts.get(cat, 0) + 1
    return counts


def reset_volatile_categories(
    store: Any,
    *,
    categories: Iterable[str] = DEFAULT_VOLATILE_CATEGORIES,
) -> dict[str, dict[str, int]]:
    """Delete rows in the listed volatile categories; keep everything else.

    Args:
        store:      ``LanceDBStore`` instance.
        categories: Iterable of category names to clear.  Anything in
                    :data:`PRESERVED_CATEGORIES` is silently skipped
                    even if asked — protects the caller from breaking
                    the next bench run.

    Returns:
        ``{"cleared": {cat: N}, "preserved": {cat: M}}`` — counts
        BEFORE the delete (so callers can log "cleared 163 query_patterns").
    """
    from olav.core.memory import MEMORY_TABLE

    requested = set(categories)
    safe_to_clear = requested - PRESERVED_CATEGORIES
    if safe_to_clear != requested:
        skipped = requested & PRESERVED_CATEGORIES
        logger.warning(
            "bench_reset: refusing to clear preserved categories %s",
            sorted(skipped),
        )

    pre_counts = _count_by_category(store)
    cleared: dict[str, int] = {cat: pre_counts.get(cat, 0) for cat in safe_to_clear}

    try:
        tbl = store.get_table(MEMORY_TABLE)
    except Exception as exc:  # noqa: BLE001
        logger.warning("bench_reset: get_table failed: %s", exc)
        return {"cleared": cleared, "preserved": pre_counts}

    for cat in safe_to_clear:
        try:
            tbl.delete(f"category = '{cat}'")
        except Exception as exc:  # noqa: BLE001
            logger.warning("bench_reset: delete %s failed: %s", cat, exc)
            cleared[cat] = -1

    preserved = {
        cat: count
        for cat, count in pre_counts.items()
        if cat not in safe_to_clear
    }
    logger.info(
        "bench_reset: cleared=%s preserved=%s",
        cleared, preserved,
    )
    return {"cleared": cleared, "preserved": preserved}


__all__ = [
    "DEFAULT_VOLATILE_CATEGORIES",
    "PRESERVED_CATEGORIES",
    "reset_volatile_categories",
]
