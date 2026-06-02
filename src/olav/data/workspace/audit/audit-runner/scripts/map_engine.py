"""map_engine.py — Phase 1: Parameterized Queries → Segmented JSON + Staging.

OLAV Audit subsystem, v4.0 architecture.

Execution contract:
  - Reads a Profile .md file (YAML frontmatter + body) from profile_path
  - Executes each Job against DuckDB (SQL) or LanceDB (semantic)
  - Uses DuckDB named parameter binding — NO string interpolation of `window`
  - Outputs a segmented JSON file (one key per Job)
  - Optionally writes a .staging.json for IngestManager.bulk_load()

Returns: json_path (str) — absolute path to the segmented JSON output.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------


def _json_default(obj: Any) -> str:
    """Custom JSON serializer for objects not serializable by default (e.g. datetime)."""
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

_PROFILES_DIR = ".olav/workspace/audit/profiles"


def _sanitize_path(path_str: str) -> str:
    """Coerce LLM-supplied paths into the workspace-relative form.

    Handles four common LLM hallucinations:
      1. Leading ``/`` but absolute path doesn't exist on disk
         → strip the slash
      2. Bare name without directory or extension
         (``"bgp_health"``) → resolve under ``_PROFILES_DIR``
      3. Bare filename with extension (``"bgp_health.md"``)
         → resolve under ``_PROFILES_DIR``
      4. Path missing the ``.olav/`` prefix
         (``"workspace/audit/profiles/bgp_health.md"``)
         → prepend ``.olav/`` if that yields an existing file

    Returns the path as-is if nothing matches; ``_parse_profile_yaml``
    will then raise a clear FileNotFoundError with discovery hints.
    """
    if not path_str:
        return path_str
    # 1. Leading-slash that doesn't exist absolutely → strip it
    if path_str.startswith("/") and not Path(path_str).exists():
        path_str = path_str.lstrip("/")
    # 2/3. Bare name (no '/') → look up under _PROFILES_DIR
    p = Path(path_str)
    if not p.exists() and "/" not in path_str:
        for suffix in ("", ".md"):
            candidate = Path(_PROFILES_DIR) / (path_str + suffix)
            if candidate.exists():
                return str(candidate)
    # 4. Path missing `.olav/` prefix (e.g. "workspace/audit/profiles/...")
    #    or missing both `.olav/` AND `workspace/` (e.g. "audit/profiles/...")
    if not p.exists():
        for prefix in (".olav", ".olav/workspace"):
            candidate = Path(prefix) / path_str
            if candidate.exists():
                return str(candidate)
    return path_str


def _parse_profile_yaml(profile_path: str) -> dict:
    """Parse YAML frontmatter from a Profile .md file and return as dict."""
    import re

    import yaml  # type: ignore

    p = Path(_sanitize_path(profile_path))
    if not p.exists():
        # Try hyphen ↔ underscore normalization before giving up
        alt = p.parent / p.name.replace("-", "_")
        if alt != p and alt.exists():
            p = alt
        else:
            alt2 = p.parent / p.name.replace("_", "-")
            if alt2 != p and alt2.exists():
                p = alt2
    if not p.exists():
        profiles_dir = p.parent
        existing = sorted(profiles_dir.glob("*.md")) if profiles_dir.exists() else []
        hint = (
            f"Available profiles: {', '.join(x.stem for x in existing)}"
            if existing
            else "No profiles exist yet."
        )
        raise FileNotFoundError(
            f"Audit profile not found: '{p.name}'. {hint}\n"
            f"Create it first: olav --agent audit-auditor 'Create {p.stem} profile'"
        )
    content = p.read_text()
    match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not match:
        raise ValueError(f"No YAML frontmatter found in profile: {p}")
    return yaml.safe_load(match.group(1)) or {}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_map_engine(
    profile_path: str,
    time_window: str = "1h",
    db_path: str | None = None,
    output_dir: str = "exports/audit_reports",
    staging_dir: str | None = None,
) -> str:
    """Execute all Jobs in a Profile and produce a segmented JSON report.

    Args:
        profile_path: Path to the Profile .md file (YAML frontmatter + body).
                      E.g. ".olav/workspace/audit/profiles/network_health_full.md"
        time_window:  Time window string, e.g. "1h", "24h", "30m".
                      Passed to DuckDB as a named parameter — NEVER interpolated.
        db_path:      Path to DuckDB file. Defaults to project MAIN_DB_PATH.
        output_dir:   Directory for the output JSON file.
        staging_dir:  If provided AND profile.persist_findings_to_db is True,
                      a .staging.json is written here for IngestManager.

    Returns:
        Absolute path of the written segmented JSON file.
    """
    if db_path is None:
        try:
            from olav.core.config import MAIN_DB_PATH
            db_path = str(MAIN_DB_PATH)
        except ImportError as err:
            raise ValueError("db_path must be provided when OLAV config is unavailable") from err

    profile = _parse_profile_yaml(profile_path)
    profile_name = profile.get("name", "unnamed")
    max_findings = profile.get("max_findings_per_job", 50)
    persist = profile.get("persist_findings_to_db", False)
    # ARCH-11 Phase 1: profile opt-in. When true, each finding is decorated
    # with a `_source` dict and render_report prints a [src: …] tag.
    emit_sources = bool(profile.get("emit_sources", False))
    # #4 per-job SQL timeout (2026-05-12). Wall-clock budget per query;
    # default 30s, override via profile YAML `job_timeout_seconds: <int>`.
    # 0 or negative → no timeout (legacy behaviour for callers that
    # explicitly opt out).
    try:
        job_timeout_seconds = float(profile.get("job_timeout_seconds", 30))
    except (TypeError, ValueError):
        job_timeout_seconds = 30.0

    # ── Resolution: parse snapshot_resolution → minutes (drives anomaly + incident engines)
    raw_resolution = profile.get("snapshot_resolution", "1d")
    try:
        from incident_engine import parse_resolution_to_minutes
        resolution_minutes = parse_resolution_to_minutes(raw_resolution)
    except Exception:
        resolution_minutes = 1440  # fallback: daily
    logger.info(
        "map_engine: profile=%s resolution=%s (%dmin) window=%s",
        profile_name, raw_resolution, resolution_minutes, time_window,
    )

    generated_at = datetime.now(tz=UTC).isoformat()

    jobs_output: dict[str, Any] = {}

    with duckdb.connect(str(db_path)) as conn:
        for job in profile.get("jobs", []):
            job_name = job["name"]
            job_type = job.get("type", "sql")
            severity = job.get("severity", "info")

            if job_type == "sql":
                try:
                    findings, total_count = _execute_sql_job(
                        conn=conn,
                        query=job["query"],
                        window=time_window,
                        max_findings=max_findings,
                        timeout_seconds=job_timeout_seconds,
                    )
                except JobTimeoutError as _to_exc:
                    # Surface as a synthetic Critical finding so the
                    # operator sees the timeout in the report instead
                    # of a section that's silently empty. Force severity
                    # promotion so render_report doesn't paint it green.
                    logger.warning(
                        "map_engine: job %r timed out (%.1fs): %s",
                        job_name, job_timeout_seconds, _to_exc,
                    )
                    findings = [{
                        "device": "(map_engine)",
                        "metric_value": int(job_timeout_seconds),
                        "metric_name": "Job Timeout",
                        "severity_hint": "Critical",
                        "_warning": "job_timeout",
                        "reason": (
                            f"Job {job_name!r} exceeded "
                            f"job_timeout_seconds={job_timeout_seconds:.0f}s "
                            f"and was interrupted. Tune `job_timeout_seconds` "
                            f"in the profile or simplify the SQL."
                        ),
                    }]
                    total_count = 1
                    severity = "Critical"
                # RAW-05: when a parsed-only SQL job returns nothing but
                # raw_output_store still has rows for the same command, the
                # operator would otherwise see a clean bill of health. Emit
                # raw_only_data sentinels so the gap is visible downstream.
                if not findings and job.get("raw_fallback"):
                    findings = _raw_fallback_probe(conn, job.get("query", ""))
                    total_count = len(findings)
                # ISSUE-AUDIT-FALSE-GREEN-EMPTY-RESULTSET: when findings is
                # still empty AND raw_fallback also produced nothing, check
                # whether the source table/view actually has data. Dead
                # tables and stale-window scenarios both look like "healthy"
                # to the renderer otherwise — promote to explicit warning.
                if not findings:
                    sufficiency = _check_data_sufficiency(
                        conn, job.get("query", ""), job_name
                    )
                    if sufficiency is not None:
                        findings = [sufficiency]
                        # Promote job severity so render_report can't ignore it
                        if sufficiency.get("severity_hint") == "Critical":
                            severity = "Critical"
                        elif severity in ("info", "Info"):
                            severity = "Warning"
                if emit_sources:
                    _attach_sql_sources(findings, job.get("query", ""))
            else:
                # Rev 274 (2026-05-12): audit collapses to a single
                # `type: sql` after the collect/audit boundary review.
                # Previously map_engine accepted `lancedb` /  `anomaly`
                # / `api_anomaly` job types — those violated the
                # contract that audit only reads from the collected
                # netops.* tables. HTTP probing, third-party API
                # polling, and Z-score baseline updates all belong in
                # the collect pipeline (netops_collect writes to
                # parsed_outputs / a dedicated stats table), and audit
                # then SELECTs anomalies via SQL CTEs.
                #
                # Existing profiles that still declare non-sql types
                # surface as an explicit finding so the operator sees
                # the drift rather than a silently-empty section.
                logger.warning(
                    "Job %r type=%r is no longer supported (rev 274 "
                    "audit collapsed to single sql type). Rewrite the "
                    "job using `type: sql` with a CTE expressing the "
                    "anomaly logic.",
                    job_name, job_type,
                )
                findings = [{
                    "device": "(map_engine)",
                    "metric_value": 0,
                    "metric_name": (
                        f"Job type {job_type!r} is deprecated (rev 274). "
                        f"Rewrite as `type: sql` with appropriate CTE."
                    ),
                    "severity_hint": "Warning",
                }]
                total_count = len(findings)

            # ── ISSUE-AUDIT-FINDINGS-CAP-SILENT-TRUNCATION (P1, 2026-05-12) ─
            # If the SQL produced more rows than max_findings let, surface
            # the truncation explicitly: render_report uses these fields to
            # print a "⚠️ showing N of TOTAL findings" warning at section
            # head. Without this, a 100-finding job silently degrades to
            # the first 50 rows and operators miss half the picture.
            _job_output: dict = {
                "severity": severity,
                "count": len(findings),
                "findings": findings,
            }
            if total_count > len(findings):
                _job_output["truncated"] = True
                _job_output["total_count"] = total_count
                _job_output["shown_count"] = len(findings)
                logger.warning(
                    "map_engine: job %r truncated to %d findings (total: %d)",
                    job_name, len(findings), total_count,
                )
            jobs_output[job_name] = _job_output

    # ── Incident clustering (post-processing, optional) ──────────────────────
    incident_clusters: list[dict] = []
    if profile.get("run_incident_clustering", False):
        try:
            from incident_engine import build_incident_clusters
            # gap_minutes in profile overrides auto-derivation; None = auto
            explicit_gap = profile.get("incident_cluster_gap_minutes")
            gap_arg = int(explicit_gap) if explicit_gap is not None else None
            with duckdb.connect(str(db_path)) as _inc_conn:
                incident_clusters = build_incident_clusters(
                    conn=_inc_conn,
                    window=time_window,
                    gap_minutes=gap_arg,
                    resolution_minutes=resolution_minutes,
                )
            logger.info(
                "map_engine: incident clustering found %d cluster(s)",
                len(incident_clusters),
            )
        except Exception as exc:
            logger.warning("map_engine: incident clustering failed: %s", exc)

    # ── ISSUE-AUDIT-FRESHNESS-GATE-MISSING (P1, 2026-05-12) ─────────────
    # Global freshness gate: even if a profile has no per-job freshness
    # check, surface device staleness at the top of the audit JSON. Every
    # downstream finding in this run is qualified by this banner —
    # otherwise small profiles like ospf_health report "✅ Healthy" on
    # 11-day-old snapshots.
    freshness_threshold_hours = float(profile.get("freshness_threshold_hours", 24))
    freshness_warning: dict | None = None
    try:
        with duckdb.connect(str(db_path)) as _fr_conn:
            row = _fr_conn.execute(
                "SELECT MAX(EXTRACT(EPOCH FROM (NOW() - last_seen)) / 3600.0) "
                "FROM netops.devices WHERE last_seen IS NOT NULL"
            ).fetchone()
            max_hours = row[0] if row and row[0] is not None else None
            null_row = _fr_conn.execute(
                "SELECT COUNT(*) FROM netops.devices WHERE last_seen IS NULL"
            ).fetchone()
            null_count = null_row[0] if null_row else 0
        if max_hours is not None and max_hours > freshness_threshold_hours:
            freshness_warning = {
                "type": "stale_data",
                "max_hours_since_last_seen": round(float(max_hours), 1),
                "threshold_hours": freshness_threshold_hours,
                "devices_with_null_last_seen": int(null_count),
                "message": (
                    f"Newest data is {round(float(max_hours), 1)}h old "
                    f"(threshold: {freshness_threshold_hours}h). All findings "
                    f"below reflect that snapshot — they DO NOT prove current "
                    f"network state. Re-collect before treating any '✅ Healthy' "
                    f"finding as authoritative."
                ),
            }
        elif null_count > 0:
            freshness_warning = {
                "type": "missing_last_seen",
                "devices_with_null_last_seen": int(null_count),
                "threshold_hours": freshness_threshold_hours,
                "message": (
                    f"{null_count} device(s) have NULL last_seen — "
                    f"freshness cannot be verified for those devices."
                ),
            }
    except Exception as exc:
        logger.warning("map_engine: freshness gate check failed: %s", exc)

    output = {
        "profile": profile_name,
        "window": time_window,
        "snapshot_resolution": raw_resolution,
        "resolution_minutes": resolution_minutes,
        "generated_at": generated_at,
        "freshness_warning": freshness_warning,
        "jobs": jobs_output,
        "incident_clusters": incident_clusters,
    }

    # Write segmented JSON (datetime objects from DuckDB need ISO string conversion)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    json_path = out_dir / f"{profile_name}_{ts}.json"
    json_path.write_text(json.dumps(output, ensure_ascii=False, indent=2, default=_json_default))
    logger.info("map_engine: wrote %s", json_path)

    # Optionally write staging file for IngestManager
    if persist and staging_dir is not None:
        _write_staging(output, Path(staging_dir), profile_name, ts)

    return str(json_path)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_first_table(query: str) -> str | None:
    """Pull the first ``FROM <table>`` token out of a SQL query.
    Returns None if the regex doesn't match (e.g. CTE-only / empty)."""
    import re
    m = re.search(r"\bFROM\s+([A-Za-z_][A-Za-z0-9_.]*)", query, re.IGNORECASE)
    return m.group(1) if m else None


# ── ISSUE-AUDIT-SCHEMA-DRIFT-NO-SELFTEST (P2, 2026-05-12) ─────────────
def selftest_profile(
    profile_path: str,
    db_path: str | None = None,
) -> dict:
    """Validate every Job in a Profile against the current DB schema.

    Catches schema drift BEFORE the profile is run for real. Each job's
    SQL gets two passes:
      1. ``EXPLAIN <query>`` — DuckDB binder verifies tables + columns
         exist. Binder errors (missing column, unknown table) surface
         here.
      2. Bind the ``$cutoff`` parameter and run ``SELECT ... LIMIT 0``
         — catches column-name typos that EXPLAIN misses (e.g.
         ``SELECT non_existent_col FROM t``).

    Returns:
        ``{"ok": bool, "profile": str, "jobs": [{"name", "status",
        "error", "table"}, ...]}``

        ``status`` is one of ``ok`` / ``schema_error`` / ``runtime_error``.

    Failure mode this protects: upstream parser renames a column (e.g.
    ``state`` → ``session_state`` on ``v_bgp_neighbors_auto``). The
    profile's SQL ``SELECT state FROM ...`` silently returns NULL or
    zero rows on the next run. Without selftest, the audit reports
    "✅ Healthy" instead of flagging the regression.
    """
    if db_path is None:
        try:
            from olav.core.config import MAIN_DB_PATH
            db_path = str(MAIN_DB_PATH)
        except ImportError as err:
            raise ValueError("db_path must be provided when OLAV config is unavailable") from err

    profile = _parse_profile_yaml(profile_path)
    profile_name = profile.get("name", "unnamed")
    jobs = profile.get("jobs", [])

    cutoff = _parse_window_to_cutoff("1h")  # placeholder for any :window refs
    results: list[dict] = []
    all_ok = True

    with duckdb.connect(str(db_path), read_only=True) as conn:
        for job in jobs:
            job_name = job.get("name", "<unnamed>")
            query = job.get("query", "")
            entry: dict = {
                "name": job_name,
                "table": _extract_first_table(query),
                "status": "ok",
                "error": None,
            }
            if job.get("type", "sql") != "sql":
                # Rev 274: only sql jobs are runnable.
                entry["status"] = "ok"
                entry["error"] = "non-sql job (deprecated; rendered as warning finding)"
                results.append(entry)
                continue
            if not query.strip():
                entry["status"] = "schema_error"
                entry["error"] = "empty query"
                all_ok = False
                results.append(entry)
                continue
            # Translate :window placeholder the same way _execute_sql_job does.
            import re as _re
            duckdb_query = _re.sub(
                r"NOW\(\)\s*-\s*INTERVAL\s*:window", "$cutoff", query,
                flags=_re.IGNORECASE,
            )
            duckdb_query = _re.sub(r":window", "$cutoff", duckdb_query, flags=_re.IGNORECASE)
            params = {"cutoff": cutoff} if "$cutoff" in duckdb_query else {}
            inner = duckdb_query.rstrip().rstrip(";")
            # Pass 1: EXPLAIN — binder check
            try:
                conn.execute(f"EXPLAIN {inner}", params)
            except Exception as exc:
                entry["status"] = "schema_error"
                entry["error"] = f"EXPLAIN failed: {exc}"
                all_ok = False
                results.append(entry)
                continue
            # Pass 2: LIMIT 0 — column-name + type check
            try:
                conn.execute(f"SELECT * FROM ({inner}) __q LIMIT 0", params)
            except Exception as exc:
                entry["status"] = "runtime_error"
                entry["error"] = f"LIMIT 0 probe failed: {exc}"
                all_ok = False
                results.append(entry)
                continue
            results.append(entry)

    return {
        "ok": all_ok,
        "profile": profile_name,
        "profile_path": str(profile_path),
        "jobs": results,
    }


def _check_data_sufficiency(
    conn: duckdb.DuckDBPyConnection,
    query: str,
    job_name: str,
) -> dict | None:
    """When a SQL job returns no findings, decide whether the underlying
    data source is empty (data-sufficiency problem) or whether the
    filters legitimately matched nothing (real "all healthy" signal).

    Returns a synthetic finding dict when the source is empty / window
    is stale; ``None`` when 0 rows is a legitimate "no anomalies"
    answer.

    Three branches:

      1. **Empty source** (table has 0 rows total) → **Critical**
         ``empty_source`` finding. Most likely: dead/legacy table or
         discovery hasn't run. Always fires regardless of query shape.

      2. **Empty window** (table has rows; query uses ``:window``
         placeholder; 0 rows matched) → **Warning** ``empty_window``
         finding. Stale data — extend window or re-collect.

      3. **Legitimate empty** (table has rows; query has no
         ``:window``) → return ``None``. The job legitimately found
         no anomalies; an "all healthy" signal that should NOT be
         promoted to a warning.
    """
    table = _extract_first_table(query)
    if table is None:
        return None
    try:
        total = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    except Exception:
        # Can't introspect — silent skip; don't fail the audit
        return None

    if total == 0:
        return {
            "device": "(no data)",
            "metric_value": 0,
            "metric_name": "Insufficient Data",
            "severity_hint": "Critical",
            "_warning": "empty_source",
            "_source": {"type": "sql", "table": table, "row_count_total": 0},
            "reason": (
                f"Job {job_name!r} queried {table!r} but the source has "
                f"0 rows total — empty table/view. Verify discovery has "
                f"run, or the audit profile may be referencing a deprecated "
                f"table (R83 zero-ETL moved BGP/OSPF/routes data to "
                f"v_*_auto views; raw tables are leftover schema)."
            ),
        }

    # Only flag empty-window when the query actually uses :window.
    # No :window placeholder + 0 rows = legitimate "all healthy" signal.
    if ":window" not in query.lower():
        return None

    return {
        "device": "(no data in window)",
        "metric_value": 0,
        "metric_name": "Insufficient Data",
        "severity_hint": "Warning",
        "_warning": "empty_window",
        "_source": {"type": "sql", "table": table, "row_count_total": int(total)},
        "reason": (
            f"Job {job_name!r}: {table!r} has {total} rows total but the "
            f"audit's time window matched 0. Either extend the time window "
            f"or re-collect; current data is older than the audit window."
        ),
    }


def _attach_sql_sources(findings: list[dict], query: str) -> None:
    """ARCH-11 Phase 1: decorate SQL findings with a ``_source`` dict.

    Extracts the first ``FROM <table>`` token from the query and annotates
    each finding row with table / snapshot_id / device / row_index so the
    render layer can emit a ``[src: …]`` citation suffix. Runs in-place.
    """
    import re

    m = re.search(r"\bFROM\s+([A-Za-z_][A-Za-z0-9_.]*)", query, re.IGNORECASE)
    table = m.group(1) if m else "unknown"
    for i, row in enumerate(findings):
        row["_source"] = {
            "type": "sql",
            "table": table,
            "snapshot_id": row.get("snapshot_id"),
            "device": row.get("device_name") or row.get("device"),
            "row_index": i,
        }


def _raw_fallback_probe(
    conn: duckdb.DuckDBPyConnection,
    query: str,
    max_findings: int = 20,
) -> list[dict]:
    """Check ``netops.raw_output_store`` for rows matching the same command
    pattern as the primary query (RAW-05).

    When a parsed-outputs-only job returns empty findings but raw captures
    exist for the same ILIKE pattern, emit ``_warning: raw_only_data``
    sentinels so operators know analysis couldn't actually run on this
    command — they're not looking at a clean-bill-of-health, they're
    looking at unparsed data.

    The command pattern is extracted from the query via regex. If no ILIKE
    clause is detected the probe is a no-op (returns empty list).
    """
    import re

    m = re.search(r"command\s+ILIKE\s+'([^']+)'", query, re.IGNORECASE)
    if not m:
        return []
    pattern = m.group(1)

    try:
        rows = conn.execute(
            """
            SELECT DISTINCT device_name, command
            FROM netops.raw_output_store
            WHERE command ILIKE ? AND raw_output IS NOT NULL AND raw_output <> ''
            LIMIT ?
            """,
            [pattern, int(max_findings)],
        ).fetchall()
    except Exception as exc:
        logger.debug("raw_fallback_probe failed: %s", exc)
        return []

    return [
        {
            "_warning": "raw_only_data",
            "device_name": dev,
            "command": cmd,
            "note": (
                "raw output is available but parsed_outputs is empty — "
                "TextFSM parser may have failed. Analysis skipped."
            ),
        }
        for dev, cmd in rows
    ]


class JobTimeoutError(RuntimeError):
    """Raised when a job's SQL exceeds the configured timeout."""


def _execute_with_timeout(
    conn: duckdb.DuckDBPyConnection,
    query: str,
    params: dict,
    timeout_seconds: float,
):
    """Run a DuckDB query under a wall-clock budget.

    DuckDB 1.4 does NOT support ``SET statement_timeout``. We run the
    query on a worker thread + poll wall-clock; on overrun we call
    ``conn.interrupt()`` to cancel the query and raise JobTimeoutError.

    Important: ``conn.interrupt()`` is connection-scoped, so this must
    be called on a connection that ONLY this thread is using. The
    audit pipeline opens a fresh conn for run_map_engine, so this
    holds in practice.
    """
    import threading
    result: list = [None]
    error: list = [None]

    def _runner():
        try:
            cursor = conn.execute(query, params) if params else conn.execute(query)
            cols = [d[0] for d in cursor.description]
            rows = cursor.fetchall()
            result[0] = (cols, rows)
        except Exception as exc:
            error[0] = exc

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    t.join(timeout=timeout_seconds)
    if t.is_alive():
        # Cancel the query on the DuckDB side, then wait briefly for
        # the worker to unwind. If it never unwinds we still raise —
        # the thread will be cleaned up at process exit.
        try:
            conn.interrupt()
        except Exception as exc:
            logger.warning("map_engine: conn.interrupt() failed: %s", exc)
        t.join(timeout=2.0)
        raise JobTimeoutError(
            f"SQL exceeded {timeout_seconds}s; query interrupted. "
            f"Tune `job_timeout_seconds` in the profile or simplify the SQL."
        )
    if error[0] is not None:
        raise error[0]
    return result[0]


def _execute_sql_job(
    conn: duckdb.DuckDBPyConnection,
    query: str,
    window: str,
    max_findings: int,
    timeout_seconds: float | None = None,
) -> tuple[list[dict], int]:
    """Run a parameterized DuckDB query and return (findings, total_count).

    Profile SQL uses `INTERVAL :window` as a documentation-friendly convention.
    DuckDB cannot bind INTERVAL values as parameters, so the engine translates:
      1. Computes cutoff = datetime.now() - parse_window(window)  (pure Python)
      2. Replaces `INTERVAL :window` occurrences with `$cutoff` in the query
      3. Binds the cutoff datetime as a named DuckDB parameter

    The window VALUE is never concatenated into the SQL string.

    Returns:
        (findings_capped_at_max_findings, total_row_count_before_cap)

    The total count lets the caller surface a `truncated` warning when
    the query produced more rows than `max_findings`. Without this, a
    100-finding job silently degrades to a 50-finding report.

    timeout_seconds: when set, wraps the query in a wall-clock budget
    via ``_execute_with_timeout``. Raises JobTimeoutError on overrun.
    None / 0 / negative → no timeout (legacy behaviour).
    """
    import re

    cutoff = _parse_window_to_cutoff(window)

    # Replace INTERVAL :window expressions with $cutoff parameter reference.
    # Pattern covers both `NOW() - INTERVAL :window` and bare `INTERVAL :window`.
    duckdb_query = re.sub(
        r"NOW\(\)\s*-\s*INTERVAL\s*:window",
        "$cutoff",
        query,
        flags=re.IGNORECASE,
    )
    # Also handle any remaining standalone :window references
    duckdb_query = re.sub(r":window", "$cutoff", duckdb_query, flags=re.IGNORECASE)

    inner_query = duckdb_query.rstrip().rstrip(";")
    # Apply LIMIT via outer CTE — integer literal, NOT a user-supplied value
    capped_query = (
        f"SELECT * FROM ({inner_query}) __q "
        f"LIMIT {int(max_findings) + 1}"  # +1 lets us detect "more than max"
    )

    # $cutoff is a Python datetime — DuckDB binds it as TIMESTAMPTZ automatically.
    # Only pass the param dict when $cutoff is actually referenced (drift queries
    # use ROW_NUMBER() and never reference $cutoff at all).
    params = {"cutoff": cutoff} if "$cutoff" in capped_query else {}

    if timeout_seconds and timeout_seconds > 0:
        columns, rows = _execute_with_timeout(
            conn, capped_query, params, float(timeout_seconds),
        )
    else:
        result = conn.execute(capped_query, params)
        columns = [desc[0] for desc in result.description]
        rows = result.fetchall()

    findings = [dict(zip(columns, row, strict=False)) for row in rows]
    if len(findings) <= max_findings:
        # No truncation — return findings as-is, total == len(findings)
        return findings, len(findings)

    # Truncation detected — find the exact total via a COUNT query so the
    # warning carries an accurate denominator. Cheap because the inner
    # query is materialised by DuckDB once.
    try:
        count_query = f"SELECT COUNT(*) FROM ({inner_query}) __q"
        if timeout_seconds and timeout_seconds > 0:
            _, count_rows = _execute_with_timeout(
                conn, count_query, params, float(timeout_seconds),
            )
            total = count_rows[0][0]
        else:
            total = conn.execute(count_query, params).fetchone()[0]
    except Exception as exc:
        logger.warning(
            "map_engine: truncation count query failed (using max+1 as floor): %s", exc,
        )
        total = max_findings + 1
    return findings[:max_findings], int(total)


def _parse_window_to_cutoff(window: str) -> datetime:
    """Convert a window string (e.g. '1h', '30m', '24h') to an absolute cutoff UTC datetime."""
    window = window.strip().lower()
    if window.endswith("h"):
        delta = timedelta(hours=float(window[:-1]))
    elif window.endswith("m"):
        delta = timedelta(minutes=float(window[:-1]))
    elif window.endswith("d"):
        delta = timedelta(days=float(window[:-1]))
    else:
        delta = timedelta(hours=1)
        logger.warning("Unrecognised window format %r — defaulting to 1h", window)
    return datetime.now(tz=UTC) - delta


def _write_staging(
    output: dict,
    staging_dir: Path,
    profile_name: str,
    ts: str,
) -> None:
    """Write a .staging.json file for IngestManager consumption.

    The staging JSON is a flat list of finding records, each annotated
    with profile metadata, suitable for DuckDB read_json_auto ingest.
    """
    staging_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for job_name, job_data in output["jobs"].items():
        for finding in job_data["findings"]:
            records.append(
                {
                    "profile": output["profile"],
                    "window": output["window"],
                    "audited_at": output["generated_at"],
                    "job_name": job_name,
                    "severity": job_data["severity"],
                    "finding": finding,
                }
            )

    staging_path = staging_dir / f"audit_findings_{ts}.staging.json"
    staging_path.write_text(json.dumps(records, ensure_ascii=False, indent=2, default=_json_default))
    logger.info("map_engine: wrote staging file %s (%d records)", staging_path, len(records))


if __name__ == "__main__":
    import json as _json
    import sys as _sys
    _args = _json.loads(_sys.stdin.read() or "{}")
    print(_json.dumps(run_map_engine(**_args), default=str))
