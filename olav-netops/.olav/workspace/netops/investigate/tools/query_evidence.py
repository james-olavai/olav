"""query_evidence @tool — unified evidence drilldown.

R-VERTICAL-SLICE Step 1 (2026-05-09, dev_docs/74).

One @tool, three sources via Literal arg routing.  Designed for the
investigate sub-agent — narrow capability ("find recorded events /
outputs / config matching pattern P on device D"), single tool, no
selection ambiguity for small-model LLMs.

Sources:
* ``syslog``         — read syslog parquet partitions in
                       ``.olav/databases/logs/YYYY-MM-DD/syslog-HH.parquet``
* ``command_output`` — read ``netops.raw_output_store`` (per-snapshot
                       per-device CLI command stdout)
* ``config``         — read ``netops.raw_output_store`` filtered to
                       ``running-config`` / ``startup-config`` commands

Returns ``{matches: [...], total: N, truncated: bool, source: str}``.
Truncates results at 50 rows to bound LLM context cost.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import duckdb
from langchain_core.tools import tool

from olav.core.config import MAIN_DB_PATH


_LOG_GLOB = ".olav/databases/logs/*/syslog-*.parquet"


def _query_syslog(
    device: str | None,
    pattern: str,
    time_range: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Query the parquet-partitioned syslog store.

    Looks at parquet files relative to the cwd at .olav/databases/logs/.
    """
    log_path = Path.cwd() / _LOG_GLOB
    # DuckDB read_parquet with glob; if no files exist, returns empty
    where = ["message ILIKE ?"]
    params: list[Any] = [f"%{pattern}%"]
    if device:
        where.append("(host = ? OR host ILIKE ?)")
        params.extend([device, f"%{device}%"])
    if time_range:
        # accept "last_1h", "last_24h", "last_7d"
        if time_range.startswith("last_"):
            unit_part = time_range[5:]
            where.append(
                "CAST(timestamp AS TIMESTAMP) >= now() - INTERVAL "
                + repr(unit_part.replace("h", " hour").replace("d", " day"))
            )
    sql = f"""
        SELECT timestamp, host, severity, facility, message
        FROM read_parquet('{log_path}')
        WHERE {' AND '.join(where)}
        ORDER BY timestamp DESC
        LIMIT {limit}
    """
    with duckdb.connect(":memory:", read_only=False) as con:
        try:
            rows = con.execute(sql, params).fetchall()
        except Exception:
            return []
    return [
        {
            "timestamp": r[0],
            "host": r[1],
            "severity": r[2],
            "facility": r[3],
            "message": r[4],
        }
        for r in rows
    ]


def _query_command_output(
    device: str | None,
    pattern: str,
    snapshot: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Query netops.raw_output_store for command output containing pattern."""
    where = ["raw_output ILIKE ?"]
    params: list[Any] = [f"%{pattern}%"]
    if device:
        where.append("device_name ILIKE ?")
        params.append(f"%{device}%")
    if snapshot:
        where.append("snapshot_id = ?")
        params.append(snapshot)
    sql = f"""
        SELECT device_name, command, snapshot_id, updated_at,
               substring(raw_output, 1, 500) AS excerpt
        FROM netops.raw_output_store
        WHERE {' AND '.join(where)}
        ORDER BY updated_at DESC
        LIMIT {limit}
    """
    with duckdb.connect(str(MAIN_DB_PATH), read_only=True) as con:
        try:
            rows = con.execute(sql, params).fetchall()
        except Exception:
            return []
    return [
        {
            "device": r[0],
            "command": r[1],
            "snapshot_id": r[2],
            "captured_at": r[3],
            "excerpt": r[4],
        }
        for r in rows
    ]


def _query_config(
    device: str | None,
    pattern: str,
    snapshot: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Query running-config / startup-config text for pattern."""
    where = [
        "(command ILIKE '%running-config%' OR command ILIKE '%startup-config%')",
        "raw_output ILIKE ?",
    ]
    params: list[Any] = [f"%{pattern}%"]
    if device:
        where.append("device_name ILIKE ?")
        params.append(f"%{device}%")
    if snapshot:
        where.append("snapshot_id = ?")
        params.append(snapshot)
    sql = f"""
        SELECT device_name, command, snapshot_id, updated_at,
               substring(raw_output, 1, 800) AS excerpt
        FROM netops.raw_output_store
        WHERE {' AND '.join(where)}
        ORDER BY updated_at DESC
        LIMIT {limit}
    """
    with duckdb.connect(str(MAIN_DB_PATH), read_only=True) as con:
        try:
            rows = con.execute(sql, params).fetchall()
        except Exception:
            return []
    return [
        {
            "device": r[0],
            "command": r[1],
            "snapshot_id": r[2],
            "captured_at": r[3],
            "excerpt": r[4],
        }
        for r in rows
    ]


@tool
def query_evidence(
    source: Literal["syslog", "command_output", "config"],
    pattern: str,
    device: str | None = None,
    time_range: str | None = None,
    snapshot: str | None = None,
) -> dict[str, Any]:
    """
    Drill into recorded evidence for fault analysis.

    One unified evidence query — picks the data source via ``source``.
    Use this when user asks "why" / "show me logs" / "what does R3's
    config say about X" / "what error did we see" — anything where
    LLM needs to look at *recorded text* rather than structured graph
    state.

    Args:
        source: Which evidence store to query.
            * ``"syslog"``         — historical syslog (parquet)
            * ``"command_output"`` — captured CLI stdout
            * ``"config"``         — running-config / startup-config text
        pattern: Required. Substring to match (case-insensitive).
            E.g. ``"BGP"``, ``"OSPF dead"``, ``"NATIVE_VLAN_MISMATCH"``.
        device: Optional hostname filter.  Substring match.
        time_range: Optional, only for ``source=syslog``.
            Form: ``"last_1h"`` / ``"last_24h"`` / ``"last_7d"``.
        snapshot: Optional, only for ``source=command_output|config``.
            Snapshot_id to scope results.

    Returns:
        ``{
            "source": str,
            "matches": [...],   # up to 50 rows
            "total": int,
            "truncated": bool,
        }``

    Example:
        >>> query_evidence(source="syslog", pattern="BGP", device="R3",
        ...                time_range="last_24h")
        {"source": "syslog", "matches": [
            {"timestamp": "...", "host": "R3", "severity": "ERROR",
             "facility": "local7", "message": "BGP-3-NOTIFICATION ..."},
            ...], "total": 12, "truncated": False}
    """
    LIMIT = 50
    if source == "syslog":
        rows = _query_syslog(device, pattern, time_range, LIMIT)
    elif source == "command_output":
        rows = _query_command_output(device, pattern, snapshot, LIMIT)
    elif source == "config":
        rows = _query_config(device, pattern, snapshot, LIMIT)
    else:
        return {
            "source": source,
            "matches": [],
            "total": 0,
            "truncated": False,
            "error": f"unknown source: {source}",
        }
    return {
        "source": source,
        "matches": rows,
        "total": len(rows),
        "truncated": len(rows) >= LIMIT,
    }
