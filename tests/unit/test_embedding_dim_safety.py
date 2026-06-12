"""Vector-dim safety guards on LanceDBStore (P0 fix, dev_docs/00).

Pins three behaviours:

1. ``add_memory`` refuses a wrong-dim vector — table stays clean.
2. Reopening an existing table with a different ``embedding_dim`` raises
   ``EmbeddingDimMismatchError`` — table NOT dropped, rows preserved.
3. ``OLAV_ALLOW_DESTRUCTIVE_DIM_MIGRATION=1`` opts back in to the legacy
   drop-and-recreate behaviour for debug.

See ``dev_docs/00 § ISSUE-EMBEDDING-FALLBACK-DIM-MISMATCH-DESTROYS-DATA``.
"""
from __future__ import annotations

import pytest


def _make_store(tmp_path, dim):
    from olav.core.memory import LanceDBStore
    s = LanceDBStore(db_path=str(tmp_path / "mem.db"), embedding_dim=dim)
    s.create_table()
    return s


def _add_one(store, mem_id="m1", *, dim):
    return store.add_memory(
        id=mem_id,
        text="hello",
        vector=[0.1] * dim,
        category="fact",
        scope="global",
    )


# ── 1. add_memory rejects wrong-dim vector ──────────────────────────


def test_add_memory_rejects_wrong_dim_vector(tmp_path):
    store = _make_store(tmp_path, dim=32)
    out = store.add_memory(
        id="bad",
        text="x",
        vector=[0.0] * 16,  # half the store's dim
        category="fact",
        scope="global",
    )
    assert out["status"] == "error"
    assert "vector dim 16" in out["reason"]
    assert "32" in out["reason"]
    # No row was written
    rows = store.get_memories(limit=10)
    assert all(r["id"] != "bad" for r in rows)


def test_add_memory_accepts_correct_dim(tmp_path):
    store = _make_store(tmp_path, dim=32)
    out = _add_one(store, dim=32)
    assert out.get("status") != "error"
    rows = store.get_memories(limit=10)
    assert any(r["id"] == "m1" for r in rows)


# ── 2. Dim-mismatch on reopen raises, does NOT drop ────────────────


def test_dim_mismatch_on_reopen_raises_and_preserves_data(tmp_path, monkeypatch):
    """Open store at dim=32, write a row, reopen at dim=64.

    The reopen MUST raise EmbeddingDimMismatchError.  After the raise,
    open the table at the *original* dim — the row must still be there.
    """
    monkeypatch.delenv("OLAV_ALLOW_DESTRUCTIVE_DIM_MIGRATION", raising=False)
    from olav.core.memory import EmbeddingDimMismatchError, LanceDBStore

    s1 = _make_store(tmp_path, dim=32)
    _add_one(s1, dim=32)
    s1.close()

    with pytest.raises(EmbeddingDimMismatchError) as exc_info:
        LanceDBStore(db_path=str(tmp_path / "mem.db"), embedding_dim=64)
    assert exc_info.value.stored_dim == 32
    assert exc_info.value.embedder_dim == 64

    # Reopen at the right dim — the row from before the mismatch must
    # still exist.  This is the data-preservation invariant.
    s2 = LanceDBStore(db_path=str(tmp_path / "mem.db"), embedding_dim=32)
    rows = s2.get_memories(limit=10)
    assert any(r["id"] == "m1" for r in rows), (
        "Pre-mismatch row was destroyed despite the raise — "
        "the dim guard is letting data loss through."
    )


# ── 3. Escape hatch: OLAV_ALLOW_DESTRUCTIVE_DIM_MIGRATION=1 ────────


def test_destructive_migration_opt_in_drops_table(tmp_path, monkeypatch):
    """With the env var set, dim mismatch falls back to old behaviour."""
    from olav.core.memory import LanceDBStore

    s1 = _make_store(tmp_path, dim=32)
    _add_one(s1, dim=32)
    s1.close()

    monkeypatch.setenv("OLAV_ALLOW_DESTRUCTIVE_DIM_MIGRATION", "1")
    # Should NOT raise — falls back to drop-and-recreate
    s2 = LanceDBStore(db_path=str(tmp_path / "mem.db"), embedding_dim=64)
    # Table is empty (was dropped); recreate to confirm it's gone
    s2.create_table()
    rows = s2.get_memories(limit=10)
    assert all(r["id"] != "m1" for r in rows), (
        "Destructive opt-in didn't drop — escape hatch broken."
    )


# ── 4. Error message is actionable ─────────────────────────────────


def test_error_message_points_at_root_cause(tmp_path, monkeypatch):
    """The raised error must mention the env-var escape hatch + the
    embedding fallback as the typical cause — operators reading the
    traceback should know what to do."""
    monkeypatch.delenv("OLAV_ALLOW_DESTRUCTIVE_DIM_MIGRATION", raising=False)
    from olav.core.memory import EmbeddingDimMismatchError, LanceDBStore

    s = _make_store(tmp_path, dim=32)
    _add_one(s, dim=32)
    s.close()

    with pytest.raises(EmbeddingDimMismatchError) as exc_info:
        LanceDBStore(db_path=str(tmp_path / "mem.db"), embedding_dim=128)
    msg = str(exc_info.value)
    assert "OLAV_ALLOW_DESTRUCTIVE_DIM_MIGRATION" in msg
    assert "embedder" in msg.lower() or "embedding" in msg.lower()
    assert "fallback" in msg.lower()
