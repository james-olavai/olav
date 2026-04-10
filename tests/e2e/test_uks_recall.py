"""Phase 4 TDD — Unified Recall: search after kb_chunks migration hits document-origin entries.

C-KB-28: after migrating kb_chunks, search_by_vector() returns entries with origin='document'
         confirming the unified memory table serves both agent and document knowledge.
"""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime

import pyarrow as pa
import pytest

DIM = 32
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _make_store(tmp_path):
    from olav.core.memory import LanceDBStore
    return LanceDBStore(db_path=str(tmp_path / "recall.db"), embedding_dim=DIM)


def _seed_kb_chunks(store, rows: list[dict]) -> None:
    """Seed legacy kb_chunks table with minimal rows."""
    import lancedb

    kb_schema = pa.schema([
        ("id", pa.string()),
        ("text", pa.string()),
        ("vector", pa.list_(pa.float32(), DIM)),
        ("category", pa.string()),
        ("scope", pa.string()),
        ("metadata", pa.string()),
        ("timestamp", pa.timestamp("us")),
        ("weight", pa.float32()),
    ])

    db = lancedb.connect(store._db_path)
    if "kb_chunks" in db.table_names():
        db.drop_table("kb_chunks")

    ts = datetime.now()
    records_dict: dict[str, list] = {f.name: [] for f in kb_schema}
    for r in rows:
        records_dict["id"].append(r.get("id", "kc-x"))
        records_dict["text"].append(r.get("text", ""))
        records_dict["vector"].append(r.get("vector", [0.0] * DIM))
        records_dict["category"].append(r.get("category", "fact"))
        records_dict["scope"].append(r.get("scope", "global"))
        records_dict["metadata"].append(r.get("metadata", "{}"))
        records_dict["timestamp"].append(ts)
        records_dict["weight"].append(float(r.get("weight", 1.0)))

    pa_table = pa.table(records_dict, schema=kb_schema)
    db.create_table("kb_chunks", data=pa_table, mode="overwrite")


# ─── C-KB-28: unified recall after migration ─────────────────────────────────

class TestUnifiedRecall:
    """C-KB-28: after migration, search hits document-origin entries in unified table."""

    def test_recall_hits_document_origin_after_migration(self, tmp_path):
        """C-KB-28: after migrate_kb_chunks(), search returns origin='document' entries."""
        store = _make_store(tmp_path)
        store.create_table()

        # Seed an agent memory
        v_agent = [1.0] + [0.0] * (DIM - 1)
        store.add_memory(
            id="agent-recall-001",
            text="BGP session established on spine01.",
            vector=v_agent,
            category="fact",
            scope="global",
            origin="agent",
            confidence=0.8,
            tags="[]",
        )

        # Seed a kb_chunk doc that should be migrated
        v_doc = [0.9] + [0.1] + [0.0] * (DIM - 2)
        _seed_kb_chunks(store, [
            {"id": "kc-recall-001", "text": "BGP MTU troubleshooting guide.", "vector": v_doc},
        ])

        # Run migration
        from olav.core.memory.migrate import migrate_kb_chunks
        result = migrate_kb_chunks(store)
        assert result["errors"] == 0, f"Migration errors: {result}"

        # Search with a vector close to both
        query_v = [0.95] + [0.05] + [0.0] * (DIM - 2)
        results = store.search_by_vector(query_vector=query_v, limit=10)

        origins = {r.get("origin") for r in results}
        assert "document" in origins, (
            f"Expected 'document' in search origins after migration, got {origins}\n"
            f"results: {[{'id': r['id'], 'origin': r.get('origin')} for r in results]}"
        )

    def test_recall_returns_both_agent_and_document(self, tmp_path):
        """C-KB-28: a single search returns both agent and document entries from unified table."""
        store = _make_store(tmp_path)
        store.create_table()

        v = [1.0] + [0.0] * (DIM - 1)

        # Add agent memory directly
        store.add_memory(
            id="agent-unified",
            text="OSPF area 0 adjacency up.",
            vector=v,
            category="fact",
            scope="global",
            origin="agent",
            confidence=0.7,
            tags="[]",
        )

        # Seed and migrate a kb_chunk
        _seed_kb_chunks(store, [
            {"id": "doc-unified", "text": "OSPF design best practices.", "vector": v},
        ])
        from olav.core.memory.migrate import migrate_kb_chunks
        migrate_kb_chunks(store)

        results = store.search_by_vector(query_vector=v, limit=10)
        result_ids = {r["id"] for r in results}
        result_origins = {r.get("origin") for r in results}

        assert "agent-unified" in result_ids, "agent entry missing from unified recall"
        assert "doc-unified" in result_ids, "document entry missing after migration"
        assert "agent" in result_origins and "document" in result_origins, (
            f"Expected both agent and document origins in unified recall, got {result_origins}"
        )

    def test_migrated_entry_has_correct_text(self, tmp_path):
        """C-KB-28: migrated entries must preserve the original text content."""
        store = _make_store(tmp_path)
        store.create_table()

        content = "EVPN Type-5 route advertisement requires BGP peering."
        _seed_kb_chunks(store, [
            {"id": "kc-text", "text": content, "vector": [0.5] * DIM},
        ])
        from olav.core.memory.migrate import migrate_kb_chunks
        migrate_kb_chunks(store)

        results = store.search_by_vector(query_vector=[0.5] * DIM, limit=5)
        texts = [r.get("text", "") for r in results]
        assert any("EVPN" in t for t in texts), (
            f"Original text not preserved after migration. Texts: {texts}"
        )
