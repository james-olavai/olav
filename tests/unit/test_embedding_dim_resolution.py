"""Embedding-dimension resolution must not invent a width.

Background (gitea CI run #338): `e2e-fast` failed intermittently with

    Error: Embedding dim mismatch on table 'memory': stored=768, embedder=512.
    Refusing to start to avoid silent data loss.

Nothing was wrong with the configuration. `detect_embedding_dim()` returned a
hardcoded 512 ("safe default for bge-small-zh-v1.5") whenever the probe failed,
so a momentary embed-endpoint flap made the store compare a real stored 768
against an invented number and refuse to start — sending the operator to audit a
config that was correct. The invented value had also stopped being plausible:
api mode is the default now and sentence-transformers moved to `[local-embed]`,
so bge-small-zh is nobody's default.

Fixing that exposed a second, worse thing: `create_table`'s dim check
`db.drop_table()`d on mismatch behind a `logger.warning` — the very silent data
loss ISSUE-EMBEDDING-FALLBACK-DIM-MISMATCH-DESTROYS-DATA was filed to remove,
still live in a second path, unreachable only because the constructor's check
normally raised first.
"""

from __future__ import annotations

import pytest

import olav.core.embedder as embedder_mod
import olav.core.memory as memory_mod


# ---------------------------------------------------------------------------
# detect_embedding_dim: None, never a guess
# ---------------------------------------------------------------------------

def test_undetectable_dimension_returns_none_not_a_default(monkeypatch):
    monkeypatch.setattr(embedder_mod, "_detected_dim", None)
    monkeypatch.setattr(embedder_mod, "embed_text", lambda _t: None)
    monkeypatch.setattr(embedder_mod, "get_embedder", lambda *a, **k: None)

    assert embedder_mod.detect_embedding_dim() is None, (
        "a failed probe must report 'unknown', not substitute 512 — that is what "
        "manufactured the false stored=768/embedder=512 alarm"
    )


def test_a_failed_probe_is_not_cached(monkeypatch):
    """A transient outage must not poison the whole process lifetime."""
    monkeypatch.setattr(embedder_mod, "_detected_dim", None)
    monkeypatch.setattr(embedder_mod, "get_embedder", lambda *a, **k: None)

    calls = {"n": 0}

    def _flaky(_text):
        calls["n"] += 1
        return None if calls["n"] == 1 else [0.0] * 768

    monkeypatch.setattr(embedder_mod, "embed_text", _flaky)

    assert embedder_mod.detect_embedding_dim() is None
    assert embedder_mod.detect_embedding_dim() == 768, (
        "the failure was cached — a later call could never recover"
    )


def test_a_successful_probe_is_cached(monkeypatch):
    monkeypatch.setattr(embedder_mod, "_detected_dim", None)
    monkeypatch.setattr(embedder_mod, "get_embedder", lambda *a, **k: None)
    calls = {"n": 0}

    def _once(_text):
        calls["n"] += 1
        return [0.0] * 1024

    monkeypatch.setattr(embedder_mod, "embed_text", _once)
    assert embedder_mod.detect_embedding_dim() == 1024
    assert embedder_mod.detect_embedding_dim() == 1024
    assert calls["n"] == 1, "cached result should not re-probe"


def test_memory_wrapper_propagates_unknown(monkeypatch):
    monkeypatch.setattr(embedder_mod, "_detected_dim", None)
    monkeypatch.setattr(embedder_mod, "embed_text", lambda _t: None)
    monkeypatch.setattr(embedder_mod, "get_embedder", lambda *a, **k: None)

    assert memory_mod._detect_embedding_dim() is None


def test_memory_wrapper_turns_a_raising_probe_into_unknown(monkeypatch):
    def _boom(*_a, **_k):
        raise RuntimeError("endpoint exploded")

    monkeypatch.setattr(embedder_mod, "detect_embedding_dim", _boom)
    assert memory_mod._detect_embedding_dim() is None


# ---------------------------------------------------------------------------
# The store adopts a stored width rather than guessing or false-alarming
# ---------------------------------------------------------------------------

def _store_with_table(tmp_path, dim: int):
    """A real LanceDB store carrying one vector table of the given width."""
    store = memory_mod.LanceDBStore(db_path=str(tmp_path / "m.lance"), embedding_dim=dim)
    store.create_table(memory_mod.MEMORY_TABLE)
    return store


def test_unknown_dimension_adopts_the_existing_tables_width(tmp_path, monkeypatch):
    """The stored table is the authoritative fact about this deployment."""
    _store_with_table(tmp_path, 768)

    monkeypatch.setattr(memory_mod, "_detect_embedding_dim", lambda: None)
    reopened = memory_mod.LanceDBStore(db_path=str(tmp_path / "m.lance"))

    assert reopened._embedding_dim == 768, (
        "should have adopted 768 from the table instead of raising a mismatch"
    )


def test_unknown_dimension_does_not_raise_a_mismatch(tmp_path, monkeypatch):
    """The regression that broke CI #338, asserted directly."""
    _store_with_table(tmp_path, 768)
    monkeypatch.setattr(memory_mod, "_detect_embedding_dim", lambda: None)

    try:
        memory_mod.LanceDBStore(db_path=str(tmp_path / "m.lance"))
    except memory_mod.EmbeddingDimMismatchError as exc:  # pragma: no cover
        pytest.fail(f"undetectable dim must not be reported as a mismatch: {exc}")


def test_a_real_mismatch_still_refuses(tmp_path, monkeypatch):
    """Widening the unknown case must not weaken the actual guarantee."""
    _store_with_table(tmp_path, 768)
    monkeypatch.setattr(memory_mod, "_detect_embedding_dim", lambda: 512)

    with pytest.raises(memory_mod.EmbeddingDimMismatchError):
        memory_mod.LanceDBStore(db_path=str(tmp_path / "m.lance"))


def test_unknown_dim_with_no_table_fails_on_availability_not_mismatch(tmp_path, monkeypatch):
    """"Backend unavailable" and "dim mismatch" are different faults."""
    monkeypatch.setattr(memory_mod, "_detect_embedding_dim", lambda: None)
    store = memory_mod.LanceDBStore(db_path=str(tmp_path / "fresh.lance"))
    assert store._embedding_dim is None

    with pytest.raises(RuntimeError, match="availability problem, not"):
        store.create_table(memory_mod.MEMORY_TABLE)


# ---------------------------------------------------------------------------
# create_table's dim check used to destroy data silently
# ---------------------------------------------------------------------------

def test_create_table_refuses_to_drop_on_mismatch(tmp_path, monkeypatch):
    """The second, worse copy of the bug: `db.drop_table()` behind a warning.

    ISSUE-EMBEDDING-FALLBACK-DIM-MISMATCH-DESTROYS-DATA removed the destructive
    drop from _check_and_migrate_vector_dim but left an identical one in
    create_table. It was unreachable only because the constructor's check
    normally raises first — two checks disagreeing about whether a dim mismatch
    destroys data, in a data path.
    """
    store = _store_with_table(tmp_path, 768)
    row_id = "keep-me"
    store.add_memory(id=row_id, text="must survive a mismatch", vector=[0.1] * 768)

    # Same store object, now believing the embedder is 512.
    store._embedding_dim = 512

    with pytest.raises(memory_mod.EmbeddingDimMismatchError, match="Refusing to start to avoid silent data loss"):
        store.create_table(memory_mod.MEMORY_TABLE)

    # And the data is still there.
    store._embedding_dim = 768
    tbl = store.get_table(memory_mod.MEMORY_TABLE)
    ids = [r["id"] for r in tbl.to_arrow().to_pylist()]
    assert row_id in ids, "the row was destroyed by a dim mismatch"


def test_destructive_drop_still_available_when_explicitly_opted_in(tmp_path, monkeypatch):
    """The escape hatch stays — it is just no longer the default."""
    store = _store_with_table(tmp_path, 768)
    store.add_memory(id="doomed", text="opted in", vector=[0.1] * 768)
    store._embedding_dim = 512
    monkeypatch.setenv("OLAV_ALLOW_DESTRUCTIVE_DIM_MIGRATION", "1")

    store.create_table(memory_mod.MEMORY_TABLE)  # drops + recreates, no raise

    tbl = store.get_table(memory_mod.MEMORY_TABLE)
    assert [r["id"] for r in tbl.to_arrow().to_pylist()] == [], (
        "opt-in path should have recreated the table empty"
    )
