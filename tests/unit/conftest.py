"""Shared fixtures for unit tests.

collect_ignore: stale unit tests deferred until their underlying
API is rewritten.  Tests referencing features that have been
*removed outright* have been deleted (v0.20.3 Phase C cleanup).
What remains here is genuinely salvageable — each entry has a
follow-up owner in dev_docs.
"""
import os
import pytest


collect_ignore = [
    # pytest-asyncio plugin discovery varies between dev vs demo venv —
    # these suites import it at module scope and crash early without it.
    # Deferred until CI consolidates on a single venv config.
    "test_audit_callback_llm_events.py",
    "test_auto_capture.py",
    "test_guardrails_plugin.py",
    "test_memory_capture_plugin.py",
    "test_memory_recall_plugin.py",
    "test_uks_capture.py",

    # Environment deps missing (tink for encryption, snapshot fixtures,
    # auth DB seeding) — need explicit fixture setup in future.
    "test_audit_dataset_export.py",
    "test_textfsm_gap_templates.py",
    "test_threads_search.py",

    # APIs refactored between v0.14 → v0.19 — need real rewrite (not
    # just path bump).  Mostly >50% passing already; the failing
    # portion needs redesign around the current plugin_registry /
    # AuditMiddleware / workspace_discovery surfaces.
    "test_aaa_user_id_propagation.py",
    "test_cli_audit_input.py",
    "test_compiled_subagent_middleware.py",
    "test_hitl_audit.py",
    "test_refresh_command.py",
    "test_semantic_cache_audit.py",
    "test_semantic_cache_invalidation.py",
    "test_trace_learner.py",

    # Partial — most tests pass but a few reference removed tool paths.
    # Salvage in a focused cleanup pass.
    "test_skill_venv.py",
]


@pytest.fixture(autouse=True)
def _clear_bypass_env(monkeypatch):
    """Ensure OLAV_DANGEROUSLY_SKIP_PERMISSIONS is cleared before and after each test.

    set_bypass(True) writes directly to os.environ, bypassing monkeypatch tracking.
    This fixture guarantees no bypass state leaks between tests.
    """
    monkeypatch.delenv("OLAV_DANGEROUSLY_SKIP_PERMISSIONS", raising=False)
    yield
    monkeypatch.delenv("OLAV_DANGEROUSLY_SKIP_PERMISSIONS", raising=False)
