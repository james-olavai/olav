"""TDD tests for SemanticRouter routing_decision audit event (P2-1).

Verifies that SemanticRouter.route() optionally records a
``routing_decision`` event to AuditEventRecorder when a recorder and
run_id are supplied — without coupling the router to any singleton.
"""
from __future__ import annotations

import json
import uuid
import duckdb
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_recorder(db_path: Path):
    from olav.core.audit_recorder import AuditEventRecorder
    return AuditEventRecorder(db_path=db_path)


def _make_router(**kwargs):
    from olav.core.router import SemanticRouter
    return SemanticRouter(**kwargs)


# ---------------------------------------------------------------------------
# Semantic routing path
# ---------------------------------------------------------------------------


def test_route_semantic_records_routing_decision(tmp_path: Path):
    """When semantic routing succeeds, a routing_decision event should be
    recorded with routing_method='semantic', matched_agent and score."""
    recorder = _make_recorder(tmp_path / "audit.duckdb")
    router = _make_router()
    run_id = str(uuid.uuid4())

    # Patch _semantic_route to return a synthetic match (no LanceDB needed)
    mock_result = {
        "agent": "ops",
        "skill": "show_interfaces",
        "confidence": 0.93,
        "method": "semantic",
    }
    with patch.object(router, "_semantic_route", return_value=mock_result):
        result = router.route("show me interface status", recorder=recorder, run_id=run_id)

    assert result["agent"] == "ops"

    rows = duckdb.connect(str(recorder._db_path)).execute(
        "SELECT event_type, payload FROM audit_events"
    ).fetchall()
    assert rows, "No event written"
    event_type, payload_str = rows[0]
    assert event_type == "routing_decision", f"Got {event_type}"
    payload = json.loads(payload_str)
    assert payload["routing_method"] == "semantic"
    assert payload["matched_agent"] == "ops"
    assert abs(payload["score"] - 0.93) < 1e-6


def test_route_fallback_records_routing_decision(tmp_path: Path):
    """When semantic routing returns None and fallback is used, the event
    routing_method must be 'llm_router'."""
    recorder = _make_recorder(tmp_path / "audit.duckdb")
    router = _make_router()
    run_id = str(uuid.uuid4())

    fallback_result = {
        "agent": "query",
        "confidence": 0.5,
        "method": "fallback",
    }
    with patch.object(router, "_semantic_route", return_value=None), \
         patch.object(router, "_fallback_route", return_value=fallback_result):
        result = router.route("what is the bgp state", recorder=recorder, run_id=run_id)

    assert result["agent"] == "query"

    rows = duckdb.connect(str(recorder._db_path)).execute(
        "SELECT event_type, payload FROM audit_events"
    ).fetchall()
    assert rows, "No event written"
    payload = json.loads(rows[0][1])
    assert payload["routing_method"] == "llm_router"
    assert payload["matched_agent"] == "query"


def test_route_no_recorder_does_not_crash():
    """Calling route() without recorder/run_id must work fine (backward compat)."""
    router = _make_router()
    mock_result = {"agent": "ops", "confidence": 0.9, "method": "semantic"}
    with patch.object(router, "_semantic_route", return_value=mock_result):
        result = router.route("show interfaces")  # no recorder, no run_id
    assert result["agent"] == "ops"


def test_route_recorder_without_run_id_does_not_crash(tmp_path: Path):
    """Passing recorder but no run_id → no event written (run_id is required
    to write a meaningful audit row), but no exception either."""
    recorder = _make_recorder(tmp_path / "audit.duckdb")
    router = _make_router()
    mock_result = {"agent": "ops", "confidence": 0.9, "method": "semantic"}
    with patch.object(router, "_semantic_route", return_value=mock_result):
        result = router.route("show interfaces", recorder=recorder)  # no run_id
    assert result["agent"] == "ops"
    count = duckdb.connect(str(recorder._db_path)).execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
    assert count == 0, "No run_id → no event expected"


def test_route_empty_query_not_recorded(tmp_path: Path):
    """Empty query early-return path must also not crash with a recorder."""
    recorder = _make_recorder(tmp_path / "audit.duckdb")
    router = _make_router()
    run_id = str(uuid.uuid4())

    result = router.route("", recorder=recorder, run_id=run_id)
    assert result["agent"] is None

    count = duckdb.connect(str(recorder._db_path)).execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
    assert count == 0, "Empty query short-circuit should not write event"
