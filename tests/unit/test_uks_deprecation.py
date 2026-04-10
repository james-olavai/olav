"""Phase 4 TDD — KB Deprecation: cleanup of olav.core.knowledge module.

C-KB-25: migrate_kb_chunks() moves kb_chunks rows → unified memory table
C-KB-26: `from olav.core.knowledge` raises ImportError after deletion
C-KB-27: search_knowledge_lancedb tool file is deleted
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pyarrow as pa
import pytest
from datetime import datetime

DIM = 32
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _make_store(tmp_path, sub="p4.db"):
    from olav.core.memory import LanceDBStore
    return LanceDBStore(db_path=str(tmp_path / sub), embedding_dim=DIM)


def _seed_kb_chunks(store, rows: list[dict]) -> None:
    """Seed legacy kb_chunks table with minimal rows for migration testing."""
    import lancedb
    import pyarrow as pa

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

    records_dict: dict[str, list] = {f.name: [] for f in kb_schema}
    ts = datetime.now()
    for r in rows:
        records_dict["id"].append(r.get("id", "kc-unknown"))
        records_dict["text"].append(r.get("text", ""))
        records_dict["vector"].append(r.get("vector", [0.0] * DIM))
        records_dict["category"].append(r.get("category", "fact"))
        records_dict["scope"].append(r.get("scope", "global"))
        records_dict["metadata"].append(r.get("metadata", "{}"))
        records_dict["timestamp"].append(ts)
        records_dict["weight"].append(float(r.get("weight", 1.0)))

    pa_table = pa.table(records_dict, schema=kb_schema)
    db.create_table("kb_chunks", data=pa_table, mode="overwrite")


# ─── C-KB-25: migrate_kb_chunks ───────────────────────────────────────────────

class TestMigrateKbChunks:
    """C-KB-25: migrate_kb_chunks() moves kb_chunks → memory table."""

    def test_migrate_moves_rows_to_memory(self, tmp_path):
        """C-KB-25: after migration, kb_chunks rows appear in memory table."""
        store = _make_store(tmp_path)
        store.create_table()

        rows = [
            {"id": "kc-001", "text": "BGP MTU best practice doc.", "vector": [0.1] * DIM},
            {"id": "kc-002", "text": "OSPF design guide.", "vector": [0.2] * DIM},
        ]
        _seed_kb_chunks(store, rows)

        from olav.core.memory.migrate import migrate_kb_chunks
        result = migrate_kb_chunks(store)

        assert result["migrated"] >= 2, f"Expected >= 2 migrated, got {result}"
        assert result["errors"] == 0, f"Expected 0 errors, got {result}"
        assert result["dry_run"] is False

        memories = store.get_memories(limit=20)
        ids = {m["id"] for m in memories}
        assert "kc-001" in ids or any("kc" in i for i in ids), (
            f"Migrated IDs not found in memory table. IDs: {ids}"
        )

    def test_migrate_sets_origin_document(self, tmp_path):
        """C-KB-25: migrated rows must have origin='document'."""
        store = _make_store(tmp_path)
        store.create_table()
        _seed_kb_chunks(store, [
            {"id": "kc-origin", "text": "RFC 4271 BGP specification.", "vector": [0.3] * DIM},
        ])

        from olav.core.memory.migrate import migrate_kb_chunks
        migrate_kb_chunks(store)

        memories = store.get_memories(limit=20)
        origins = {m["origin"] for m in memories}
        assert "document" in origins, f"Migrated rows must have origin='document', got {origins}"

    def test_migrate_sets_confidence_1(self, tmp_path):
        """C-KB-25: migrated rows must have confidence=1.0."""
        store = _make_store(tmp_path)
        store.create_table()
        _seed_kb_chunks(store, [
            {"id": "kc-conf", "text": "EVPN design whitepaper.", "vector": [0.4] * DIM},
        ])

        from olav.core.memory.migrate import migrate_kb_chunks
        migrate_kb_chunks(store)

        memories = store.get_memories(limit=20)
        assert all(abs(float(m["confidence"]) - 1.0) < 1e-4 for m in memories), (
            f"Expected confidence=1.0 for all migrated rows: {[m['confidence'] for m in memories]}"
        )

    def test_migrate_dry_run_does_not_write(self, tmp_path):
        """C-KB-25: dry_run=True reports count without writing."""
        store = _make_store(tmp_path)
        store.create_table()
        _seed_kb_chunks(store, [
            {"id": "kc-dry", "text": "Dry-run test content.", "vector": [0.5] * DIM},
        ])

        from olav.core.memory.migrate import migrate_kb_chunks
        result = migrate_kb_chunks(store, dry_run=True)

        assert result["dry_run"] is True
        assert result["migrated"] >= 1, "dry_run should still report what would be migrated"
        memories = store.get_memories(limit=20)
        assert len(memories) == 0, (
            f"dry_run must not write, found {len(memories)} memories"
        )

    def test_migrate_no_kb_chunks_is_noop(self, tmp_path):
        """C-KB-25: if kb_chunks table doesn't exist, migrate returns zeros."""
        store = _make_store(tmp_path)
        store.create_table()

        from olav.core.memory.migrate import migrate_kb_chunks
        result = migrate_kb_chunks(store)
        assert result["migrated"] == 0
        assert result["errors"] == 0


# ─── C-KB-26: olav.core.knowledge raises ImportError ─────────────────────────

class TestKnowledgeModuleDeleted:
    """C-KB-26: after Phase 4, olav.core.knowledge must not be importable."""

    def test_knowledge_module_not_importable(self):
        """C-KB-26: `from olav.core.knowledge import ...` must raise ImportError."""
        result = subprocess.run(
            [sys.executable, "-c", "from olav.core.knowledge import get_knowledge_base"],
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
        )
        # Should fail — module should not exist after Phase 4
        assert result.returncode != 0, (
            f"olav.core.knowledge is still importable — must be deleted in Phase 4.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_no_knowledge_imports_in_src(self):
        """C-KB-26: no remaining `from olav.core.knowledge` in src/."""
        result = subprocess.run(
            ["grep", "-r", "from olav.core.knowledge", "src/"],
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
        )
        assert result.stdout == "", (
            f"Remaining olav.core.knowledge imports in src/:\n{result.stdout}"
        )


# ─── C-KB-27: search_knowledge_lancedb tool deleted ──────────────────────────

class TestSearchKnowledgeToolDeleted:
    """C-KB-27: search_knowledge_lancedb tool file must be deleted."""

    def test_search_knowledge_lancedb_file_deleted(self):
        """C-KB-27: the legacy search_knowledge_lancedb.py tool must not exist."""
        tool_path = _REPO_ROOT / "src" / "olav" / "data" / "workspace" / "core" / "tools" / "search_knowledge_lancedb.py"
        assert not tool_path.exists(), (
            f"Legacy search_knowledge_lancedb.py still exists at {tool_path} — must be deleted in Phase 4."
        )

    def test_olav_workspace_tool_deleted(self):
        """C-KB-27: the installed workspace copy must also not exist."""
        workspace_tool = _REPO_ROOT / ".olav" / "workspace" / "core" / "tools" / "search_knowledge_lancedb.py"
        assert not workspace_tool.exists(), (
            f"Workspace copy of search_knowledge_lancedb.py still exists — must be deleted in Phase 4.\n"
            f"Path: {workspace_tool}"
        )
