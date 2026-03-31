"""Write OC-mapped records to netops.oc_outputs at sync time.

Public functions:

- ``write_oc_outputs``: Called once per (device, command) during sync.
  Uses its own DuckDB connection for thread safety (sync_tools uses ThreadPoolExecutor).
  Silently skips when no schema_catalog entry exists — never raises.

- ``export_oc_snapshot``: Reads oc_outputs for a set of devices and returns
  per-device OC dicts plus coverage_gaps from a LEFT JOIN with parsed_outputs.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import duckdb

from olav.core.normalization import (
    OC_MODULE_MAP,
    _build_nested,
    _deep_merge,
    _oc_module_for_path,
)

logger = logging.getLogger(__name__)

# Scalar values that are not meaningful network data (platform names, bare booleans)
_GARBAGE_VALUES: frozenset[str] = frozenset(
    {
        "cisco", "juniper", "arista", "nokia", "huawei",
        "cisco_ios", "cisco_nxos", "cisco_xr", "juniper_junos",
        "true", "false", "yes", "no", "none", "null", "n/a", "-",
    }
)


def _count_meaningful_leaves(data: Any) -> int:
    """Count scalar leaves that carry real network data.

    Skips: None, "", empty collections, known garbage values (platform names,
    bare boolean strings). Used as a quality gate before writing to oc_outputs.
    """
    if data is None or data == "":
        return 0
    if isinstance(data, (list, tuple)):
        return sum(_count_meaningful_leaves(item) for item in data)
    if isinstance(data, dict):
        return sum(_count_meaningful_leaves(v) for v in data.values())
    # Scalar leaf
    s = str(data).strip().lower()
    if s == "" or s in _GARBAGE_VALUES:
        return 0
    return 1


def _upsert_oc_row(
    con: duckdb.DuckDBPyConnection,
    device_name: str,
    snapshot_id: str,
    oc_module: str,
    oc_data: Any,
    command: str,
) -> None:
    """INSERT or deep-merge a single row in netops.oc_outputs."""
    from olav.core.normalization import _deep_merge  # noqa: PLC0415

    existing = con.execute(
        "SELECT oc_data::varchar FROM netops.oc_outputs "
        "WHERE device_name=? AND snapshot_id=? AND oc_module=?",
        [device_name, snapshot_id, oc_module],
    ).fetchone()

    if existing:
        merged = json.loads(existing[0])
        _deep_merge(merged, oc_data)
        con.execute(
            "UPDATE netops.oc_outputs SET oc_data=?, source_cmd=? "
            "WHERE device_name=? AND snapshot_id=? AND oc_module=?",
            [json.dumps(merged), command, device_name, snapshot_id, oc_module],
        )
    else:
        con.execute(
            """
            INSERT INTO netops.oc_outputs
                (device_name, snapshot_id, oc_module, oc_data, source_cmd)
            VALUES (?, ?, ?, ?, ?)
            """,
            [device_name, snapshot_id, oc_module, json.dumps(oc_data), command],
        )


def write_oc_outputs(
    db_path: str,
    device_name: str,
    snapshot_id: str,
    raw_records: list[dict[str, Any]],
    command: str,
    oc_catalog_cache: dict[str, dict[str, str]],
    min_leaves: int = 3,
    platform: str = "",
    oc_transform_cache: dict[tuple[str, str], str] | dict[str, str] | None = None,
    skip_modules: set[str] | None = None,
) -> None:
    """Write OC-mapped JSON for one (device, command) pair to netops.oc_outputs.

    Args:
        db_path:             Filesystem path to the DuckDB database.
        device_name:         Device hostname.
        snapshot_id:         Snapshot identifier (e.g. "2026-03-28").
        raw_records:         Flat TextFSM dicts for this command.
        command:             CLI command string.
        oc_catalog_cache:    Pre-loaded {command: {field: oc_path}}.
        min_leaves:          Quality gate — drop modules below this leaf count.
        platform:            Device platform string (e.g. "cisco_ios"). Used for
                             platform-specific transform lookup with fallback to generic.
        oc_transform_cache:  Optional transform cache. Supports two formats:
                             - {(command, platform): code} — platform-aware (preferred)
                             - {command: code} — legacy/generic (backward-compatible)
                             When present, tried first; falls back to field-map on failure.
        skip_modules:        OC module names already covered by gNMI for this device.
                             These modules will not be overwritten (gNMI has higher priority,
                             but _upsert_oc_row handles priority logic — this is a fast path
                             to avoid the transform entirely for already-covered modules).
    """
    if not raw_records:
        return

    try:
        con = duckdb.connect(db_path)
        try:
            # --- Path 1: LLM-generated transform function ---
            # Resolve transform code: try (command, platform) first, then (command, "") generic
            _transform_code: str | None = None
            if oc_transform_cache:
                _transform_code = (
                    oc_transform_cache.get((command, platform or ""))  # type: ignore[call-overload]
                    or oc_transform_cache.get((command, ""))           # type: ignore[call-overload]
                    or oc_transform_cache.get(command)                  # type: ignore[arg-type]
                )
            if _transform_code:
                try:
                    from olav.core.oc_transform_runner import run_transform  # noqa: PLC0415
                    oc_data = run_transform(_transform_code, raw_records)
                    if _count_meaningful_leaves(oc_data) >= min_leaves:
                        # Split transform output by module: each top-level key may belong
                        # to a different OC module (e.g. a transform that emits both
                        # "interfaces" and "lldp").  Store each module separately so
                        # oc_outputs rows stay 1-module-per-row.
                        by_module: dict[str, dict] = {}
                        for top_key, subtree in oc_data.items():
                            mod = _oc_module_for_path(top_key)
                            if mod is None:
                                # Try hyphen-normalisation: "bgp_neighbors" → "bgp-neighbors"
                                mod = _oc_module_for_path(top_key.replace("_", "-"))
                            if mod is None:
                                # Last resort: scan command words against OC_MODULE_MAP keys
                                mod = next(
                                    (OC_MODULE_MAP[k] for k in OC_MODULE_MAP if k in command),
                                    "openconfig-unknown",
                                )
                            # Normalize key: strip "openconfig-*:" prefix if present
                            from olav.core.normalization import _strip_module_qualifier  # noqa: PLC0415
                            bare_key = _strip_module_qualifier(top_key)
                            if mod not in by_module:
                                by_module[mod] = {}
                            by_module[mod][bare_key] = subtree

                        for mod, mod_data in by_module.items():
                            if _count_meaningful_leaves(mod_data) >= min_leaves:
                                _upsert_oc_row(
                                    con, device_name, snapshot_id, mod, mod_data, command
                                )
                        return
                except Exception as exc:
                    logger.debug(
                        "transform path failed for device=%r command=%r, "
                        "falling back to field-map: %s",
                        device_name, command, exc,
                    )

            # --- Path 2: Field-map (schema_catalog) fallback ---
            field_map = oc_catalog_cache.get(command)
            if field_map is None:
                return

            module_data: dict[str, Any] = {}
            for record in raw_records:
                for field_name, value in record.items():
                    oc_path = field_map.get(field_name)
                    if oc_path is None:
                        continue
                    module = _oc_module_for_path(oc_path)
                    if module is None:
                        continue
                    segments = oc_path.split("/")
                    nested = _build_nested(segments, value)
                    if module not in module_data:
                        module_data[module] = nested
                    else:
                        _deep_merge(module_data[module], nested)

            if not module_data:
                return

            module_data = {
                mod: data
                for mod, data in module_data.items()
                if _count_meaningful_leaves(data) >= min_leaves
            }

            for oc_module, oc_data in module_data.items():
                _upsert_oc_row(con, device_name, snapshot_id, oc_module, oc_data, command)

        finally:
            con.close()
    except Exception:
        logger.warning(
            "write_oc_outputs failed for device=%r command=%r snapshot=%r",
            device_name,
            command,
            snapshot_id,
            exc_info=True,
        )


def export_oc_snapshot(
    conn,
    devices: list[str],
    snapshot_id: str | None = None,
) -> dict[str, Any]:
    """Read OC data from oc_outputs for the given devices.

    Args:
        conn:        An open DuckDB connection.
        devices:     List of device hostnames to export.
        snapshot_id: Snapshot to export. If None, uses the latest snapshot.

    Returns::

        {
          "r1": {
            "openconfig-interfaces": {...},
            "openconfig-bgp":        {...},
          },
          "coverage_gaps": [
            {"device": "r1", "commands_in_parsed": 8, "oc_modules": 3}
          ]
        }
    """
    if snapshot_id is None:
        row = conn.execute(
            "SELECT MAX(snapshot_id) FROM netops.oc_outputs"
        ).fetchone()
        snapshot_id = row[0] if row else None

    if snapshot_id is None:
        return {"coverage_gaps": []}

    # Fetch OC data per device per module
    placeholders = ", ".join("?" for _ in devices)
    rows = conn.execute(
        f"""
        SELECT device_name, oc_module, oc_data
        FROM netops.oc_outputs
        WHERE device_name IN ({placeholders})
          AND snapshot_id = ?
        """,
        [*devices, snapshot_id],
    ).fetchall()

    result: dict[str, Any] = {}
    for device_name, oc_module, oc_data in rows:
        if device_name not in result:
            result[device_name] = {}
        data = json.loads(oc_data) if isinstance(oc_data, str) else oc_data
        result[device_name][oc_module] = data

    # Coverage gaps: devices with parsed commands but no (or fewer) OC modules
    gap_rows = conn.execute(
        f"""
        SELECT
            p.device_name,
            COUNT(DISTINCT p.command)  AS commands_in_parsed,
            COUNT(DISTINCT o.oc_module) AS oc_modules
        FROM netops.parsed_outputs p
        LEFT JOIN netops.oc_outputs o
            ON p.device_name = o.device_name
           AND p.snapshot_id = o.snapshot_id
        WHERE p.device_name IN ({placeholders})
          AND p.snapshot_id = ?
        GROUP BY p.device_name
        HAVING COUNT(DISTINCT p.command) > COUNT(DISTINCT o.oc_module)
        """,
        [*devices, snapshot_id],
    ).fetchall()

    result["coverage_gaps"] = [
        {"device": row[0], "commands_in_parsed": row[1], "oc_modules": row[2]}
        for row in gap_rows
    ]

    return result
