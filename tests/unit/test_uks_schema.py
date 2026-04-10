"""Phase 1 TDD: Unified Knowledge Store — Schema Extension.

C-KB-01: 新表含 origin/confidence/tags 列
C-KB-02: add_memory() 不传新参数时默认值正确
C-KB-03: 旧 schema 表自动 migration
"""

import json

import pyarrow as pa
import pytest

DIM = 32  # small dimension for tests


class TestUKSSchema:
    """C-KB-01, C-KB-02, C-KB-03"""

    def test_new_table_has_origin_column(self, tmp_path):
        """C-KB-01a: create_table() 建立的新表包含 origin 列。"""
        from olav.core.memory import LanceDBStore

        store = LanceDBStore(db_path=tmp_path / "test.lance", embedding_dim=DIM)
        store.create_table()
        schema = store.get_schema()
        assert "origin" in schema.names, f"origin not in schema: {schema.names}"

    def test_new_table_has_confidence_column(self, tmp_path):
        """C-KB-01b: create_table() 建立的新表包含 confidence 列。"""
        from olav.core.memory import LanceDBStore

        store = LanceDBStore(db_path=tmp_path / "test.lance", embedding_dim=DIM)
        store.create_table()
        schema = store.get_schema()
        assert "confidence" in schema.names, f"confidence not in schema: {schema.names}"

    def test_new_table_has_tags_column(self, tmp_path):
        """C-KB-01c: create_table() 建立的新表包含 tags 列。"""
        from olav.core.memory import LanceDBStore

        store = LanceDBStore(db_path=tmp_path / "test.lance", embedding_dim=DIM)
        store.create_table()
        schema = store.get_schema()
        assert "tags" in schema.names, f"tags not in schema: {schema.names}"

    def test_add_memory_default_origin(self, tmp_path):
        """C-KB-02a: add_memory() 不传 origin 时默认值为 'agent'。"""
        from olav.core.memory import LanceDBStore

        store = LanceDBStore(db_path=tmp_path / "test.lance", embedding_dim=DIM)
        store.create_table()
        result = store.add_memory(
            id="test-1",
            text="test fact",
            vector=[0.1] * DIM,
        )
        assert result["status"] == "success", f"add_memory failed: {result}"
        mem = store.get_memory("test-1")
        assert mem is not None, "get_memory returned None for test-1"
        assert mem["origin"] == "agent", f"Expected origin='agent', got {mem['origin']!r}"

    def test_add_memory_default_confidence(self, tmp_path):
        """C-KB-02b: add_memory() 不传 confidence 时默认值为 0.5。"""
        from olav.core.memory import LanceDBStore

        store = LanceDBStore(db_path=tmp_path / "test.lance", embedding_dim=DIM)
        store.create_table()
        store.add_memory(id="test-2", text="test fact 2", vector=[0.2] * DIM)
        mem = store.get_memory("test-2")
        assert mem is not None
        assert mem["confidence"] == pytest.approx(0.5), (
            f"Expected confidence=0.5, got {mem['confidence']!r}"
        )

    def test_add_memory_default_tags(self, tmp_path):
        """C-KB-02c: add_memory() 不传 tags 时默认值为 '[]'（JSON 空数组字符串）。"""
        from olav.core.memory import LanceDBStore

        store = LanceDBStore(db_path=tmp_path / "test.lance", embedding_dim=DIM)
        store.create_table()
        store.add_memory(id="test-3", text="test fact 3", vector=[0.3] * DIM)
        mem = store.get_memory("test-3")
        assert mem is not None
        assert mem["tags"] == "[]", f"Expected tags='[]', got {mem['tags']!r}"

    def test_add_memory_explicit_origin(self, tmp_path):
        """C-KB-02d: add_memory() 传 origin='document' 时正确存储。"""
        from olav.core.memory import LanceDBStore

        store = LanceDBStore(db_path=tmp_path / "test.lance", embedding_dim=DIM)
        store.create_table()
        store.add_memory(
            id="doc-1",
            text="document fact",
            vector=[0.4] * DIM,
            origin="document",
            confidence=1.0,
            tags=json.dumps(["spine01", "bgp"]),
        )
        mem = store.get_memory("doc-1")
        assert mem is not None
        assert mem["origin"] == "document"
        assert mem["confidence"] == pytest.approx(1.0)
        assert json.loads(mem["tags"]) == ["spine01", "bgp"]

    def test_old_schema_migration(self, tmp_path):
        """C-KB-03: 旧 schema 表（无 origin/confidence/tags）调用 create_table() 后自动 migration。

        构造一张不含新列的旧表，再让 LanceDBStore.create_table() 触发迁移，
        验证现有记录的 origin 字段被补填了默认值（非 None）。
        """
        import lancedb

        db_path = tmp_path / "old.lance"

        # 建一张旧 schema 的表（10 列，无 origin/confidence/tags）
        old_schema = pa.schema(
            [
                ("id", pa.string()),
                ("text", pa.string()),
                ("vector", pa.list_(pa.float32(), DIM)),
                ("category", pa.string()),
                ("scope", pa.string()),
                ("metadata", pa.string()),
                ("timestamp", pa.timestamp("us")),
                ("created_at", pa.timestamp("us")),
                ("access_count", pa.int32()),
                ("weight", pa.float32()),
            ]
        )
        import datetime

        now = datetime.datetime.now()
        old_record = pa.table(
            [
                pa.array(["existing-1"]),
                pa.array(["existing memory text"]),
                pa.array([[0.5] * DIM]),
                pa.array(["fact"]),
                pa.array(["global"]),
                pa.array(["{}"] ),
                pa.array([now]),
                pa.array([now]),
                pa.array([0], type=pa.int32()),
                pa.array([1.0], type=pa.float32()),
            ],
            schema=old_schema,
        )
        db = lancedb.connect(str(db_path))
        db.create_table("memory", old_record)

        # 用 LanceDBStore 打开相同 db 路径 → 触发 migration
        from olav.core.memory import LanceDBStore, MEMORY_TABLE

        store = LanceDBStore(db_path=db_path, embedding_dim=DIM)
        store.create_table(MEMORY_TABLE)  # should trigger migration

        # 验证：existing-1 的 origin 已被补填（非 None）
        mem = store.get_memory("existing-1")
        assert mem is not None, "existing-1 should survive migration"
        assert mem.get("origin") is not None, (
            "Migration should backfill origin for existing records"
        )
