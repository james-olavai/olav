"""anomaly_engine.py — Statistical anomaly detection (no hardcoded thresholds).

Replaces fixed-threshold queries with per-device adaptive baselines.
A device that normally runs at 80% CPU is healthy; one that jumps from
20% to 65% is flagged — the anomaly is *relative* to its own history.

Supported methods
-----------------
zscore      Per-group Z-score via scipy.stats.zscore.
            Groups by group_col (default: device_name) so each device's
            baseline is computed independently.
            Flags rows where |z| > threshold (default 2.5 ≈ 99th percentile).

isolation   Scikit-learn IsolationForest over one or more metric columns.
            Vendor-agnostic, works on any numerical feature set.
            contamination = threshold (0–0.5, proportion of expected anomalies).

Job YAML schema (type: anomaly)
--------------------------------
  - name: CPU_Anomaly
    type: anomaly
    severity: Warning
    section_prompt: >
      ...
    anomaly:
      method:      zscore        # zscore | isolation
      threshold:   2.5           # z-score cutoff | IsolationForest contamination
      group_col:   device_name   # partition key for zscore (omit for isolation)
      metric_cols: [cpu]         # numeric columns to analyse
      query: >                   # DuckDB SQL — must return metric_cols + created_at
        SELECT device_name,
               CAST(json_extract(parsed_data,'$.five_sec_cpu') AS DOUBLE) AS cpu,
               snapshot_id, created_at
        FROM parsed_outputs
        WHERE command ILIKE '%processes cpu%'
          AND created_at >= NOW() - INTERVAL :window

Raw fallback (RAW-05)
---------------------

Profile jobs can set ``raw_fallback: true`` to opt into automatic
raw-output probing. When this engine returns zero findings, the calling
``map_engine`` (see ``map_engine._raw_fallback_probe``) re-runs the
query's ``command ILIKE '...'`` pattern against
``netops.raw_output_store`` and emits ``_warning: raw_only_data``
sentinel findings — one per (device, command) whose TextFSM parser
failed. This prevents a parse failure from silently looking like a
clean bill of health; the operator sees "N devices produced raw output
for this command but it wasn't parseable" instead of an empty section.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas as pd

import duckdb

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public entry point (called by map_engine for type: anomaly jobs)
# ---------------------------------------------------------------------------


def run_anomaly_job(
    conn: duckdb.DuckDBPyConnection,
    job: dict,
    window: str,
    max_findings: int = 100,
    resolution_minutes: int = 1440,
    emit_sources: bool = False,
) -> list[dict]:
    """Execute an anomaly-detection job. Returns list of anomalous rows with scores.

    Args:
        conn:                Open DuckDB connection.
        job:                 Job definition dict from Profile YAML.
        window:              Time window string, e.g. "7d", "24h".
        max_findings:        Maximum rows to return.
        resolution_minutes:  Expected interval between samples (minutes).
                             Derived from profile `snapshot_resolution`.
                             Used to compute minimum required sample count for
                             statistical validity.
                             Default: 1440 (daily SSH snapshots).

    Returns:
        List of dicts — each is a detected anomaly with extra fields:
          z_score / anomaly_score, anomaly_method, metric_col (zscore mode)
          or anomaly_score_raw (isolation mode).
        May include a single sentinel dict with `_warning: insufficient_data`
        when the sample count is too low for reliable detection.
    """
    import numpy as np
    import pandas as pd

    cfg = job.get("anomaly", {})
    method = cfg.get("method", "zscore").lower()
    threshold = float(cfg.get("threshold", 2.5))
    group_col = cfg.get("group_col", "device_name")
    metric_cols: list[str] = cfg.get("metric_cols", [])
    query: str = cfg.get("query", "")

    if not query:
        logger.warning("anomaly job %r has no query — skipping", job.get("name"))
        return []

    # ── Resolve time window into a cutoff datetime ──────────────────────────
    cutoff = _parse_window_to_cutoff(window)
    sql = _substitute_window(query, cutoff)

    try:
        result = conn.execute(sql)
        columns = [desc[0] for desc in result.description]
        rows = result.fetchall()
    except Exception as exc:
        logger.error("anomaly_engine: SQL failed for job %r: %s", job.get("name"), exc)
        return []

    if not rows:
        return []

    df = pd.DataFrame(rows, columns=columns)

    # ── Resolution-aware minimum sample guard ──────────────────────────────
    # Statistical methods need sufficient data points per device.
    # Rule: need at least 10 samples OR enough to cover 50% of the window.
    window_minutes = _parse_window_to_minutes(window)
    expected_samples_per_device = max(1, window_minutes // max(1, resolution_minutes))
    min_samples = max(10, expected_samples_per_device // 2)

    # Check per-group sample count if group_col available
    if group_col in df.columns:
        group_counts = df.groupby(group_col).size()
        thin_groups = group_counts[group_counts < min_samples]
        total_groups = len(group_counts)
        if len(thin_groups) == total_groups:
            # ALL devices have insufficient data — bail with informative warning
            max_seen = int(group_counts.max()) if len(group_counts) else 0
            logger.info(
                "anomaly_engine: %r — insufficient samples for all devices "
                "(need %d/device, max seen: %d). resolution=%dmin, window=%s",
                job.get("name"), min_samples, max_seen, resolution_minutes, window,
            )
            return [{
                "_warning": "insufficient_data",
                "min_samples_required": min_samples,
                "max_samples_seen": max_seen,
                "resolution_minutes": resolution_minutes,
                "window": window,
                "recommendation": (
                    f"Increase snapshot frequency (current: every ~{resolution_minutes}min) "
                    f"or extend time window beyond '{window}' to accumulate "
                    f"≥{min_samples} snapshots/device."
                ),
            }]

    # ── Infer metric_cols if not specified ─────────────────────────────────
    if not metric_cols:
        metric_cols = [
            c for c in df.columns
            if c not in (group_col, "snapshot_id", "created_at", "id")
            and pd.api.types.is_numeric_dtype(df[c])
        ]
        if not metric_cols:
            logger.warning("anomaly job %r: no numeric metric columns found", job.get("name"))
            return []

    # Drop rows with all-NaN metrics
    df = df.dropna(subset=metric_cols, how="all")
    if df.empty:
        return []

    # ── Dispatch to detection method ────────────────────────────────────────
    if method == "zscore":
        anomalies = _zscore_detect(df, metric_cols, group_col, threshold)
    elif method == "isolation":
        anomalies = _isolation_detect(df, metric_cols, threshold)
    else:
        logger.warning("anomaly_engine: unknown method %r — defaulting to zscore", method)
        anomalies = _zscore_detect(df, metric_cols, group_col, threshold)

    # Convert back to list[dict] for JSON serialisation, trim to max_findings
    records = anomalies.head(max_findings).to_dict(orient="records")

    # Sanitise numpy/pandas types for JSON
    sanitised = [_sanitise_row(r) for r in records]

    # ARCH-11 Phase 1: attach `_source` so render_report can print a
    # [src: ...] citation suffix. Only runs when the caller opts in via
    # `emit_sources` — default behaviour is unchanged.
    if emit_sources:
        for i, row in enumerate(sanitised):
            row["_source"] = {
                "type": "anomaly",
                "table": "netops.parsed_outputs",
                "snapshot_id": row.get("snapshot_id"),
                "device": row.get(group_col),
                "row_index": i,
            }

    return sanitised


# ---------------------------------------------------------------------------
# Detection strategies
# ---------------------------------------------------------------------------


def _zscore_detect(
    df: pd.DataFrame,
    metric_cols: list[str],
    group_col: str,
    threshold: float,
) -> pd.DataFrame:
    """Per-group Z-score detection.

    Each device's baseline is computed from its own history within the
    time window — so a permanently high-CPU core router won't trigger,
    but a sudden spike on a quiet access switch will.

    Returns rows where ANY metric_col exceeds the threshold.
    """
    import numpy as np
    import pandas as pd
    from scipy import stats

    result_frames = []

    for metric in metric_cols:
        col_data = df[metric].astype(float)

        if group_col in df.columns:
            # Per-group Z-score
            def _group_zscore(x: pd.Series) -> pd.Series:
                if len(x) < 2:
                    # Single snapshot: cannot compute baseline — skip (return NaN)
                    return pd.Series([float("nan")] * len(x), index=x.index)
                z = stats.zscore(x.fillna(x.median()), nan_policy="omit")
                return pd.Series(z, index=x.index)

            z_col = df.groupby(group_col)[metric].transform(_group_zscore)
        else:
            # Global Z-score
            z_col = stats.zscore(col_data.fillna(col_data.median()), nan_policy="omit")

        sub = df.copy()
        sub["z_score"] = z_col
        sub["metric_col"] = metric
        sub["anomaly_method"] = "zscore"
        sub["threshold_used"] = threshold
        flagged = sub[sub["z_score"].abs() > threshold].copy()
        flagged = flagged.sort_values("z_score", key=abs, ascending=False)
        result_frames.append(flagged)

    if not result_frames:
        return df.head(0)

    combined = pd.concat(result_frames).drop_duplicates()
    return combined.sort_values("z_score", key=abs, ascending=False)


def _isolation_detect(
    df: pd.DataFrame,
    metric_cols: list[str],
    contamination: float,
) -> pd.DataFrame:
    """IsolationForest multi-variable anomaly detection.

    Works on ANY set of numerical features without per-column baselines.
    Good for detecting multi-dimensional outliers that zscore would miss
    individually (e.g. CPU=50% and Mem=70% simultaneously, both
    just under threshold — but combined, statistically unusual).
    """
    import numpy as np
    from sklearn.ensemble import IsolationForest

    contamination = max(0.01, min(0.5, contamination))  # IsolationForest constraint

    X = df[metric_cols].fillna(0).to_numpy(dtype=float)
    if X.shape[0] < 4:
        # Too few samples for IsolationForest
        logger.warning("isolation_detect: too few samples (%d) — skipping", X.shape[0])
        return df.head(0)

    iso = IsolationForest(
        contamination=contamination,
        n_estimators=100,
        random_state=42,
        n_jobs=1,
    )
    labels = iso.fit_predict(X)          # -1 = anomaly, 1 = normal
    scores = iso.decision_function(X)    # lower = more anomalous

    result = df.copy()
    result["anomaly_score_raw"] = scores
    result["anomaly_method"] = "isolation"
    result["threshold_used"] = contamination
    flagged = result[labels == -1].copy()
    return flagged.sort_values("anomaly_score_raw", ascending=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _substitute_window(query: str, cutoff: datetime) -> str:
    """Replace INTERVAL :window / :window with a literal ISO timestamp string.

    Anomaly queries often need to fetch many historical snapshots (not just
    the cutoff boundary check), so we substitute as a literal string rather
    than using DuckDB parameter binding — this keeps the query simple and
    lets the DB optimise the full time scan.
    """
    cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")
    sql = re.sub(
        r"NOW\(\)\s*-\s*INTERVAL\s*:window",
        f"TIMESTAMPTZ '{cutoff_str}'",
        query,
        flags=re.IGNORECASE,
    )
    sql = re.sub(r":window", f"TIMESTAMPTZ '{cutoff_str}'", sql, flags=re.IGNORECASE)
    return sql


def _parse_window_to_cutoff(window: str) -> datetime:
    window = window.strip().lower()
    if window.endswith("h"):
        delta = timedelta(hours=float(window[:-1]))
    elif window.endswith("m"):
        delta = timedelta(minutes=float(window[:-1]))
    elif window.endswith("d"):
        delta = timedelta(days=float(window[:-1]))
    else:
        delta = timedelta(hours=1)
    return datetime.now(tz=UTC) - delta


def _parse_window_to_minutes(window: str) -> int:
    """Convert window string to total minutes for sample count estimation."""
    window = window.strip().lower()
    if window.endswith("w"):
        return int(float(window[:-1]) * 10080)
    elif window.endswith("h"):
        return int(float(window[:-1]) * 60)
    elif window.endswith("m"):
        return int(float(window[:-1]))
    elif window.endswith("d"):
        return int(float(window[:-1]) * 1440)
    return 60  # default 1h


def _sanitise_row(row: dict) -> dict:
    """Convert numpy/pandas scalars to native Python types for JSON."""
    import math

    clean: dict[str, Any] = {}
    for k, v in row.items():
        if hasattr(v, "item"):          # numpy scalar
            v = v.item()
        if isinstance(v, float) and math.isnan(v):
            v = None
        if isinstance(v, datetime):
            v = v.isoformat()
        clean[k] = v
    return clean
