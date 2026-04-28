"""L2 of agentic memory growth — extract reusable patterns from L1
``operational_event`` memories.

Reads operational_event memories for a given scope, groups by tool
name, and (when group size ≥ ``min_samples``) calls the chat model
once per group to abstract a reusable pattern. The pattern is
written back as a ``expert_knowledge`` memory so future
AutoRecall pulls one well-curated entry instead of N raw events.

Why this is a Python helper, not middleware:
* Triggered on demand (cron, agent task, manual CLI) — not hot-path
* LLM call is expensive — must be batchable / scheduled
* Failure isolation: an extraction run that crashes shouldn't break
  the agent's main flow

Why this is NOT a new agent:
* Curator agent already exists for cross-cutting memory work; this
  is simply a callable it can spin up via ``run_python_simulation``
  or the CLI can invoke directly
* No new agent registry entry, no new SKILL.md, no new prompts —
  just a one-shot Python entry point

Usage::

    from olav.core.memory.pattern_extractor import extract_operational_patterns
    result = extract_operational_patterns(
        scope="services",
        min_samples=5,
        window_days=30,
    )
    # → {"groups_processed": 2, "patterns_written": 2, "skipped": 0}

Or from CLI / agent:

    python -m olav.core.memory.pattern_extractor --scope services --min-samples 5
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)


_EXTRACT_PROMPT_TEMPLATE = """You are a network ops knowledge curator.

Below are {n} captured operational events from scope='{scope}' for tool
'{tool}'. Each event records one successful call (action + args + result).

Your task: extract a single reusable PATTERN that captures the
"how we tend to do this here" — naming conventions, common args,
typical outcomes — that another engineer (or agent) reading the pattern
once could re-apply to a new request.

Rules:
* Output 5-12 short bullet points
* No invented details — use only facts from the samples
* Highlight conventions: naming patterns, auth modes, env vars, IPs
* Note any sample-to-sample variance worth flagging
* Format: plain text, no markdown headers; one bullet per line starting "- "

EVENTS:

{events}

PATTERN (5-12 bullets):
"""


def _format_events_for_prompt(events: list[dict]) -> str:
    """Concatenate event summaries into the prompt block."""
    lines = []
    for i, e in enumerate(events, 1):
        text = e.get("text", "")
        ts = e.get("created_at", "?")
        lines.append(f"--- event {i} (recorded {ts}) ---\n{text}\n")
    return "\n".join(lines)


def _build_pattern_text(
    tool: str,
    scope: str,
    pattern_body: str,
    sample_count: int,
) -> str:
    """Wrap the LLM-extracted body with attribution + provenance metadata."""
    return (
        f"Operational pattern for {tool!r} in scope {scope!r} "
        f"(extracted from {sample_count} prior events):\n\n"
        f"{pattern_body.strip()}\n"
    )


def extract_operational_patterns(
    scope: str = "global",
    *,
    min_samples: int = 5,
    window_days: int = 30,
    chat_model: Any | None = None,
    store: Any | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Read operational_event memories for ``scope``, group by tool,
    and write one ``expert_knowledge`` pattern per group with ≥
    ``min_samples`` events in the last ``window_days``.

    Args:
        scope: Memory scope to scan (e.g. "services", "ops", "global").
        min_samples: Minimum events per tool to bother extracting.
        window_days: Only consider events created within this window.
        chat_model: Pre-configured LangChain chat model. If None, uses
            ``olav.core.llm.get_chat_model(temperature=0.1)``.
        store: Memory store. If None, uses ``olav.core.memory.get_store()``.
        dry_run: When True, run the LLM and return the patterns but
            don't write to memory. For inspection / debugging.

    Returns:
        dict: ``{groups_seen, groups_processed, patterns_written,
                  skipped_low_samples, skipped_llm_error,
                  patterns: [{tool, sample_count, body}]}``.
    """
    from olav.core.memory import MEMORY_TABLE, get_store

    if store is None:
        store = get_store()
    if chat_model is None:
        from olav.core.llm import get_chat_model
        chat_model = get_chat_model(temperature=0.1)

    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)

    # Pull operational_event memories for the scope
    try:
        tbl = store.get_table(MEMORY_TABLE)
        rows = (
            tbl.search()
            .where(
                f"scope = '{scope}' AND category = 'operational_event'",
                prefilter=True,
            )
            .limit(10_000)
            .to_list()
        )
    except Exception as exc:
        logger.warning("pattern_extractor: read failed: %s", exc)
        return {
            "groups_seen": 0,
            "groups_processed": 0,
            "patterns_written": 0,
            "error": str(exc),
        }

    # Group by tool name (from metadata)
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        md = r.get("metadata") or "{}"
        try:
            md_dict = json.loads(md) if isinstance(md, str) else md
        except Exception:
            md_dict = {}
        tool = md_dict.get("tool")
        if not tool:
            continue
        # Filter by window
        ts = r.get("created_at")
        if ts is not None:
            try:
                if isinstance(ts, str):
                    ts_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                else:
                    ts_dt = ts
                if ts_dt.tzinfo is None:
                    ts_dt = ts_dt.replace(tzinfo=timezone.utc)
                if ts_dt < cutoff:
                    continue
            except Exception:
                pass  # if parse fails, include defensively
        groups[tool].append(r)

    out: dict[str, Any] = {
        "groups_seen": len(groups),
        "groups_processed": 0,
        "patterns_written": 0,
        "skipped_low_samples": 0,
        "skipped_llm_error": 0,
        "patterns": [],
    }

    for tool, events in groups.items():
        if len(events) < min_samples:
            out["skipped_low_samples"] += 1
            continue
        # Compose prompt
        prompt = _EXTRACT_PROMPT_TEMPLATE.format(
            n=len(events),
            scope=scope,
            tool=tool,
            events=_format_events_for_prompt(events),
        )
        try:
            resp = chat_model.invoke(prompt)
            body = resp.content if hasattr(resp, "content") else str(resp)
        except Exception as exc:
            logger.warning(
                "pattern_extractor: LLM extract failed for tool=%s: %s",
                tool, exc,
            )
            out["skipped_llm_error"] += 1
            continue

        text = _build_pattern_text(tool, scope, body, len(events))
        out["patterns"].append({
            "tool": tool,
            "sample_count": len(events),
            "body": body,
            "text": text,
        })
        out["groups_processed"] += 1

        if dry_run:
            continue

        # Write back as expert_knowledge memory
        try:
            from olav.core.embedder import embed_text
            vec = embed_text(text)
            if vec is None:
                continue
            store.add_memory(
                id=f"opev-pattern-{scope}-{tool}",
                text=text,
                vector=vec,
                category="expert_knowledge",
                scope=scope,
                metadata={
                    "tool": tool,
                    "source": "pattern_extractor",
                    "sample_count": len(events),
                    "extracted_at": datetime.now(timezone.utc).isoformat(),
                },
                origin="agent",
                confidence=min(0.5 + 0.05 * len(events), 0.9),
                tags=json.dumps(["pattern", tool]),
            )
            out["patterns_written"] += 1
        except Exception as exc:
            logger.warning(
                "pattern_extractor: write failed for tool=%s: %s", tool, exc,
            )

    return out


# ── CLI entry point ─────────────────────────────────────────────────────────


def _cli_main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="olav-pattern-extract")
    p.add_argument("--scope", default="global")
    p.add_argument("--min-samples", type=int, default=5)
    p.add_argument("--window-days", type=int, default=30)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    result = extract_operational_patterns(
        scope=args.scope,
        min_samples=args.min_samples,
        window_days=args.window_days,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli_main())
