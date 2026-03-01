import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestSQLReflection:
    def test_sql_reflector_import(self):
        from olav.core.sql_reflection import SQLReflector, execute_sql_with_reflection

        assert SQLReflector is not None
        assert execute_sql_with_reflection is not None

    def test_sql_reflector_init(self):
        from olav.core.sql_reflection import SQLReflector

        reflector = SQLReflector(max_retries=2)
        assert reflector.max_retries == 2

    def test_sql_reflection_error(self):
        from olav.core.sql_reflection import SQLReflectionError

        error = SQLReflectionError("test error", ["SELECT 1"])
        assert "test error" in str(error)
        assert error.sql_attempts == ["SELECT 1"]

    def test_execute_sql_with_reflection_function(self):
        from olav.core.sql_reflection import execute_sql_with_reflection

        assert execute_sql_with_reflection is not None

    def test_reflector_default_retries(self):
        from olav.core.sql_reflection import SQLReflector, DEFAULT_MAX_RETRIES

        reflector = SQLReflector()
        assert reflector.max_retries == DEFAULT_MAX_RETRIES
        assert DEFAULT_MAX_RETRIES == 3


class TestSQLReflectionExecution:
    def test_execute_invalid_sql(self):
        from olav.core.sql_reflection import SQLReflector
        import duckdb

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.duckdb"
            conn = duckdb.connect(str(db_path))
            conn.execute("CREATE TABLE devices (id INTEGER, name VARCHAR)")
            conn.execute("INSERT INTO devices VALUES (1, 'test')")
            conn.close()

            reflector = SQLReflector(db_path=str(db_path), max_retries=1)
            result = reflector.execute("SELECT * FROM devicez")

            assert result["success"] is False
            assert result["error"] is not None
            assert result["attempts"][0]["error"] is not None

    def test_execute_valid_sql(self):
        from olav.core.sql_reflection import SQLReflector
        import duckdb

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.duckdb"
            conn = duckdb.connect(str(db_path))
            conn.execute("CREATE TABLE devices (id INTEGER, name VARCHAR)")
            conn.execute("INSERT INTO devices VALUES (1, 'router1'), (2, 'router2')")
            conn.close()

            reflector = SQLReflector(db_path=str(db_path), max_retries=1)
            result = reflector.execute("SELECT * FROM devices")

            assert result["success"] is True
            assert result["row_count"] == 2
            assert len(result["results"]) == 2

    def test_get_schema_context(self):
        from olav.core.sql_reflection import SQLReflector
        import duckdb

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.duckdb"
            conn = duckdb.connect(str(db_path))
            conn.execute("CREATE TABLE devices (id INTEGER, name VARCHAR)")
            conn.close()

            reflector = SQLReflector(db_path=str(db_path))
            schema = reflector._get_schema_context()

            assert "devices" in schema
            assert "id" in schema


class TestSQLCorrection:
    def test_llm_correction_called_on_failure(self):
        from olav.core.sql_reflection import SQLReflector
        import duckdb

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.duckdb"
            conn = duckdb.connect(str(db_path))
            conn.execute("CREATE TABLE devices (id INTEGER, name VARCHAR)")
            conn.close()

            reflector = SQLReflector(db_path=str(db_path), max_retries=2)

            mock_llm = MagicMock()
            mock_llm.invoke.return_value = MagicMock(content="SELECT * FROM devices")
            reflector._llm = mock_llm

            result = reflector.execute("SELECT * FROM devicez")

            assert mock_llm.invoke.called


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
