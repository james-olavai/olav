"""OLAV Schema Migration v0.13.0 — role_skill_permissions.

Creates the ``role_skill_permissions`` table and seeds the baseline
permission rows from :data:`olav.core.auth.authz.DEFAULT_PERMISSIONS`.

Idempotent — safe to run multiple times.

Usage::

    from olav.core.migrations.v0_13_rbac import apply_migration
    apply_migration(conn)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import duckdb as _duckdb_type

logger = logging.getLogger(__name__)

_DDL_ROLE_SKILL_PERMISSIONS = """
CREATE TABLE IF NOT EXISTS role_skill_permissions (
    role        VARCHAR NOT NULL,
    agent_id    VARCHAR NOT NULL,
    skill_name  VARCHAR NOT NULL,
    action      VARCHAR NOT NULL,
    is_allowed  BOOLEAN NOT NULL DEFAULT true,
    PRIMARY KEY (role, agent_id, skill_name, action)
)
"""

_INSERT_DEFAULT = """
INSERT OR IGNORE INTO role_skill_permissions (role, agent_id, skill_name, action, is_allowed)
VALUES (?, ?, ?, ?, ?)
"""


def apply_migration(conn: _duckdb_type.DuckDBPyConnection) -> None:
    """Create role_skill_permissions table and seed defaults. Idempotent."""
    from olav.core.auth.authz import DEFAULT_PERMISSIONS

    conn.execute(_DDL_ROLE_SKILL_PERMISSIONS)

    for rule in DEFAULT_PERMISSIONS:
        conn.execute(
            _INSERT_DEFAULT,
            [rule.role, rule.agent_id, rule.skill_name, rule.action, rule.is_allowed],
        )

    logger.info("v0_13_rbac migration applied")


if __name__ == "__main__":
    import duckdb

    from olav.core.config import DATABASES_DIR

    db_path = DATABASES_DIR / "users.duckdb"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(db_path)) as conn:
        apply_migration(conn)
    print(f"Migration applied to {db_path}")
