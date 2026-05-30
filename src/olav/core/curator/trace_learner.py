"""Trace-review learning helper for OLAV NetOps.

Reads recent failed runs from audit.duckdb, extracts failure
constraints via an LLM, and writes them to LanceDB memory for
future guardrail injection. Per ADR-0007 + ADR-0008, called from
curator skill scripts; not registered as an MCP tool.

Functions:
  _analyze_failures(hours, limit, db_path)          → failure report dict
  _extract_constraints(report, llm=None)             → list[str] of constraints
  _write_constraints_to_memory(constraints, store, scope) → int (written count)
  _run_learn_cycle(hours, limit, db_path, store, llm)    → combined result dict
  trace_learner(hours, limit)                       → public entry point
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Step 1: Analyze failures
# ---------------------------------------------------------------------------

_FAILURE_STATUSES = ("error", "cancelled")
_ERROR_EVENT_TYPES = ("tool_call_failed", "run_error")


def _analyze_failures(
    hours: int,
    limit: int,
    db_path: Path,
) -> dict:
    """Query audit.duckdb for recent failed runs and their error events.

    Returns:
        {
          status: "success" | "error",
          total_failures: int,
          total_ok: int,
          failures: [
            {run_id, agent_id, status, error_events: [{event_type, ...payload}]}
          ],
          window_hours: int,
          message: str   # only present on error
        }
    """
    db_path = Path(db_path)
    if not db_path.exists():
        return {
            "status": "error",
            "message": f"audit.duckdb not found at {db_path}",
        }

    try:
        import duckdb

        with duckdb.connect(str(db_path)) as con:
            # Count all runs in window (ok + failed)
            total_row = con.execute(
                """
                SELECT COUNT(*) AS n
                FROM audit_runs
                WHERE start_time >= (CURRENT_TIMESTAMP - INTERVAL (?) HOUR)
                """,
                [hours],
            ).fetchone()
            total_all = total_row[0] if total_row else 0

            # Fetch failed runs
            failed_rows = con.execute(
                """
                SELECT run_id, agent_id, status
                FROM audit_runs
                WHERE status IN ('error', 'cancelled')
                  AND start_time >= (CURRENT_TIMESTAMP - INTERVAL (?) HOUR)
                ORDER BY start_time DESC
                LIMIT ?
                """,
                [hours, limit],
            ).fetchall()

            failures: list[dict] = []
            for run_id, agent_id, status in failed_rows:
                event_rows = con.execute(
                    """
                    SELECT event_type, payload
                    FROM audit_events
                    WHERE run_id = ?
                      AND event_type IN ('tool_call_failed', 'run_error')
                    ORDER BY timestamp
                    """,
                    [run_id],
                ).fetchall()

                error_events: list[dict[str, Any]] = []
                for event_type, payload_str in event_rows:
                    ev: dict[str, Any] = {"event_type": event_type}
                    if payload_str:
                        try:
                            ev.update(json.loads(payload_str))
                        except json.JSONDecodeError:
                            ev["raw"] = payload_str
                    error_events.append(ev)

                failures.append(
                    {
                        "run_id": run_id,
                        "agent_id": agent_id,
                        "status": status,
                        "error_events": error_events,
                    }
                )

        total_failures = len(failures)
        total_ok = total_all - total_failures

        return {
            "status": "success",
            "total_failures": total_failures,
            "total_ok": max(0, total_ok),
            "failures": failures,
            "window_hours": hours,
        }

    except Exception as exc:
        logger.exception("_analyze_failures error")
        return {"status": "error", "message": str(exc)}


# ---------------------------------------------------------------------------
# Step 2: Extract constraints via LLM
# ---------------------------------------------------------------------------

_EXTRACT_PROMPT = """\
You are an OLAV operations analyst reviewing recent agent failures.
Below is a structured failure report from an autonomous network operations agent.

Failure Report:
{report_json}

Analyze the failures and extract a concise list of operational constraints or
lessons learned that should guide future agent behaviour. Focus on actionable
rules (e.g., "Always verify SSH connectivity before running execute_cli").

Respond with ONLY a JSON array of constraint strings. No explanations, no
markdown fences, no extra text. Example:
["Constraint one.", "Constraint two."]

If there is nothing useful to extract, respond with an empty array: []
"""


def _extract_constraints(
    report: dict,
    llm=None,
) -> list[str]:
    """Extract failure-constraint strings from a failure report using an LLM.

    Args:
        report: Output of _analyze_failures().
        llm:    LangChain chat model. If None, lazy-loads via olav config.
                If total_failures == 0, LLM is never called.

    Returns:
        list[str] of constraint strings. Empty list on failure or zero errors.
    """
    if report.get("total_failures", 0) == 0:
        return []

    if llm is None:
        try:
            from olav.core.config import get_llm

            llm = get_llm()
        except Exception as exc:
            logger.warning("_extract_constraints: cannot load LLM — %s", exc)
            return []

    report_json = json.dumps(report, indent=2, default=str)
    prompt = _EXTRACT_PROMPT.format(report_json=report_json)

    try:
        response = llm.invoke(prompt)
        raw = response.content if hasattr(response, "content") else str(response)
    except Exception as exc:
        logger.warning("_extract_constraints: LLM call failed — %s", exc)
        return []

    # Strip markdown fences if present: ```json\n...\n```
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    raw = raw.strip()

    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(c) for c in parsed if c]
        return []
    except json.JSONDecodeError:
        logger.warning("_extract_constraints: could not parse LLM response as JSON")
        return []


# ---------------------------------------------------------------------------
# Step 3: Write constraints to LanceDB memory
# ---------------------------------------------------------------------------


def _tags_from_constraint(text: str) -> list[str]:
    """Extract simple keyword tags from a constraint string for hybrid search."""
    import re as _re
    # Pull known OLAV-domain keywords as tags
    _KEYWORDS = re.compile(
        r"\b(sql|bgp|ospf|bgp|ssh|cli|interface|vlan|route|snapshot|"
        r"describe_table|execute_sql|v_show_\w+|netops|audit|runner|"
        r"explorer|author|curator|error|timeout|column|table)\b",
        re.IGNORECASE,
    )
    seen: list[str] = []
    for m in _KEYWORDS.finditer(text):
        tag = m.group(0).lower()
        if tag not in seen:
            seen.append(tag)
    return seen[:8]


def _write_constraints_to_memory(
    constraints: list[str],
    store=None,
) -> int:
    """Write extracted constraint strings to LanceDB as expert_knowledge.

    Writes with category='expert_knowledge' and scope='shared:audit' so
    AutoRecallMiddleware delivers them to all audit sub-agents (runner,
    author, explorer, curator) during ranked recall, subject to the
    normal quota/cap controls.  Non-audit agents are not affected.
    """
    if not constraints:
        return 0

    import json
    import uuid

    from olav.core.memory import MEMORY_TABLE, MemoryCategory, get_store

    if store is None:
        try:
            store = get_store()
        except Exception as exc:
            logger.warning("_write_constraints_to_memory: cannot load store — %s", exc)
            return 0

    tname = MEMORY_TABLE
    if not store.table_exists(tname):
        store.create_table(tname)

    written = 0
    for constraint in constraints:
        constraint = constraint.strip()
        if not constraint:
            continue
        try:
            memory_id = f"trace-{uuid.uuid4().hex[:8]}"
            tags = _tags_from_constraint(constraint)
            store.add_memory(
                id=memory_id,
                text=constraint,
                vector=[0.0] * store.embedding_dim,
                category=MemoryCategory.EXPERT_KNOWLEDGE,
                scope="shared:audit",
                metadata={"source": "trace_learner", "origin": "failure_learning"},
                tags=json.dumps(tags),
                table_name=tname,
            )
            written += 1
        except Exception as exc:
            logger.warning("_write_constraints_to_memory: failed to write %r — %s", constraint, exc)

    return written


# ---------------------------------------------------------------------------
# Orchestration: _run_learn_cycle
# ---------------------------------------------------------------------------


def _run_learn_cycle(
    hours: int = 168,
    limit: int = 50,
    db_path: Path | None = None,
    store=None,
    llm=None,
) -> dict:
    """Run the full trace-learn closed loop.

    Steps:
      1. Analyse recent failures from audit.duckdb
      2. Extract operational constraints via LLM (skipped if 0 failures)
      3. Write constraints to LanceDB memory

    Args:
        hours:   Look-back window in hours.
        limit:   Max failed runs to process.
        db_path: Path to audit.duckdb. Defaults to .olav/databases/audit.duckdb.
        store:   LanceDBStore (injectable for tests).
        llm:     LangChain chat model (injectable for tests).

    Returns:
        {status, total_failures, total_ok, failures, window_hours,
         constraints_extracted, learn_count}
    """
    if db_path is None:
        try:
            from olav.core.config import DATABASES_DIR

            db_path = DATABASES_DIR / "audit.duckdb"
        except Exception:
            db_path = Path(".olav") / "databases" / "audit.duckdb"

    # Step 1
    report = _analyze_failures(hours=hours, limit=limit, db_path=db_path)
    if report.get("status") == "error":
        return report

    # Step 2
    constraints = _extract_constraints(report, llm=llm)

    # Step 3
    learn_count = _write_constraints_to_memory(constraints, store=store)

    return {
        **report,
        "constraints_extracted": constraints,
        "learn_count": learn_count,
    }


def trace_learner(hours: int = 168, limit: int = 50) -> dict:
    """Analyse recent agent failures and learn operational constraints.

    Reads the last ``hours`` hours of audit data, finds error /
    cancelled runs, extracts constraint lessons via LLM, and stores
    them in memory for future guardrail injection.
    """
    return _run_learn_cycle(hours=hours, limit=limit)
