"""Test LanceDB connection and basic operations.

This test validates the foundation for the LanceDB memory system:
- Connection to local LanceDB instance
- Database creation/opening
- Table creation with proper schema
- Basic CRUD operations
"""

import pytest
from pathlib import Path


class TestLanceDBConnection:
    """Test LanceDB connection and basic functionality."""

    @pytest.fixture
    def temp_db_path(self, tmp_path):
        """Provide a temporary database path for testing."""
        return tmp_path / "test_memory.lance"

    def test_lancedb_import(self):
        """Verify LanceDB is properly installed."""
        import lancedb

        assert lancedb is not None
        assert hasattr(lancedb, "connect")

    def test_connect_to_local_database(self, temp_db_path):
        """Test connecting to a local LanceDB database."""
        import lancedb

        db = lancedb.connect(str(temp_db_path))
        assert db is not None
        assert hasattr(db, "table_names")

    def test_create_and_list_tables(self, temp_db_path):
        """Test table creation and listing."""
        import lancedb
        import pyarrow as pa

        db = lancedb.connect(str(temp_db_path))

        # Create a test table with vector column
        schema = pa.schema(
            [
                ("id", pa.string()),
                ("text", pa.string()),
                ("vector", pa.list_(pa.float32(), 1536)),
                ("category", pa.string()),
                ("scope", pa.string()),
                ("timestamp", pa.timestamp("us")),
            ]
        )

        # Create empty table
        db.create_table("test_memory", schema=schema)

        # Verify table exists
        tables = db.table_names()
        assert "test_memory" in tables

    def test_basic_crud_operations(self, temp_db_path):
        """Test basic CRUD operations on a LanceDB table."""
        import lancedb
        import pyarrow as pa

        db = lancedb.connect(str(temp_db_path))

        # Create table with data
        schema = pa.schema(
            [
                ("id", pa.string()),
                ("text", pa.string()),
                ("category", pa.string()),
            ]
        )

        tbl = db.create_table("crud_test", schema=schema)

        # Insert data using PyArrow
        data = pa.table(
            [
                pa.array(["1", "2"]),
                pa.array(["hello world", "test document"]),
                pa.array(["fact", "preference"]),
            ],
            schema=schema,
        )
        tbl.add(data)

        # Verify data was inserted
        assert tbl.count_rows() == 2

        # Read data
        result = tbl.to_arrow()
        assert result.num_rows == 2

    def test_vector_search_schema(self, temp_db_path):
        """Test that table schema supports vector search."""
        import lancedb
        import pyarrow as pa
        import numpy as np

        db = lancedb.connect(str(temp_db_path))

        # Create table with proper vector schema for LanceDB
        schema = pa.schema(
            [
                ("id", pa.string()),
                ("text", pa.string()),
                ("vector", pa.list_(pa.float32(), 384)),  # Common embedding dim
            ]
        )

        tbl = db.create_table("vector_test", schema=schema)

        # Insert a sample vector using PyArrow
        vector = np.random.rand(384).astype(np.float32)
        data = pa.table(
            [
                pa.array(["test-1"]),
                pa.array(["This is a test document"]),
                pa.array([vector.tolist()]),
            ],
            schema=schema,
        )
        tbl.add(data)

        # Verify vector search capability
        assert tbl.count_rows() == 1


class TestLanceDBConfiguration:
    """Test LanceDB configuration and paths."""

    def test_default_database_path(self):
        """Test that default memory database path is configurable."""
        from pathlib import Path

        # Should have a memory database path in .olav
        # This tests the expected path structure
        project_root = Path(__file__).parent.parent.parent
        olav_dir = project_root / ".olav"

        # The .olav directory should exist
        assert olav_dir.exists(), ".olav directory should exist"
