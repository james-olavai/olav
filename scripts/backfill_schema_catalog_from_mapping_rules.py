#!/usr/bin/env python3
"""Backfill schema_catalog.fields openconfig_path from mapping_rules.

This migration script is intended for Phase 3 recovery. It enriches existing
schema_catalog field metadata with mapping paths derived from mapping_rules
using exact (platform/vendor, command, field) matching.

Default mode is dry-run. Use --apply to persist changes.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import duckdb


@dataclass
class BackfillStats:
    total_rows: int = 0
    changed_rows: int = 0
    total_fields: int = 0
    mapped_fields_added: int = 0
    already_mapped_fields: int = 0
    missing_mapping_fields: int = 0
    mapping_key_conflicts: int = 0


def _norm(value: str | None) -> str:
    if value is None:
        return ""
    return value.strip().lower()


def _load_mapping_index(con: duckdb.DuckDBPyConnection) -> tuple[dict[tuple[str, str, str], tuple[str, str]], int]:
    rows = con.execute(
        "SELECT vendor, command, src_field, oc_path, confidence FROM mapping_rules"
    ).fetchall()
    index: dict[tuple[str, str, str], tuple[str, str]] = {}
    conflicts = 0

    for vendor, command, src_field, oc_path, confidence in rows:
        key = (_norm(vendor), _norm(command), _norm(src_field))
        value = (str(oc_path), str(confidence))
        existing = index.get(key)
        if existing is None:
            index[key] = value
            continue
        if existing[0] != value[0]:
            conflicts += 1

    return index, conflicts


def run_backfill(db_path: Path, apply: bool) -> dict[str, Any]:
    stats = BackfillStats()
    con = duckdb.connect(str(db_path), read_only=False)

    try:
        mapping_index, conflicts = _load_mapping_index(con)
        stats.mapping_key_conflicts = conflicts

        rows = con.execute(
            "SELECT source_type, source_name, platform, fields FROM schema_catalog"
        ).fetchall()

        updates: list[tuple[str, str, str, str]] = []

        for source_type, source_name, platform, fields_raw in rows:
            stats.total_rows += 1

            fields = fields_raw
            if isinstance(fields_raw, str):
                try:
                    fields = json.loads(fields_raw)
                except json.JSONDecodeError:
                    fields = []

            if not isinstance(fields, list):
                fields = []

            field_list = cast(list[Any], fields)
            row_changed = False

            for item in field_list:
                if not isinstance(item, dict):
                    continue
                item_map = cast(dict[str, Any], item)
                stats.total_fields += 1

                existing_path = item_map.get("openconfig_path")
                if isinstance(existing_path, str) and existing_path.strip():
                    stats.already_mapped_fields += 1
                    continue

                field_name_val = item_map.get("name")
                field_name = field_name_val.strip() if isinstance(field_name_val, str) else ""
                if not field_name:
                    stats.missing_mapping_fields += 1
                    continue

                key = (_norm(str(platform)), _norm(str(source_name)), _norm(field_name))
                mapping = mapping_index.get(key)
                if mapping is None:
                    stats.missing_mapping_fields += 1
                    continue

                oc_path, confidence = mapping
                item["openconfig_path"] = oc_path
                item["mapping_confidence"] = confidence
                item["mapping_source"] = "mapping_rules_backfill"
                row_changed = True
                stats.mapped_fields_added += 1

            if row_changed:
                stats.changed_rows += 1
                updates.append(
                    (
                        json.dumps(field_list, ensure_ascii=True),
                        str(source_type),
                        str(source_name),
                        str(platform),
                    )
                )

        if apply and updates:
            con.execute("BEGIN")
            try:
                con.executemany(
                    """
                    UPDATE schema_catalog
                    SET fields = ?
                    WHERE source_type = ? AND source_name = ? AND platform = ?
                    """,
                    updates,
                )
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise

        return {
            "db_path": str(db_path),
            "apply": apply,
            "stats": {
                "total_rows": stats.total_rows,
                "changed_rows": stats.changed_rows,
                "total_fields": stats.total_fields,
                "mapped_fields_added": stats.mapped_fields_added,
                "already_mapped_fields": stats.already_mapped_fields,
                "missing_mapping_fields": stats.missing_mapping_fields,
                "mapping_key_conflicts": stats.mapping_key_conflicts,
            },
        }
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill schema_catalog mapping paths from mapping_rules")
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(".olav/databases/main.duckdb"),
        help="Path to DuckDB database",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist changes to schema_catalog (default is dry-run)",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional path to write JSON report",
    )
    args = parser.parse_args()

    report = run_backfill(args.db, apply=args.apply)
    stats = report["stats"]

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"Schema Catalog Mapping Backfill ({mode})")
    print(f"DB: {report['db_path']}")
    print(
        "Rows: "
        f"total={stats['total_rows']}, changed={stats['changed_rows']}"
    )
    print(
        "Fields: "
        f"total={stats['total_fields']}, "
        f"added={stats['mapped_fields_added']}, "
        f"already_mapped={stats['already_mapped_fields']}, "
        f"missing_mapping={stats['missing_mapping_fields']}"
    )
    print(f"Mapping key conflicts observed: {stats['mapping_key_conflicts']}")

    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
        print(f"JSON report: {args.json_out}")

    if not args.apply:
        print("No database changes were written (dry-run mode).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
