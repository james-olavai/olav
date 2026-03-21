"""In-memory schema mapping cache with DuckDB persistence.

Provides fast lookups keyed by (command, raw_key) → openconfig_path.
Cache hydration reads canonical metadata from ``schema_catalog``.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class SchemaCache:
    """Two-level dict cache: command → {raw_key → openconfig_path}.

    Thread-safety is *not* provided — callers in multi-user scenarios
    should create per-request instances or wrap access with a lock.
    """

    def __init__(self) -> None:
        self._store: dict[str, dict[str, str]] = {}

    # ------------------------------------------------------------------
    # Core CRUD
    # ------------------------------------------------------------------

    def get(self, command: str, raw_key: str) -> str | None:
        """Return cached openconfig_path or ``None`` on miss."""
        return self._store.get(command, {}).get(raw_key)

    def put(self, command: str, raw_key: str, openconfig_path: str) -> None:
        """Insert or overwrite a mapping."""
        self._store.setdefault(command, {})[raw_key] = openconfig_path

    def has(self, command: str, raw_key: str) -> bool:
        """Return ``True`` if a mapping exists for *(command, raw_key)*."""
        return raw_key in self._store.get(command, {})

    def get_all(self, command: str) -> dict[str, str]:
        """Return every ``{raw_key: openconfig_path}`` for *command*."""
        return dict(self._store.get(command, {}))

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_duckdb(cls, db_path: str) -> SchemaCache:
        """Hydrate a cache from ``schema_catalog``.

        Parameters
        ----------
        db_path:
            Filesystem path to a DuckDB database that contains a
            ``schema_catalog`` table with at least ``source_name`` and
            ``fields`` columns.

        Returns
        -------
        SchemaCache
            A fully populated cache instance.
        """
        import duckdb
        import json as _json

        cache = cls()
        conn = duckdb.connect(db_path, read_only=True)
        try:
            has_catalog = conn.execute(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema='main' AND table_name='schema_catalog'"
            ).fetchone()
            if not has_catalog or has_catalog[0] == 0:
                raise ValueError("schema_catalog table is required for SchemaCache hydration")

            rows = conn.execute(
                "SELECT source_name, fields FROM schema_catalog"
            ).fetchall()
            for command, fields_json in rows:
                if not command or not fields_json:
                    continue
                try:
                    fields = _json.loads(fields_json) if isinstance(fields_json, str) else fields_json
                except Exception as exc:
                    raise ValueError(f"Invalid schema_catalog.fields JSON for command={command!r}") from exc

                if not isinstance(fields, list):
                    raise ValueError(f"schema_catalog.fields must be a list for command={command!r}")

                for field in fields:
                    if not isinstance(field, dict):
                        continue
                    raw_key = field.get("name")
                    oc_path = (
                        field.get("openconfig_path")
                        or field.get("oc_path")
                        or field.get("canonical_path")
                    )
                    if raw_key and oc_path:
                        cache.put(str(command), str(raw_key), str(oc_path))
        finally:
            conn.close()

        logger.debug("SchemaCache loaded %d commands from %s", len(cache._store), db_path)
        return cache
