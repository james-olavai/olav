"""audit_runner.py — Execute Mode tool for olav-audit skill.

Single @tool function that runs a complete audit pipeline:
  1. load_audit_config         reads config/AUDIT_X/audit.yaml
  2. query parsed_outputs      pull fresh data from DuckDB (read-only)
  3. run_audit_reduce          config-driven rule evaluation        [Reduce]
  4. generate_audit_report     format markdown from results
  5. write to disk             exports/reports/audit_*.md
  6. write KB                  CRITICAL findings → .olav/knowledge/alerts/

NOTE: olav-audit is a read-only governance layer.
Data collection (take_snapshot) is owned by olav-config.
If no data is available, instruct the user to run take_snapshot via olav-config.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Path resolution — ensures cross-skill imports work
# ---------------------------------------------------------------------------


def _find_project_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


_PROJECT_ROOT = _find_project_root()
_SKILL_DIR = Path(__file__).resolve().parent.parent
_CONFIG_DIR = _SKILL_DIR / "config"
_DEFAULT_OUTPUT_DIR = _PROJECT_ROOT / "exports" / "reports"

# Make audit_engine importable (same tools/ directory)
_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

# Now import the engine
import schema_inspector as _si  # noqa: E402
from audit_engine import (  # noqa: E402
    _build_target_def,
    generate_audit_report,
    load_audit_config,
    run_audit_analyze,
    run_audit_reduce,
)

# ---------------------------------------------------------------------------
# Helper: query DuckDB for today's parsed_outputs
# ---------------------------------------------------------------------------


def _query_parsed_outputs(devices: list[str] | None = None) -> list[dict[str, Any]]:
    """Pull today's parsed_outputs from DuckDB.

    Args:
        devices: Optional filter by device names.

    Returns:
        List of row dicts: {device_name, command, parsed_data}.
    """
    try:
        # Prefer the framework database layer
        from olav.core.database import get_database

        db = get_database()
        conn = db.conn
    except Exception:
        # Fallback: open main DuckDB directly
        try:
            import duckdb

            db_path = _PROJECT_ROOT / ".olav" / "db" / "main.duckdb"
            if not db_path.exists():
                # Try alternative paths
                for alt in [
                    _PROJECT_ROOT / ".olav" / "databases" / "main.duckdb",
                    _PROJECT_ROOT / "data" / "main.duckdb",
                ]:
                    if alt.exists():
                        db_path = alt
                        break
                        with duckdb.connect(str(db_path)) as conn:
        except Exception as exc:
            logger.error("Cannot connect to DuckDB: %s", exc)
            return []

    try:
        where_clauses = ["snapshot_id = (SELECT MAX(snapshot_id) FROM parsed_outputs)"]
        params: list[Any] = []

        if devices:
            placeholders = ", ".join(["?" for _ in devices])
            where_clauses.append(f"device_name IN ({placeholders})")
            params.extend(devices)

        sql = (
            "SELECT device_name, command, parsed_data "
            "FROM parsed_outputs "
            f"WHERE {' AND '.join(where_clauses)} "
            "ORDER BY device_name, command"
        )
        rows = conn.execute(sql, params).fetchall()

        results = []
        for row in rows:
            results.append(
                {
                    "device_name": row[0],
                    "command": row[1],
                    "parsed_data": row[2],
                }
            )
        return results

    except Exception as exc:
        logger.warning("Failed to query parsed_outputs: %s", exc)
        return []


# ---------------------------------------------------------------------------
# run_audit — main tool
# ---------------------------------------------------------------------------


@tool
def run_audit(
    audit_name: str,
    devices: list[str] | None = None,
    output_dir: str | None = None,
) -> dict[str, Any]:
    """Run a named audit: snapshot → SQL query → rule engine → markdown report.

    This is the main Execute Mode tool. It handles the full pipeline:
      1. Load and validate audit config from config/AUDIT_<name>/audit.yaml
      2. Query parsed_outputs      read today's data from DuckDB (no collection)
      3. Query DuckDB parsed_outputs for today's data
      4. Evaluate all rules (config-driven rule engine)
      5. Write markdown report to exports/reports/

    Args:
        audit_name: Directory name under config/ (e.g. "AUDIT_HEALTH").
                    Call list_audits() first to see available options.
        devices:    Optional list of device names to inspect.
                    None = all devices from Nornir inventory.
        output_dir: Output directory for the report file.
                    None = exports/reports/ (default).

    Returns:
        {
          "status": "success",
          "audit_name": "AUDIT_HEALTH",
          "report_path": "/path/to/exports/reports/audit_health_20260220_143000.md",
          "overall_health": "healthy" | "warning" | "critical",
          "device_count": 6,
          "finding_count": 3,
          "summary": "3 findings across 6 devices. Overall: WARNING."
        }

    Example usage:
        run_audit("AUDIT_HEALTH")
        run_audit("AUDIT_HEALTH", devices=["R1", "R2"])
        run_audit("AUDIT_INTF_COMPLIANCE", devices=None, output_dir="/tmp/reports")
    """
    # --- Step 1: Load + validate audit config ---
    try:
        config = load_audit_config(audit_name)
    except (FileNotFoundError, ValueError) as e:
        return {"status": "error", "message": str(e)}

    logger.info(
        "run_audit: '%s' (%s) — %d rules, intents: %s",
        audit_name,
        config.type,
        len(config.rules),
        config.collect.intents,
    )

    # --- Step 2: Query parsed_outputs (read-only) ---
    sql_rows = _query_parsed_outputs(devices=devices)

    if not sql_rows:
        # Before giving up: check if the config has raw_contains/raw_not_contains
        # rules AND today's raw snapshot files exist — those audits work without
        # parsed_outputs (audit_engine discovers devices from the snapshot dir).
        _today = datetime.now().strftime("%Y-%m-%d")
        _raw_dir = _PROJECT_ROOT / "exports" / "snapshots" / _today / "raw"
        _has_raw_rules = any(
            r.condition in ("raw_contains", "raw_not_contains") for r in config.rules
        )
        _has_raw_files = _raw_dir.exists() and any(d for d in _raw_dir.iterdir() if d.is_dir())
        if not (_has_raw_rules and _has_raw_files):
            return {
                "status": "no_data",
                "message": (
                    "No parsed_outputs found for today (CURRENT_DATE). "
                    "Data collection is owned by olav-config. "
                    "Ask the user to run take_snapshot() via the olav-config agent, "
                    "or check if Cron A (daily 02:00) is scheduled. "
                    "Command: ask olav-config to run take_snapshot"
                ),
            }
        logger.info(
            "run_audit '%s': no parsed_outputs, but %d raw_contains rule(s) and "
            "raw snapshot dir found — proceeding with raw-file-only evaluation.",
            audit_name,
            sum(1 for r in config.rules if r.condition in ("raw_contains", "raw_not_contains")),
        )

    logger.info("Queried %d parsed_output rows for audit", len(sql_rows))

    # --- Step 3: Pre-warm LLM field resolution cache ---
    # Build device_rows_map from sql_rows (same structure schema_inspector expects)
    _device_rows_map: dict[str, list[tuple[str, list[dict]]]] = {}
    for _row in sql_rows:
        _dev = _row.get("device_name", "unknown")
        _cmd = (_row.get("command") or "").lower()
        _pd = _row.get("parsed_data") or []
        if isinstance(_pd, str):
            try:
                _pd = json.loads(_pd)
            except Exception:
                _pd = []
        _device_rows_map.setdefault(_dev, []).append((_cmd, _pd))

    _target_defs = {rule.target: _build_target_def(rule) for rule in config.rules}
    _platforms = _si.get_device_platforms()
    _prewarm_stats = _si.prewarm_resolution_cache(
        _device_rows_map,
        _target_defs,
        device_platforms=_platforms,
        llm=None,  # auto-loaded from workspace settings
        audit_config=config,  # rules carry expected/allowed/forbidden for value normalisation
    )
    logger.info("Field resolution cache prewarm: %s", _prewarm_stats)

    # --- Step 4: Rule engine (Reduce phase) ---
    try:
        result = run_audit_reduce(sql_rows, config)
    except Exception as exc:
        logger.exception("run_audit_reduce failed")
        return {"status": "error", "message": f"Rule engine error: {exc}"}

    # --- Step 4.5: LLM Analyze phase (per-device + global correlation) ---
    try:
        run_audit_analyze(result, config)  # attaches result['_analysis'] in-place
    except Exception as exc:
        logger.warning("run_audit_analyze failed (non-fatal): %s", exc)

    # --- Step 5: Generate report ---
    try:
        report_md = generate_audit_report(result, config, devices_requested=devices)
    except Exception as exc:
        logger.exception("generate_audit_report failed")
        return {"status": "error", "message": f"Report generation error: {exc}"}

    # --- Step 6: Write to disk ---
    out_dir = Path(output_dir) if output_dir else _DEFAULT_OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename_tpl = config.output.filename_pattern
    filename = filename_tpl.replace("{timestamp}", timestamp_str)
    report_path = out_dir / filename

    try:
        report_path.write_text(report_md, encoding="utf-8")
        logger.info("Audit report written: %s (%d bytes)", report_path, report_path.stat().st_size)
    except Exception as exc:
        logger.exception("Failed to write report")
        return {"status": "error", "message": f"Cannot write report: {exc}"}

    # --- Step 6.5: Write CRITICAL findings to KB ---
    critical_count_val = result.get("critical_count", 0)
    if critical_count_val > 0:
        try:
            _config_tools = str(_PROJECT_ROOT / ".olav" / "skills" / "olav-config" / "tools")
            if _config_tools not in sys.path:
                sys.path.insert(0, _config_tools)
            from kb_manager import add_knowledge_entry  # noqa: F401

            _title = f"[{audit_name}] Critical findings " + datetime.now().strftime("%Y-%m-%d")
            # Summarise critical findings for KB entry
            _critical_lines = [
                f"Audit: {audit_name} ({config.type})",
                f"Devices: {result.get('device_count', 0)}",
                f"Critical: {critical_count_val}",
                f"Report: {report_path}",
                "",
                "## Critical Findings",
            ]
            for dev_result in result.get("device_results", []):
                for finding in dev_result.get("findings", []):
                    if finding.get("severity", "").lower() == "critical":
                        _critical_lines.append(
                            f"- [{finding.get('device', '?')}] "
                            f"{finding.get('rule_name', '?')}: "
                            f"{finding.get('detail', '')}"
                        )
            add_knowledge_entry.func(
                title=_title,
                content="\n".join(_critical_lines),
                tags=["audit", "critical", audit_name.lower().replace(" ", "-")],
            )
            logger.info("CRITICAL findings written to KB: %s", _title)
        except Exception as exc:
            logger.warning("KB write failed (non-fatal): %s", exc)

    # --- Build summary ---
    overall = result.get("overall_health", "unknown")
    device_count = result.get("device_count", 0)
    finding_count = result.get("finding_count", 0)
    critical_count = result.get("critical_count", 0)
    warning_count = result.get("warning_count", 0)

    summary = f"{finding_count} findings across {device_count} devices. Overall: {overall.upper()}."
    if critical_count > 0:
        summary += f" ({critical_count} critical, {warning_count} warning)"

    return {
        "status": "success",
        "audit_name": audit_name,
        "audit_type": config.type,
        "report_path": str(report_path),
        "overall_health": overall,
        "overall_health_score": result.get("overall_health_score", 0),
        "device_count": device_count,
        "finding_count": finding_count,
        "critical_count": critical_count,
        "warning_count": warning_count,
        "summary": summary,
        "recommendations": result.get("recommendations", [])[:5],  # top 5
    }
