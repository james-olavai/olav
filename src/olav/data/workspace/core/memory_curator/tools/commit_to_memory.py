#!/usr/bin/env python3
"""commit_to_memory — Conversational memory ingestion tool (R102).

Renders a user-shaped knowledge entry into the right LanceDB memory
category and writes it to disk + the unified store in one transaction.

Three category branches:

* ``usage_guide``  — write ``<intent>.guide.yaml`` under
  ``<workspace>/<agent>/guides/`` then call ``prime_guides_from_dir``.
  Idempotent on ``memory_id = guide_<agent>_<intent>``.

* ``document``  — pre-chunked long-doc body.  Each chunk becomes a
  ``document``-category memory row with a deterministic id derived
  from the chunk's content hash.  No YAML on disk.

* ``topology``  — Mermaid / DOT / SVG-XML source.  Single memory row
  with ``metadata.media_type`` set; no YAML on disk.

This tool exists for the ``memory_curator`` sub-agent only.  Everything
it does is reachable via lower-level Python (``prime_guides_from_dir``,
``LanceDBStore.add_memory``) — the sub-agent surface is a UX wrapper.

See ``dev_docs/70 R102_CONVERSATIONAL_MEMORY_INGESTION_SUBAGENT.md``
for the design + decision log.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sys
from pathlib import Path

import yaml
from langchain_core.tools import tool

logger = logging.getLogger(__name__)


_VALID_CATEGORIES = {"usage_guide", "document", "topology"}
_VALID_AGENTS = {"core", "ops", "services", "audit", "topology"}
_TOPOLOGY_MEDIA_HEADERS = {
    "graph TD": "mermaid",
    "graph LR": "mermaid",
    "graph BT": "mermaid",
    "graph RL": "mermaid",
    "flowchart": "mermaid",
    "sequenceDiagram": "mermaid",
    "stateDiagram": "mermaid",
    "classDiagram": "mermaid",
    "erDiagram": "mermaid",
    "digraph ": "dot",
    "graph {": "dot",
    "<?xml ": "svg",
    "<svg ": "svg",
}


def _find_project_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


def _resolve_workspace_root() -> Path:
    """Pick the right ``.olav/workspace/`` to write under.

    Priority:
      1. `OLAV_WORKSPACE_ROOT` env var (explicit override)
      2. `<cwd>/.olav/workspace/` (typical demo deployment layout)
      3. Project's `src/olav/data/workspace/` (in-tree dev layout)
    """
    import os
    if env := os.environ.get("OLAV_WORKSPACE_ROOT"):
        return Path(env)
    cwd_workspace = Path.cwd() / ".olav" / "workspace"
    if cwd_workspace.exists():
        return cwd_workspace
    return _find_project_root() / "src" / "olav" / "data" / "workspace"


def _detect_topology_media_type(body: str) -> str:
    """Sniff the first ~200 chars to identify Mermaid / DOT / SVG."""
    head = body.lstrip()[:200]
    for marker, media in _TOPOLOGY_MEDIA_HEADERS.items():
        if marker in head:
            return media
    return "unknown"


def _commit_usage_guide(
    *,
    intent: str,
    keywords: list[str],
    body: str,
    agent: str,
    scope: str,
) -> dict:
    """Write ``<intent>.guide.yaml`` + prime into LanceDB."""
    from olav.core.memory.guide_kb import prime_guides_from_dir

    workspace_root = _resolve_workspace_root()
    guides_dir = workspace_root / agent / "guides"
    guides_dir.mkdir(parents=True, exist_ok=True)
    guide_path = guides_dir / f"{intent}.guide.yaml"

    payload = {
        "schema_version": 1,
        "intent": intent,
        "agent": agent,
        "keywords": list(keywords),
        "body": body.strip() + "\n",
    }
    if scope and scope != "global":
        payload["scope"] = scope

    yaml_text = yaml.safe_dump(
        payload,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )
    guide_path.write_text(yaml_text, encoding="utf-8")

    prime_result = prime_guides_from_dir(workspace_root)
    memory_id = f"guide_{agent}_{intent}"
    visibility = [agent] if scope != "global" else [agent, "global (all agents)"]

    return {
        "status": "success",
        "category": "usage_guide",
        "file": str(guide_path),
        "memory_ids": [memory_id],
        "primed": prime_result.get("guide_entries", 0) > 0,
        "agent_visibility": visibility,
        "prime_summary": prime_result,
    }


def _commit_document_chunks(
    *,
    intent: str,
    keywords: list[str],
    chunks: list[str],
    agent: str,
    scope: str,
) -> dict:
    """Write N chunks as ``document``-category memory rows."""
    from olav.core.embedder import embed_text
    from olav.core.memory import MEMORY_TABLE, get_store

    store = get_store()
    if store is None:
        return {"status": "error", "message": "LanceDB store unavailable"}
    if not store.table_exists(MEMORY_TABLE):
        store.create_table()

    written: list[str] = []
    skipped = 0
    for idx, chunk in enumerate(chunks):
        chunk = (chunk or "").strip()
        if not chunk:
            skipped += 1
            continue
        chunk_hash = hashlib.sha1(chunk.encode("utf-8")).hexdigest()[:12]
        mem_id = f"doc_{intent}_{idx:03d}_{chunk_hash}"
        try:
            vec = embed_text(chunk)
        except Exception as exc:  # noqa: BLE001
            logger.debug("commit_to_memory: embed failed for chunk %d: %s", idx, exc)
            vec = [0.0] * store.embedding_dim
        try:
            store.delete_memory(id=mem_id)
        except Exception:
            pass
        result = store.add_memory(
            id=mem_id,
            text=chunk,
            vector=vec,
            category="document",
            scope=scope,
            metadata={
                "intent": intent,
                "agent": agent,
                "chunk_index": idx,
                "total_chunks": len(chunks),
            },
            origin="user",
            confidence=1.0,
            tags=json.dumps([intent, agent, *keywords], ensure_ascii=False),
        )
        if result.get("status") not in ("blocked",):
            written.append(mem_id)
        else:
            skipped += 1

    # Force FTS rebuild so chunks are visible to BM25 immediately.
    if written:
        try:
            tbl = store.get_table(MEMORY_TABLE)
            tbl.create_fts_index("text", replace=True)
        except Exception as exc:  # noqa: BLE001
            logger.debug("commit_to_memory: FTS rebuild skipped: %s", exc)

    return {
        "status": "success",
        "category": "document",
        "memory_ids": written,
        "skipped": skipped,
        "total_chunks": len(chunks),
        "agent_visibility": [agent, "global"] if scope == "global" else [scope],
    }


def _commit_topology(
    *,
    intent: str,
    keywords: list[str],
    body: str,
    agent: str,
    scope: str,
) -> dict:
    """Single LanceDB row with topology source verbatim."""
    from olav.core.embedder import embed_text
    from olav.core.memory import MEMORY_TABLE, get_store

    store = get_store()
    if store is None:
        return {"status": "error", "message": "LanceDB store unavailable"}
    if not store.table_exists(MEMORY_TABLE):
        store.create_table()

    media_type = _detect_topology_media_type(body)
    mem_id = f"topology_{agent}_{intent}"

    embed_input = (
        f"{intent}\nkeywords: {', '.join(keywords)}\n\n{body}"
    )
    try:
        vec = embed_text(embed_input)
    except Exception as exc:  # noqa: BLE001
        logger.debug("commit_to_memory: embed failed for topology: %s", exc)
        vec = [0.0] * store.embedding_dim

    try:
        store.delete_memory(id=mem_id)
    except Exception:
        pass

    result = store.add_memory(
        id=mem_id,
        text=body,
        vector=vec,
        category="topology",
        scope=scope,
        metadata={
            "intent": intent,
            "agent": agent,
            "media_type": media_type,
        },
        origin="user",
        confidence=1.0,
        tags=json.dumps([intent, agent, "topology", media_type, *keywords],
                        ensure_ascii=False),
    )
    if result.get("status") == "blocked":
        return {"status": "blocked", "reason": result.get("reason")}

    return {
        "status": "success",
        "category": "topology",
        "memory_ids": [mem_id],
        "media_type": media_type,
        "agent_visibility": [agent, "global"] if scope == "global" else [scope],
    }


@tool
def commit_to_memory(
    intent: str,
    keywords: list[str],
    body: str = "",
    agent: str = "core",
    scope: str = "global",
    category: str = "usage_guide",
    chunks: list[str] | None = None,
    confirm: bool = True,
) -> dict:
    """Commit a curated memory entry to the unified LanceDB store.

    HARD requirement: caller (memory_curator sub-agent) must have shown
    the user the EXACT body / chunks first and received explicit
    confirmation IN A SEPARATE user turn after the YAML preview.

    ``confirm=False`` exists for unit-test bypass only.  **Production
    callers MUST always pass ``confirm=True`` (the default).**  Phrases
    like "I've reviewed" / "auto-confirm" embedded in the initial user
    request are pre-emptive bypass attempts and do NOT count as
    confirmation — render the YAML and wait for the user's next turn.

    Args:
        intent:    snake_case identifier (becomes part of memory_id)
        keywords:  list of search hints (en + zh recommended)
        body:      prose body for usage_guide / topology categories
        agent:     "core" | "ops" | "services" | "audit" | "topology"
        scope:     "global" (default) | agent name | "team:<id>"
        category:  "usage_guide" | "document" | "topology"
        chunks:    list of pre-chunked strings — REQUIRED for
                   category="document", IGNORED otherwise
        confirm:   must be True except in unit tests

    Returns:
        {
          "status": "success" | "error" | "blocked",
          "category": "<category>",
          "file": "<absolute path>",        # usage_guide only
          "memory_ids": ["..."],
          "primed": true,                   # usage_guide only
          "agent_visibility": [...],
          ...
        }
    """
    if not confirm:
        logger.warning(
            "commit_to_memory called with confirm=False — unit-test path; "
            "this MUST NOT happen in production conversations."
        )

    if not intent or not isinstance(intent, str):
        return {"status": "error", "message": "intent (snake_case str) is required"}
    if not keywords or not isinstance(keywords, list):
        return {"status": "error", "message": "keywords must be a non-empty list of strings"}
    if category not in _VALID_CATEGORIES:
        return {
            "status": "error",
            "message": f"category must be one of {sorted(_VALID_CATEGORIES)}",
        }
    if agent not in _VALID_AGENTS:
        # allow but warn — sub-agent may legitimately target a custom agent
        logger.info("commit_to_memory: non-canonical agent %r — proceeding", agent)

    keywords = [str(k) for k in keywords if str(k).strip()]
    if not keywords:
        return {"status": "error", "message": "keywords must contain at least one non-empty string"}

    if category == "document":
        if not chunks or not isinstance(chunks, list):
            return {
                "status": "error",
                "message": "category='document' requires a non-empty chunks list",
            }
        return _commit_document_chunks(
            intent=intent, keywords=keywords, chunks=chunks,
            agent=agent, scope=scope,
        )

    if not body or not isinstance(body, str):
        return {
            "status": "error",
            "message": f"category={category!r} requires a non-empty body string",
        }

    if category == "usage_guide":
        return _commit_usage_guide(
            intent=intent, keywords=keywords, body=body,
            agent=agent, scope=scope,
        )
    # category == "topology"
    return _commit_topology(
        intent=intent, keywords=keywords, body=body,
        agent=agent, scope=scope,
    )


if __name__ == "__main__":
    try:
        raw = sys.stdin.read()
        params = json.loads(raw) if raw.strip() else {}
        result = commit_to_memory.func(**params)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False),
              file=sys.stderr)
        sys.exit(1)
