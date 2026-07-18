#!/usr/bin/env python3
"""propose_guide_draft — draft a usage_guide for human (HITL) review.

The KB "draft → HITL" lane of the reflector agent. Unlike a reflection (one
disposable line, TTL-bounded, written directly by record_reflection), a
``usage_guide`` is a permanent steering document that AutoRecall injects on
matching intent. Because it's permanent, the reflector never commits one
directly — it writes a DRAFT to ``.curator_drafts/`` and a human seals it via
memory-curator's ``commit_to_memory(from_draft=True, intent=...)``.

The draft payload format is byte-compatible with what memory-curator's
commit_to_memory reads (same as trace_review --propose), so the existing
HITL bridge handles the commit — this script only proposes.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any


def _resolve_drafts_dir() -> Path:
    """Resolve the memory-curator drafts dir (must match propose_memory_draft/
    trace_learner so commit_to_memory finds the draft)."""
    import os

    if env := os.environ.get("OLAV_WORKSPACE_ROOT"):
        root = Path(env)
    else:
        cwd_ws = Path.cwd() / ".olav" / "workspace"
        root = cwd_ws if cwd_ws.exists() else Path(__file__).resolve().parents[4]
    d = root / ".curator_drafts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def propose_guide_draft(
    intent: str,
    body: str,
    keywords: list[str] | None = None,
    agent: str = "core",
    scope: str | None = None,
) -> dict[str, Any]:
    """Write a usage_guide draft for HITL commit.

    Args:
        intent:   short slug identifying the guide (e.g. "handle_dict_arg_coercion").
        body:     the guide text (WHAT + constraints, not raw log dumps).
        keywords: recall keywords; defaults derived from the intent.
        agent:    which agent the guide steers (its scope). "core" = broad.
        scope:    override the memory scope; defaults to ``agent``.

    Returns:
        ``{"status", "intent", "draft_path", "next_step"}``.
    """
    intent = (intent or "").strip().replace(" ", "_")
    body = (body or "").strip()
    if not intent or not body:
        return {"status": "error", "message": "intent and body are required"}

    payload = {
        "intent": intent,
        "keywords": (keywords or [intent.replace("_", " ")]) + [agent, "reflector"],
        "body": body,
        "agent": agent,
        "scope": scope or agent,
        "category": "usage_guide",
        "chunks": None,
        "created_at": time.time(),
        "source": "admin_reflector_propose",
    }
    drafts_dir = _resolve_drafts_dir()
    draft_path = drafts_dir / f"{intent}.draft.json"
    draft_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "status": "draft_saved",
        "intent": intent,
        "draft_path": str(draft_path),
        "next_step": (
            f"Human review, then seal via memory-curator: "
            f"commit_to_memory(from_draft=True, intent='{intent}')."
        ),
    }


if __name__ == "__main__":
    args = json.loads(sys.stdin.read() or "{}")
    print(json.dumps(propose_guide_draft(**args), default=str))
