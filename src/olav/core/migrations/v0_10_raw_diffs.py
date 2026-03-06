"""OLAV Schema Migration v0.10.0 — raw_diffs & commands.is_primary_config.

Applies:
  1. CREATE TABLE raw_diffs (...)
  2. ALTER TABLE commands ADD COLUMN is_primary_config BOOLEAN DEFAULT FALSE
  3. UPDATE commands SET is_primary_config = TRUE WHERE command matches config patterns

Usage:
  from olav.core.migrations.v0_10_raw_diffs import apply_migration
  apply_migration(conn)   # idempotent — safe to run multiple times

Or run as a script against the real DB:
  uv run python -m olav.core.migrations.v0_10_raw_diffs
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import duckdb as _duckdb_type

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_DDL_RAW_DIFFS = """
CREATE TABLE IF NOT EXISTS raw_diffs (
    snapshot_id_1  VARCHAR              NOT NULL,
    snapshot_id_2  VARCHAR              NOT NULL,
    device_name    VARCHAR              NOT NULL,
    command        VARCHAR              NOT NULL,
    diff_content   TEXT,
    diff_normalized TEXT,
    added_count    INTEGER  DEFAULT 0,
    removed_count  INTEGER  DEFAULT 0,
    is_pinned      BOOLEAN  DEFAULT FALSE,
    timestamp      TIMESTAMP DEFAULT now(),
    PRIMARY KEY (snapshot_id_1, snapshot_id_2, device_name, command)
)
"""

_DDL_ADD_IS_PRIMARY_CONFIG = """
ALTER TABLE commands ADD COLUMN IF NOT EXISTS is_primary_config BOOLEAN DEFAULT FALSE
"""

# Patterns whose command name indicates it is the primary running configuration.
# NOTE: This fallback list is used only when backup_only_commands.yaml cannot be read.
# The authoritative source is backup_only_commands.yaml (type=configuration entries).
_PRIMARY_CONFIG_PATTERNS_FALLBACK = [
    "running-config",
    "running_config",
    "current-configuration",
    "current_configuration",
]


def _get_config_command_names() -> list[str]:
    """Return exact command names classified type=configuration in backup_only_commands.yaml.

    Reads YAML directly via PathsConfig. Falls back to empty list to trigger
    pattern-matching fallback in mark_primary_config_commands().
    """
    try:
        from pathlib import Path as _Path

        import yaml  # type: ignore[import]

        from olav.core.config import get_paths_config

        pc = get_paths_config()
        yaml_path = _Path(pc.project_root) / pc.backup_only_commands_file
        if yaml_path.exists():
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or []
            return [
                item["command"].strip()
                for item in data
                if isinstance(item, dict)
                and item.get("type") == "configuration"
                and item.get("command")
            ]
    except Exception:  # noqa: BLE001
        pass
    return []  # signal: fall back to pattern matching


def apply_migration(conn: _duckdb_type.DuckDBPyConnection) -> None:
    """Apply v0.10 migration to the given DuckDB connection (idempotent).

    Args:
        conn: An open DuckDB connection (in-memory or file-based).
    """
    conn.execute(_DDL_RAW_DIFFS)
    logger.info("v0.10 migration: raw_diffs table ensured")

    # ALTER TABLE IF NOT EXISTS column is supported in DuckDB 0.9+
    try:
        conn.execute(_DDL_ADD_IS_PRIMARY_CONFIG)
        logger.info("v0.10 migration: commands.is_primary_config column ensured")
    except Exception as exc:  # noqa: BLE001
        # Column already exists — ignore
        if "already exists" in str(exc).lower():
            logger.debug("commands.is_primary_config already present, skipping")
        else:
            raise


def mark_primary_config_commands(conn: _duckdb_type.DuckDBPyConnection) -> int:
    """Set is_primary_config=TRUE for known running-config commands.

    Prefers exact command names from backup_only_commands.yaml (type=configuration).
    Falls back to substring pattern matching if the YAML is unavailable.

    Args:
        conn: An open DuckDB connection.

    Returns:
        Number of rows updated.
    """
    exact_names = _get_config_command_names()
    if exact_names:
        # Exact match — YAML is authoritative
        quoted = ", ".join(f"'{c}'" for c in exact_names)
        conn.execute(f"""
            UPDATE commands
            SET    is_primary_config = TRUE
            WHERE  command IN ({quoted})
        """)
        logger.info(
            "v0.10 migration: is_primary_config set from YAML (%d commands)", len(exact_names)
        )
    else:
        # Fallback: substring patterns
        conditions = " OR ".join(
            f"lower(command) LIKE '%{pat}%'" for pat in _PRIMARY_CONFIG_PATTERNS_FALLBACK
        )
        conn.execute(f"""
            UPDATE commands
            SET    is_primary_config = TRUE
            WHERE  ({conditions})
        """)
        logger.warning(
            "v0.10 migration: is_primary_config set via fallback patterns (YAML unavailable)"
        )

    updated = conn.execute(
        "SELECT count(*) FROM commands WHERE is_primary_config = TRUE"
    ).fetchone()
    count = updated[0] if updated else 0
    logger.info("v0.10 migration: %d commands flagged as is_primary_config", count)
    return count


def run(db_path: str | None = None) -> None:
    """Apply migration to the real project database.

    Args:
        db_path: Optional path override; uses MAIN_DB_PATH if not provided.
    """
    import duckdb

    from olav.core.config import MAIN_DB_PATH

    path = db_path or str(MAIN_DB_PATH)
    with duckdb.connect(path, read_only=False) as conn:
        apply_migration(conn)
        mark_primary_config_commands(conn)
    logger.info("v0.10 migration complete on %s", path)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
