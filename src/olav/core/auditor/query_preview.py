"""Trial-run an audit Profile Job query and preview results.

The auditor agent uses this to validate SQL / LanceDB queries before
committing them to a Profile. Always uses parameterized binding —
never interpolates the window value into the SQL string. Per
ADR-0007 + ADR-0008, called from auditor skill scripts.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_PREVIEW_LIMIT = 10


def preview_map_query(
    job_type: str,
    query: str,
    params: dict | None = None,
    threshold: float | None = None,
    db_path: str | None = None,
) -> list[dict]:
    """Execute a trial query and return up to 10 rows as a list of dicts.

    Args:
        job_type:  "sql" or "lancedb"
        query:     SQL query (with :window placeholder) OR semantic search string.
        params:    For SQL: dict of named parameters, e.g. {"window": "1h"}.
                   Window is always bound via DuckDB parameterization — never
                   string-interpolated.
        threshold: For LanceDB: minimum similarity score (0-1).
        db_path:   Path to DuckDB file. Defaults to OLAV MAIN_DB_PATH.

    Returns:
        List of dicts (at most 10 rows).
    """
    job_type = job_type.lower().strip()
    if job_type not in ("sql", "lancedb"):
        raise ValueError(f"Unsupported job_type: {job_type!r}. Use 'sql' or 'lancedb'.")
    try:
        if job_type == "sql":
            return _preview_sql(query, params or {}, db_path)
        else:
            return _preview_lancedb(query, threshold or 0.8)
    except Exception as exc:
        # Return error as structured result so the LLM can see it and retry
        return [{"error": str(exc), "hint": "Fix the query and call preview_map_query again"}]


def _preview_sql(query: str, params: dict, db_path: str | None) -> list[dict]:
    import re
    import duckdb

    if db_path is None:
        try:
            from olav.core.config import MAIN_DB_PATH
            db_path = str(MAIN_DB_PATH)
        except ImportError:
            raise ValueError("db_path required when OLAV config is unavailable")

    # DuckDB cannot bind INTERVAL values as parameters.
    # Strategy: detect any :window / $window placeholder (LLM may write either),
    # convert to absolute cutoff datetime, bind as $cutoff.
    # Falls back to "1h" if params["window"] is absent but placeholder is present.
    duckdb_query = query
    bound_params: dict = {}

    # Detect window placeholder regardless of whether params carries it
    has_window_placeholder = bool(
        re.search(r"INTERVAL\s+[':$]?window\b", duckdb_query, re.IGNORECASE)
        or re.search(r"[:\$]window\b", duckdb_query, re.IGNORECASE)
    )
    window = params.get("window") or ("1h" if has_window_placeholder else None)

    if window:
        cutoff = _compute_cutoff(str(window))
        # Replace all forms: INTERVAL :window, INTERVAL $window, :window, $window
        duckdb_query = re.sub(
            r"NOW\(\)\s*-\s*INTERVAL\s*['\"]?[:\$]?window['\"]?",
            "$cutoff",
            duckdb_query,
            flags=re.IGNORECASE,
        )
        duckdb_query = re.sub(r"[:\$]window\b", "$cutoff", duckdb_query, flags=re.IGNORECASE)
        bound_params["cutoff"] = cutoff
    else:
        # No window param — normalise :name → $name for DuckDB named params
        duckdb_query = re.sub(r":(\w+)", r"$\1", duckdb_query)
        bound_params = {k: v for k, v in params.items()}

    # Wrap in CTE to apply LIMIT — integer literal, NOT a user-supplied value
    preview_query = (
        f"SELECT * FROM ({duckdb_query.rstrip().rstrip(';')}) __preview "
        f"LIMIT {_PREVIEW_LIMIT}"
    )

    with duckdb.connect(str(db_path), read_only=True) as conn:
        # bound_params contains only safe Python values — no SQL concatenation
        result = conn.execute(preview_query, bound_params)
        columns = [desc[0] for desc in result.description]
        rows = result.fetchall()

    return [dict(zip(columns, row)) for row in rows]


def _compute_cutoff(window: str):
    """Convert window string to an absolute UTC cutoff datetime."""
    from datetime import datetime, timedelta, timezone
    w = window.strip().lower()
    if w.endswith("h"):
        delta = timedelta(hours=float(w[:-1]))
    elif w.endswith("m"):
        delta = timedelta(minutes=float(w[:-1]))
    elif w.endswith("d"):
        delta = timedelta(days=float(w[:-1]))
    else:
        delta = timedelta(hours=1)
    return datetime.now(tz=timezone.utc) - delta


def _preview_lancedb(semantic_query: str, threshold: float) -> list[dict]:
    try:
        import lancedb  # type: ignore
    except ImportError:
        logger.warning("lancedb not installed")
        return []

    try:
        from olav.core.config import get_paths_config
        lancedb_path = str(get_paths_config().knowledge_db_dir)
    except Exception:
        logger.warning("Cannot resolve LanceDB path")
        return []

    try:
        db = lancedb.connect(lancedb_path)
        table = db.open_table("syslog_vectors")
        results = (
            table.search(semantic_query)
            .metric("cosine")
            .limit(_PREVIEW_LIMIT * 2)
            .to_pandas()
        )
        if "_distance" in results.columns:
            results = results[1 - results["_distance"] >= threshold]
        return results.head(_PREVIEW_LIMIT).to_dict(orient="records")
    except Exception as exc:
        logger.warning("LanceDB preview failed: %s", exc)
        return []


