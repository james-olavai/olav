"""First-run empty-state check for the netops extension (dev_docs/99 §7.1).

Registered under the platform's ``olav.first_run_checks`` entry-point group
(see ``pyproject.toml``). The platform discovers and calls this on every
agent launch and shows any returned finding on the TUI welcome screen — so
a fresh install answers "installed, now what?" itself instead of leaving
the user to read docs.

Contract: zero-arg, deterministic, local-only (file stat + read-only
DuckDB count — no LLM, no network), returns a user-facing string or None.
Must never raise; the platform ignores a broken check but silence here
costs the user the guidance.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def check_netops_data() -> str | None:
    """Report whether netops has any device data yet, with the fix action.

    Returns:
        - ``None`` — netops workspace not deployed (nothing to say), data
          present (healthy), or state undeterminable (fail silent).
        - Init guidance — DB/table missing: ``/netops_init`` never ran.
        - Import guidance — table exists but holds zero devices.
    """
    if not (Path(".olav") / "workspace" / "netops").is_dir():
        return None

    try:
        import duckdb

        from olav.core import config as _config

        db_path = Path(_config.MAIN_DB_PATH)
        if not db_path.exists():
            return _INIT_FINDING

        try:
            with duckdb.connect(str(db_path), read_only=True) as conn:
                count = conn.execute("SELECT COUNT(*) FROM netops.devices").fetchone()[0]
        except duckdb.CatalogException:
            # Table absent — /netops_init has not been run yet.
            return _INIT_FINDING

        if count == 0:
            return _IMPORT_FINDING
        return None
    except Exception as exc:  # noqa: BLE001
        # DB locked, driver missing, … — undeterminable, stay silent.
        logger.debug("check_netops_data skipped: %s", exc)
        return None


_INIT_FINDING = (
    "netops is installed but not initialized yet — run /netops_init to "
    "create its tables, then import a snapshot or collect from devices."
)

_IMPORT_FINDING = (
    "netops has no device data yet — import a snapshot (olav kb import) or "
    "ask /netops to collect from your devices to get your first answers."
)
