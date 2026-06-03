#!/usr/bin/env python3
"""Store Memory — Explicit long-term memory WRITE for agents.

Plain-function (script) counterpart to the ``olav_store_memory`` @tool, runnable
via ``execute_skill_script`` (stdin JSON). Write-side counterpart to
``olav_recall_memory``. Persists a durable fact/preference to OLAV's LanceDB
semantic memory (``origin="user"``) — separate from deepagents' native AGENTS.md
file memory. Later retrievable via ``olav_recall_memory``.
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


def olav_store_memory(
    text: str,
    category: str = "fact",
    tags: list[str] | None = None,
    scope: str = "global",
) -> str:
    """Save a durable fact or preference to OLAV long-term memory (LanceDB).

    Call this when the user EXPLICITLY asks you to remember something, or when
    you learn a durable preference/decision/fact worth recalling in future
    sessions. The text is embedded and stored with ``origin="user"`` so it is
    later retrievable via ``olav_recall_memory``.

    Do NOT use for transient/one-off task context. Never store credentials.

    Args:
        text:     The fact/preference to remember — clear and self-contained.
        category: "fact" (default) / "decision" / "preference".
        tags:     Optional topic/entity tags for retrieval.
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
    _args = json.loads(sys.stdin.read() or "{}")
    result = olav_store_memory(**_args)
    print(json.dumps(result, default=str))
