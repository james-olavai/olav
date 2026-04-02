"""trace_learner.py — Background agentic tool for failure-pattern analysis.

Reads recent error/cancelled runs from audit.duckdb, extracts failure patterns,
and prepares constraint text for GuardrailInjector (LanceDB LTM injection).

Trigger points:
  - Post take_snapshot hook (called from take_snapshot.py Stage 2 completion)
  - Cron: manage_cron(action="schedule", schedule="0 3 * * *", workflow="trace-learner")
  - Manual: /trace-review slash command

Architecture per agent_traces.md §5:
  config-system (system-doctor)  ←  interactive: user asks → agent answers
  trace_learner                  ←  background: triggered → autonomous improvement

Output:
  - Structured failure report (returned as tool result)
  - (Phase 2) LanceDB memory[audit] write for GuardrailInjector
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import duckdb
from langchain_core.tools import tool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Path resolution (same pattern as take_snapshot.py)
# ---------------------------------------------------------------------------

def _find_project_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


PROJECT_ROOT = _find_project_root()

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))


# ---------------------------------------------------------------------------
# Default DB path
# ---------------------------------------------------------------------------

try:
    from olav.core.config import DATABASES_DIR as _DB_DIR
    _DEFAULT_AUDIT_DB = _DB_DIR / "audit.duckdb"
except Exception:
    _DEFAULT_AUDIT_DB = PROJECT_ROOT / ".olav" / "databases" / "audit.duckdb"


# ---------------------------------------------------------------------------
# Core analysis function (injectable db_path for TDD)
# ---------------------------------------------------------------------------

_ERROR_EVENT_TYPES = ("tool_call_failed", "run_error", "run_cancelled")


def _analyze_failures(
    hours: int = 168,          # 7 days default
    limit: int = 50,
    db_path: Path | None = None,
) -> dict:
    """Query audit.duckdb for recent failures and collect error event details.

    Returns a structured dict:
    {
        "status": "success" | "error",
        "total_failures": int,
        "total_ok": int,
        "failures": [
            {
                "run_id": str,
                "agent_id": str,
                "status": str,
                "start_time": str,
                "error_events": [
                    {"event_type": str, "tool": str|None, "error": str|None}
                ]
            }
        ]
    }
    """
    db_path = db_path or _DEFAULT_AUDIT_DB
    if not db_path.exists():
        return {"status": "error", "message": f"audit.duckdb not found at {db_path}"}

    try:
        conn = duckdb.connect(str(db_path), read_only=True)
    except Exception as exc:
        return {"status": "error", "message": f"Cannot open audit.duckdb: {exc}"}

    try:
        from datetime import datetime, timedelta, timezone
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")

        # --- Summary counts ---
        counts = conn.execute(
            """
            SELECT
                SUM(CASE WHEN status IN ('error', 'run_error', 'cancelled') THEN 1 ELSE 0 END) AS failures,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS ok
            FROM audit_runs
            WHERE start_time >= ?
            """,
            [cutoff],
        ).fetchone()
        total_failures = int(counts[0] or 0)
        total_ok = int(counts[1] or 0)

        if total_failures == 0:
            return {
                "status": "success",
                "total_failures": 0,
                "total_ok": total_ok,
                "failures": [],
                "window_hours": hours,
            }

        # --- Fetch failed runs ---
        failed_runs = conn.execute(
            """
            SELECT run_id, agent_id, status, start_time
            FROM audit_runs
            WHERE status IN ('error', 'run_error', 'cancelled')
              AND start_time >= ?
            ORDER BY start_time DESC
            LIMIT ?
            """,
            [cutoff, limit],
        ).fetchall()

        failures = []
        for run_id, agent_id, status, start_time in failed_runs:
            # Collect error events for this run
            error_rows = conn.execute(
                """
                SELECT event_type, payload
                FROM audit_events
                WHERE run_id = ?
                  AND event_type IN ('tool_call_failed', 'run_error', 'run_cancelled')
                ORDER BY timestamp
                """,
                [run_id],
            ).fetchall()

            error_events = []
            for ev_type, payload_str in error_rows:
                payload = {}
                try:
                    payload = json.loads(payload_str) if payload_str else {}
                except (json.JSONDecodeError, TypeError):
                    pass
                error_events.append({
                    "event_type": ev_type,
                    "tool":  payload.get("tool"),
                    "error": payload.get("error"),
                })

            failures.append({
                "run_id":        run_id,
                "agent_id":      agent_id,
                "status":        status,
                "start_time":    str(start_time),
                "error_events":  error_events,
            })

        return {
            "status":          "success",
            "total_failures":  total_failures,
            "total_ok":        total_ok,
            "failures":        failures,
            "window_hours":    hours,
        }

    except Exception as exc:
        logger.exception("trace_learner._analyze_failures error")
        return {"status": "error", "message": str(exc)}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Step 3: LLM-based constraint extraction
# ---------------------------------------------------------------------------

_LLM_PROMPT = """\
You are analyzing recent OLAV network-automation agent execution failures \
to extract actionable guardrail constraints.

Given these failure records (JSON):
{failures_json}

Extract 1-5 concise constraint sentences an agent should follow to avoid \
similar failures. Each constraint must:
- Be a single actionable sentence (≤120 characters)
- Start with "Avoid", "Always", "When", or "Never"
- Be specific to the failure patterns observed

Respond ONLY with a valid JSON array of strings, nothing else. Example:
["Avoid calling execute_cli without verifying SSH reachability first.",
 "Always validate table existence before running execute_sql."]
"""


def _build_failures_summary(failures: list[dict]) -> str:
    """Condense failure list for LLM prompt (strip UUIDs, keep essentials)."""
    condensed = []
    for f in failures:
        condensed.append({
            "agent": f.get("agent_id"),
            "status": f.get("status"),
            "errors": [
                {
                    "type": ev.get("event_type"),
                    "tool": ev.get("tool"),
                    "error": ev.get("error"),
                }
                for ev in f.get("error_events", [])
            ],
        })
    return json.dumps(condensed, indent=2)


def _extract_constraints(
    failure_report: dict,
    llm=None,
) -> list[str]:
    """Step 3: Call LLM to extract constraint strings from a failure report.

    Args:
        failure_report: Output from _analyze_failures().
        llm: Optional LangChain chat model (lazy-loaded via LLMFactory if None).

    Returns:
        List of constraint strings (empty on no failures or LLM error).
    """
    failures = failure_report.get("failures", [])
    if not failures:
        return []

    if llm is None:
        try:
            from olav.core.llm import LLMFactory
            llm = LLMFactory.get_chat_model(agent_id="trace_learner", temperature=0)
        except Exception as exc:
            logger.warning("trace_learner: cannot load LLM — %s", exc)
            return []

    prompt = _LLM_PROMPT.format(failures_json=_build_failures_summary(failures))
    try:
        from langchain_core.messages import HumanMessage
        response = llm.invoke([HumanMessage(content=prompt)])
        raw = response.content.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1] if len(parts) > 1 else ""
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        constraints = json.loads(raw)
        if not isinstance(constraints, list):
            return []
        return [str(c).strip() for c in constraints if str(c).strip()]
    except Exception as exc:
        logger.warning("trace_learner: LLM constraint extraction failed — %s", exc)
        return []


# ---------------------------------------------------------------------------
# Step 4: Write constraints to LanceDB memory[audit]
# ---------------------------------------------------------------------------


def _write_constraints_to_memory(
    constraints: list[str],
    store=None,
    scope: str = "global",
) -> int:
    """Step 4: Store constraint strings as audit memories for GuardrailInjector.

    Args:
        constraints: List of constraint strings from _extract_constraints().
        store: Optional LanceDBStore (lazy-loaded via get_store() if None).
        scope: Memory scope (default "global").

    Returns:
        Number of constraints actually stored.
    """
    if not constraints:
        return 0

    if store is None:
        try:
            from olav.core.memory import get_store
            store = get_store()
        except Exception as exc:
            logger.warning("trace_learner: cannot load LanceDB store — %s", exc)
            return 0

    from olav.core.memory.guardrails import store_failure_memory

    stored_count = 0
    for constraint in constraints:
        if not constraint.strip():
            continue
        try:
            store_failure_memory(store=store, description=constraint, scope=scope)
            stored_count += 1
        except Exception as exc:
            logger.warning(
                "trace_learner: failed to store constraint '%.50s': %s", constraint, exc
            )
    return stored_count


# ---------------------------------------------------------------------------
# Orchestration: full learn cycle (injectable for TDD)
# ---------------------------------------------------------------------------


def _run_learn_cycle(
    hours: int = 168,
    limit: int = 50,
    db_path: Path | None = None,
    store=None,
    llm=None,
    scope: str = "global",
) -> dict:
    """Run the full trace-learn cycle: collect → analyse → write to LTM.

    Steps:
        1+2. Read audit.duckdb for recent failures (_analyze_failures)
        3.   LLM-extract constraint strings (_extract_constraints)
        4.   Write constraints to LanceDB memory[audit] (_write_constraints_to_memory)

    Args:
        hours:   Look-back window in hours.
        limit:   Max failure runs to process.
        db_path: Optional audit.duckdb path override (for TDD).
        store:   Optional LanceDBStore override (for TDD).
        llm:     Optional chat model override (for TDD).
        scope:   LanceDB memory scope (default "global").

    Returns:
        Extended failure report dict with 'learn_count' and 'constraints_extracted' keys.
    """
    report = _analyze_failures(hours=hours, limit=limit, db_path=db_path)

    if report.get("status") != "success" or report.get("total_failures", 0) == 0:
        report["learn_count"] = 0
        return report

    constraints = _extract_constraints(failure_report=report, llm=llm)
    learn_count = _write_constraints_to_memory(
        constraints=constraints, store=store, scope=scope
    )

    report["constraints_extracted"] = constraints
    report["learn_count"] = learn_count
    logger.info(
        "trace_learner: %d failure(s) → %d constraint(s) learned",
        report["total_failures"],
        learn_count,
    )
    return report


# ---------------------------------------------------------------------------
# LangChain @tool wrapper
# ---------------------------------------------------------------------------

@tool
def trace_learner(
    hours: int = 168,
    limit: int = 50,
) -> dict:
    """Analyze recent agent execution failures and autonomously extract learnings.

    Reads the last *hours* hours of audit.duckdb, identifies error/cancelled
    runs, feeds them to an LLM for pattern analysis, and writes derived
    constraints to LanceDB memory[audit] so GuardrailInjector can inject them
    into future agent system prompts automatically.

    Args:
        hours: Time window in hours to look back (default 168 = 7 days).
        limit: Maximum number of failed runs to include (default 50).

    Returns:
        dict with keys: status, total_failures, total_ok, failures,
        window_hours, constraints_extracted, learn_count
    """
    return _run_learn_cycle(hours=hours, limit=limit)
