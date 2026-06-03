"""Store Memory Tool — Explicit long-term memory WRITE for agents.

Write-side counterpart to ``olav_recall_memory`` (read). Use this when the user
explicitly asks to remember a durable fact/preference, or when you learn
something worth persisting for future sessions.

Writes to OLAV's own LanceDB semantic memory (``origin="user"``), which is
SEPARATE from deepagents' native AGENTS.md file memory — OLAV does not touch
the native memory subsystem. Entries written here are later retrievable via
``olav_recall_memory`` (hybrid vector + BM25 search) and by the Auto-Recall
middleware.
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

logger = logging.getLogger(__name__)


@tool
def olav_store_memory(
    text: str,
    category: str = "fact",
    tags: list[str] | None = None,
    scope: str = "global",
) -> str:
    """Save a durable fact or preference to OLAV long-term memory (LanceDB).

    Call this when the user EXPLICITLY asks you to remember something
    ("remember that ...", "记住 ..."), or when you learn a durable
    preference/decision/fact worth recalling in future sessions. The text is
    embedded and stored with ``origin="user"`` so it is later retrievable via
    ``olav_recall_memory``.

    Do NOT use for transient/one-off task context — only durable knowledge.
    Never store credentials, API keys, or passwords.

    Args:
        text:     The fact/preference to remember — a clear, self-contained
                  statement ("R2 is scheduled for decommission in Q3").
        category: "fact" (default) / "decision" / "preference".
        tags:     Optional topic/entity tags for retrieval (e.g. ["R2", "decommission"]).
        scope:    Memory scope (default "global").

    Returns:
        Confirmation with the stored memory id, or an error message.
    """
    if not text or not text.strip():
        return "Error: text must not be empty."

    from olav.tools.memory import store_memory as _store

    result = _store(text=text, category=category, tags=tags, scope=scope, confidence=1.0)

    if isinstance(result, dict) and (result.get("id") and result.get("status") not in ("error", "blocked")):
        return f"✓ Stored to long-term memory [{category}] (id={result.get('id')})."
    reason = result.get("reason", result) if isinstance(result, dict) else result
    return f"Failed to store memory: {reason}"


if __name__ == "__main__":
    data = json.loads(sys.stdin.read() or "{}")
    print(json.dumps(olav_store_memory.invoke(data), ensure_ascii=False))
