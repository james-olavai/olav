"""sync_inventory — Sync device inventory from Nornir into DuckDB.

olav-config is the infrastructure layer.  Device inventory management lives
here.  olav-audit and olav-ops read the devices table but never write to it.

Design: Source-Agnostic via Nornir
  Nornir abstracts the backend (SimpleInventory / NetBox / Ansible / etc.).
  We call InitNornir() and read nr.inventory.hosts — never yaml.safe_load().
  Changing the backend only requires updating nornir/config.yaml; no code change.

  Nornir → nr.inventory.hosts  →  DuckDB: devices table
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


def _find_project_root() -> Path:
    p = Path(__file__).resolve().parent
    found = None
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            found = p
        p = p.parent
    return found or Path.cwd()


PROJECT_ROOT = _find_project_root()

try:
    from olav.core.config import NORNIR_CONFIG_PATH as _NORNIR_CONFIG_PATH

    _DEFAULT_NORNIR_CONFIG = Path(_NORNIR_CONFIG_PATH)
except ImportError:
    _DEFAULT_NORNIR_CONFIG = PROJECT_ROOT / ".olav" / "config" / "nornir" / "config.yaml"


# ---------------------------------------------------------------------------
# Private helper — Nornir-native inventory reader
# ---------------------------------------------------------------------------

def _import_devices_from_nornir(
    nornir_config_path: Path,
    db_path: Path,
    table_name: str = "netops.devices",
) -> dict[str, Any]:
    """Import devices via Nornir inventory API into DuckDB devices table.

    Uses InitNornir() so the backend (SimpleInventory / NetBox / Ansible)
    is transparent.  nr.inventory.hosts provides a unified host object
    regardless of the underlying data source.
    """
    from nornir import InitNornir  # noqa: PLC0415

    from olav.core.database import get_database  # noqa: PLC0415

    stats: dict[str, Any] = {
        "imported": 0,
        "roles_found": set(),
        "sites_found": set(),
        "errors": 0,
    }

    if not nornir_config_path.exists():
        logger.warning(f"nornir config not found at {nornir_config_path}")
        return stats

    config_root = nornir_config_path.resolve().parent
    while config_root != config_root.parent:
        if (config_root / "pyproject.toml").exists():
            break
        config_root = config_root.parent

    try:
        # Nornir config.yaml may contain relative paths — resolve from project root
        _orig_cwd = os.getcwd()
        os.chdir(config_root)
        nr = InitNornir(config_file=str(nornir_config_path))
        os.chdir(_orig_cwd)
    except Exception as exc:
        logger.warning(f"InitNornir failed: {exc}")
        os.chdir(_orig_cwd)  # type: ignore[possibly-undefined]
        return stats

    db = get_database()

    for device_name, host in nr.inventory.hosts.items():
        # Nornir host objects expose .hostname, .platform, .data, .groups
        # regardless of backend — this is the source-agnostic contract.
        role = host.data.get("role") or host.data.get("device_role") or ""
        site = host.data.get("site") or host.data.get("site_id") or ""
        platform = host.platform or host.data.get("platform") or ""
        hostname = host.hostname or device_name
        mgmt_ip = hostname
        groups = ",".join(str(g) for g in host.groups) if host.groups else ""

        if role:
            stats["roles_found"].add(role)
        if site:
            stats["sites_found"].add(site)

        if groups:
            logger.debug(f"{device_name}: groups={groups}")

        try:
            db.conn.execute(
                f"""
                UPDATE {table_name}
                SET
                    name = ?,
                    hostname = ?,
                    platform = ?,
                    mgmt_ip = ?,
                    device_role = ?,
                    site = ?,
                    updated_at = now()
                WHERE device_id = ?
                """,
                [device_name, hostname, platform, mgmt_ip, role, site, device_name],
            )

            existing = db.conn.execute(
                f"SELECT COUNT(*) FROM {table_name} WHERE device_id = ?",
                [device_name],
            ).fetchone()
            if not existing or existing[0] == 0:
                db.conn.execute(
                    f"""
                    INSERT INTO {table_name}
                        (device_id, name, hostname, platform, mgmt_ip, device_role, site, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, now(), now())
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
def sync_inventory(nornir_config: str | None = None) -> dict[str, Any]:
    """Sync device inventory from Nornir into DuckDB devices table.

    Source-agnostic: uses InitNornir() so the backend (SimpleInventory,
    NetBox, Ansible, etc.) is transparent. Writes into DuckDB `netops.devices`
    and the `main.devices` compatibility view reflects the result.

    Call this:
      - On first OLAV setup (after init_db)
      - After adding or removing devices in any Nornir backend
      - Before take_snapshot() to ensure the device list is current

    Args:
        nornir_config: Optional path to nornir config.yaml.  Defaults to
                       .olav/config/nornir/config.yaml.

    Returns:
        {
            "status":      "success" | "error",
            "imported":    int,   # rows upserted
            "roles_found": int,
            "sites_found": int,
            "errors":      int,
            "source":      str,   # nornir config path used
        }
    """
    config_path = Path(nornir_config) if nornir_config else _DEFAULT_NORNIR_CONFIG

    if not config_path.exists():
        msg = f"nornir config.yaml not found at {config_path}"
        logger.warning(msg)
        return {"status": "error", "message": msg, "imported": 0}

    try:
        from olav.core.config import NETWORK_DB_PATH as _db_path  # noqa: PLC0415, N811
    except ImportError:
        _db_path = PROJECT_ROOT / ".olav" / "databases" / "main.duckdb"

    stats = _import_devices_from_nornir(
        nornir_config_path=config_path,
        db_path=_db_path,
    )

    result = {
        "status": "success",
        "imported": stats.get("imported", 0),
        "roles_found": stats.get("roles_found", 0),
        "sites_found": stats.get("sites_found", 0),
        "errors": stats.get("errors", 0),
        "source": str(config_path),
    }

    logger.info(
        f"sync_inventory: {result['imported']} devices via {config_path} "
        f"({result['errors']} errors)"
    )
    return result
