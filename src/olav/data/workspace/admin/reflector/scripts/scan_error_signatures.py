#!/usr/bin/env python3
"""scan_error_signatures — bounded error histogram for the reflector agent.

The reflection agent must look at "what's failing" WITHOUT loading megabytes of
log text into a small model's context (``.olav/logs/api_server.log`` alone is
~239 MB). So this script never returns raw log lines. It:

  1. pulls recent error events from ``audit.duckdb`` (the structured store —
     ``tool_call_failed / run_error / tool_call_error / llm_error / run_cancelled``),
  2. tail-scans the plain-text ``.olav/logs/*.log`` files (last few MB only)
     for ``ERROR/CRITICAL/Traceback`` lines,
  3. NORMALIZES each message (strips timestamps, ids, numbers, paths) into a
     stable "signature", groups by signature, counts, and keeps ONE truncated
     example per signature,
  4. returns the top-K signatures by count (K = tier ``log_scan_max_signatures``),
     each example truncated to a char cap, with a ``truncated`` flag.

The output is a HISTOGRAM ("ERROR X happened 47× today, here's one instance"),
which is precise (real counts, real examples), bounded (top-K + char cap), and
hallucination-resistant (the model can't invent errors that aren't in the
counts). This is the deterministic backbone; the LLM only decides what to
propose from it.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

# ── message normalization ────────────────────────────────────────────────
# Order matters: strip the log-line prefix first, then collapse volatile tokens
# so "same bug, different id/number/path" folds to one signature.
_TS = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?")
_LEVEL_PREFIX = re.compile(r"^\s*(?:\[[^\]]*\]\s*)?(?:DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL)\s*[:\-|]?\s*", re.I)
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
_HEX = re.compile(r"\b0x[0-9a-f]+\b|\b[0-9a-f]{16,}\b", re.I)
# id-like token: ≥6 chars, alphanumeric, containing BOTH a letter and a digit
# (run ids like ``abcd1234``, serials like ``FDO20370B33``). Pure words and
# pure numbers are left for _NUM so they don't get over-collapsed.
_ALNUM_ID = re.compile(r"\b(?=[a-z0-9]*[a-z])(?=[a-z0-9]*\d)[a-z0-9]{6,}\b", re.I)
_PATH = re.compile(r"(/[\w.\-]+)+\.(py|log|json|yaml|duckdb|db)\b")
_LINENO = re.compile(r"\bline \d+\b", re.I)
_NUM = re.compile(r"(?<![A-Za-z])\d+(?![A-Za-z])")
_WS = re.compile(r"\s+")
_ERROR_LINE = re.compile(r"\b(ERROR|CRITICAL|Traceback|Exception|Error:|Failed)\b")


def _signature(msg: str) -> str:
    """Collapse a raw message to a stable grouping key."""
    s = _TS.sub("<TS>", msg)
    s = _LEVEL_PREFIX.sub("", s)
    s = _UUID.sub("<ID>", s)
    s = _HEX.sub("<HEX>", s)
    s = _ALNUM_ID.sub("<ID>", s)
    s = _PATH.sub(lambda m: "<PATH>." + m.group(2), s)
    s = _LINENO.sub("line <N>", s)
    s = _NUM.sub("<N>", s)
    s = _WS.sub(" ", s).strip()
    return s[:200]  # signatures themselves stay short


def _extract_audit_message(event_type: str, payload: Any) -> str:
    """Pull a human message out of an audit_events.payload (JSON or str)."""
    data: Any = payload
    if isinstance(payload, str):
        try:
            data = json.loads(payload)
        except Exception:  # noqa: BLE001
            return f"{event_type}: {payload}"
    if isinstance(data, dict):
        for k in ("error", "message", "detail", "exception", "reason", "traceback"):
            v = data.get(k)
            if v:
                return f"{event_type}: {str(v)}"
        return f"{event_type}: {json.dumps(data, default=str)}"
    return f"{event_type}: {data}"


def _tail_bytes(path: Path, max_bytes: int) -> str:
    """Read at most the last ``max_bytes`` of a file (never the whole 239 MB)."""
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size > max_bytes:
                fh.seek(size - max_bytes)
                fh.readline()  # discard partial first line
            return fh.read().decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return ""


def scan_error_signatures(
    since_hours: int = 24,
    max_signatures: int | None = None,
    example_chars: int | None = None,
    scan_text_logs: bool = True,
    tail_bytes_per_log: int = 2_000_000,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Return a bounded error-signature histogram.

    Args:
        since_hours:   look-back window for the structured audit store.
        max_signatures: cap on distinct signatures returned. None → tier
                        ``log_scan_max_signatures``.
        example_chars: truncate each stored example to this many chars. None →
                        tier ``execute_sql_max_cell_chars``.
        scan_text_logs: also tail-scan ``.olav/logs/*.log``.
        tail_bytes_per_log: max bytes read from the END of each text log.
        db_path:       override AUDIT_DB_PATH.

    Returns:
        ``{"since_hours", "total_events", "distinct_signatures", "shown",
            "truncated", "signatures": [{"signature","count","agents",
            "sources","example"}...]}`` — signatures sorted by count desc.
    """
    from olav.core.config import LOGS_DIR, get_llm_config, tier_default

    tier = get_llm_config().model_tier
    if max_signatures is None:
        max_signatures = int(tier_default(tier, "log_scan_max_signatures", 15))
    if example_chars is None:
        example_chars = int(tier_default(tier, "execute_sql_max_cell_chars", 800))

    # per-signature accumulator
    agg: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "agents": set(), "sources": set(), "example": ""}
    )
    total = 0

    # ── source A: structured audit errors ────────────────────────────────
    try:
        from olav.cli.log_cmd import log_errors

        for ev in log_errors(db_path, since_hours=since_hours):
            msg = _extract_audit_message(ev.get("event_type", ""), ev.get("payload"))
            sig = _signature(msg)
            if not sig:
                continue
            total += 1
            slot = agg[sig]
            slot["count"] += 1
            if ev.get("agent_id"):
                slot["agents"].add(str(ev["agent_id"]))
            slot["sources"].add("audit")
            if not slot["example"]:
                slot["example"] = msg[:example_chars]
    except Exception as exc:  # noqa: BLE001
        agg[f"<scan_error: audit source failed: {exc}>"]["count"] += 1

    # ── source B: plain-text log tails ───────────────────────────────────
    if scan_text_logs:
        try:
            logs_dir = Path(LOGS_DIR)
            for logf in sorted(logs_dir.glob("*.log")):
                text = _tail_bytes(logf, tail_bytes_per_log)
                for line in text.splitlines():
                    if not _ERROR_LINE.search(line):
                        continue
                    sig = _signature(line)
                    if not sig:
                        continue
                    total += 1
                    slot = agg[sig]
                    slot["count"] += 1
                    slot["sources"].add(logf.name)
                    if not slot["example"]:
                        slot["example"] = line.strip()[:example_chars]
        except Exception:  # noqa: BLE001
            pass

    ranked = sorted(agg.items(), key=lambda kv: kv[1]["count"], reverse=True)
    shown = ranked[:max_signatures]
    signatures = [
        {
            "signature": sig,
            "count": d["count"],
            "agents": sorted(d["agents"]),
            "sources": sorted(d["sources"]),
            "example": d["example"],
        }
        for sig, d in shown
    ]
    return {
        "since_hours": since_hours,
        "total_events": total,
        "distinct_signatures": len(agg),
        "shown": len(signatures),
        "truncated": len(agg) > len(signatures),
        "signatures": signatures,
    }


if __name__ == "__main__":
    import sys

    args = json.loads(sys.stdin.read() or "{}")
    print(json.dumps(scan_error_signatures(**args), default=str))
