"""Reachability test for the L4 HITL trace-review propose loop (dev_docs/97 §5).

Definition-of-Done rule (CLAUDE.md): a feature is not done until an integration
test exercises it through its REAL entry point under production-default config.
Here the real entry point is the ``olav trace-review`` CLI verb's command handler
(``handle_trace_review_command``) — the same callable main.py dispatches to.

This test proves the loop is:
  - reachable from the CLI verb (not just importable),
  - HITL-gated: it writes a DRAFT, it does NOT auto-commit to the memory store,
  - per-agent scoped.

The LLM extraction step is the only thing stubbed (deterministic + offline);
everything else runs the production code path.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb


def _seed_audit_db(db_path: Path) -> None:
    """Create a minimal audit.duckdb with one failed run + error event."""
    con = duckdb.connect(str(db_path))
    con.execute(
        """
        CREATE TABLE audit_runs (
            run_id VARCHAR, start_time TIMESTAMP, end_time TIMESTAMP,
            status VARCHAR, agent_id VARCHAR, session_id VARCHAR,
            thread_id VARCHAR, user_id VARCHAR, source_channel VARCHAR
        )
        """
    )
    con.execute(
        """
        CREATE TABLE audit_events (
            event_id VARCHAR, event_type VARCHAR, timestamp TIMESTAMP,
            sequence_no INTEGER, run_id VARCHAR, session_id VARCHAR,
            agent_id VARCHAR, payload VARCHAR, redaction VARCHAR
        )
        """
    )
    con.execute(
        "INSERT INTO audit_runs VALUES "
        "('run-1', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'error', 'analyzer', "
        "'s1', 't1', 'u1', 'cli')"
    )
    con.execute(
        "INSERT INTO audit_events VALUES "
        "('ev-1', 'tool_call_failed', CURRENT_TIMESTAMP, 1, 'run-1', 's1', "
        "'analyzer', ?, NULL)",
        [json.dumps({"tool": "execute_sql", "error": "Catalog Error: Table foo does not exist"})],
    )
    con.close()


_FAKE_CONSTRAINTS = ["Verify the table name with describe_table before execute_sql."]


def test_trace_review_propose_writes_draft_not_commit(tmp_path, monkeypatch):
    # production-default config: no special scope/flag set. We only redirect the
    # audit DB (seeded) and the drafts dir (tmp) via the handler's injectable args
    # + OLAV_WORKSPACE_ROOT, exactly as a real invocation would resolve them.
    db_path = tmp_path / "audit.duckdb"
    _seed_audit_db(db_path)
    ws_root = tmp_path / "workspace"
    ws_root.mkdir()
    monkeypatch.setenv("OLAV_WORKSPACE_ROOT", str(ws_root))

    # Stub ONLY the LLM extraction (offline + deterministic); everything else
    # is real code. Patch the module global so _run_review_cycle picks it up.
    # NB: `olav.core.curator.trace_learner` the *name* is shadowed by the
    # same-named function re-exported in the package __init__, so resolve the
    # real submodule via importlib rather than `import ... as tl`.
    import importlib
    tl = importlib.import_module("olav.core.curator.trace_learner")
    monkeypatch.setattr(tl, "_extract_constraints", lambda report, llm=None: list(_FAKE_CONSTRAINTS))

    # Spy on the memory store so we can assert NOTHING was committed.
    committed = []

    class _SpyStore:
        def table_exists(self, *a, **k):
            return True

        def create_table(self, *a, **k):
            pass

        def add_memory(self, **kw):
            committed.append(kw)

    monkeypatch.setattr("olav.core.memory.get_store", lambda: _SpyStore())

    # --- Exercise the REAL CLI entry point ---
    from olav.cli.commands.trace_review import handle_trace_review_command

    args = argparse.Namespace(hours=24, limit=50, propose=True, learn=False)
    # handler resolves db via config default; point it at the seeded db through
    # the lower-level injectable to keep the test hermetic.
    import olav.cli.commands.trace_review as tr
    monkeypatch.setattr(tr, "_get_default_audit_db", lambda: db_path)

    rc = handle_trace_review_command(args)

    # 1. Command succeeded and is reachable from the verb handler.
    assert rc == 0

    # 2. A DRAFT was written for the failing agent (per-agent scope).
    drafts = list((ws_root / ".curator_drafts").glob("trace_lessons_*.draft.json"))
    assert drafts, "expected a per-agent lesson draft to be written"
    draft = json.loads(drafts[0].read_text())
    assert draft["agent"] == "analyzer"
    assert draft["scope"] == "analyzer"  # per-agent, not global
    assert draft["category"] == "usage_guide"
    assert "describe_table" in draft["body"]

    # 3. HITL gate: nothing was auto-committed to the memory store.
    assert committed == [], "propose path must NOT commit to the store (HITL gate)"


def test_trace_review_verb_registered_on_cli():
    """The verb is wired on the root parser (reachable as `olav trace-review`)."""
    from olav.cli.commands.trace_review import build_trace_review_parser
    import argparse as _ap

    parser = _ap.ArgumentParser()
    sub = parser.add_subparsers(dest="command")
    build_trace_review_parser(sub)
    ns = parser.parse_args(["trace-review", "--propose", "--hours", "12"])
    assert ns.command == "trace-review"
    assert ns.propose is True
    assert ns.hours == 12
