"""v0.12 schema split migration — flat tables → netops.* schema.

Idempotent: safe to run multiple times.

What this does
--------------
1. Creates the ``netops`` DuckDB schema.
2. For each legacy flat table (``parsed_outputs``, ``devices``,
   ``topology_links``), copies all rows into ``netops.<table>``
   (creating it if absent via ``CREATE TABLE … AS SELECT``).
3. Creates backward-compat views ``main.<table>`` → ``netops.<table>``
   so existing code that references the flat name keeps working for
   one version (views will be dropped in v0.13).
4. Drops the original flat tables (after the compat views are in place).

Usage
-----
Via CLI::

    olav-netops migrate [--db PATH]

Or programmatically::

    import duckdb
    from olav_netops.migrations.v0_12_schema_split import migrate

    with duckdb.connect(".olav/databases/main.duckdb") as conn:
        migrate(conn)
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Tables to migrate from flat layout → netops.*
_NETOPS_TABLES = [
    "parsed_outputs",
    "devices",
    "topology_links",
]


def migrate(conn) -> None:
    """Run the v0.12 flat → netops.* schema split migration.

    Args:
        conn: An open, writable ``duckdb.DuckDBPyConnection``.
    """
    logger.info("v0_12_schema_split: starting migration")

    conn.execute("CREATE SCHEMA IF NOT EXISTS netops")
    logger.debug("Ensured schema: netops")

    # Import table definitions so UNIQUE constraints are applied correctly.
    try:
        from olav_netops.core.tables import ParsedOutputsTable, DevicesTable, TopologyLinksTable  # noqa: PLC0415
        _TABLE_DEFS = {
            "parsed_outputs": ParsedOutputsTable(),
            "devices":         DevicesTable(),
            "topology_links":  TopologyLinksTable(),
        }
    except ImportError:
        _TABLE_DEFS = {}  # graceful fallback

    for table in _NETOPS_TABLES:
        _migrate_table(conn, table, _TABLE_DEFS.get(table))

    logger.info("v0_12_schema_split: migration complete")


def _migrate_table(conn, table: str, table_def=None) -> None:
    """Migrate a single flat table to netops.<table> with compat view.

    If *table_def* is provided its ``ensure_schema()`` is used to create
    the target table so that UNIQUE constraints are applied correctly.
    """
    netops_table = f"netops.{table}"

    flat_exists = _table_exists(conn, table, schema="main")
    netops_exists = _table_exists(conn, table, schema="netops")

    if not flat_exists and not netops_exists:
        if table_def is not None:
            table_def.ensure_schema(conn)
            logger.info("Created empty %s via ensure_schema", netops_table)
        else:
            logger.warning("Table %s not found — skipping", table)
        return

    if not netops_exists:
        if table_def is not None:
            # Create with constraints, then copy rows from flat source
            table_def.ensure_schema(conn)
            cols = ", ".join(c.name for c in table_def.columns)
            conn.execute(
                f"INSERT OR IGNORE INTO {netops_table} ({cols})"
                f" SELECT {cols} FROM {table}"
            )
        else:
            conn.execute(f"CREATE TABLE IF NOT EXISTS {netops_table} AS SELECT * FROM {table}")
        logger.info("Copied main.%s → %s", table, netops_table)
    else:
        logger.debug("%s already exists — skipping copy", netops_table)

    if flat_exists:
        # Could be a legacy TABLE or an existing compat VIEW — drop either.
        conn.execute(f"DROP VIEW IF EXISTS main.{table}")
        conn.execute(f"DROP TABLE IF EXISTS main.{table}")
        logger.info("Dropped flat table/view: main.%s", table)

    conn.execute(f"CREATE VIEW IF NOT EXISTS {table} AS SELECT * FROM {netops_table}")
    logger.info("Created compat view: main.%s → %s", table, netops_table)


def _table_exists(conn, table: str, schema: str = "main") -> bool:
    """Return True if *schema*.*table* exists in DuckDB."""
    result = conn.execute(
        """
        SELECT COUNT(*) FROM information_schema.tables
        WHERE table_schema = ? AND table_name = ?
        """,
        [schema, table],
    ).fetchone()
    return bool(result and result[0] > 0)
