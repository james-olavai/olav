"""Tests for L2→L4 grader-verdict persistence (dev_docs/97 ISSUE-LE-L2-SIGNAL-NOT-PERSISTED).

Grader verdicts were only logged; now they are appended to a lock-free JSONL
sink and folded into the L4 trace-review as grader-hotspot lesson proposals.
"""

from __future__ import annotations

import importlib
import json
import time

from olav.agents import grader_metrics as gm


# --- record + read ---

def test_record_and_read_aggregates(tmp_path, monkeypatch):
    sink = tmp_path / "grader_evaluations.jsonl"
    monkeypatch.setattr(gm, "_sink_path", lambda: sink)
    gm.record_grader_verdict("api-query", {"result": "needs_revision", "criteria": [{"name": "grounded_result"}]})
    gm.record_grader_verdict("api-query", {"result": "needs_revision", "criteria": [{"name": "synthesis"}]})
    gm.record_grader_verdict("api-query", {"result": "satisfied", "criteria": [{"name": "synthesis"}]})
    gm.record_grader_verdict("writer", {"result": "satisfied", "criteria": [{"name": "synthesis"}]})

    agg = gm.read_grader_failures(hours=24, sink=sink)
    assert agg["api-query"] == {"fail": 2, "total": 3}
    assert agg["writer"] == {"fail": 0, "total": 1}


def test_read_excludes_outside_window(tmp_path, monkeypatch):
    sink = tmp_path / "g.jsonl"
    old = json.dumps({"ts": time.time() - 99 * 3600, "agent": "x", "result": "needs_revision"})
    new = json.dumps({"ts": time.time(), "agent": "x", "result": "needs_revision"})
    sink.write_text(old + "\n" + new + "\n", encoding="utf-8")
    agg = gm.read_grader_failures(hours=24, sink=sink)
    assert agg["x"] == {"fail": 1, "total": 1}  # old row excluded


def test_record_handles_object_evaluation(tmp_path, monkeypatch):
    sink = tmp_path / "g.jsonl"
    monkeypatch.setattr(gm, "_sink_path", lambda: sink)

    class _Crit:
        name = "prose_synthesis_present"

    class _Eval:
        result = "needs_revision"
        criteria = [_Crit()]

    gm.record_grader_verdict("collector", _Eval())
    rows = [json.loads(l) for l in sink.read_text().splitlines()]
    assert rows[0]["agent"] == "collector"
    assert rows[0]["result"] == "needs_revision"
    assert rows[0]["criterion"] == "prose_synthesis_present"


def test_record_never_raises_on_bad_path(monkeypatch):
    monkeypatch.setattr(gm, "_sink_path", lambda: (_ for _ in ()).throw(OSError("nope")))
    # must swallow — a metrics failure cannot break an agent run
    gm.record_grader_verdict("x", {"result": "needs_revision"})


# --- L4 trace-review folds in the grader signal ---

def test_trace_review_proposes_grader_hotspot(tmp_path, monkeypatch):
    tl = importlib.import_module("olav.core.curator.trace_learner")
    # no run-level failures → isolate the grader-hotspot path
    monkeypatch.setattr(tl, "_analyze_failures",
                        lambda hours, limit, db_path: {"status": "success", "total_failures": 0,
                                                       "total_ok": 5, "failures": [], "window_hours": hours})
    # one agent over the grader-fail threshold
    monkeypatch.setattr("olav.agents.grader_metrics.read_grader_failures",
                        lambda hours: {"api-query": {"fail": 4, "total": 6}, "writer": {"fail": 1, "total": 9}})

    res = tl._run_review_cycle(hours=24, db_path=tmp_path / "audit.duckdb", drafts_dir=tmp_path / "drafts")

    assert res["status"] == "success"
    assert res["grader_failures"]["api-query"]["fail"] == 4
    # api-query (4 ≥ 3) gets a hotspot draft; writer (1 < 3) does not
    drafts = list((tmp_path / "drafts").glob("grader_hotspot_*.draft.json"))
    assert len(drafts) == 1
    d = json.loads(drafts[0].read_text())
    assert d["agent"] == "api-query"
    assert d["scope"] == "api-query"
    assert d["category"] == "usage_guide"
    assert "4 of 6" in d["body"]
    assert not (tmp_path / "drafts" / "grader_hotspot_writer.draft.json").exists()
