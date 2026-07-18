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


def _norm(s: str) -> str:
    return _WS.sub(" ", s.lower()).strip()


def record_reflection(lessons: list[str] | str, dedup: bool = True) -> dict[str, Any]:
    """Write reflection lessons to the KB.

    Args:
        lessons: one lesson string or a list of them. Each becomes one
                 reflection memory (scope=global, TTL-bounded).
        dedup:   skip a lesson whose text already exists as a live reflection.

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

    written, skipped, ids = 0, 0, []
    for lesson in lessons:
        if dedup and _norm(lesson) in existing:
            skipped += 1
            continue
        try:
            try:
                from olav.core.embedder import embed_text
                vector = embed_text(lesson)
            except Exception:  # noqa: BLE001
                vector = None
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
            ids.append(mid)
            written += 1
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "message": f"write failed: {exc}",
                    "written": written, "skipped": skipped, "ids": ids}

    return {"status": "ok", "written": written, "skipped": skipped, "ids": ids}


if __name__ == "__main__":
    args = json.loads(sys.stdin.read() or "{}")
    print(json.dumps(record_reflection(**args), default=str))
