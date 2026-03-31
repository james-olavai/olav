"""Phase 3-2 TDD: config.py must expose AUDIT_DB_PATH."""


def test_audit_db_path_importable():
    from olav.core.config import AUDIT_DB_PATH  # noqa: F401


def test_audit_db_path_ends_with_audit_duckdb():
    from olav.core.config import AUDIT_DB_PATH

    path_str = str(AUDIT_DB_PATH).replace("\\", "/")
    assert path_str.endswith(".olav/databases/audit.duckdb"), (
        f"AUDIT_DB_PATH should end with '.olav/databases/audit.duckdb', got: {path_str}"
    )
