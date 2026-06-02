"""analyze_thresholds.py — Statistical Analysis for Smart Threshold Recommendations.

Runs percentile distribution analysis on any numeric metric extracted via SQL.
Returns P50/P75/P90/P95/P99 statistics plus evidence-based threshold suggestions.

Usage pattern (HMITL):
  1. LLM calls analyze_thresholds with a metric_query that yields a `value` column
  2. Tool returns distribution + recommended Warning/Critical thresholds
  3. LLM presents recommendations to user for confirmation/adjustment
  4. User confirms → LLM uses confirmed values in save_profile / append_jobs
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_PREVIEW_LIMIT = 5


class AnalyzeThresholdsInput(BaseModel):
    """Input schema for analyze_thresholds tool."""
    metric_query: str = Field(
        description=(
            "SQL query that extracts a single numeric column aliased as 'value'. "
            "Example: \"SELECT CAST(json_extract(parsed_data, '$.cpu_usage') AS DOUBLE) AS value "
            "FROM parsed_outputs WHERE command ILIKE '%cpu%'\" . "
            "The query MUST produce a column named 'value'. "
            "Do NOT add LIMIT — the tool wraps it in a CTE for statistics."
        )
    )
    metric_name: str = Field(
        description="Human-readable metric label, e.g. 'CPU utilization (%)', 'Memory usage (%)'"
    )
    higher_is_worse: bool = Field(
        default=True,
        description=(
            "True when high values are bad (CPU%, memory%, latency). "
            "False when low values are bad (free memory MB, available bandwidth)."
        )
    )
    unit: str = Field(
        default="",
        description="Optional unit label for display, e.g. '%', 'ms', 'MB'"
    )
    db_path: str | None = Field(
        default=None,
        description="Path to DuckDB file. Leave None to use OLAV default MAIN_DB_PATH."
    )


def analyze_thresholds(
    metric_query: str,
    metric_name: str,
    higher_is_worse: bool = True,
    unit: str = "",
    db_path: str | None = None,
) -> dict:
    """Run percentile distribution analysis on a numeric metric to suggest alert thresholds.

    Args:
        metric_query:     SQL extracting a numeric `value` column (no LIMIT needed).
        metric_name:      Human label for the metric, e.g. "CPU utilization (%)".
        higher_is_worse:  True = high values trigger alerts (CPU, memory).
                          False = low values trigger alerts (free space).
        unit:             Display unit, e.g. "%", "ms".
        db_path:          DuckDB path. Defaults to OLAV MAIN_DB_PATH.

    Returns:
        Dict with:
          - metric_name, unit, sample_count
          - distribution: {min, max, mean, stddev, p50, p75, p90, p95, p99}
          - recommendations: {warning_threshold, critical_threshold, reasoning}
          - sample_values: up to 5 representative data points
          - error: error message if query failed (allows LLM to retry)
    """

    if db_path is None:
        try:
            from olav.core.config import MAIN_DB_PATH
            db_path = str(MAIN_DB_PATH)
        except ImportError:
            return {"error": "db_path required when OLAV config is unavailable"}

    # Wrap user query in CTE — strip trailing semicolons first
    inner = metric_query.rstrip().rstrip(";")
    stats_query = f"""
WITH _metric AS ({inner}),
_filtered AS (
    SELECT value::DOUBLE AS value FROM _metric WHERE value IS NOT NULL
)
SELECT
    count(*)                                                         AS sample_count,
    min(value)                                                       AS min_val,
    max(value)                                                       AS max_val,
    round(avg(value), 2)                                             AS mean,
    round(stddev(value), 2)                                          AS stddev,
    round(percentile_cont(0.50) WITHIN GROUP (ORDER BY value), 2)   AS p50,
    round(percentile_cont(0.75) WITHIN GROUP (ORDER BY value), 2)   AS p75,
    round(percentile_cont(0.90) WITHIN GROUP (ORDER BY value), 2)   AS p90,
    round(percentile_cont(0.95) WITHIN GROUP (ORDER BY value), 2)   AS p95,
    round(percentile_cont(0.99) WITHIN GROUP (ORDER BY value), 2)   AS p99
FROM _filtered
"""

    sample_query = f"""
WITH _metric AS ({inner}),
_filtered AS (
    SELECT value::DOUBLE AS value FROM _metric WHERE value IS NOT NULL
)
SELECT value FROM _filtered ORDER BY value DESC LIMIT {_PREVIEW_LIMIT}
"""

    try:
        import duckdb
        with duckdb.connect(str(db_path), read_only=True) as conn:
            row = conn.execute(stats_query).fetchone()
            if row is None or row[0] == 0:
                return {
                    "metric_name": metric_name,
                    "unit": unit,
                    "sample_count": 0,
                    "distribution": None,
                    "recommendations": None,
                    "message": (
                        "No data found for this metric. "
                        "Cannot suggest thresholds without baseline data. "
                        "Try broadening the query or check if data has been collected."
                    ),
                    "sample_values": [],
                }

            (sample_count, min_val, max_val, mean, stddev,
             p50, p75, p90, p95, p99) = row

            sample_rows = conn.execute(sample_query).fetchall()
            sample_values = [round(float(r[0]), 2) for r in sample_rows if r[0] is not None]

    except Exception as exc:
        return {
            "metric_name": metric_name,
            "error": str(exc),
            "hint": "Fix metric_query and retry. Query must return a column named 'value'.",
        }

    distribution = {
        "min": float(min_val) if min_val is not None else None,
        "max": float(max_val) if max_val is not None else None,
        "mean": float(mean) if mean is not None else None,
        "stddev": float(stddev) if stddev is not None else None,
        "p50": float(p50) if p50 is not None else None,
        "p75": float(p75) if p75 is not None else None,
        "p90": float(p90) if p90 is not None else None,
        "p95": float(p95) if p95 is not None else None,
        "p99": float(p99) if p99 is not None else None,
    }

    # --- Threshold recommendation logic ---
    # For "higher is worse": Warning = P90, Critical = P95 (capped at max-10%)
    # For "lower is worse": Warning = P25, Critical = P10
    recommendations = _suggest_thresholds(distribution, higher_is_worse, unit, sample_count)

    return {
        "metric_name": metric_name,
        "unit": unit,
        "sample_count": int(sample_count),
        "distribution": distribution,
        "recommendations": recommendations,
        "sample_values": sample_values,
    }


def _suggest_thresholds(
    dist: dict,
    higher_is_worse: bool,
    unit: str,
    sample_count: int,
) -> dict:
    """Generate threshold recommendations with reasoning from distribution stats."""
    u = unit or ""

    def fmt(v):
        if v is None:
            return "N/A"
        return f"{v}{u}"

    if higher_is_worse:
        # Alert when value is too HIGH
        warn = dist["p90"]
        crit = dist["p95"]
        # Safety: don't set alert below the mean + 1 stddev
        if dist["mean"] is not None and dist["stddev"] is not None:
            floor = round(dist["mean"] + dist["stddev"], 2)
            if warn is not None and warn < floor:
                warn = floor
            if crit is not None and crit < floor:
                crit = round(floor * 1.1, 2)
        reasoning = (
            f"Based on {sample_count} samples: "
            f"P90={fmt(dist['p90'])}, P95={fmt(dist['p95'])}, P99={fmt(dist['p99'])}. "
            f"Warning at P90 catches the top 10% of values; "
            f"Critical at P95 catches the top 5% (likely anomalies). "
            f"Mean={fmt(dist['mean'])}, max={fmt(dist['max'])}."
        )
        operator = ">="
    else:
        # Alert when value is too LOW
        warn = dist["p25"] if "p25" in dist else dist["p50"]
        crit = dist["p10"] if "p10" in dist else dist.get("p50")
        # Use p50 and p25 as proxies when p10/p25 not available
        warn = dist["p50"]
        crit = round(dist["p50"] * 0.7, 2) if dist["p50"] else None
        reasoning = (
            f"Based on {sample_count} samples: "
            f"P50={fmt(dist['p50'])}, mean={fmt(dist['mean'])}, min={fmt(dist['min'])}. "
            f"Warning when below P50; Critical when significantly below baseline."
        )
        operator = "<="

    return {
        "warning_threshold": warn,
        "critical_threshold": crit,
        "operator": operator,
        "reasoning": reasoning,
        "confidence": "high" if sample_count >= 100 else ("medium" if sample_count >= 20 else "low"),
        "confidence_note": (
            f"{'High' if sample_count >= 100 else 'Medium' if sample_count >= 20 else 'Low'} confidence "
            f"({sample_count} data points). "
            + ("Recommend collecting more data before finalizing." if sample_count < 20 else "")
        ),
    }


AnalyzeThresholdsInput.model_rebuild()


if __name__ == "__main__":
    import json as _json
    import sys as _sys
    _args = _json.loads(_sys.stdin.read() or "{}")
    print(_json.dumps(analyze_thresholds(**_args), default=str))
