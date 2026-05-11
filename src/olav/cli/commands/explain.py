"""``olav explain`` — resolve a citation token back to its DuckDB source row.

ARCH-11 last mile. When an audit report renders a finding it attaches a
``[src: <table>[#<snapshot>][; device=<name>][; row=<n>]]`` tag (see
``.olav/workspace/audit/auditor/tools/render_report.py::_format_source_suffix``).
Round 44 added :func:`render_report.parse_src_token` — the parser side.
Round 45 adds this CLI: paste a token, see the underlying row(s) without
writing SQL yourself.

Usage::

    olav explain "[src: netops.parsed_outputs#snap_20260418_0201; device=R1; row=4]"
    olav explain --no-color "[src: netops.devices; device=R2]"

Exit codes:
  0 — rows printed (or 0 rows matched, reported as an info line)
  1 — token unparseable / table unresolvable
  2 — query execution failed
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


# ── Token parser (delegates to the audit workspace helper) ──────────────


def _load_parse_src_token():
    """Locate ``parse_src_token`` in the workspace-vendored auditor tools.

    The function lives in
    ``.olav/workspace/audit/auditor/tools/render_report.py`` (which is not
    part of the ``olav`` package path). Loading via ``importlib`` matches
    the approach other workspace-consumers use in tests.
    """
    import importlib.util

    from olav.core.config import get_paths_config

    try:
        repo_root = Path(get_paths_config().workspace_root).resolve().parents[0]
    except Exception:
        repo_root = Path.cwd()

    # rev 259 Run/Author split: render_report.py moved auditor/ → runner/.
    # Probe both locations for backwards compatibility.
    _LAYOUTS = (
        (".olav", "workspace", "audit", "runner", "tools", "render_report.py"),
        (".olav", "workspace", "audit", "auditor", "tools", "render_report.py"),
    )
    candidate = None
    for layout in _LAYOUTS:
        c = repo_root.joinpath(*layout)
        if c.exists():
            candidate = c
            break
    if candidate is None:
        # Fallback: walk up from this file until we find .olav/workspace.
        here = Path(__file__).resolve()
        for anc in here.parents:
            for layout in _LAYOUTS:
                alt = anc.joinpath(*layout)
                if alt.exists():
                    candidate = alt
                    break
            if candidate is not None:
                break
    if candidate is None:
        # Neither new nor legacy layout found anywhere — bail out.
        return None
    spec = importlib.util.spec_from_file_location(
        "_olav_explain_render_report", candidate
    )
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    except Exception:
        return None
    return getattr(mod, "parse_src_token", None)


# ── Table resolution (mirrors describe_table's name-resolution) ─────────


def _resolve_table_name(conn, table_name: str) -> str | None:
    """Return the schema-qualified name DuckDB accepts, or None if missing.

    Attempts ``table_name`` as-is, then ``netops.<name>``, then
    ``main.<name>``. Mirrors ``describe_table._resolve_table_name`` so
    callers can paste either form.
    """
    candidates = [table_name]
    if "." not in table_name:
        candidates.extend([f"netops.{table_name}", f"main.{table_name}"])
    for cand in candidates:
        try:
            conn.execute(f"SELECT 1 FROM {cand} LIMIT 0")
            return cand
        except Exception:
            continue
    return None


# ── Query building ──────────────────────────────────────────────────────


def _fetch_source_rows(
    src: dict[str, Any],
    limit: int = 3,
) -> tuple[str, list[dict[str, Any]]] | tuple[None, str]:
    """Fetch up to ``limit`` rows matching the source token.

    Returns either ``(qualified_table, rows)`` on success, or
    ``(None, error_message)`` on failure.

    Filter strategy (best-effort, narrowest to broadest):
      * ``snapshot_id`` + ``device`` → strong filter
      * ``snapshot_id`` only         → one snapshot's rows for this table
      * ``device`` only              → most-recent rows for this device
      * neither                      → ``LIMIT 1`` from the table
    """
    try:
        import duckdb
        from olav.core.config import MAIN_DB_PATH
    except Exception as exc:
        return None, f"bootstrap failed: {exc}"

    if not src.get("table"):
        return None, "token missing table name"

    try:
        conn = duckdb.connect(str(MAIN_DB_PATH), read_only=True)
    except Exception as exc:
        return None, f"cannot open DuckDB: {exc}"

    try:
        qualified = _resolve_table_name(conn, str(src["table"]))
        if qualified is None:
            return None, f"table not found: {src['table']!r}"

        where: list[str] = []
        params: list[Any] = []
        snap = src.get("snapshot_id")
        device = src.get("device")
        # Only push down filters for tables we know carry these columns.
        # For arbitrary views we fall through to an unfiltered LIMIT so the
        # operator still sees schema + sample rather than an empty result.
        cols = _describe_columns(conn, qualified)
        if snap and "snapshot_id" in cols:
            where.append("snapshot_id = ?")
            params.append(snap)
        if device and "device_name" in cols:
            where.append("device_name = ?")
            params.append(device)
        elif device and "host" in cols:
            where.append("host = ?")
            params.append(device)

        sql = f"SELECT * FROM {qualified}"
        if where:
            sql += " WHERE " + " AND ".join(where)
        if "created_at" in cols:
            sql += " ORDER BY created_at DESC"
        sql += f" LIMIT {int(limit)}"

        try:
            cur = conn.execute(sql, params)
            col_names = [d[0] for d in cur.description] if cur.description else []
            rows = [
                dict(zip(col_names, r, strict=False)) for r in cur.fetchall()
            ]
        except Exception as exc:
            return None, f"query failed: {exc}"

        # row_index is a position within findings, not SQL offset — but if
        # the caller supplied it, the first result is usually "close enough"
        # for a human verify step.
        row_index = src.get("row_index")
        if isinstance(row_index, int) and 0 <= row_index < len(rows):
            rows = [rows[row_index]]

        return qualified, rows
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _describe_columns(conn, qualified: str) -> set[str]:
    try:
        cur = conn.execute(f"DESCRIBE {qualified}")
        out: set[str] = set()
        for row in cur.fetchall():
            # row layout: (column_name, column_type, null, key, default, extra)
            if row and row[0]:
                out.add(str(row[0]))
        return out
    except Exception:
        return set()


# ── Formatting ──────────────────────────────────────────────────────────


def _format_row(row: dict[str, Any], max_field_chars: int = 400) -> str:
    lines: list[str] = []
    for k, v in row.items():
        if isinstance(v, (dict, list)):
            s = json.dumps(v, ensure_ascii=False, default=str)
        else:
            s = str(v) if v is not None else "NULL"
        if len(s) > max_field_chars:
            s = s[:max_field_chars] + "…"
        lines.append(f"  {k}: {s}")
    return "\n".join(lines)


# ── Public entry points ─────────────────────────────────────────────────


def build_explain_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Register ``olav explain`` on the root CLI's subparser collection."""
    p = subparsers.add_parser(
        "explain",
        help="Resolve an audit-report [src: ...] citation token to its raw DuckDB row(s)",
        description=(
            "Resolve an audit-report citation token (e.g. "
            "'[src: netops.parsed_outputs#snap_20260418; device=R1; row=4]') "
            "to the underlying DuckDB row so you can verify a finding without "
            "writing SQL. Read-only."
        ),
    )
    p.add_argument(
        "token",
        help="The [src: ...] token to resolve (quote it; it contains spaces/brackets).",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=3,
        help="Max rows to print when the token's filters are ambiguous (default 3).",
    )
    return p


def handle_explain_command(args) -> int:
    """Dispatch ``olav explain`` — parse the token, fetch rows, print them."""
    token = getattr(args, "token", None) or ""
    parse_src_token = _load_parse_src_token()
    if parse_src_token is None:
        print(
            "error: could not load render_report.parse_src_token — run "
            "from the repo root or ensure `.olav/workspace/audit/auditor/"
            "tools/render_report.py` exists.",
            file=sys.stderr,
        )
        return 1

    src = parse_src_token(token)
    if not src:
        print(
            f"error: no [src: ...] token recognised in: {token!r}",
            file=sys.stderr,
        )
        return 1

    limit = max(1, int(getattr(args, "limit", 3) or 3))
    result = _fetch_source_rows(src, limit=limit)
    if result[0] is None:
        print(f"error: {result[1]}", file=sys.stderr)
        return 2

    qualified, rows = result
    print(f"Token     : {token}")
    print(f"Resolved  : table={qualified}")
    for k in ("snapshot_id", "device", "row_index"):
        if k in src:
            print(f"          : {k}={src[k]}")
    print()
    if not rows:
        print("(no rows matched)")
        return 0
    for i, row in enumerate(rows, start=1):
        print(f"Row #{i}")
        print(_format_row(row))
        print()
    return 0
