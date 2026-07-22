"""Memory-layer project dimension (dev_docs/100 §4.4/§4.5, ADR-0017).

The first multi-tenancy dimension in the memory layer. Generic (core carries no
presales semantics): the active project is a plain ``OLAV_ACTIVE_PROJECT`` env
signal that the presales domain sets.

  * Recall predicate (§4.4): with an active project P, keep untagged records +
    records tagged project==P; exclude other projects. With NO active project,
    keep only untagged (project facts never leak into a non-project session).
  * Capture policy (§4.5): during an active-project session, non-reflection
    captures get metadata.project=P and any shared:*/org/global scope is
    downgraded to project-local — never a shared tier without curator provenance.
"""

from __future__ import annotations

import pytest


# ── recall predicate (pure) ───────────────────────────────────────────────────

def _rows():
    return [
        {"id": "u", "metadata": "{}"},                       # untagged
        {"id": "a", "metadata": '{"project": "acme"}'},       # project acme
        {"id": "b", "metadata": '{"project": "globex"}'},     # project globex
        {"id": "a2", "metadata": {"project": "acme"}},        # dict form too
    ]


def test_filter_active_project_keeps_untagged_and_own():
    from olav.core.memory import filter_by_active_project

    kept = {r["id"] for r in filter_by_active_project(_rows(), active="acme")}
    assert kept == {"u", "a", "a2"}  # untagged + acme, not globex


def test_filter_no_active_project_keeps_only_untagged():
    from olav.core.memory import filter_by_active_project

    kept = {r["id"] for r in filter_by_active_project(_rows(), active=None)}
    assert kept == {"u"}  # project facts never leak into a non-project session


def test_filter_reads_env_when_active_unset(monkeypatch):
    from olav.core.memory import filter_by_active_project

    monkeypatch.setenv("OLAV_ACTIVE_PROJECT", "globex")
    kept = {r["id"] for r in filter_by_active_project(_rows())}
    assert kept == {"u", "b"}


# ── capture policy (pure) ─────────────────────────────────────────────────────

def test_capture_tags_project_and_downgrades_shared_scope():
    from olav.core.memory import apply_project_capture_policy

    md, scope = apply_project_capture_policy(
        {"foo": 1}, scope="shared:presales", category="expert_knowledge", active="acme"
    )
    assert md["project"] == "acme"
    assert scope == "acme"  # shared:* downgraded to project-local


def test_capture_downgrades_org_and_global():
    from olav.core.memory import apply_project_capture_policy

    for tier in ("org", "global"):
        md, scope = apply_project_capture_policy(
            {}, scope=tier, category="fact", active="acme"
        )
        assert md["project"] == "acme"
        assert scope == "acme"


def test_capture_reflection_stays_cross_project():
    """reflection = generic failure constraints, cross-project (§4.4)."""
    from olav.core.memory import apply_project_capture_policy

    md, scope = apply_project_capture_policy(
        {}, scope="global", category="reflection", active="acme"
    )
    assert "project" not in md
    assert scope == "global"


def test_capture_curator_provenance_bypasses():
    """L4 HITL promotion may write shared scope (§4.5 #2)."""
    from olav.core.memory import apply_project_capture_policy

    md, scope = apply_project_capture_policy(
        {}, scope="shared:presales", category="expert_knowledge",
        active="acme", curator_provenance=True,
    )
    assert "project" not in md
    assert scope == "shared:presales"


def test_capture_noop_without_active_project():
    from olav.core.memory import apply_project_capture_policy

    md, scope = apply_project_capture_policy(
        {"x": 1}, scope="shared:presales", category="fact", active=None
    )
    assert md == {"x": 1} and scope == "shared:presales"


def test_capture_preserves_explicit_project():
    from olav.core.memory import apply_project_capture_policy

    md, _ = apply_project_capture_policy(
        {"project": "explicit"}, scope="agent", category="fact", active="acme"
    )
    assert md["project"] == "explicit"  # don't override caller's tag


# ── integration through the store + AutoRecall (production-default config) ────

def _temp_store(tmp_path):
    lancedb = pytest.importorskip("lancedb")  # noqa: F841
    from olav.core.memory import LanceDBStore

    return LanceDBStore(db_path=str(tmp_path / "mem.lance"), embedding_dim=8)


def test_add_memory_applies_capture_policy(tmp_path, monkeypatch):
    monkeypatch.setenv("OLAV_ACTIVE_PROJECT", "acme")
    store = _temp_store(tmp_path)
    vec = [0.1] * 8
    store.add_memory(id="m1", text="acme core is dual N9K", vector=vec,
                     category="expert_knowledge", scope="shared:presales")
    rows = store.search_by_vector(query_vector=vec, limit=5, category="expert_knowledge")
    import json
    row = next(r for r in rows if r.get("id") == "m1")
    md = row.get("metadata")
    md = json.loads(md) if isinstance(md, str) else md
    assert md.get("project") == "acme"           # tagged
    assert row.get("scope") == "acme"            # shared:* downgraded


def test_autorecall_gather_isolates_by_project(tmp_path, monkeypatch):
    from olav.core.memory import LanceDBStore  # noqa: F401
    from olav.core.memory.middleware import AutoRecallMiddleware

    store = _temp_store(tmp_path)
    vec = [0.2] * 8
    # untagged + two projects, all same category/vector
    store.add_memory(id="u", text="generic BGP tip", vector=vec, category="fact")
    monkeypatch.setenv("OLAV_ACTIVE_PROJECT", "acme")
    store.add_memory(id="a", text="acme fact", vector=vec, category="fact")
    monkeypatch.setenv("OLAV_ACTIVE_PROJECT", "globex")
    store.add_memory(id="b", text="globex fact", vector=vec, category="fact")

    mw = AutoRecallMiddleware(store)
    monkeypatch.setenv("OLAV_ACTIVE_PROJECT", "acme")
    got = {r["id"] for r in mw._gather_candidates("fact", vec, scope=None, top_k=10)}
    assert "b" not in got                # other project excluded
    assert "u" in got and "a" in got     # untagged + own project
