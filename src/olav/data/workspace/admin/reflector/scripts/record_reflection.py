#!/usr/bin/env python3
"""record_reflection — write reflection lessons directly to the KB.

The KB "direct write" lane of the reflector agent. A reflection lesson is one
line the model derived from today's error histogram (e.g. "execute_skill_script
fails when script_args is passed a list — coerce to a dict at the boundary").

Written as ``category=reflection, scope=global`` (mirrors trace_learner), which
means AutoRecall injects it into EVERY agent's ranked recall — but bounded:
reflection has a quota of 1 slot and a 30-day TTL (ADR-0015), so this is
self-limiting and reversible (``olav kb gc`` sweeps expired rows). That safety
envelope is exactly why direct write is acceptable here while permanent
``usage_guide`` changes go through the draft→HITL lane (propose_guide_draft).

Dedup: skips a lesson whose normalized text already exists as a live
reflection, so a daily run doesn't pile up near-duplicates.
"""
from __future__ import annotations

import json
import re
import sys
import uuid
from typing import Any

_WS = re.compile(r"\s+")

#: L2 distance below which two reflections are treated as the same lesson.
#: Calibrated with olav kb bench (nomic-embed L2): genuine paraphrase
#: near-duplicates sit under ~0.3; distinct lessons are farther.
NEAR_DUP_L2 = 0.3


def _norm(s: str) -> str:
    return _WS.sub(" ", s.lower()).strip()


def _l2(a: list[float], b: list[float]) -> float:
    """Euclidean distance between two vectors (same metric LanceDB reports)."""
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def _nearest_reflection_l2(store, vector, tname) -> float:
    """L2 distance to the nearest existing reflection, or +inf if none/error."""
    try:
        hits = store.search_by_vector(
            vector, limit=1, category="reflection", table_name=tname
        )
        if hits:
            d = hits[0].get("score", hits[0].get("_distance"))
            if d is not None:
                return float(d)
    except Exception:  # noqa: BLE001
        pass
    return float("inf")


def record_reflection(
    lessons: list[str] | str,
    dedup: bool = True,
    near_dup_l2: float = NEAR_DUP_L2,
) -> dict[str, Any]:
    """Write reflection lessons to the KB.

    Args:
        lessons: one lesson string or a list of them. Each becomes one
                 reflection memory (scope=global, TTL-bounded).
        dedup:   skip a lesson that duplicates a live reflection — exact text
                 OR a semantic near-duplicate (L2 < ``near_dup_l2``).
        near_dup_l2: L2 distance under which two reflections are "the same
                 lesson" (default 0.3).

    Returns:
        ``{"status", "written", "skipped", "ids"}``.
    """
    if isinstance(lessons, str):
        lessons = [lessons]
    lessons = [x.strip() for x in (lessons or []) if x and x.strip()]
    if not lessons:
        return {"status": "error", "message": "no lessons given", "written": 0}

    from olav.core.memory import MEMORY_TABLE, MemoryCategory, get_store

    try:
        store = get_store()
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": f"cannot load store: {exc}", "written": 0}

    tname = MEMORY_TABLE
    if not store.table_exists(tname):
        store.create_table(tname)

    existing: set[str] = set()
    if dedup:
        try:
            for m in store.get_memories(
                category="reflection", limit=500, table_name=tname
            ):
                text = m.get("text") if isinstance(m, dict) else getattr(m, "text", None)
                if text:
                    existing.add(_norm(text))
        except Exception:  # noqa: BLE001
            existing = set()

    try:
        from olav.core.embedder import embed_text
    except Exception:  # noqa: BLE001
        embed_text = None  # type: ignore

    batch_vectors: list[list[float]] = []  # near-dup guard within this batch
    written, skipped, ids = 0, 0, []
    for lesson in lessons:
        # Fast exact-dup pre-check (also catches exact within-batch).
        if dedup and _norm(lesson) in existing:
            skipped += 1
            continue

        vector = None
        if embed_text is not None:
            try:
                vector = embed_text(lesson)
            except Exception:  # noqa: BLE001
                vector = None

        # Near-duplicate check (semantic): skip a lesson that paraphrases an
        # existing reflection. `olav kb bench` surfaced that exact-match dedup
        # let near-identical reflections pile up (they then outrank each other
        # at recall rank-1). A persisted reflection within NEAR_DUP_L2 of this
        # one, OR one already written this batch, means "same lesson" → skip.
        if dedup and vector is not None:
            if _nearest_reflection_l2(store, vector, tname) < near_dup_l2:
                skipped += 1
                continue
            if any(_l2(vector, bv) < near_dup_l2 for bv in batch_vectors):
                skipped += 1
                continue

        try:
            mid = f"reflect-{uuid.uuid4().hex[:8]}"
            store.add_memory(
                id=mid,
                text=lesson,
                vector=vector or [0.0] * store.embedding_dim,
                category=MemoryCategory.REFLECTION,
                scope="global",
                metadata={"source": "admin_reflector", "origin": "daily_reflection"},
                tags=json.dumps(["reflection", "reflector"]),
                table_name=tname,
            )
            existing.add(_norm(lesson))
            if vector is not None:
                batch_vectors.append(vector)
            ids.append(mid)
            written += 1
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "message": f"write failed: {exc}",
                    "written": written, "skipped": skipped, "ids": ids}

    return {"status": "ok", "written": written, "skipped": skipped, "ids": ids}


if __name__ == "__main__":
    args = json.loads(sys.stdin.read() or "{}")
    print(json.dumps(record_reflection(**args), default=str))
