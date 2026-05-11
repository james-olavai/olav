"""Audit job executors — Phase F-Audit (rev 273, 2026-05-12).

Each executor implements one ``audit_job_schemas/<type>.job.yaml``
``executor:`` dotted-path target. Signature is uniform:

    def execute_<job_type>(args: dict, db_conn) -> list[dict]:
        return [{"device": ..., "metric_value": ..., ...}, ...]

The signature contract is:
  * args: validated + defaulted dict from generic_job_runner
  * db_conn: read-only duck-typed DB connection (or None if not needed)
  * returns: list of findings; each finding dict must satisfy the
    schema's ``finding_shape.required_columns`` (typically device,
    metric_value, metric_name, severity_hint)

Adding a new executor:
  1. Define ``execute_<new_type>(args, db_conn) -> list[dict]`` here
     (or in any importable module — the schema's executor path can
     point anywhere).
  2. Write ``audit_job_schemas/<new_type>.job.yaml`` pointing at it.

That's it — generic_job_runner discovers + dispatches automatically.
"""
from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)


# ── SQL executor (mirrors map_engine._execute_sql_job) ──────────────


_INTERVAL_RE = re.compile(r":window\b", re.IGNORECASE)


def execute_sql_job(args: dict[str, Any], db_conn: Any) -> list[dict[str, Any]]:
    """Run a DuckDB SQL query and return rows as findings.

    Matches the behaviour of ``map_engine._execute_sql_job`` for the
    Phase F-Audit prototype:
      * ``:window`` is substituted with ``$cutoff`` (datetime param)
      * outer wrapper caps rows at ``max_findings``
      * each row is dict-mapped via cursor.description
    """
    query: str = args["query"]
    max_findings: int = int(args.get("max_findings") or 50)

    # 1 hour window default — production map_engine takes the window
    # from the renderer call site; this prototype uses a hardcoded
    # safe default so the executor stays self-contained for testing.
    cutoff = datetime.now(tz=UTC) - timedelta(hours=1)
    duckdb_query = _INTERVAL_RE.sub("$cutoff", query)

    capped = (
        f"SELECT * FROM ({duckdb_query.rstrip().rstrip(';')}) __q "
        f"LIMIT {max_findings}"
    )
    params = {"cutoff": cutoff} if "$cutoff" in capped else {}
    result = db_conn.execute(capped, params)
    cols = [d[0] for d in result.description]
    rows = result.fetchall()
    return [dict(zip(cols, row, strict=False)) for row in rows]


# ── LanceDB executor (stub for prototype) ───────────────────────────


def execute_lancedb_job(args: dict[str, Any], db_conn: Any) -> list[dict[str, Any]]:
    """LanceDB semantic search.

    Production version lives in ``map_engine._execute_lancedb_job``; this
    is a thin shim that delegates so we don't duplicate the LanceDB
    plumbing while the prototype iterates. When the elif chain is
    eventually replaced, the original implementation moves here.
    """
    # Lazy import — keeps lancedb optional for environments that only
    # exercise sql / http_probe.
    try:
        # The prototype shares the in-tree map_engine helper to avoid
        # divergence while it stays parallel.
        import sys
        from pathlib import Path
        _mehome = (
            Path.cwd() / ".olav" / "workspace" / "audit" / "runner" / "tools"
        )
        if str(_mehome) not in sys.path:
            sys.path.insert(0, str(_mehome))
        from map_engine import _execute_lancedb_job  # type: ignore[import-not-found]
    except Exception:
        logger.warning(
            "execute_lancedb_job: map_engine not importable in this context "
            "(prototype stub) — returning empty findings."
        )
        return []
    semantic_query = args["semantic_query"]
    threshold = float(args.get("threshold") or 0.75)
    max_findings = int(args.get("max_findings") or 50)
    return _execute_lancedb_job(
        semantic_query=semantic_query,
        threshold=threshold,
        max_findings=max_findings,
    )


# ── HTTP probe executor — zero-Python-dispatch demonstration ────────


def execute_http_probe(args: dict[str, Any], db_conn: Any = None) -> list[dict[str, Any]]:
    """Probe each URL with a GET; emit one finding per URL.

    Healthy: status == expected_status → 'Info', metric_value = latency_ms.
    Unhealthy: any other status / network error → 'Critical',
               metric_value = 0, severity_hint encodes the failure.

    db_conn is ignored — http_probe has no DB dependency. Listed in
    the signature for uniformity with other executors.
    """
    _ = db_conn  # unused
    urls = args.get("urls") or []
    if not isinstance(urls, list):
        raise ValueError("http_probe: 'urls' must be a list")
    timeout_s: float = float(args.get("timeout_s") or 5)
    expected_status: int = int(args.get("expected_status") or 200)

    findings: list[dict[str, Any]] = []
    for url in urls:
        url_str = str(url)
        t0 = datetime.now(tz=UTC)
        status = None
        err: str | None = None
        try:
            req = Request(url_str, method="GET")
            with urlopen(req, timeout=timeout_s) as resp:
                status = resp.status
        except URLError as e:
            err = f"URLError: {e.reason}"
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"
        elapsed_ms = (datetime.now(tz=UTC) - t0).total_seconds() * 1000.0

        if err:
            severity = "Critical"
            metric = 0.0
            metric_name = f"HTTP Probe FAIL ({err})"
        elif status != expected_status:
            severity = "Critical"
            metric = float(status or 0)
            metric_name = f"HTTP {status} != expected {expected_status}"
        else:
            severity = "Info"
            metric = round(elapsed_ms, 1)
            metric_name = f"HTTP {status} OK ({elapsed_ms:.0f} ms)"

        findings.append({
            "device": url_str,
            "metric_value": metric,
            "metric_name": metric_name,
            "severity_hint": severity,
        })
    return findings
