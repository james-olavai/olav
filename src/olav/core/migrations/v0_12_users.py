"""OLAV Schema Migration v0.12.0 — users.duckdb schema.

Creates the `users` table in the users.duckdb database.
Idempotent — safe to run multiple times.

Usage::

    from olav.core.migrations.v0_12_users import apply_migration
    apply_migration(conn)

Or as a script::

    uv run python -m olav.core.migrations.v0_12_users
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import duckdb as _duckdb_type

logger = logging.getLogger(__name__)

_DDL_USERS = """
CREATE TABLE IF NOT EXISTS users (
    username       VARCHAR PRIMARY KEY,
    display_name   VARCHAR,
    role           VARCHAR NOT NULL DEFAULT 'user',
    token_hash     VARCHAR,
    token_salt     VARCHAR,
    created_at     TIMESTAMPTZ DEFAULT now(),
    expires_at     TIMESTAMPTZ,
    last_login_at  TIMESTAMPTZ,
    is_active      BOOLEAN DEFAULT true,
    source         VARCHAR DEFAULT 'local'
)
"""


def apply_migration(conn: _duckdb_type.DuckDBPyConnection) -> None:
    """Create users table. Idempotent."""
    conn.execute(_DDL_USERS)
    logger.info("v0_12_users migration applied")


if __name__ == "__main__":
    import duckdb

    from olav.core.config import DATABASES_DIR

    db_path = DATABASES_DIR / "users.duckdb"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(db_path)) as conn:
        apply_migration(conn)
    print(f"Migration applied to {db_path}")
