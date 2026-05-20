#!/usr/bin/env python3
"""propose_memory_draft — Turn-1 helper for R102 multi-turn HITL.

deepagents `task()` sub-agent calls are stateless per invocation, so
``memory_curator`` Turn-2 (user confirms) cannot see the YAML it
proposed in Turn-1.  This tool persists the draft to disk:

* Turn 1: agent calls ``propose_memory_draft(...)`` → writes
  ``<workspace>/.curator_drafts/<intent>.draft.json`` and returns the
  formatted YAML preview text + a draft_id the agent shows to the
  user.
* Turn 2: user confirms → agent calls
  ``commit_to_memory(from_draft=True)`` (or with intent=) which reads
  the draft, commits, and archives it.

This breaks the stateless-task() ↔ HITL impasse without any
architectural change to deepagents itself.

See ``dev_docs/00 § ISSUE-R102-MULTITURN-HITL-BROKEN``.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


_VALID_CATEGORIES = {"usage_guide", "document", "topology"}


def _find_project_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


def _resolve_workspace_root() -> Path:
    if env := os.environ.get("OLAV_WORKSPACE_ROOT"):
        return Path(env)
    cwd_workspace = Path.cwd() / ".olav" / "workspace"
    if cwd_workspace.exists():
        return cwd_workspace
    return _find_project_root() / "src" / "olav" / "data" / "workspace"


def _drafts_dir() -> Path:
    """Where curator drafts live — under workspace_root/.curator_drafts/."""
    d = _resolve_workspace_root() / ".curator_drafts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _render_preview(payload: dict) -> str:
    """Render the YAML preview the user will see + confirm."""
    visibility = (
        f"{payload['agent']} agent + global"
        if payload["scope"] == "global"
        else payload["scope"]
    )
    if payload["category"] == "document":
        n = len(payload.get("chunks") or [])
        return (
            f"Proposed memory entry ({n} document chunks):\n\n"
            f"```yaml\n"
            f"intent:    {payload['intent']}\n"
            f"agent:     {payload['agent']}\n"
            f"scope:     {payload['scope']}\n"
            f"category:  document\n"
            f"keywords:  {payload['keywords']}\n"
            f"chunks:    [{n} chunks, {sum(len(c) for c in (payload.get('chunks') or []))} total chars]\n"
            f"```\n\n"
            f"Will write to: LanceDB ({n} document rows, no on-disk YAML).\n"
            f"AutoRecall surfaces to: {visibility}.\n\n"
            f"Confirm? (Reply ``OK`` / ``yes`` / ``可以`` / ``入库`` / ``确认`` "
            f"and I'll commit.)"
        )
    body_yaml = yaml.safe_dump(
        {
            "schema_version": 1,
            "intent": payload["intent"],
            "agent": payload["agent"],
            "scope": payload["scope"],
            "category": payload["category"],
            "keywords": payload["keywords"],
            "body": payload["body"],
        },
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )
    target_file = (
        f"<workspace>/{payload['agent']}/guides/{payload['intent']}.guide.yaml"
        if payload["category"] == "usage_guide"
        else f"LanceDB topology row (id=topology_{payload['agent']}_{payload['intent']})"
    )
    return (
        f"Proposed memory entry:\n\n"
        f"```yaml\n{body_yaml}```\n\n"
        f"Will write to: {target_file}.\n"
        f"AutoRecall surfaces to: {visibility}.\n\n"
        f"Confirm? (Reply ``OK`` / ``yes`` / ``可以`` / ``入库`` / ``确认`` "
        f"and I'll commit.)"
    )


def propose_memory_draft(
    intent: str,
    keywords: list[str],
    body: str = "",
    agent: str = "core",
    scope: str = "global",
    category: str = "usage_guide",
    chunks: list[str] | None = None,
) -> dict:
    """Propose a memory entry — write draft to disk + return YAML preview.

    Use this in Turn 1 of the conversational ingestion flow.  Then ask
    the user to confirm; on their confirmation reply (Turn 2) call
    ``commit_to_memory(from_draft=True, intent=...)``  to seal it.

    Args:
        intent:    snake_case identifier (also used as draft filename)
        keywords:  list of search hints (en + zh recommended)
        body:      prose body for usage_guide / topology categories
        agent:     "core" | "ops" | "services" | "audit" | ...
        scope:     "global" (default) | agent name | "team:<id>"
        category:  "usage_guide" | "document" | "topology"
        chunks:    list of pre-chunked strings (REQUIRED for category=document)

    Returns:
        {
          "status": "draft_saved",
          "draft_id": "<intent>",
          "draft_path": "<absolute path>",
          "preview": "<rendered YAML + confirm prompt to show user>",
          "expires_at": <unix-ts 24h from now>,
        }
    """
    if not intent or not isinstance(intent, str):
        return {"status": "error", "message": "intent (snake_case str) required"}
    if not keywords or not isinstance(keywords, list):
        return {"status": "error", "message": "keywords must be a non-empty list"}
    if category not in _VALID_CATEGORIES:
        return {
            "status": "error",
            "message": f"category must be one of {sorted(_VALID_CATEGORIES)}",
        }

    keywords = [str(k) for k in keywords if str(k).strip()]
    if not keywords:
        return {"status": "error", "message": "keywords must contain at least one non-empty string"}

    if category == "document":
        if not chunks or not isinstance(chunks, list):
            return {
                "status": "error",
                "message": "category='document' requires a non-empty chunks list",
            }
    elif not body or not isinstance(body, str):
        return {
            "status": "error",
            "message": f"category={category!r} requires a non-empty body string",
        }

    payload = {
        "intent": intent,
        "keywords": keywords,
        "body": body,
        "agent": agent,
        "scope": scope,
        "category": category,
        "chunks": chunks,
        "created_at": time.time(),
    }
    draft_path = _drafts_dir() / f"{intent}.draft.json"
    draft_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                          encoding="utf-8")

    return {
        "status": "draft_saved",
        "draft_id": intent,
        "draft_path": str(draft_path),
        "preview": _render_preview(payload),
        "expires_at": payload["created_at"] + 86400,  # 24h
    }


if __name__ == "__main__":
    try:
        raw = sys.stdin.read()
        params = json.loads(raw) if raw.strip() else {}
        print(json.dumps(propose_memory_draft(**params),
                         ensure_ascii=False, indent=2))
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)},
                         ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
