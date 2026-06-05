"""TDD tests for trace_learner.py Steps 3-5 (LLM analysis + LanceDB write).

Tests for:
  Step 3: _extract_constraints(failure_report, llm) — LLM extracts constraint strings
  Step 4: _write_constraints_to_memory(constraints, store) — writes to LanceDB audit memory
  Orchestration: _run_learn_cycle(hours, limit, db_path, store, llm) — full closed loop

All LLM and LanceDB calls are injected as mocks — no real API calls.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import importlib
_tl_mod = importlib.import_module("olav.core.curator.trace_learner")


def _make_llm_mock(content: str):
    """Return a minimal LangChain-like chat model mock."""
    msg = SimpleNamespace(content=content)
    llm = MagicMock()
    llm.invoke.return_value = msg
    return llm


def _seed_failures(db_path: Path):
    """Insert 2 error runs and 1 completed run into audit.duckdb."""
    from olav.core.audit_recorder import AuditEventRecorder

    rec = AuditEventRecorder(db_path=db_path)

    run_ok = str(uuid.uuid4())
    run_err1 = str(uuid.uuid4())
    run_err2 = str(uuid.uuid4())

    rec.record_run_start(
        run_id=run_ok, agent_id="ops", session_id="s1", thread_id="t1", user_id="u1"
    )
    rec.record_run_end(run_id=run_ok, status="completed")

    rec.record_run_start(
        run_id=run_err1, agent_id="ops", session_id="s2", thread_id="t2", user_id="u1"
    )
    rec.record(
        event_type="tool_call_failed",
        run_id=run_err1,
        payload={"tool": "execute_cli", "error": "SSH timeout"},
    )
    rec.record_run_end(run_id=run_err1, status="error")

    rec.record_run_start(
        run_id=run_err2, agent_id="query", session_id="s3", thread_id="t3", user_id="u1"
    )
    rec.record(
        event_type="tool_call_failed",
        run_id=run_err2,
        payload={"tool": "execute_sql", "error": "table not found"},
    )
    rec.record_run_end(run_id=run_err2, status="error")


# ---------------------------------------------------------------------------
# Step 3: _extract_constraints
# ---------------------------------------------------------------------------


def test_extract_constraints_no_failures_skips_llm():
    """Zero failures → empty list, LLM never called."""
    mod = _tl_mod
    llm = _make_llm_mock("[]")
    report = {"status": "success", "total_failures": 0, "failures": []}

    result = mod._extract_constraints(report, llm=llm)

    assert result == []
    llm.invoke.assert_not_called()


def test_extract_constraints_returns_list_from_llm():
    """LLM returns valid JSON array → list of strings returned."""
    mod = _tl_mod
    constraints = [
        "Avoid calling execute_cli without checking SSH first.",
        "Always validate table existence before execute_sql.",
    ]
    llm = _make_llm_mock(json.dumps(constraints))
    report = {
        "status": "success",
        "total_failures": 1,
        "failures": [
            {
                "agent_id": "ops",
                "status": "error",
                "error_events": [
                    {
                        "event_type": "tool_call_failed",
                        "tool": "execute_cli",
                        "error": "SSH timeout",
                    }
                ],
            },
        ],
    }

    result = mod._extract_constraints(report, llm=llm)

    assert result == constraints
    llm.invoke.assert_called_once()


def test_extract_constraints_llm_bad_json_returns_empty():
    """LLM returns non-JSON garbage → graceful fallback to empty list."""
    mod = _tl_mod
    llm = _make_llm_mock("Sorry, I cannot analyze this. Please try again.")
    report = {
        "status": "success",
        "total_failures": 1,
        "failures": [{"agent_id": "ops", "status": "error", "error_events": []}],
    }

    result = mod._extract_constraints(report, llm=llm)

    assert result == []


def test_extract_constraints_strips_markdown_fences():
    """LLM wraps response in ```json ... ``` → still parsed correctly."""
    mod = _tl_mod
    raw = '```json\n["Avoid SSHing without timeout.", "Always check connectivity."]\n```'
    llm = _make_llm_mock(raw)
    report = {
        "status": "success",
        "total_failures": 1,
        "failures": [{"agent_id": "ops", "status": "error", "error_events": []}],
    }

    result = mod._extract_constraints(report, llm=llm)

    assert len(result) == 2
    assert result[0].startswith("Avoid")


# ---------------------------------------------------------------------------
# Step 4: _write_constraints_to_memory
# ---------------------------------------------------------------------------


def test_write_constraints_calls_store_failure_memory():
    """Empty constraints list → _write_constraints_to_memory returns 0."""
    mod = _tl_mod
    store_mock = MagicMock()

    result = mod._write_constraints_to_memory(
        constraints=[], store=store_mock
    )
    assert result == 0  # empty list → nothing written


def test_write_constraints_blank_strings_skipped():
    """Empty/blank constraint strings are skipped; only non-blank ones are stored."""
    mod = _tl_mod
    store_mock = MagicMock()
    store_mock.table_exists.return_value = True

    result = mod._write_constraints_to_memory(
        constraints=["", "  ", "Valid constraint here."],
        store=store_mock,
    )

    # Only the one non-blank constraint should be stored
    assert result == 1
    store_mock.add_memory.assert_called_once()


# ---------------------------------------------------------------------------
# Orchestration: _run_learn_cycle
# ---------------------------------------------------------------------------


def test_run_learn_cycle_zero_failures_no_llm_call(tmp_path: Path):
    """No failures in DB → learn_count=0, LLM never invoked."""
    db_path = tmp_path / "audit.duckdb"
    from olav.core.audit_recorder import AuditEventRecorder

    AuditEventRecorder(db_path=db_path)  # empty DB

    mod = _tl_mod
    llm = _make_llm_mock("[]")
    store_mock = MagicMock()

    result = mod._run_learn_cycle(hours=24, limit=10, db_path=db_path, store=store_mock, llm=llm)

    assert result["status"] == "success"
    assert result["learn_count"] == 0
    llm.invoke.assert_not_called()


def test_run_learn_cycle_with_failures_writes_to_store(tmp_path: Path):
    """Seeded failures + LLM mock + store mock → learn_count matches constraints returned."""
    db_path = tmp_path / "audit.duckdb"
    _seed_failures(db_path)

    mod = _tl_mod
    constraints = [
        "Avoid calling execute_cli on unreachable hosts.",
        "Always verify table exists before SQL queries.",
    ]
    llm = _make_llm_mock(json.dumps(constraints))
    store_mock = MagicMock()

    with patch("olav.core.memory.guardrails.store_failure_memory", return_value={"status": "ok"}):
        result = mod._run_learn_cycle(
            hours=48, limit=20, db_path=db_path, store=store_mock, llm=llm
        )

    assert result["status"] == "success"
    assert result["total_failures"] == 2
    assert result["learn_count"] == 2
    assert "constraints_extracted" in result
    assert result["constraints_extracted"] == constraints
    llm.invoke.assert_called_once()


def test_write_constraints_uses_reflection_category():
    """ADR-0015: _write_constraints_to_memory must write category=REFLECTION, not EXPERT_KNOWLEDGE."""
    mod = _tl_mod
    store_mock = MagicMock()
    store_mock.table_exists.return_value = True
    store_mock.embedding_dim = 32

    mod._write_constraints_to_memory(
        constraints=["Always verify SSH before running execute_cli."],
        store=store_mock,
    )

    store_mock.add_memory.assert_called_once()
    call_kwargs = store_mock.add_memory.call_args
    # category may be positional or keyword; check kwargs first then args
    kwargs = call_kwargs.kwargs if call_kwargs.kwargs else {}
    args = call_kwargs.args if call_kwargs.args else ()

    category = kwargs.get("category") or (args[3] if len(args) > 3 else None)
    assert category == "reflection", (
        f"trace_learner should write category='reflection' (ADR-0015), got {category!r}"
    )
