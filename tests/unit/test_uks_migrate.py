"""Phase 2 TDD — migrate.py: backfill existing memory entries.

C-KB-09: migrate_memory_table() infers origin/confidence from metadata.source
         and writes them back to the memory table
"""

import json
import pytest
import pyarrow as pa

DIM = 32
DUMMY_VECTOR = [0.0] * DIM


def _make_store(tmp_path):
    from olav.core.memory import LanceDBStore
    return LanceDBStore(db_path=str(tmp_path / "mig.db"), embedding_dim=DIM)


def _insert_legacy_memory(store, id_, text, metadata_dict, table_name=None):
    """Insert a memory entry with legacy metadata (simulates pre-UKS records)."""
    from olav.core.memory import MEMORY_TABLE
    from datetime import datetime, UTC

    tname = table_name or MEMORY_TABLE
    if not store.table_exists(tname):
        store.create_table(tname)

    tbl = store.get_table(tname)
    ts = datetime.now().replace(tzinfo=None)

    record = pa.table(
        [
            pa.array([id_]),
            pa.array([text]),
            pa.array([DUMMY_VECTOR]),
            pa.array(["fact"]),
            pa.array(["global"]),
            pa.array([json.dumps(metadata_dict)]),
            pa.array([ts]),
            pa.array([ts]),
            pa.array([1]),
            pa.array([1.0]),
            pa.array(["agent"]),          # origin col (default)
            pa.array([0.5], type=pa.float32()),   # confidence col (default)
            pa.array(["[]"]),             # tags col (default)
            pa.array([None], type=pa.timestamp("us", tz="UTC")),  # expires_at (ADR-0015)
        ],
        schema=store._get_schema(),
    )
    tbl.add(record)


# ─── C-KB-09: migrate_memory_table() ─────────────────────────────────────────

def test_migrate_module_exists():
    """C-KB-09: migrate.py must exist and export migrate_memory_table."""
    from olav.core.memory import migrate  # noqa: F401
    assert hasattr(migrate, "migrate_memory_table"), (
        "migrate module must export migrate_memory_table()"
    )


def test_migrate_auto_capture_sets_agent_origin(tmp_path):
    """C-KB-09: source='auto_capture' → origin='agent', confidence=importance."""
    store = _make_store(tmp_path)
    _insert_legacy_memory(
        store, "cap-legacy-01", "Old captured fact.",
        {"source": "auto_capture", "importance": 0.65},
    )

    from olav.core.memory.migrate import migrate_memory_table
    migrate_memory_table(store)

    mem = store.get_memory("cap-legacy-01")
    assert mem is not None
    assert mem["origin"] == "agent", f"Expected 'agent', got {mem['origin']!r}"
    assert abs(float(mem["confidence"]) - 0.65) < 1e-4, (
        f"Expected confidence≈0.65, got {mem['confidence']}"
    )


def test_migrate_failure_record_sets_audit_origin(tmp_path):
    """C-KB-09: source='failure_record' → origin='audit', confidence=1.0."""
    store = _make_store(tmp_path)
    _insert_legacy_memory(
        store, "aud-legacy-01", "BGP failure recorded.",
        {"source": "failure_record"},
    )

    from olav.core.memory.migrate import migrate_memory_table
    migrate_memory_table(store)

    mem = store.get_memory("aud-legacy-01")
    assert mem is not None
    assert mem["origin"] == "audit", f"Expected 'audit', got {mem['origin']!r}"
    assert abs(float(mem["confidence"]) - 1.0) < 1e-4


def test_migrate_unknown_source_defaults_to_user(tmp_path):
    """C-KB-09: unknown/missing source → origin='user', confidence=0.8."""
    store = _make_store(tmp_path)
    _insert_legacy_memory(
        store, "usr-legacy-01", "Random old memory.",
        {},
    )

    from olav.core.memory.migrate import migrate_memory_table
    migrate_memory_table(store)

    mem = store.get_memory("usr-legacy-01")
    assert mem is not None
    assert mem["origin"] == "user", f"Expected 'user', got {mem['origin']!r}"
    assert abs(float(mem["confidence"]) - 0.8) < 1e-4


def test_migrate_tags_default_empty_list(tmp_path):
    """C-KB-09: migrate_memory_table must ensure tags='[]' for all migrated rows."""
    store = _make_store(tmp_path)
    _insert_legacy_memory(
        store, "cap-legacy-02", "Another old fact.",
        {"source": "auto_capture", "importance": 0.5},
    )

    from olav.core.memory.migrate import migrate_memory_table
    migrate_memory_table(store)

    mem = store.get_memory("cap-legacy-02")
    assert mem is not None
    tags_raw = mem["tags"]
    assert isinstance(tags_raw, str)
    assert json.loads(tags_raw) == [], f"Expected empty list, got {json.loads(tags_raw)}"


def test_migrate_idempotent(tmp_path):
    """C-KB-09: running migrate_memory_table() twice must not corrupt data."""
    store = _make_store(tmp_path)
    _insert_legacy_memory(
        store, "cap-idem-01", "Idempotency check.",
        {"source": "auto_capture", "importance": 0.7},
    )

    from olav.core.memory.migrate import migrate_memory_table
    migrate_memory_table(store)
    migrate_memory_table(store)  # second run

    mem = store.get_memory("cap-idem-01")
    assert mem is not None
    assert mem["origin"] == "agent"
    assert abs(float(mem["confidence"]) - 0.7) < 1e-4


def test_migrate_network_event_source(tmp_path):
    """C-KB-09: source='network_event' → origin='agent', confidence=0.7."""
    store = _make_store(tmp_path)
    _insert_legacy_memory(
        store, "cap-net-01", "OSPF neighbour lost.",
        {"source": "network_event"},
    )

    from olav.core.memory.migrate import migrate_memory_table
    migrate_memory_table(store)

    mem = store.get_memory("cap-net-01")
    assert mem is not None
    assert mem["origin"] == "agent"
    assert abs(float(mem["confidence"]) - 0.7) < 1e-4
