"""Baseline auth schema for OLAV.

This module owns the ``users`` table DDL that every supported OLAV release
depends on. It is *not* a versioned migration — it is the current schema,
applied idempotently at install time and by any CLI that needs the table.

The schema lived in ``olav.core.migrations.v0_12_users`` through 0.18.x;
ARCH-22 B promoted it to baseline so ``COMPATIBILITY_CUTOFF`` can advance
past v0.12 without losing fresh-install support.

Callers::

    from olav.core.auth.schema import apply_baseline
    with duckdb.connect(...) as conn:
        apply_baseline(conn)
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


def apply_baseline(conn: "_duckdb_type.DuckDBPyConnection") -> None:
    """Create the ``users`` table if it does not already exist.

    Idempotent: safe to call on every ``olav init`` or admin command
    invocation. Succeeds silently when the table is already present.
    """
    conn.execute(_DDL_USERS)
    logger.info("auth baseline schema applied (users table)")
