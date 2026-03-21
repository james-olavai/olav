#!/usr/bin/env python3
"""Report remaining OpenConfig mapping gaps from schema_catalog.

This script lists commands/fields that still lack openconfig_path metadata,
so Phase 3 recovery can prioritize mapping completion.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, TypedDict, cast

import duckdb


class GapCommand(TypedDict):
    platform: str
    source_name: str
    total_fields: int
    mapped_fields: int
    missing_fields: int
    mapped_pct: float


def _load_fields(fields_raw: Any) -> list[dict[str, Any]]:
    data = fields_raw
    if isinstance(fields_raw, str):
        try:
            data = json.loads(fields_raw)
        except json.JSONDecodeError:
            data = []
    if not isinstance(data, list):
        return []
    items = cast(list[Any], data)
    out: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict):
            out.append(cast(dict[str, Any], item))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Report schema_catalog fields missing openconfig_path")
    parser.add_argument("--db", type=Path, default=Path(".olav/databases/main.duckdb"))
    parser.add_argument(
        "--csv-out",
        type=Path,
        default=Path("tmp/openconfig_mapping_gaps.csv"),
        help="CSV output path",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=Path("tmp/openconfig_mapping_gaps_summary.json"),
        help="JSON summary output path",
    )
    parser.add_argument("--limit", type=int, default=200, help="Print top N gap commands")
    args = parser.parse_args()

    con = duckdb.connect(str(args.db), read_only=True)
    try:
        rows = con.execute(
            "SELECT source_type, source_name, platform, fields FROM schema_catalog"
        ).fetchall()
    finally:
        con.close()

    gap_rows: list[dict[str, str]] = []
    command_stats: dict[tuple[str, str], dict[str, int]] = {}

    for source_type, source_name, platform, fields_raw in rows:
        fields = _load_fields(fields_raw)
        key = (str(platform), str(source_name))
        stat = command_stats.setdefault(key, {"total": 0, "mapped": 0, "missing": 0})

        for item in fields:
            field_name_val = item.get("name")
            field_name = field_name_val.strip() if isinstance(field_name_val, str) else ""
            if not field_name:
                continue

            stat["total"] += 1
            oc_path_val = item.get("openconfig_path")
            oc_path = oc_path_val.strip() if isinstance(oc_path_val, str) else ""
            if oc_path:
                stat["mapped"] += 1
                continue

            stat["missing"] += 1
            gap_rows.append(
                {
                    "source_type": str(source_type),
                    "platform": str(platform),
                    "source_name": str(source_name),
                    "field_name": field_name,
                }
            )

    ranked: list[GapCommand] = sorted(
        (
            {
                "platform": platform,
                "source_name": source_name,
                "total_fields": stat["total"],
                "mapped_fields": stat["mapped"],
                "missing_fields": stat["missing"],
                "mapped_pct": round((100.0 * stat["mapped"] / stat["total"]), 2)
                if stat["total"] > 0
                else 0.0,
            }
            for (platform, source_name), stat in command_stats.items()
        ),
        key=lambda x: (x["missing_fields"], x["total_fields"]),
        reverse=True,
    )

    args.csv_out.parent.mkdir(parents=True, exist_ok=True)
    with args.csv_out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["source_type", "platform", "source_name", "field_name"])
        writer.writeheader()
        writer.writerows(gap_rows)

    summary: dict[str, Any] = {
        "db_path": str(args.db),
        "total_gap_fields": len(gap_rows),
        "total_commands": len(command_stats),
        "commands_with_gaps": sum(1 for x in ranked if int(x["missing_fields"]) > 0),
        "top_gap_commands": ranked[: max(0, args.limit)],
        "csv_output": str(args.csv_out),
    }

    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(summary, indent=2, ensure_ascii=True), encoding="utf-8")

    print("OpenConfig Mapping Gap Report")
    print(f"DB: {args.db}")
    print(f"Total gap fields: {summary['total_gap_fields']}")
    print(f"Commands with gaps: {summary['commands_with_gaps']}/{summary['total_commands']}")
    print(f"CSV: {args.csv_out}")
    print(f"JSON: {args.json_out}")
    print("Top gap commands:")
    top_commands = ranked[: min(20, len(ranked))]
    for item in top_commands:
        print(
            f"- {item['platform']} | {item['source_name']} | "
            f"missing={item['missing_fields']}/{item['total_fields']} mapped={item['mapped_pct']}%"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
