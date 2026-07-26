"""registry_sync — sync services.yaml → api_registry.services in main.duckdb.

Called by:
  - register_service / deregister_service scripts (after each mutation)
  - olav init (bootstrap full sync)

The api_registry.services table is the queryable index for agents:
    execute_sql("SELECT name, endpoint FROM api_registry.services")

services.yaml remains the authoritative source; DuckDB is a derived cache.
"""
from __future__ import annotations

import logging
from pathlib import Path
from contextlib import contextmanager
from typing import Any

from olav.core.db_write import open_write_connection

logger = logging.getLogger(__name__)

_DDL = """
CREATE SCHEMA IF NOT EXISTS api_registry;
CREATE TABLE IF NOT EXISTS api_registry.services (
    name          VARCHAR PRIMARY KEY,
    endpoint      VARCHAR NOT NULL,
    display_name  VARCHAR,
    description   VARCHAR,
    readonly_only BOOLEAN DEFAULT false,
    auth_type     VARCHAR,
    token_env     VARCHAR,
    schema_url    VARCHAR,
    registered_at TIMESTAMPTZ DEFAULT now(),
    updated_at    TIMESTAMPTZ DEFAULT now()
);
"""


@contextmanager
def _open_main_db(read_only: bool = False):
    """Yield a connection to the main DB's api_registry schema. Writes route
    through the shared write seam (open_write_connection) — ADR-0018/0019."""
    import duckdb
    from olav.core.config import MAIN_DB_PATH
    db_path = Path(MAIN_DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if read_only:
        con = duckdb.connect(str(db_path), read_only=True)
        try:
            yield con
        finally:
            con.close()
        return
    with open_write_connection(db_path) as con:
        for stmt in _DDL.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                con.execute(stmt)
        yield con


def _load_services_yaml() -> dict[str, Any]:
    from olav.core.config import CONFIG_DIR
    path = Path(CONFIG_DIR) / "services.yaml"
    if not path.exists():
        return {}
    import yaml
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data.get("services", {})


def _auth_info(svc: dict) -> tuple[str, str | None]:
    """Return (auth_type, token_env) from a service entry."""
    auth = svc.get("auth", {})
    if not auth:
        return svc.get("auth_type", "none"), None
    atype = auth.get("type", "none")
    token_env = auth.get("token_env") or auth.get("header_name")
    return atype, token_env


def upsert_service(name: str, entry: dict) -> None:
    """Upsert a single service entry into api_registry.services."""
    auth_type, token_env = _auth_info(entry)
    try:
        with _open_main_db() as con:
            con.execute(
                """
                INSERT INTO api_registry.services
                    (name, endpoint, display_name, description, readonly_only,
                     auth_type, token_env, schema_url, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, now())
                ON CONFLICT (name) DO UPDATE SET
                    endpoint     = excluded.endpoint,
                    display_name = excluded.display_name,
                    description  = excluded.description,
                    readonly_only= excluded.readonly_only,
                    auth_type    = excluded.auth_type,
                    token_env    = excluded.token_env,
                    schema_url   = excluded.schema_url,
                    updated_at   = now()
                """,
                [
                    name,
                    entry.get("endpoint", ""),
                    entry.get("display_name", name),
                    entry.get("description", ""),
                    bool(entry.get("readonly_only", False)),
                    auth_type,
                    token_env,
                    entry.get("schema_url"),
                ],
            )
    except Exception as exc:
        logger.warning("registry_sync.upsert_service failed for '%s': %s", name, exc)


def delete_service(name: str) -> None:
    """Remove a service entry from api_registry.services."""
    try:
        with _open_main_db() as con:
            con.execute("DELETE FROM api_registry.services WHERE name = ?", [name])
    except Exception as exc:
        logger.warning("registry_sync.delete_service failed for '%s': %s", name, exc)


def bootstrap_from_yaml() -> dict:
    """Full sync: read services.yaml → upsert all entries → return summary."""
    services = _load_services_yaml()
    if not services:
        return {"status": "ok", "synced": 0, "skipped": 0, "message": "services.yaml empty or missing"}

    synced, errors = 0, []
    for name, entry in services.items():
        if not isinstance(entry, dict):
            continue
        try:
            upsert_service(name, entry)
            synced += 1
        except Exception as exc:
            errors.append(f"{name}: {exc}")

    result: dict = {"status": "ok", "synced": synced, "skipped": len(errors)}
    if errors:
        result["status"] = "partial"
        result["errors"] = errors
    return result
