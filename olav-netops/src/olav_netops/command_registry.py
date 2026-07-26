"""Command registry — entry-point shims delegating to R73 SSOT (``netops.commands``).

Post-R75 simplification:

The heavy `CommandRegistry` singleton(whitelist / blacklist / template
globbing / per-platform command indexing)has been removed. Its data
paths were orphaned after R73 introduced
:mod:`olav_netops.core.commands_sync`:py:mod:, which is now the single
source of truth for everything commands-related.

What survives in this module(因为 pyproject.toml entry-points 引用了它们):

* :func:`reload_hook` — ``olav.reload_hooks.netops`` entry-point;
  re-runs :func:`olav_netops.core.commands_sync.sync_commands`.
* :func:`get_config_commands` — ``olav.config_commands.netops``
  entry-point; returns the list of ``backup_only=true`` commands from
  the ``netops.commands`` table.

Everything else(``CommandRegistry`` class, ``_load_whitelist`` /
``_load_blacklist`` / ``_load_platform_commands``, ``reload()``,
``get_platform_commands``, ``get_backup_only_commands``) has been
deleted.  ~250 LOC of dead code removed, zero functional impact —
no caller referenced those methods after R73.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────
# Entry-point callables (pyproject.toml → olav.reload_hooks / olav.config_commands)
# ──────────────────────────────────────────────────────────────────────────

def reload_hook() -> dict[str, Any]:
    """Re-sync the ``netops.commands`` table.

    Called by the platform whenever templates / parsers / yaml overlays
    change and need to be re-indexed. Delegates to
    :func:`olav_netops.core.commands_sync.sync_commands`.

    Returns the sync stats dict (``{ntc, custom, pac, user, blacklisted,
    total, seeded}``).
    """
    try:
        import duckdb
        from olav.core.config import MAIN_DB_PATH
        from olav.core.db_write import open_write_connection
        from olav_netops.core.commands_sync import sync_commands
    except Exception as exc:  # noqa: BLE001
        logger.warning("reload_hook: import failed: %s", exc)
        return {"error": str(exc)}

    try:
        with open_write_connection(MAIN_DB_PATH) as conn:
            return sync_commands(conn)
    except Exception as exc:  # noqa: BLE001
        logger.warning("reload_hook: sync_commands raised: %s", exc)
        return {"error": str(exc)}


def get_config_commands() -> list[str]:
    """Return every command flagged ``backup_only=true``.

    R75: reads from ``netops.commands`` rather than the legacy
    ``backup_only_commands.yaml`` (which is still consulted by
    :mod:`olav.core.ingest_manager` for ARCH-22-C backward compat —
    migration to the DB-only path is tracked in that issue).

    Used by the platform's ``olav.config_commands.netops`` entry-point
    to classify snapshot rows as "configuration backup" vs "operational
    state" during diffs.
    """
    try:
        import duckdb
        from olav.core.config import MAIN_DB_PATH
    except Exception as exc:  # noqa: BLE001
        logger.warning("get_config_commands: import failed: %s", exc)
        return []

    try:
        with duckdb.connect(str(MAIN_DB_PATH), read_only=True) as conn:
            rows = conn.execute(
                "SELECT DISTINCT command FROM netops.commands "
                "WHERE backup_only = true "
                "ORDER BY command"
            ).fetchall()
            return [r[0] for r in rows]
    except Exception as exc:  # noqa: BLE001
        # Table absent (no /netops_init yet) or DB unavailable.
        logger.debug("get_config_commands: query failed: %s", exc)
        return []
