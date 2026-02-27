"""sync_inventory — Sync device inventory from Nornir hosts.yaml into DuckDB.

olav-config is the infrastructure layer.  Device inventory management lives
here.  olav-audit and olav-ops read the devices table but never write to it.

Single source of truth for device inventory:
  .olav/config/nornir/hosts.yaml  →  DuckDB: devices table
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


def _find_project_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


PROJECT_ROOT = _find_project_root()
_DEFAULT_HOSTS_YAML = (
    PROJECT_ROOT / ".olav" / "config" / "nornir" / "hosts.yaml"
)


# ---------------------------------------------------------------------------
# Private helper — inlined from src/olav/core/devices_import.py
# ---------------------------------------------------------------------------

def _import_devices_from_nornir(
    hosts_yaml_path: Path,
    db_path: Path,
    table_name: str = "devices",
) -> dict[str, Any]:
    """Import devices from Nornir hosts.yaml into DuckDB devices table."""
    import yaml  # noqa: PLC0415

    from olav.core.database import get_database  # noqa: PLC0415

    stats: dict[str, Any] = {
        "imported": 0,
        "roles_found": set(),
        "sites_found": set(),
        "errors": 0,
    }

    if not hosts_yaml_path.exists():
        logger.warning(f"hosts.yaml not found at {hosts_yaml_path}")
        return stats

    try:
        with open(hosts_yaml_path, encoding="utf-8") as fh:
            hosts: dict[str, Any] = yaml.safe_load(fh) or {}
    except Exception as exc:
        logger.warning(f"Failed to parse hosts.yaml: {exc}")
        return stats

    db = get_database()

    for device_name, host_data in hosts.items():
        if not isinstance(host_data, dict):
            continue
        data: dict[str, Any] = host_data.get("data", {}) or {}
        role = data.get("role") or data.get("device_role") or ""
        site = data.get("site") or data.get("site_id") or ""
        platform = host_data.get("platform") or data.get("platform") or ""
        hostname = host_data.get("hostname") or device_name
        mgmt_ip = hostname

        if role:
            stats["roles_found"].add(role)
        if site:
            stats["sites_found"].add(site)

        try:
            db.conn.execute(
                f"""
                INSERT INTO {table_name}
                    (device_id, name, hostname, platform, mgmt_ip, device_role, site)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (device_id) DO UPDATE SET
                    hostname    = excluded.hostname,
                    platform    = excluded.platform,
                    mgmt_ip     = excluded.mgmt_ip,
                    device_role = excluded.device_role,
                    site        = excluded.site,
                    updated_at  = now()
                """,
                [device_name, device_name, hostname, platform, mgmt_ip, role, site],
            )
            stats["imported"] += 1
        except Exception as exc:
            logger.debug(f"Failed to upsert device {device_name}: {exc}")
            stats["errors"] += 1

    db.conn.commit()
    stats["roles_found"] = len(stats["roles_found"])
    stats["sites_found"] = len(stats["sites_found"])
    logger.info(
        "_import_devices_from_nornir: %d devices imported (%d errors)",
        stats["imported"],
        stats["errors"],
    )
    return stats


@tool
def sync_inventory(hosts_yaml: str | None = None) -> dict[str, Any]:
    """Sync device inventory from Nornir hosts.yaml into DuckDB devices table.

    Reads device definitions from hosts.yaml and upserts them into the
    DuckDB `devices` table.  Uses ON CONFLICT DO UPDATE so existing rows
    are refreshed rather than duplicated.

    Call this:
      - On first OLAV setup (after init_db)
      - After adding or removing devices from hosts.yaml
      - Before take_snapshot() to ensure the device list is current

    Args:
        hosts_yaml: Optional path to hosts.yaml.  Defaults to
                    .olav/config/nornir/hosts.yaml.

    Returns:
        {
            "status":      "success" | "error",
            "imported":    int,   # rows upserted
            "roles_found": int,
            "sites_found": int,
            "errors":      int,
            "source":      str,   # path used
        }
    """
    hosts_path = Path(hosts_yaml) if hosts_yaml else _DEFAULT_HOSTS_YAML

    if not hosts_path.exists():
        msg = f"hosts.yaml not found at {hosts_path}"
        logger.warning(msg)
        return {"status": "error", "message": msg, "imported": 0}

    try:
        from olav.core.config import NETWORK_DB_PATH as _db_path  # noqa: PLC0415
    except ImportError:
        _db_path = PROJECT_ROOT / ".olav" / "databases" / "main.duckdb"

    stats = _import_devices_from_nornir(
        hosts_yaml_path=hosts_path,
        db_path=_db_path,
    )

    result = {
        "status": "success",
        "imported": stats.get("imported", 0),
        "roles_found": stats.get("roles_found", 0),
        "sites_found": stats.get("sites_found", 0),
        "errors": stats.get("errors", 0),
        "source": str(hosts_path),
    }

    logger.info(
        f"sync_inventory: {result['imported']} devices from {hosts_path} "
        f"({result['errors']} errors)"
    )
    return result
