"""LanceDB memory table dim-mismatch handling.

Originally these tests pinned an auto-drop migration: if the embedder's
dim changed (e.g. switching from 1536 → 768), the memory table got
silently dropped + recreated.  That behaviour was reclassified P0 data
loss bug after R102 in-vivo testing — a transient embedder fallback
(api 2048 → local 768) wiped 12 user-curated memory rows.

The new contract:

* Mismatch on connect → raise ``EmbeddingDimMismatchError``
* Existing rows preserved across the raise
* Operator opts in to old destructive behaviour with
  ``OLAV_ALLOW_DESTRUCTIVE_DIM_MIGRATION=1``

See ``dev_docs/00 § ISSUE-EMBEDDING-FALLBACK-DIM-MISMATCH-DESTROYS-DATA``.
The eager-fail behaviour is also pinned by
``tests/unit/test_embedding_dim_safety.py`` (companion file).
"""
from __future__ import annotations

import pyarrow as pa
import pytest
import lancedb

from olav.core.memory import (
    EmbeddingDimMismatchError,
    LanceDBStore,
    MEMORY_TABLE,
)


def _make_table_with_dim(db_path, dim: int) -> None:
    """Pre-create a memory.lance table with the given vector dim."""
    db = lancedb.connect(str(db_path))
    schema = pa.schema([
        ("id", pa.string()),
        ("text", pa.string()),
        ("vector", pa.list_(pa.float32(), dim)),
        ("category", pa.string()),
        ("scope", pa.string()),
        ("metadata", pa.string()),
        ("timestamp", pa.timestamp("us")),
        ("created_at", pa.timestamp("us")),
        ("access_count", pa.int32()),
        ("weight", pa.float32()),
        ("origin", pa.string()),
        ("confidence", pa.float32()),
        ("tags", pa.string()),
    ])
    db.create_table(MEMORY_TABLE, schema=schema)


def _table_vector_dim(db_path) -> int:
    db = lancedb.connect(str(db_path))
    tbl = db.open_table(MEMORY_TABLE)
    for field in tbl.schema:
        if field.name == "vector" and hasattr(field.type, "list_size"):
            return field.type.list_size
    raise AssertionError("no vector field")


def test_dim_mismatch_raises_on_connect_and_preserves_table(tmp_path, monkeypatch):
    """Pre-existing 1536-dim table + new embedder at 768 → raise.

    The table is NOT dropped — operator must explicitly migrate or set
    OLAV_ALLOW_DESTRUCTIVE_DIM_MIGRATION=1.
    """
    monkeypatch.delenv("OLAV_ALLOW_DESTRUCTIVE_DIM_MIGRATION", raising=False)
    db_path = tmp_path / "memory.lance"
    _make_table_with_dim(db_path, dim=1536)
    assert _table_vector_dim(db_path) == 1536

    with pytest.raises(EmbeddingDimMismatchError) as exc_info:
        LanceDBStore(db_path=db_path, embedding_dim=768)
    assert exc_info.value.stored_dim == 1536
    assert exc_info.value.embedder_dim == 768

    # Table preserved at original dim
    db = lancedb.connect(str(db_path))
    assert MEMORY_TABLE in list(db.table_names()), (
        "stale 1536-dim table should NOT have been dropped — "
        "fail-fast must preserve user data"
    )
    assert _table_vector_dim(db_path) == 1536


def test_destructive_opt_in_drops_and_recreates(tmp_path, monkeypatch):
    """OLAV_ALLOW_DESTRUCTIVE_DIM_MIGRATION=1 restores legacy drop behaviour."""
    monkeypatch.setenv("OLAV_ALLOW_DESTRUCTIVE_DIM_MIGRATION", "1")
    db_path = tmp_path / "memory.lance"
    _make_table_with_dim(db_path, dim=1536)

    # Should NOT raise — falls back to drop
    store = LanceDBStore(db_path=db_path, embedding_dim=768)
    store.create_table()
    assert _table_vector_dim(db_path) == 768


def test_dim_match_no_action(tmp_path, monkeypatch):
    """Pre-existing 768-dim table + 768 embedder → no change, no raise."""
    monkeypatch.delenv("OLAV_ALLOW_DESTRUCTIVE_DIM_MIGRATION", raising=False)
    db_path = tmp_path / "memory.lance"
    _make_table_with_dim(db_path, dim=768)
    store = LanceDBStore(db_path=db_path, embedding_dim=768)
    db = lancedb.connect(str(db_path))
    assert MEMORY_TABLE in list(db.table_names())
    assert _table_vector_dim(db_path) == 768


def test_missing_table_no_error(tmp_path, monkeypatch):
    """No existing table → no error, no action."""
    monkeypatch.delenv("OLAV_ALLOW_DESTRUCTIVE_DIM_MIGRATION", raising=False)
    db_path = tmp_path / "memory.lance"
    db_path.mkdir(parents=True, exist_ok=True)  # empty DB dir
    LanceDBStore(db_path=db_path, embedding_dim=768)  # must not raise


def test_extract_table_names_handles_all_lancedb_shapes():
    """LanceDB list-tables APIs vary across versions. Pin the coercion
    so a future version bump can't silently break the dim check with a
    Rust panic on InvalidTableName (demo7 Ch6 step 2 surfaced this:
    ``open_table('('page_token', None)')`` panics)."""
    S = LanceDBStore
    # Flat list[str] (older lancedb)
    assert S._extract_table_names(["a", "b"]) == ["a", "b"]
    # Paginated dict (newer)
    assert S._extract_table_names(
        {"tables": ["m"], "page_token": None}
    ) == ["m"]
    # Paginated cast to list-of-tuples (some Python 3.14 builds)
    assert S._extract_table_names(
        [("tables", ["m"]), ("page_token", None)]
    ) == ["m"]
    # Empty / None / garbage all yield []
    assert S._extract_table_names([]) == []
    assert S._extract_table_names(None) == []
    assert S._extract_table_names(42) == []
    # Mixed flat list — only strings kept
    assert S._extract_table_names(["m", 123, None, "n"]) == ["m", "n"]


def test_unrelated_tables_unaffected_by_destructive_opt_in(tmp_path, monkeypatch):
    """When opt-in destructive mode is on, unrelated tables (no vector
    column) are preserved — only the dim-mismatched one is dropped."""
    monkeypatch.setenv("OLAV_ALLOW_DESTRUCTIVE_DIM_MIGRATION", "1")
    db_path = tmp_path / "memory.lance"
    db = lancedb.connect(str(db_path))
    # Memory table at wrong dim
    _make_table_with_dim(db_path, dim=1536)
    # Unrelated table without a vector column
    other_schema = pa.schema([("k", pa.string()), ("v", pa.string())])
    db.create_table("config_blobs", schema=other_schema)

    LanceDBStore(db_path=db_path, embedding_dim=768)

    db2 = lancedb.connect(str(db_path))
    names = list(db2.table_names())
    assert MEMORY_TABLE not in names, "stale memory table should be dropped"
    assert "config_blobs" in names, "unrelated table should be preserved"


# ── ISSUE-CH8-DEMO-DIRECTIVE-VANISHES-ON-DIM-MIGRATION (P2, 2026-05-12) ─


def test_destructive_dim_migration_warning_includes_recovery_hint(tmp_path, monkeypatch, caplog):
    """ISSUE-CH8-DEMO-DIRECTIVE-VANISHES-ON-DIM-MIGRATION (P2, 2026-05-12).
    When OLAV_ALLOW_DESTRUCTIVE_DIM_MIGRATION=1 + dim changes, the
    warning log MUST include `olav kb import-guides` + `/netops_init`
    recovery commands so demo / directive guides can be restored.
    Without this the user is left with a one-line cryptic message
    and no recovery path."""
    import logging
    db_path = tmp_path / "lance.db"
    _make_table_with_dim(db_path, dim=1536)
    monkeypatch.setenv("OLAV_ALLOW_DESTRUCTIVE_DIM_MIGRATION", "1")

    with caplog.at_level(logging.WARNING):
        LanceDBStore(db_path=db_path, embedding_dim=768)

    relevant = [r for r in caplog.records if "DESTRUCTIVE" in r.getMessage() or "DIM MIGRATION" in r.getMessage()]
    assert relevant, (
        f"expected destructive-dim-migration warning; got "
        f"{[r.getMessage()[:80] for r in caplog.records]!r}"
    )
    msg = relevant[0].getMessage()
    assert "olav kb import-guides" in msg, (
        "warning must include the import-guides recovery command"
    )
    assert "netops_init" in msg, (
        "warning must include the /netops_init recovery command"
    )
    assert "ALL EXISTING ROWS LOST" in msg, (
        "warning must make the destruction prominently visible (ROWS LOST)"
    )
