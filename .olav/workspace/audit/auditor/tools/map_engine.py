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
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import duckdb
from langchain_core.tools import StructuredTool

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
    """Strip leading '/' from LLM-supplied paths and resolve bare profile names.

    ISSUE-004: If given a bare name like 'health_full_drift' (no directory, no .md),
    look up the file under _PROFILES_DIR so the LLM can pass short names.
    """
    if not path_str:
        return path_str
    # Strip leading slash if the absolute path doesn't actually exist on disk
    if path_str.startswith("/") and not Path(path_str).exists():
        path_str = path_str.lstrip("/")
    # Resolve bare profile name (no directory separator)
    p = Path(path_str)
    if not p.exists() and "/" not in path_str:
        for suffix in ("", ".md"):
            candidate = Path(_PROFILES_DIR) / (path_str + suffix)
            if candidate.exists():
                return str(candidate)
    return path_str


def _parse_profile_yaml(profile_path: str) -> dict:
    """Parse YAML frontmatter from a Profile .md file and return as dict."""
    import re

    import yaml  # type: ignore

    p = Path(_sanitize_path(profile_path))
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
                findings = _execute_sql_job(
                    conn=conn,
                    query=job["query"],
                    window=time_window,
                    max_findings=max_findings,
                )
            elif job_type == "lancedb":
                findings = _execute_lancedb_job(
                    job=job,
                    time_window=time_window,
                    max_findings=max_findings,
                )
            elif job_type == "anomaly":
                from anomaly_engine import run_anomaly_job
                findings = run_anomaly_job(
                    conn=conn,
                    job=job,
                    window=time_window,
                    max_findings=max_findings,
                    resolution_minutes=resolution_minutes,
                )
            elif job_type == "api_anomaly":
                # Third-party API path: no raw history in DuckDB.
                # Observations are fetched via HTTP (job.api.endpoint) or
                # pre-staged in DuckDB table `api_metrics`.
                # baseline_engine maintains a Welford rolling stats table
                # (anomaly_baselines) so Z-scores work after min_samples polls.
                from baseline_engine import run_baseline_job
                api_cfg = job.get("api", {})
                observations = _fetch_api_observations(api_cfg, conn, time_window)
                findings = run_baseline_job(
                    conn=conn,
                    observations=observations,
                    metric_cols=api_cfg.get("metric_cols", []),
                    threshold=api_cfg.get("threshold", 2.5),
                    device_col=api_cfg.get("device_col", "device_name"),
                    max_findings=max_findings,
                    resolution_minutes=resolution_minutes,
                )
            else:
                logger.warning("Unknown job type %r for job %r — skipping", job_type, job_name)
                findings = []

            jobs_output[job_name] = {
                "severity": severity,
                "count": len(findings),
                "findings": findings,
            }

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

    output = {
        "profile": profile_name,
        "window": time_window,
        "snapshot_resolution": raw_resolution,
        "resolution_minutes": resolution_minutes,
        "generated_at": generated_at,
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


def _fetch_api_observations(
    api_cfg: dict,
    conn: duckdb.DuckDBPyConnection,
    time_window: str,
) -> list[dict]:
    """Fetch observations for an api_anomaly job.

    Two strategies, selected by api_cfg keys:

    1. DuckDB query (api.query)  — reads from a pre-staged api_metrics table or
       any DuckDB-accessible source.  Use this when a collector script already
       writes API results to DuckDB via IngestManager.

    2. HTTP GET/POST (api.endpoint) — calls the third-party URL directly and
       extracts observations from the JSON response body.
       Supports:
         api:
           endpoint: "https://nms.example.com/api/v2/metrics"
           method: GET            # GET (default) or POST
           headers: {"X-APIKey": "secret"}
           params: {"window": "7d", "format": "json"}
           observations_key: "data.devices"   # dot-path into the response JSON
           device_col: device_name
           metric_cols: [cpu_5min, mem_used_pct]
           threshold: 2.5
    """
    # ── Strategy 1: DuckDB-backed staging table ────────────────────────────
    if "query" in api_cfg:
        try:
            # Use parameterized binding — NEVER interpolate time_window directly into SQL.
            # The query template uses INTERVAL :window; we bind the safe interval string.
            interval_str = _window_to_interval_str(time_window)
            df = conn.execute(api_cfg["query"], {"window": interval_str}).fetchdf()
            return df.to_dict(orient="records")
        except Exception as exc:
            logger.warning("api_anomaly DuckDB query failed: %s", exc)
            return []

    # ── Strategy 2: HTTP fetch ─────────────────────────────────────────────
    endpoint = api_cfg.get("endpoint", "")
    if not endpoint:
        logger.warning("api_anomaly job has no 'query' or 'endpoint' — returning empty")
        return []

    try:
        import json as _json
        import urllib.parse
        import urllib.request

        method = api_cfg.get("method", "GET").upper()
        headers = api_cfg.get("headers", {})
        params = api_cfg.get("params", {})

        if method == "GET" and params:
            endpoint = endpoint + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(endpoint, headers=headers, method=method)
        if method == "POST" and params:
            req.data = _json.dumps(params).encode()
            req.add_header("Content-Type", "application/json")

        with urllib.request.urlopen(req, timeout=30) as resp:
            body = _json.loads(resp.read())

        # Navigate dot-path into response, e.g. "data.devices"
        obs_key = api_cfg.get("observations_key", "")
        for part in obs_key.split("."):
            if part and isinstance(body, dict):
                body = body.get(part, body)

        if isinstance(body, list):
            return body
        if isinstance(body, dict):
            # Wrap single-device response
            return [body]
        logger.warning("api_anomaly: unexpected response structure from %s", endpoint)
        return []
    except Exception as exc:
        logger.warning("api_anomaly HTTP fetch failed (%s): %s", endpoint, exc)
        return []


def _execute_sql_job(
    conn: duckdb.DuckDBPyConnection,
    query: str,
    window: str,
    max_findings: int,
) -> list[dict]:
    """Run a parameterized DuckDB query.

    Profile SQL uses `INTERVAL :window` as a documentation-friendly convention.
    DuckDB cannot bind INTERVAL values as parameters, so the engine translates:
      1. Computes cutoff = datetime.now() - parse_window(window)  (pure Python)
      2. Replaces `INTERVAL :window` occurrences with `$cutoff` in the query
      3. Binds the cutoff datetime as a named DuckDB parameter

    The window VALUE is never concatenated into the SQL string.
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

    # Apply LIMIT via outer CTE — integer literal, NOT a user-supplied value
    capped_query = (
        f"SELECT * FROM ({duckdb_query.rstrip().rstrip(';')}) __q "
        f"LIMIT {int(max_findings)}"
    )

    # $cutoff is a Python datetime — DuckDB binds it as TIMESTAMPTZ automatically.
    # Only pass the param dict when $cutoff is actually referenced (drift queries
    # use ROW_NUMBER() and never reference $cutoff at all).
    params = {"cutoff": cutoff} if "$cutoff" in capped_query else {}
    result = conn.execute(capped_query, params)
    columns = [desc[0] for desc in result.description]
    rows = result.fetchall()
    return [dict(zip(columns, row, strict=False)) for row in rows]


def _execute_lancedb_job(
    job: dict,
    time_window: str,
    max_findings: int,
) -> list[dict]:
    """Run a LanceDB semantic query with time filtering.

    Time filter is computed as an absolute Python datetime — NOT a template string.
    """
    try:
        import lancedb  # type: ignore
    except ImportError:
        logger.warning("lancedb not installed — skipping LanceDB job %r", job.get("name"))
        return []

    # ISSUE-005: knowledge_db_dir may be None on minimal configs — fallback to default
    try:
        from olav.core.config import get_paths_config
        lancedb_path = get_paths_config().knowledge_db_dir
        if not lancedb_path:
            raise ValueError("knowledge_db_dir is None")
    except Exception:
        lancedb_path = None

    if lancedb_path is None:
        default = Path(".olav/databases/knowledge")
        if default.exists():
            lancedb_path = default
        else:
            logger.warning("Cannot resolve LanceDB path — skipping job %r", job.get("name"))
            return []

    cutoff = _parse_window_to_cutoff(time_window)
    semantic_query = job.get("semantic_query", "")
    threshold = job.get("similarity_threshold", 0.8)

    try:
        db = lancedb.connect(str(lancedb_path))
        table = db.open_table("syslog_vectors")
        results = (
            table.search(semantic_query)
            .metric("cosine")
            .limit(max_findings * 2)  # over-fetch, then filter by time + threshold
            .to_pandas()
        )

        # Filter by time and similarity
        if "_distance" in results.columns:
            results = results[1 - results["_distance"] >= threshold]
        if "timestamp" in results.columns:
            results = results[results["timestamp"] >= cutoff]

        return results.head(max_findings).to_dict(orient="records")

    except Exception as exc:
        logger.warning("LanceDB query failed for job %r: %s", job.get("name"), exc)
        return []


def _window_to_interval_str(window: str) -> str:
    """Convert a short window string to a DuckDB-compatible INTERVAL value string.

    Used for parameterized binding — the returned string is bound as a value,
    never interpolated into SQL source.
    """
    w = window.strip().lower()
    if w.endswith("h"):
        return f"{w[:-1]} hours"
    if w.endswith("m"):
        return f"{w[:-1]} minutes"
    if w.endswith("d"):
        return f"{w[:-1]} days"
    return "1 hours"


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


_run_map_engine_tool = StructuredTool.from_function(run_map_engine)
