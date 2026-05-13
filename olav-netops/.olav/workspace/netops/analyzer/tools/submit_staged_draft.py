"""submit_staged_draft @tool — section-by-section draft compose with per-section lint.

R-MULTI-LLM-HYBRID design 4 (dev_docs/76, prototype 2026-05-13).

Replaces the one-shot ``submit_draft`` workflow for change requests.
Inside the tool we orchestrate:

  S1 scope        — LLM: extract user_prompt + devices_in_scope (JSON)
  (Python: inspect_devices(scope), inspect_topology(scope) — DB query)
  S2 facts        — LLM: copy inspector JSON → facts_collected envelope
  S3 intent       — LLM: choose intent + rationale
  S4 intent_args  — LLM: per-intent shape (currently freeform_cli only)

Each section: focused prompt + JSON parse + lint → retry feedback if
fail (max 3). Final whole-draft lint before disk write.

The user only passes ``user_prompt``. Everything else (inspector calls,
schema lookup, lint, retry) is internal. Returns same envelope shape
as the old submit_draft so orchestrator routing is unchanged:

    {
      "status": "ok",
      "change_id": "...",
      "draft_path": "exports/cab/<id>/draft.yaml",
      "journal_path": "exports/cab/<id>/staged_fill_journal.json",
      "next_step": {"action": "sim_finalize", "sub_agent": "sim",
                     "args": {"draft_path": ...}}
    }

On failure (lint exhausted, parse error, etc.) the envelope reports
``status: "error"`` with the journal path so HITL can inspect WHY.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml
from langchain_core.tools import tool


_INTENT_STEM_RE = re.compile(r"[^a-z0-9]+")


def _slugify(s: str) -> str:
    return _INTENT_STEM_RE.sub("-", s.lower()).strip("-")[:60] or "change"


def _auto_change_id(devices: list[str], intent: str) -> str:
    stem = intent.split("_")[0]
    return _slugify("-".join(devices) + "-" + stem)


@tool
def submit_staged_draft(
    user_prompt: str,
    output_root: str = "exports/cab",
) -> dict[str, Any]:
    """Compose a DraftChangePlan section-by-section with per-section lint.

    Use this for ANY change request — single or multi-device, any intent.
    The tool runs through inspector queries + 4 focused LLM passes
    internally, with lint after each pass and bounded retries. You do
    NOT need to call inspect_* yourself first; this tool does it.

    Args:
        user_prompt: The user's request, verbatim (e.g. "Add OSPF
            Area 0 between R1 and R3"). The tool will:
              1. Extract devices_in_scope from your prompt
              2. Query DB for facts (devices + topology)
              3. Choose intent + rationale
              4. Fill intent_args per the chosen intent
              5. Write draft.yaml + journal to disk
        output_root: Where to write ``<change_id>/draft.yaml``.
            Defaults to "exports/cab".

    Returns:
        On success:
            {"status": "ok", "change_id": ..., "draft_path": ...,
             "journal_path": ...,
             "next_step": {"action": "sim_finalize", "sub_agent": "sim",
                           "args": {"draft_path": ...}}}
        On failure (any section exhausted retries):
            {"status": "error", "error": "...", "journal_path": ...}

    The journal_path always exists — it records every LLM call, every
    lint feedback round, every retry. Useful for debugging analyzer
    behaviour on the operator side.
    """
    from olav.core.cab.draft_fill import (
        run_staged_fill,
        inspect_devices,
        inspect_topology,
        make_llm_callable,
    )

    llm = make_llm_callable(agent_id="analyzer")

    journal_obj = None
    journal_path: Path | None = None

    try:
        draft, journal = run_staged_fill(
            user_prompt=user_prompt,
            llm=llm,
            inspect_devices=inspect_devices,
            inspect_topology=inspect_topology,
            max_attempts_per_section=3,
        )
        journal_obj = journal
    except Exception as e:
        # Persist whatever journal we managed to build (run_staged_fill
        # journal is internal — if it raised, we don't have access).
        cab_dir = Path(output_root) / "staged_fill_failures"
        cab_dir.mkdir(parents=True, exist_ok=True)
        from datetime import datetime, UTC
        ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
        journal_path = cab_dir / f"failure_{ts}.json"
        journal_path.write_text(json.dumps(
            {"user_prompt": user_prompt, "error": str(e)},
            indent=2, default=str,
        ), encoding="utf-8")
        return {
            "status": "error",
            "error": f"staged-fill failed: {e}",
            "journal_path": str(journal_path),
            "hint": (
                "One section exhausted its retry budget. Common causes: "
                "(a) user_prompt content contradicts DB facts (e.g. "
                "claiming a different platform/AS than recorded); "
                "(b) model returns empty content (check num_ctx /  "
                "num_predict in LLMFactory); (c) network device names "
                "not in DB. Inspect the journal for per-attempt lint "
                "errors and LLM responses."
            ),
        }

    # Write draft.yaml + journal
    change_id = _auto_change_id(
        draft.devices_in_scope, draft.proposed_intent,
    )
    cab_dir = Path(output_root) / change_id
    cab_dir.mkdir(parents=True, exist_ok=True)
    draft_path = cab_dir / "draft.yaml"
    draft_path.write_text(
        yaml.safe_dump(draft.model_dump(mode="python"), sort_keys=False),
        encoding="utf-8",
    )
    journal_path = cab_dir / "staged_fill_journal.json"
    journal_path.write_text(
        json.dumps(journal_obj.to_dict(), indent=2, default=str),
        encoding="utf-8",
    )

    return {
        "status": "ok",
        "change_id": change_id,
        "draft_path": str(draft_path),
        "journal_path": str(journal_path),
        "next_step": {
            "action": "sim_finalize",
            "sub_agent": "sim",
            "args": {"draft_path": str(draft_path)},
            "hint": (
                f"Draft saved via staged-fill ({journal_obj.total_elapsed_s:.0f}s, "
                f"{sum(s['attempts'] for s in journal_obj.per_section_stats().values())} "
                f"LLM calls). Hand off to Sim via "
                f"task('sim', 'finalize', {{'draft_path': {str(draft_path)!r}}})."
            ),
        },
    }
