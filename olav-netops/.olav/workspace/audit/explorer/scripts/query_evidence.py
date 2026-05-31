#!/usr/bin/env python3
"""query_evidence script — unified evidence drilldown.

R-VERTICAL-SLICE Step 1 (2026-05-09, dev_docs/74).

One function, three sources via Literal arg routing.  Designed for the
investigate sub-agent — narrow capability ("find recorded events /
outputs / config matching pattern P on device D"), single function, no
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

import sys
from pathlib import Path
from typing import Any, Literal

import duckdb


def _find_project_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


_PROJECT_ROOT = _find_project_root()
if str(_PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from olav.core.config import MAIN_DB_PATH


_LOG_GLOB = ".olav/databases/logs/*/syslog-*.parquet"

# Aggregate char budget per call — prevents a broad pattern (no device filter)
# from dumping 50 × 1200-char excerpts (~60 K chars) into context.  Forces the
# agent to be specific: add device= or narrow the pattern to get more rows.
_MAX_RESULT_CHARS = 12_000  # ≈ 3 K tokens; fits ~10 good excerpts comfortably


def _trim_to_char_budget(rows: list[dict], max_chars: int) -> list[dict]:
    """Keep rows until cumulative serialized size exceeds max_chars."""
    total = 0
    kept = []
    for row in rows:
        size = sum(len(str(v)) for v in row.values())
        if kept and total + size > max_chars:
            break
        kept.append(row)
        total += size
    return kept


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


def _context_excerpt_expr(pattern_placeholder: str = "?") -> str:
    """DuckDB SQL expression: extract ~1200 chars centred on the first match.

    Falls back to the first 800 chars if strpos returns 0 (shouldn't
    happen because the WHERE clause already filters with ILIKE, but keeps
    the query safe against edge cases).

    The caller must supply two positional ``?`` params for the two
    occurrences of ``pattern_placeholder`` in the CASE expression
    (both bound to the bare pattern string, no % wildcards).
    """
    return f"""
        CASE
          WHEN strpos(lower(raw_output), lower({pattern_placeholder})) > 0
          THEN substring(
                 raw_output,
                 GREATEST(1, strpos(lower(raw_output), lower({pattern_placeholder})) - 200),
                 1200
               )
          ELSE substring(raw_output, 1, 800)
        END
    """.strip()


def _query_command_output(
    device: str | None,
    pattern: str,
    snapshot: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Query netops.raw_output_store for command output containing pattern."""
    where = ["raw_output ILIKE ?"]
    # WHERE params (% wildcards for ILIKE)
    where_params: list[Any] = [f"%{pattern}%"]
    if device:
        where.append("device_name ILIKE ?")
        where_params.append(f"%{device}%")
    if snapshot:
        where.append("snapshot_id = ?")
        where_params.append(snapshot)
    # CASE expr uses pattern twice (bare, no wildcards) — must come first
    excerpt_expr = _context_excerpt_expr()
    sql = f"""
        SELECT device_name, command, snapshot_id, updated_at,
               {excerpt_expr} AS excerpt
        FROM netops.raw_output_store
        WHERE {' AND '.join(where)}
        ORDER BY updated_at DESC
        LIMIT {limit}
    """
    params = [pattern, pattern] + where_params
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
    # WHERE params
    where_params: list[Any] = [f"%{pattern}%"]
    if device:
        where.append("device_name ILIKE ?")
        where_params.append(f"%{device}%")
    if snapshot:
        where.append("snapshot_id = ?")
        where_params.append(snapshot)
    # CASE expr uses pattern twice (bare) — must come first in params
    excerpt_expr = _context_excerpt_expr()
    sql = f"""
        SELECT device_name, command, snapshot_id, updated_at,
               {excerpt_expr} AS excerpt
        FROM netops.raw_output_store
        WHERE {' AND '.join(where)}
        ORDER BY updated_at DESC
        LIMIT {limit}
    """
    params = [pattern, pattern] + where_params
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


def query_evidence(
    source: str,
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
    """
    LIMIT = 50
    # Reject empty / whitespace pattern up front — would dump the
    # entire syslog parquet (~14k rows) or full command output table
    # without bound, busting the LLM's context.
    if not pattern or not pattern.strip():
        return {
            "status": "error",
            "error_kind": "invalid_pattern",
            "message": (
                "pattern must be a non-empty substring.  Use a real "
                "filter like 'BGP' / 'OSPF dead' / 'NATIVE_VLAN' — "
                "an empty pattern would return tens of thousands of "
                "rows."
            ),
            "source": source,
        }

    if source == "syslog":
        rows = _query_syslog(device, pattern, time_range, LIMIT)
    elif source == "command_output":
        rows = _query_command_output(device, pattern, snapshot, LIMIT)
    elif source == "config":
        rows = _query_config(device, pattern, snapshot, LIMIT)
    else:
        return {
            "status": "error",
            "error_kind": "unknown_source",
            "message": f"unknown source {source!r}; pick from "
                       f"syslog / command_output / config",
            "source": source,
        }
    raw_count = len(rows)
    rows = _trim_to_char_budget(rows, _MAX_RESULT_CHARS)
    result = {
        "status": "success",
        "source": source,
        "matches": rows,
        "total": len(rows),
        "truncated": raw_count > len(rows) or raw_count >= LIMIT,
    }
    if not rows:
        # Empty results trigger pattern-variation rambling on small
        # models — boundary test 2 saw 16 query_evidence calls trying
        # synonyms.  Steer the LLM away from that loop.
        result["hint"] = (
            "Empty result. DO NOT try synonyms or near-variants of "
            "this pattern (e.g. don't go 'BGP' → 'bgp' → 'b.g.p' → "
            "'border gateway' → 'denied' → 'filter' → ...).  Either "
            "the data genuinely doesn't contain it, or the right "
            "pattern is in a DIFFERENT source (try source=command_output "
            "or source=config), or this device wasn't probed for "
            "this command.  After 2 empty calls accept the null "
            "result and move on; cite 'no recorded evidence' to the "
            "user — that's a real answer, not a problem to keep "
            "drilling on."
        )
    return result


if __name__ == "__main__":
    import json, sys
    _args = json.loads(sys.stdin.read() or "{}")
    result = query_evidence(**_args)
    print(json.dumps(result, default=str))
