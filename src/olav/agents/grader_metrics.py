"""Persist + read grader verdicts (dev_docs/97 ISSUE-LE-L2-SIGNAL-NOT-PERSISTED).

Closes the L2→L4 gap: the deterministic synthesis/grounded grader's verdicts
were only `logger.info`-ed, so the L4 trace-review could not see *which* agents
most often fail their output grader. Here each verdict is appended to a
lock-free JSONL sink (one line per evaluation) under the databases dir;
`trace_learner._run_review_cycle` reads it to propose lessons for grader-hotspot
agents.

Why a JSONL append rather than audit.duckdb: grader callbacks fire *during* agent
runs, concurrently with the audit recorder + the background trace-learner — a
per-verdict DuckDB write would contend on the file lock (observed in this repo).
An ``O_APPEND`` write of one small JSON line is contention-free and best-effort:
losing a metrics line is acceptable, blocking an agent run is not.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _sink_path() -> Path:
    try:
        from olav.core.config import DATABASES_DIR

        base = Path(DATABASES_DIR)
    except Exception:
        base = Path(".olav") / "databases"
    d = base / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d / "grader_evaluations.jsonl"


def _extract_result(evaluation: Any) -> tuple[str, str]:
    """Pull ``(result, criterion)`` from either a dict or a RubricEvaluation."""
    if isinstance(evaluation, dict):
        result = evaluation.get("result") or ""
        crits = evaluation.get("criteria") or []
    else:
        result = getattr(evaluation, "result", "") or ""
        crits = getattr(evaluation, "criteria", []) or []
    criterion = ""
    if crits:
        c0 = crits[0]
        criterion = (c0.get("name") if isinstance(c0, dict) else getattr(c0, "name", "")) or ""
    return str(result), str(criterion)


def record_grader_verdict(agent: str, evaluation: Any) -> None:
    """Best-effort, lock-free append of one grader verdict. Never raises."""
    try:
        result, criterion = _extract_result(evaluation)
        if not result:
            return
        line = json.dumps(
            {"ts": time.time(), "agent": agent or "", "result": result, "criterion": criterion},
            ensure_ascii=False,
        )
        with open(_sink_path(), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as exc:  # never let metrics break an agent run
        logger.debug("record_grader_verdict failed: %s", exc)


def read_grader_failures(hours: int = 24, sink: Path | None = None) -> dict[str, dict]:
    """Aggregate recent verdicts → ``{agent: {"fail": n, "total": n}}``.

    ``fail`` counts ``result == "needs_revision"`` within the look-back window.
    """
    p = sink or _sink_path()
    out: dict[str, dict] = {}
    if not p.exists():
        return out
    cutoff = time.time() - hours * 3600
    try:
        for ln in p.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:
                continue
            try:
                if float(r.get("ts", 0)) < cutoff:
                    continue
            except (TypeError, ValueError):
                continue
            a = r.get("agent") or "unknown"
            d = out.setdefault(a, {"fail": 0, "total": 0})
            d["total"] += 1
            if r.get("result") == "needs_revision":
                d["fail"] += 1
    except Exception as exc:
        logger.debug("read_grader_failures failed: %s", exc)
    return out
