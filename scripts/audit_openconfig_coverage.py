#!/usr/bin/env python3
"""Audit OpenConfig mapping coverage from schema_catalog.

This script computes Phase 3 gate metrics directly from DuckDB and returns
an explicit pass/fail result based on configurable thresholds.

Usage:
    uv run python scripts/audit_openconfig_coverage.py
    uv run python scripts/audit_openconfig_coverage.py --db .olav/databases/main.duckdb --json-out tmp/openconfig_coverage.json
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, cast

import duckdb


@dataclass
class CoverageThresholds:
    command_coverage_pct: float = 95.0
    field_coverage_pct: float = 90.0


@dataclass
class CoverageSummary:
    total_fields: int
    mapped_fields: int
    total_platform_commands: int
    mapped_platform_commands: int
    field_coverage_pct: float
    command_coverage_pct: float


def _normalize_field_entry(entry: Any) -> tuple[str | None, str | None]:
    """Return (source_field_name, mapping_path) from one schema field item.

    Supports multiple key names to stay forward-compatible with migration states.
    """
    if not isinstance(entry, dict):
        return (None, None)
    entry_map: Mapping[str, Any] = cast(Mapping[str, Any], entry)

    source_name = None
    for key in ("raw_key", "src_field", "name", "field", "source_field"):
        value = entry_map.get(key)
        if isinstance(value, str) and value.strip():
            source_name = value.strip()
            break

    mapping_path = None
    for key in ("openconfig_path", "oc_path", "canonical_path", "canonical_name"):
        value = entry_map.get(key)
        if isinstance(value, str) and value.strip():
            mapping_path = value.strip()
            break

    return (source_name, mapping_path)


def _safe_percent(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round((100.0 * numerator) / denominator, 2)


def audit_openconfig_coverage(
    db_path: Path,
    thresholds: CoverageThresholds,
) -> dict[str, Any]:
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        rows = con.execute(
            "SELECT platform, source_name, fields FROM schema_catalog"
        ).fetchall()
    finally:
        con.close()

    total_fields = 0
    mapped_fields = 0

    total_platform_commands = 0
    mapped_platform_commands = 0

    per_platform: dict[str, dict[str, int | float]] = {}

    for platform, source_name, fields_json in rows:
        total_platform_commands += 1

        fields = fields_json
        if isinstance(fields_json, str):
            try:
                fields = json.loads(fields_json)
            except json.JSONDecodeError:
                fields = []

        if not isinstance(fields, list):
            fields = []
        field_entries = cast(list[Any], fields)

        command_total = 0
        command_mapped = 0

        for entry in field_entries:
            source_field, mapping_path = _normalize_field_entry(entry)
            if source_field is None:
                continue
            command_total += 1
            if mapping_path is not None:
                command_mapped += 1

        total_fields += command_total
        mapped_fields += command_mapped

        if command_total > 0 and command_mapped > 0:
            mapped_platform_commands += 1

        stats = per_platform.setdefault(
            str(platform),
            {
                "commands": 0,
                "mapped_commands": 0,
                "fields": 0,
                "mapped_fields": 0,
            },
        )
        stats["commands"] += 1
        stats["mapped_commands"] += 1 if (command_total > 0 and command_mapped > 0) else 0
        stats["fields"] += command_total
        stats["mapped_fields"] += command_mapped

    summary = CoverageSummary(
        total_fields=total_fields,
        mapped_fields=mapped_fields,
        total_platform_commands=total_platform_commands,
        mapped_platform_commands=mapped_platform_commands,
        field_coverage_pct=_safe_percent(mapped_fields, total_fields),
        command_coverage_pct=_safe_percent(mapped_platform_commands, total_platform_commands),
    )

    for platform_stats in per_platform.values():
        mapped_fields_count = int(platform_stats["mapped_fields"])
        total_fields_count = int(platform_stats["fields"])
        mapped_commands_count = int(platform_stats["mapped_commands"])
        total_commands_count = int(platform_stats["commands"])
        platform_stats["field_coverage_pct"] = _safe_percent(
            mapped_fields_count, total_fields_count
        )
        platform_stats["command_coverage_pct"] = _safe_percent(
            mapped_commands_count, total_commands_count
        )

    failed_checks: list[str] = []
    if summary.command_coverage_pct < thresholds.command_coverage_pct:
        failed_checks.append(
            f"command_coverage_pct {summary.command_coverage_pct}% < threshold {thresholds.command_coverage_pct}%"
        )
    if summary.field_coverage_pct < thresholds.field_coverage_pct:
        failed_checks.append(
            f"field_coverage_pct {summary.field_coverage_pct}% < threshold {thresholds.field_coverage_pct}%"
        )

    return {
        "db_path": str(db_path),
        "thresholds": asdict(thresholds),
        "summary": asdict(summary),
        "passed": len(failed_checks) == 0,
        "failed_checks": failed_checks,
        "platforms": per_platform,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit OpenConfig mapping coverage for Phase 3 gate")
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(".olav/databases/main.duckdb"),
        help="Path to DuckDB database",
    )
    parser.add_argument(
        "--command-threshold",
        type=float,
        default=95.0,
        help="Minimum platform-command mapping coverage percentage",
    )
    parser.add_argument(
        "--field-threshold",
        type=float,
        default=90.0,
        help="Minimum field mapping coverage percentage",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional path to write full JSON report",
    )
    args = parser.parse_args()

    thresholds = CoverageThresholds(
        command_coverage_pct=args.command_threshold,
        field_coverage_pct=args.field_threshold,
    )
    report = audit_openconfig_coverage(args.db, thresholds)

    summary = report["summary"]
    print("OpenConfig Coverage Audit")
    print(f"DB: {report['db_path']}")
    print(
        "Coverage: "
        f"fields {summary['mapped_fields']}/{summary['total_fields']} ({summary['field_coverage_pct']}%), "
        f"platform-commands {summary['mapped_platform_commands']}/{summary['total_platform_commands']} "
        f"({summary['command_coverage_pct']}%)"
    )
    print(
        "Thresholds: "
        f"field>={report['thresholds']['field_coverage_pct']}%, "
        f"command>={report['thresholds']['command_coverage_pct']}%"
    )

    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
        print(f"JSON report: {args.json_out}")

    if report["passed"]:
        print("Gate: PASS")
        return 0

    print("Gate: FAIL")
    for check in report["failed_checks"]:
        print(f"- {check}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
