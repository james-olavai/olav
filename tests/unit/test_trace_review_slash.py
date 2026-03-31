"""TDD tests for /trace-review slash command handler.

Contracts:
1. _handle_trace_review(hours, limit, db_path) exists in cli/commands/trace_review.py
2. Empty DB → status='success', total_failures=0, learn_count=0
3. Seeded failures + mock LLM → learn_count > 0, constraints_extracted non-empty
4. DB not found → status='error', message contains 'not found'
5. Returns structured dict (not a printed string) — caller formats output
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from olav.cli.commands.trace_review import _handle_trace_review


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_failures(db_path: Path):
    from olav.core.audit_recorder import AuditEventRecorder
    rec = AuditEventRecorder(db_path=db_path)
    run_id = str(uuid.uuid4())
    rec.record_run_start(run_id=run_id, agent_id="ops", session_id="s1", thread_id="t1", user_id="u")
    rec.record(event_type="tool_call_failed", run_id=run_id,
               payload={"tool": "execute_cli", "error": "SSH timeout"})
    rec.record_run_end(run_id=run_id, status="error")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_handle_trace_review_exists():
    """_handle_trace_review must be importable from trace_review.py."""
    assert callable(_handle_trace_review)


def test_handle_trace_review_empty_db(tmp_path: Path):
    """Empty DB → success, zero failures, zero learned."""
    from olav.core.audit_recorder import AuditEventRecorder
    db_path = tmp_path / "audit.duckdb"
    AuditEventRecorder(db_path=db_path)

    result = _handle_trace_review(hours=24, limit=10, db_path=db_path)

    assert result["status"] == "success"
    assert result["total_failures"] == 0
    assert result.get("learn_count", 0) == 0


def test_handle_trace_review_no_db(tmp_path: Path):
    """Non-existent DB path → status='error' with message."""
    result = _handle_trace_review(
        hours=24, limit=10, db_path=tmp_path / "missing.duckdb"
    )
    assert result["status"] == "error"
    assert "not found" in result.get("message", "").lower()


def test_handle_trace_review_with_failures(tmp_path: Path):
    """Seeded failures + mocked LLM + mocked store → learn_count == constraints returned."""
    db_path = tmp_path / "audit.duckdb"
    _seed_failures(db_path)

    constraints = ["Avoid SSH calls without pre-checking reachability."]
    fake_llm = MagicMock()
    fake_llm.invoke.return_value = SimpleNamespace(content=json.dumps(constraints))
    fake_store = MagicMock()

    from unittest.mock import patch
    with patch("olav.core.memory.guardrails.store_failure_memory", return_value={"status": "ok"}):
        result = _handle_trace_review(
            hours=48, limit=20, db_path=db_path, llm=fake_llm, store=fake_store
        )

    assert result["status"] == "success"
    assert result["total_failures"] >= 1
    assert result["learn_count"] == 1
    assert result["constraints_extracted"] == constraints


def test_handle_trace_review_returns_dict_not_string(tmp_path: Path):
    """Return value must be a dict so the caller controls formatting."""
    from olav.core.audit_recorder import AuditEventRecorder
    db_path = tmp_path / "audit.duckdb"
    AuditEventRecorder(db_path=db_path)

    result = _handle_trace_review(hours=24, limit=10, db_path=db_path)

    assert isinstance(result, dict), f"Expected dict, got {type(result)}: {result!r}"
