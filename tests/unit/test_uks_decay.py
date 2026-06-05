"""Phase 2 TDD — Time-decay differentiation by origin.

C-KB-06: document origin does NOT decay
C-KB-07: agent origin DOES decay normally
C-KB-08: high-frequency recall (access_count >= 5) halves the decay rate
"""

import json
import math
import pytest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
import tempfile

DIM = 32
DUMMY_VECTOR = [0.0] * DIM

HALF_LIFE = 60.0
WEIGHT_FLOOR = 0.1


def _make_store(tmp_path):
    from olav.core.memory import LanceDBStore
    return LanceDBStore(db_path=str(tmp_path / "decay.db"), embedding_dim=DIM)


def _add_memory_with_origin(store, id_, text, origin, access_count=1,
                             timestamp_days_ago=30.0, table_name=None):
    """Insert a memory directly with controlled timestamp for decay testing."""
    from olav.core.memory import MEMORY_TABLE
    tname = table_name or MEMORY_TABLE

    if not store.table_exists(tname):
        store.create_table(tname)

    import pyarrow as pa
    from datetime import datetime, timedelta, UTC
    ts = datetime.now(UTC) - timedelta(days=timestamp_days_ago)
    ts = ts.replace(tzinfo=None)  # LanceDB stores naive timestamps

    tbl = store.get_table(tname)
    record = pa.table(
        [
            pa.array([id_]),
            pa.array([text]),
            pa.array([DUMMY_VECTOR]),
            pa.array(["fact"]),
            pa.array(["global"]),
            pa.array(["{}"] ),
            pa.array([ts]),
            pa.array([ts]),
            pa.array([access_count]),
            pa.array([1.0]),
            pa.array([origin]),
            pa.array([0.8], type=pa.float32()),
            pa.array(["[]"]),
            pa.array([None], type=pa.timestamp("us", tz="UTC")),  # expires_at (ADR-0015)
        ],
        schema=store._get_schema(),
    )
    tbl.add(record)


# ─── C-KB-06: document origin → NO decay ─────────────────────────────────────

def test_document_origin_not_decayed(tmp_path):
    """C-KB-06: apply_time_decay() must skip entries with origin='document'."""
    store = _make_store(tmp_path)
    store.create_table()

    _add_memory_with_origin(store, "doc-001", "RFC 7752 defines BGP-LS.",
                             origin="document", timestamp_days_ago=90)

    from olav.core.memory.middleware import apply_time_decay
    apply_time_decay(store, half_life_days=HALF_LIFE, weight_floor=WEIGHT_FLOOR)

    mem = store.get_memory("doc-001")
    assert mem is not None
    weight = float(mem["weight"])
    # Weight must remain at initial 1.0 (unchanged)
    assert abs(weight - 1.0) < 1e-4, (
        f"document memory weight should not decay, expected 1.0 got {weight}"
    )


def test_user_origin_not_decayed(tmp_path):
    """C-KB-06: apply_time_decay() must also skip origin='user'."""
    store = _make_store(tmp_path)
    store.create_table()

    _add_memory_with_origin(store, "usr-001", "User note: prefer Python 3.12.",
                             origin="user", timestamp_days_ago=120)

    from olav.core.memory.middleware import apply_time_decay
    apply_time_decay(store, half_life_days=HALF_LIFE, weight_floor=WEIGHT_FLOOR)

    mem = store.get_memory("usr-001")
    assert mem is not None
    weight = float(mem["weight"])
    assert abs(weight - 1.0) < 1e-4, (
        f"user memory weight should not decay, expected 1.0 got {weight}"
    )


# ─── C-KB-07: agent origin → normal decay ────────────────────────────────────

def test_agent_origin_decays_normally(tmp_path):
    """C-KB-07: apply_time_decay() must decay origin='agent' using half_life_days."""
    store = _make_store(tmp_path)
    store.create_table()

    age_days = 60.0  # exactly one half-life
    _add_memory_with_origin(store, "cap-001", "BGP session established.",
                             origin="agent", timestamp_days_ago=age_days)

    from olav.core.memory.middleware import apply_time_decay
    apply_time_decay(store, half_life_days=HALF_LIFE, weight_floor=WEIGHT_FLOOR)

    mem = store.get_memory("cap-001")
    assert mem is not None
    weight = float(mem["weight"])

    # Expected: max(0.1, 0.5 + 0.5 * exp(-60/60)) ≈ 0.684
    expected = max(WEIGHT_FLOOR, 0.5 + 0.5 * math.exp(-age_days / HALF_LIFE))
    assert abs(weight - expected) < 0.01, (
        f"agent decay at {age_days}d: expected≈{expected:.4f}, got {weight:.4f}"
    )


def test_agent_origin_does_not_match_document_behaviour(tmp_path):
    """C-KB-07: agent weight must be lower than document weight after same age."""
    store = _make_store(tmp_path)
    store.create_table()

    _add_memory_with_origin(store, "cap-002", "Capture A.", origin="agent",
                             timestamp_days_ago=90)
    _add_memory_with_origin(store, "doc-002", "Document B.", origin="document",
                             timestamp_days_ago=90)

    from olav.core.memory.middleware import apply_time_decay
    apply_time_decay(store, half_life_days=HALF_LIFE, weight_floor=WEIGHT_FLOOR)

    agent_mem = store.get_memory("cap-002")
    doc_mem = store.get_memory("doc-002")
    assert agent_mem and doc_mem

    assert float(agent_mem["weight"]) < float(doc_mem["weight"]), (
        "agent memory must decay faster than document memory"
    )


# ─── C-KB-08: high access_count halves the decay rate ────────────────────────

def test_high_access_count_slows_decay(tmp_path):
    """C-KB-08: access_count >= 5 doubles the effective half_life."""
    store = _make_store(tmp_path)
    store.create_table()

    age_days = 60.0
    _add_memory_with_origin(store, "cap-low", "Rarely accessed fact.",
                             origin="agent", access_count=1, timestamp_days_ago=age_days)
    _add_memory_with_origin(store, "cap-high", "Frequently accessed fact.",
                             origin="agent", access_count=10, timestamp_days_ago=age_days)

    from olav.core.memory.middleware import apply_time_decay
    apply_time_decay(store, half_life_days=HALF_LIFE, weight_floor=WEIGHT_FLOOR)

    low_mem = store.get_memory("cap-low")
    high_mem = store.get_memory("cap-high")
    assert low_mem and high_mem

    low_weight = float(low_mem["weight"])
    high_weight = float(high_mem["weight"])

    # High access memory should have higher weight (slower decay)
    assert high_weight > low_weight, (
        f"High-frequency memory ({high_weight:.4f}) should outlast "
        f"low-frequency ({low_weight:.4f})"
    )

    # Verify the maths: effective half_life doubled → weight closer to initial
    expected_low = max(WEIGHT_FLOOR, 0.5 + 0.5 * math.exp(-age_days / HALF_LIFE))
    expected_high = max(WEIGHT_FLOOR, 0.5 + 0.5 * math.exp(-age_days / (HALF_LIFE * 2)))
    assert abs(low_weight - expected_low) < 0.01, (
        f"low: expected≈{expected_low:.4f}, got {low_weight:.4f}"
    )
    assert abs(high_weight - expected_high) < 0.01, (
        f"high (2× half_life): expected≈{expected_high:.4f}, got {high_weight:.4f}"
    )
