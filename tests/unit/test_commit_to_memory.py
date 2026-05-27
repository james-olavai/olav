"""commit_to_memory tool — R102 Phase B/E.

Pins the contract for the memory_curator sub-agent's tool.  Three
category branches are tested independently:

* ``usage_guide`` — writes ``<intent>.guide.yaml`` to disk + primes
* ``document``   — N pre-chunked rows, no YAML on disk
* ``topology``   — single row, ``metadata.media_type`` set

Each test uses ``tmp_path`` for FS isolation and points
``OLAV_WORKSPACE_ROOT`` at it so the tool writes under tmp.
``LanceDBStore`` runs against a tmp DB via ``get_store()`` after
patching the cached singleton.

Mirrors ``tests/unit/test_guide_kb.py`` style.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest


DIM = 32


# Path to the in-tree commit_to_memory tool — sub-agents live under
# src/olav/data/workspace/ which isn't on sys.path; import via spec.
import importlib.util
import sys

_TOOL_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "src" / "olav" / "data" / "workspace" / "core"
    / "memory_curator" / "scripts" / "commit_to_memory.py"
)


def _load_tool_module():
    spec = importlib.util.spec_from_file_location(
        "_test_commit_to_memory_mod", str(_TOOL_PATH)
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_test_commit_to_memory_mod"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def tool_mod():
    return _load_tool_module()


def _embed_stub(text: str) -> list[float]:
    return [float(len(text) % 100) / 100.0] * DIM


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("OLAV_WORKSPACE_ROOT", str(tmp_path))
    return tmp_path


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Patch the cached store singleton to a tmp LanceDB."""
    from olav.core import memory as mem_mod
    from olav.core.memory import LanceDBStore

    s = LanceDBStore(db_path=str(tmp_path / "mem.db"), embedding_dim=DIM)
    s.create_table()
    # patch the singleton getter so tool internals pick up our store
    monkeypatch.setattr(mem_mod, "_store", s, raising=False)
    monkeypatch.setattr(mem_mod, "get_store", lambda: s)
    # also patch embed_text since tool imports embedder directly
    import olav.core.embedder as embedder_mod
    monkeypatch.setattr(embedder_mod, "embed_text", _embed_stub)
    return s


# ── input validation ────────────────────────────────────────────────


def test_rejects_empty_intent(tool_mod):
    out = tool_mod.commit_to_memory(
        intent="", keywords=["a"], body="hello",
    )
    assert out["status"] == "error"
    assert "intent" in out["message"]


def test_rejects_empty_keywords(tool_mod):
    out = tool_mod.commit_to_memory(
        intent="foo", keywords=[], body="hello",
    )
    assert out["status"] == "error"
    assert "keyword" in out["message"].lower()


def test_rejects_invalid_category(tool_mod):
    out = tool_mod.commit_to_memory(
        intent="foo", keywords=["a"], body="x", category="bogus",
    )
    assert out["status"] == "error"
    assert "category" in out["message"].lower()


def test_rejects_document_without_chunks(tool_mod):
    out = tool_mod.commit_to_memory(
        intent="foo", keywords=["a"], category="document",
    )
    assert out["status"] == "error"
    assert "chunks" in out["message"].lower()


def test_rejects_usage_guide_without_body(tool_mod):
    out = tool_mod.commit_to_memory(
        intent="foo", keywords=["a"], body="", category="usage_guide",
    )
    assert out["status"] == "error"
    assert "body" in out["message"].lower()


# ── usage_guide branch ──────────────────────────────────────────────


def test_usage_guide_writes_yaml_and_primes(tool_mod, workspace, store):
    with patch("olav.core.memory.guide_kb._embed", side_effect=_embed_stub):
        out = tool_mod.commit_to_memory(
            intent="netbox_sync_team_acme",
            keywords=["netbox", "sync", "tenant"],
            body="Tenant is always acme-network-ops.",
            agent="services",
            category="usage_guide",
        )

    assert out["status"] == "success"
    assert out["category"] == "usage_guide"
    assert out["primed"] is True
    expected_file = (
        workspace / "services" / "guides" / "netbox_sync_team_acme.guide.yaml"
    )
    assert Path(out["file"]) == expected_file
    assert expected_file.exists()

    # YAML round-trip
    import yaml
    parsed = yaml.safe_load(expected_file.read_text())
    assert parsed["intent"] == "netbox_sync_team_acme"
    assert parsed["agent"] == "services"
    assert parsed["keywords"] == ["netbox", "sync", "tenant"]
    assert "acme-network-ops" in parsed["body"]

    # LanceDB row landed with the deterministic id
    assert "guide_services_netbox_sync_team_acme" in out["memory_ids"]
    memories = store.get_memories(limit=20)
    ids = [m["id"] for m in memories]
    assert "guide_services_netbox_sync_team_acme" in ids


def test_usage_guide_idempotent_on_recommit(tool_mod, workspace, store):
    """Re-commit same intent → same memory_id, no duplicate row."""
    kwargs = dict(
        intent="x_rule",
        keywords=["a", "b"],
        body="rule body",
        agent="core",
        category="usage_guide",
    )
    with patch("olav.core.memory.guide_kb._embed", side_effect=_embed_stub):
        r1 = tool_mod.commit_to_memory(**kwargs)
        r2 = tool_mod.commit_to_memory(**kwargs)

    assert r1["memory_ids"] == r2["memory_ids"]
    memories = store.get_memories(limit=20)
    matching = [m for m in memories if m["id"] == "guide_core_x_rule"]
    assert len(matching) == 1


# ── document branch ─────────────────────────────────────────────────


def test_document_writes_n_chunks_no_yaml(tool_mod, workspace, store):
    chunks = [
        "Section 1: NetBox sync overview.",
        "Section 2: Tenant rules.",
        "Section 3: Status defaults.",
    ]
    out = tool_mod.commit_to_memory(
        intent="runbook_netbox_sop",
        keywords=["runbook", "netbox", "sop"],
        chunks=chunks,
        agent="services",
        category="document",
    )

    assert out["status"] == "success"
    assert out["category"] == "document"
    assert len(out["memory_ids"]) == 3
    assert out["skipped"] == 0
    # No YAML on disk for document chunks
    guides_dir = workspace / "services" / "guides"
    if guides_dir.exists():
        assert not list(guides_dir.glob("runbook_netbox_sop*"))

    # Each row is category=document
    memories = store.get_memories(limit=20)
    doc_rows = [m for m in memories if m["category"] == "document"]
    assert len(doc_rows) == 3
    metas = [json.loads(m["metadata"]) for m in doc_rows]
    assert {m["chunk_index"] for m in metas} == {0, 1, 2}
    assert all(m["intent"] == "runbook_netbox_sop" for m in metas)


def test_document_skips_empty_chunks(tool_mod, workspace, store):
    out = tool_mod.commit_to_memory(
        intent="r1",
        keywords=["a"],
        chunks=["body 1", "", "  ", "body 2"],
        agent="core",
        category="document",
    )
    assert out["status"] == "success"
    assert len(out["memory_ids"]) == 2
    assert out["skipped"] == 2


# ── LLM-only mode: embed_text returns None (mode='none' or backend down) ──


def test_document_writes_zero_vec_when_embed_returns_none(
    tool_mod, workspace, store, monkeypatch,
):
    """Patch C — when embed_text returns None (not raises), commit_to_memory
    must substitute a zero-vector instead of feeding None into pa.array
    against the fixed-size-list schema.

    Pins the LLM-only minimum-environment contract: agents can still
    write to memory when no embedding backend is configured; the row
    just won't surface via vector search (BM25/FTS keeps it findable).
    """
    import olav.core.embedder as embedder_mod
    monkeypatch.setattr(embedder_mod, "embed_text", lambda text: None)

    out = tool_mod.commit_to_memory(
        intent="no_embed",
        keywords=["llm-only"],
        chunks=["chunk one", "chunk two"],
        agent="core",
        category="document",
    )

    assert out["status"] == "success"
    assert len(out["memory_ids"]) == 2

    # Inspect the actual rows — vectors should be all-zero with the
    # store's expected dim, NOT None or wrong-shape.
    import lancedb
    db = lancedb.connect(str(store.db_path))
    df = db.open_table("memory").to_pandas()
    written = df[df["id"].isin(out["memory_ids"])]
    assert len(written) == 2
    for vec in written["vector"]:
        assert len(vec) == DIM
        assert all(v == 0.0 for v in vec)


def test_topology_writes_zero_vec_when_embed_returns_none(
    tool_mod, workspace, store, monkeypatch,
):
    """Same Patch C contract for the single-row topology branch."""
    import olav.core.embedder as embedder_mod
    monkeypatch.setattr(embedder_mod, "embed_text", lambda text: None)

    out = tool_mod.commit_to_memory(
        intent="no_embed_topo",
        keywords=["topology"],
        body="graph TD\n  A --> B\n",
        agent="ops",
        category="topology",
    )

    assert out["status"] == "success"
    assert len(out["memory_ids"]) == 1

    import lancedb
    db = lancedb.connect(str(store.db_path))
    df = db.open_table("memory").to_pandas()
    written = df[df["id"].isin(out["memory_ids"])]
    assert len(written) == 1
    vec = written.iloc[0]["vector"]
    assert len(vec) == DIM
    assert all(v == 0.0 for v in vec)


# ── topology branch ─────────────────────────────────────────────────


def test_topology_mermaid_detection(tool_mod, workspace, store):
    body = "graph TD\n  R1 --> R2\n  R2 --> R3\n"
    out = tool_mod.commit_to_memory(
        intent="lab_demo7_topology",
        keywords=["topology", "demo7"],
        body=body,
        agent="ops",
        category="topology",
    )
    assert out["status"] == "success"
    assert out["category"] == "topology"
    assert out["media_type"] == "mermaid"
    assert out["memory_ids"] == ["topology_ops_lab_demo7_topology"]

    memories = store.get_memories(limit=10)
    topo = [m for m in memories if m["category"] == "topology"]
    assert len(topo) == 1
    meta = json.loads(topo[0]["metadata"])
    assert meta["media_type"] == "mermaid"
    assert "R1 --> R2" in topo[0]["text"]


def test_topology_dot_detection(tool_mod, workspace, store):
    body = "digraph G {\n  R1 -> R2;\n  R2 -> R3;\n}"
    out = tool_mod.commit_to_memory(
        intent="dot_topo",
        keywords=["dot", "topology"],
        body=body,
        agent="ops",
        category="topology",
    )
    assert out["media_type"] == "dot"


def test_topology_unknown_format(tool_mod, workspace, store):
    out = tool_mod.commit_to_memory(
        intent="freeform",
        keywords=["custom"],
        body="just some plain text describing topology",
        agent="ops",
        category="topology",
    )
    assert out["media_type"] == "unknown"


# ── confirm flag ────────────────────────────────────────────────────


def test_confirm_false_logs_warning_but_writes(tool_mod, workspace, store, caplog):
    """confirm=False is unit-test-only; warns loudly but proceeds."""
    import logging

    with caplog.at_level(logging.WARNING):
        with patch("olav.core.memory.guide_kb._embed", side_effect=_embed_stub):
            out = tool_mod.commit_to_memory(
                intent="bypass",
                keywords=["test"],
                body="bypass body",
                agent="core",
                category="usage_guide",
                confirm=False,
            )

    assert out["status"] == "success"
    assert any("confirm=False" in m for m in caplog.messages)


# ── propose_memory_draft → commit_to_memory(from_draft=True) cycle ──


def _load_propose_module():
    spec = importlib.util.spec_from_file_location(
        "_test_propose_mod",
        str(_TOOL_PATH.parent / "propose_memory_draft.py"),
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_test_propose_mod"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_propose_writes_draft_returns_preview(workspace, store):
    propose_mod = _load_propose_module()
    out = propose_mod.propose_memory_draft(
        intent="bgp_active_l3_check",
        keywords=["bgp", "active"],
        body="BGP Active = check L3 reach",
        agent="ops",
        category="usage_guide",
    )
    assert out["status"] == "draft_saved"
    assert out["draft_id"] == "bgp_active_l3_check"
    draft_path = Path(out["draft_path"])
    assert draft_path.exists()
    payload = json.loads(draft_path.read_text())
    assert payload["intent"] == "bgp_active_l3_check"
    assert payload["agent"] == "ops"
    assert "Confirm?" in out["preview"]
    assert "可以" in out["preview"]


def test_commit_from_draft_seals_and_archives(tool_mod, workspace, store):
    """End-to-end Turn-1 propose → Turn-2 commit_to_memory(from_draft=True)."""
    propose_mod = _load_propose_module()

    # Turn 1
    propose_out = propose_mod.propose_memory_draft(
        intent="bgp_active_l3_check",
        keywords=["bgp", "active", "L3"],
        body="BGP Active state: check L3 reach (route + ACL)",
        agent="ops",
        category="usage_guide",
    )
    draft_path = Path(propose_out["draft_path"])
    assert draft_path.exists()

    # Turn 2 — agent calls commit_to_memory(from_draft=True) only
    with patch("olav.core.memory.guide_kb._embed", side_effect=_embed_stub):
        commit_out = tool_mod.commit_to_memory(from_draft=True)

    assert commit_out["status"] == "success"
    assert commit_out["category"] == "usage_guide"
    assert "guide_ops_bgp_active_l3_check" in commit_out["memory_ids"]
    assert commit_out.get("draft_archived") is True

    # Draft moved to committed/
    assert not draft_path.exists()
    archive_dir = draft_path.parent / "committed"
    archived = list(archive_dir.glob("bgp_active_l3_check*.json"))
    assert len(archived) == 1


def test_commit_from_draft_picks_latest_when_intent_omitted(tool_mod, workspace, store):
    """Multiple drafts pending → latest by mtime wins when intent unset."""
    import time as _time
    propose_mod = _load_propose_module()
    propose_mod.propose_memory_draft(
        intent="rule_a", keywords=["a"], body="rule a", agent="ops",
    )
    _time.sleep(0.05)  # ensure different mtime
    propose_mod.propose_memory_draft(
        intent="rule_b", keywords=["b"], body="rule b", agent="ops",
    )

    with patch("olav.core.memory.guide_kb._embed", side_effect=_embed_stub):
        out = tool_mod.commit_to_memory(from_draft=True)  # no intent

    assert out["status"] == "success"
    assert "guide_ops_rule_b" in out["memory_ids"]


def test_commit_from_draft_missing_returns_error(tool_mod, workspace, store):
    out = tool_mod.commit_to_memory(from_draft=True)
    assert out["status"] == "error"
    assert "no draft found" in out["message"].lower()
