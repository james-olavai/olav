"""baseline_engine.py — Welford Online Baseline Store for API-sourced metrics.

Problem
-------
When data arrives via a third-party API (not SSH snapshots into DuckDB), the
local historical time series is unavailable.  Z-score requires mean + std over
N samples — where do those statistics come from?

Solution: Welford's Online Algorithm
--------------------------------------
Instead of storing raw history, store a single *statistics row* per
(device, metric): (n, mean, M2).  On each new observation the row is updated
in O(1) — no scan, no history retention.  After `min_samples` observations the
baseline is considered "warm" and Z-scores become meaningful.

    Welford update:
        delta  = x_new – mean
        mean  += delta / n
        M2    += delta * (x_new – mean)   ← second delta, post-update
        std    = sqrt(M2 / (n – 1))
        z      = (x_new – mean) / std

This is exactly how Prometheus alertmanager, Datadog anomaly detection, and
InfluxDB Flux `stddev()` work internally.

DuckDB table schema
--------------------
    anomaly_baselines (
        device      TEXT,
        metric      TEXT,
        n           INTEGER,        -- observation count
        mean        DOUBLE,
        m2          DOUBLE,         -- sum of squared deviations (Welford M2)
        last_value  DOUBLE,
        last_seen   TIMESTAMPTZ,
        PRIMARY KEY (device, metric)
    )

Usage (two modes)
------------------
Mode 1 — API integration (push observations):
    from baseline_engine import BaselineStore
    store = BaselineStore(conn)
    store.update("Router-A", "cpu", 42.5)
    result = store.zscore("Router-A", "cpu", 42.5)
    # → {"z_score": 1.2, "mean": 35.0, "std": 6.1, "n": 47, "is_anomaly": False}

Mode 2 — Batch backfill from DuckDB query (same interface as anomaly_engine):
    store.bulk_update_from_query(conn, sql, device_col="device_name", metric_col="cpu")

Mode 3 — run_baseline_job (drop-in for run_anomaly_job when type=api_anomaly):
    findings = run_baseline_job(conn, job, observations, threshold=2.5)
    # observations: list[dict] from API response, each must have 'device_name' + metric fields
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timezone
from typing import Any

import duckdb

# ──────────────────────────────────────────────────────────────────────────────
# Schema bootstrap
# ──────────────────────────────────────────────────────────────────────────────

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS anomaly_baselines (
    device     TEXT        NOT NULL,
    metric     TEXT        NOT NULL,
    n          INTEGER     NOT NULL DEFAULT 0,
    mean       DOUBLE      NOT NULL DEFAULT 0.0,
    m2         DOUBLE      NOT NULL DEFAULT 0.0,
    last_value DOUBLE,
    last_seen  TIMESTAMPTZ,
    PRIMARY KEY (device, metric)
);
"""

_UPSERT = """
INSERT INTO anomaly_baselines (device, metric, n, mean, m2, last_value, last_seen)
VALUES (?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (device, metric) DO UPDATE SET
    n          = excluded.n,
    mean       = excluded.mean,
    m2         = excluded.m2,
    last_value = excluded.last_value,
    last_seen  = excluded.last_seen;
"""

_SELECT = """
SELECT n, mean, m2 FROM anomaly_baselines WHERE device = ? AND metric = ?;
"""


# ──────────────────────────────────────────────────────────────────────────────
# Welford helpers (pure functions — testable without DuckDB)
# ──────────────────────────────────────────────────────────────────────────────

def welford_update(n: int, mean: float, m2: float, x: float) -> tuple[int, float, float]:
    """Return updated (n, mean, M2) after incorporating new observation x.

    Numerically stable single-pass algorithm — no catastrophic cancellation.
    """
    n += 1
    delta = x - mean
    mean += delta / n
    delta2 = x - mean          # NOTE: uses updated mean
    m2 += delta * delta2
    return n, mean, m2


def welford_zscore(n: int, mean: float, m2: float, x: float) -> dict[str, Any]:
    """Compute Z-score for x against the Welford baseline.

    Returns a dict with z_score, std, mean, n, is_warm.
    is_warm=False means the baseline has fewer than MIN_SAMPLES observations
    and z-scores should not be trusted yet.
    """
    MIN_SAMPLES = 10
    if n < 2:
        return {"z_score": None, "mean": mean, "std": None, "n": n, "is_warm": False}
    std = math.sqrt(m2 / (n - 1))
    if std == 0.0:
        return {"z_score": 0.0, "mean": mean, "std": 0.0, "n": n, "is_warm": n >= MIN_SAMPLES}
    z = (x - mean) / std
    return {
        "z_score": round(z, 4),
        "mean": round(mean, 4),
        "std": round(std, 4),
        "n": n,
        "is_warm": n >= MIN_SAMPLES,
    }


# ──────────────────────────────────────────────────────────────────────────────
# BaselineStore — DuckDB-backed Welford state machine
# ──────────────────────────────────────────────────────────────────────────────

class BaselineStore:
    """Lightweight Welford baseline store backed by an `anomaly_baselines` DuckDB table.

    Designed to work regardless of data provenance:
      - SSH snapshots written to parsed_outputs (legacy mode)
      - Third-party API payloads pushed directly via .update()
      - SNMP poll results, streaming telemetry, webhook callbacks

    The store is data-source agnostic; caller responsibility is to extract
    (device, metric, value) triples from whatever API response format.
    """

    def __init__(self, conn: duckdb.DuckDBPyConnection) -> None:
        self.conn = conn
        conn.execute(_CREATE_TABLE)

    # ── Core update ────────────────────────────────────────────────────────

    def update(self, device: str, metric: str, value: float) -> dict[str, Any]:
        """Incorporate one new observation and return the Z-score result.

        This is the hot path for API-streaming integration.  Idempotent on
        same (device, metric, value, timestamp) within the same second.
        """
        row = self.conn.execute(_SELECT, [device, metric]).fetchone()
        if row:
            n, mean, m2 = row
        else:
            n, mean, m2 = 0, 0.0, 0.0

        # Compute z-score BEFORE updating (current value vs historical baseline)
        z_info = welford_zscore(n, mean, m2, value)

        # Update baseline with new observation
        n, mean, m2 = welford_update(n, mean, m2, value)
        now = datetime.now(tz=UTC)
        self.conn.execute(_UPSERT, [device, metric, n, mean, m2, value, now])

        return {
            "device": device,
            "metric": metric,
            "value": value,
            **z_info,
        }

    # ── Batch helpers ──────────────────────────────────────────────────────

    def bulk_update(self, observations: list[dict], device_col: str = "device_name") -> list[dict]:
        """Update baselines from a list of observation dicts.

        Each dict must contain `device_col` + one or more numeric metric keys.
        Returns a list of Z-score result dicts (one per device+metric pair).
        """
        results = []
        for obs in observations:
            device = obs.get(device_col, obs.get("device", "unknown"))
            for key, val in obs.items():
                if key == device_col or not isinstance(val, (int, float)):
                    continue
                try:
                    result = self.update(device, key, float(val))
                    results.append(result)
                except Exception:
                    pass
        return results

    def bulk_update_from_query(
        self,
        sql: str,
        device_col: str = "device_name",
        metric_cols: list[str] | None = None,
    ) -> list[dict]:
        """Run a DuckDB SQL query and bulk-update baselines from the result.

        Useful for backfilling the baseline store from existing DuckDB tables
        (e.g. on first deployment, warm the baseline from the last 30 days
        of parsed_outputs before switching to API-only mode).

        Example:
            store.bulk_update_from_query(
                "SELECT device_name, cpu FROM parsed_outputs WHERE ...",
                metric_cols=["cpu"],
            )
        """
        rows = self.conn.execute(sql).fetchdf().to_dict(orient="records")
        if metric_cols:
            filtered = [{k: v for k, v in r.items() if k == device_col or k in metric_cols}
                        for r in rows]
        else:
            filtered = rows
        return self.bulk_update(filtered, device_col=device_col)

    # ── Query ──────────────────────────────────────────────────────────────

    def get_baseline(self, device: str, metric: str) -> dict[str, Any] | None:
        """Return the current stored baseline statistics for (device, metric)."""
        row = self.conn.execute(_SELECT, [device, metric]).fetchone()
        if not row:
            return None
        n, mean, m2 = row
        std = math.sqrt(m2 / (n - 1)) if n >= 2 else None
        return {"device": device, "metric": metric, "n": n, "mean": round(mean, 4),
                "std": round(std, 4) if std is not None else None}

    def all_baselines(self) -> list[dict]:
        """Return all stored baselines."""
        df = self.conn.execute(
            "SELECT device, metric, n, ROUND(mean,4) AS mean, "
            "ROUND(SQRT(NULLIF(m2,0)/(NULLIF(n,1)-1)),4) AS std, "
            "last_value, last_seen FROM anomaly_baselines ORDER BY device, metric"
        ).fetchdf()
        return df.to_dict(orient="records")


# ──────────────────────────────────────────────────────────────────────────────
# run_baseline_job — drop-in replacement for run_anomaly_job (type: api_anomaly)
# ──────────────────────────────────────────────────────────────────────────────

def run_baseline_job(
    conn: duckdb.DuckDBPyConnection,
    observations: list[dict],
    metric_cols: list[str],
    threshold: float = 2.5,
    device_col: str = "device_name",
    max_findings: int = 50,
    resolution_minutes: int = 1440,
) -> list[dict]:
    """Detect anomalies in API observations using the Welford baseline store.

    Parameters
    ----------
    conn             : DuckDB connection (holds the anomaly_baselines table)
    observations     : list[dict] from API — each must have device_col + metric fields
    metric_cols      : which numeric keys to check for anomalies
    threshold        : |z_score| cutoff (default 2.5 ≈ 99th percentile)
    device_col       : key for the device identifier in each observation dict
    max_findings     : cap on returned anomaly rows
    resolution_minutes : used to determine if baseline is "warm enough"
                         (same guard as anomaly_engine.py)

    Returns
    -------
    List of anomaly dicts, each with: device, metric, value, z_score, mean, std, n, is_warm.
    Returns insufficient_data sentinel if no device has a warm baseline yet.
    """
    store = BaselineStore(conn)

    MIN_SAMPLES = 10
    anomalies: list[dict] = []
    warm_count = 0

    for obs in observations:
        device = obs.get(device_col, obs.get("device", "unknown"))
        for metric in metric_cols:
            raw = obs.get(metric)
            if raw is None:
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue

            result = store.update(device, metric, value)
            if result.get("is_warm"):
                warm_count += 1

            z = result.get("z_score")
            if z is not None and abs(z) >= threshold:
                anomalies.append({**result, "threshold": threshold})

            if len(anomalies) >= max_findings:
                break

    if warm_count == 0:
        # No device has a warm baseline — return sentinel
        needed = MIN_SAMPLES
        return [{
            "_warning": "insufficient_data",
            "min_samples_required": needed,
            "current_max_n": max(
                (store.get_baseline(obs.get(device_col, "?"), m) or {}).get("n", 0)
                for obs in observations
                for m in metric_cols
            ),
            "recommendation": (
                f"Baseline not yet warm. Continue polling the API until each device "
                f"has at least {needed} observations. Z-scores will activate automatically."
            ),
        }]

    return anomalies
