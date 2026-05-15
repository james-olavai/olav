#!/usr/bin/env python3
"""import_netbox_csv — validate (and someday push) a NetBox-shaped CSV.

Symmetric counterpart to ``netops/export_netbox_csv``.  Reads
``exports/netbox_devices.csv`` (or any path passed in), validates the
shape against the canonical column contract, and produces a per-row
dry-run report — what each row would create / update / skip if we
were really POSTing to NetBox.

dev_docs/71 Ch10b semantics:

* Default: ``--dry-run`` (validate + report, no HTTP).  Safe for CI.
* ``--write`` is a stub — errors out with "real-write path requires
  registered NetBox service + auth".  Will be wired up once the
  services agent learns ``netbox_dcim_create_device`` / etc. tools.

Validations (dry-run):

1. CSV opens, has the 11 expected columns in the expected order
2. No required-field is empty (name / site / device_role /
   manufacturer / device_type / primary_ip4)
3. ``primary_ip4`` parses as IPv4 (allows blank — interfaceless devs)
4. ``status`` is one of NetBox's allowed device statuses (active /
   planned / staged / failed / inventory / decommissioning / offline)
5. ``snapshot_id`` non-empty (provenance watermark)
6. ``exported_at`` parses as ISO-8601

Output: a Markdown report under
``exports/reports/netbox_import_dry_run.md`` listing each row's verdict
+ a top-line summary.

Usage::

    /import_netbox_csv                                # default file
    /import_netbox_csv --csv exports/my.csv
    /import_netbox_csv --report exports/reports/foo.md
    /import_netbox_csv --write                        # NotImplemented
"""
from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass, field
from datetime import datetime
from ipaddress import IPv4Address
from pathlib import Path


EXPECTED_COLUMNS = (
    "name", "device_role", "manufacturer", "device_type", "primary_ip4",
    "platform", "site", "status", "tenant", "snapshot_id", "exported_at",
)
REQUIRED_NONEMPTY = ("name", "device_role", "manufacturer", "device_type",
                     "site", "status", "snapshot_id", "exported_at")
ALLOWED_STATUSES = frozenset({
    "active", "planned", "staged", "failed",
    "inventory", "decommissioning", "offline",
})


@dataclass
class RowVerdict:
    line_no: int
    name: str
    verdict: str       # "would_create" | "would_update_metadata" | "skip"
    errors: list[str] = field(default_factory=list)


def _validate_row(row: dict, line_no: int) -> RowVerdict:
    errs: list[str] = []
    for col in REQUIRED_NONEMPTY:
        if not (row.get(col) or "").strip():
            errs.append(f"required column '{col}' is empty")

    # IPv4 parse if non-empty
    ip = (row.get("primary_ip4") or "").strip()
    if ip:
        try:
            IPv4Address(ip)
        except ValueError as exc:
            errs.append(f"primary_ip4 '{ip}' is not a valid IPv4: {exc}")

    status = (row.get("status") or "").strip().lower()
    if status and status not in ALLOWED_STATUSES:
        errs.append(
            f"status '{status}' not in NetBox-allowed set "
            f"{sorted(ALLOWED_STATUSES)}"
        )

    exported_at = (row.get("exported_at") or "").strip()
    if exported_at:
        try:
            datetime.fromisoformat(exported_at)
        except ValueError as exc:
            errs.append(f"exported_at '{exported_at}' not ISO-8601: {exc}")

    verdict = "skip" if errs else "would_create"
    return RowVerdict(
        line_no=line_no,
        name=row.get("name", "").strip() or "(unknown)",
        verdict=verdict,
        errors=errs,
    )


def _render_report(verdicts: list[RowVerdict], csv_path: Path,
                   col_check: str) -> str:
    n_total = len(verdicts)
    n_skip = sum(1 for v in verdicts if v.verdict == "skip")
    n_ok = n_total - n_skip
    overall = "✅ ALL ROWS VALID" if n_skip == 0 else "❌ VALIDATION FAILURES"

    lines = [
        "# NetBox CSV Dry-Run Import Report",
        "",
        f"**Source CSV**: `{csv_path}`",
        f"**Total rows**: {n_total}",
        f"**Would create**: {n_ok}",
        f"**Skipped (validation errors)**: {n_skip}",
        f"**Verdict**: {overall}",
        "",
        "## Column header check",
        "",
        col_check,
        "",
        "## Per-row verdicts",
        "",
        "| Line | Name | Verdict | Notes |",
        "|---|---|---|---|",
    ]
    for v in verdicts:
        notes = "; ".join(v.errors) if v.errors else "—"
        lines.append(f"| {v.line_no} | {v.name} | {v.verdict} | {notes} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="import_netbox_csv",
        description="Validate + dry-run import a NetBox-shaped CSV.",
    )
    parser.add_argument(
        "--csv", default="exports/netbox_devices.csv",
        help="Source CSV (default: exports/netbox_devices.csv)",
    )
    parser.add_argument(
        "--report", default="exports/reports/netbox_import_dry_run.md",
        help="Output markdown report path",
    )
    parser.add_argument(
        "--write", action="store_true",
        help="(STUB) actually POST to NetBox — not yet implemented; errors out.",
    )
    args = parser.parse_args()

    if args.write:
        print(
            "❌ --write is not implemented yet — needs registered NetBox "
            "service + per-tier write tools.  Use --dry-run (default) for "
            "validation. (Tracked: Ch10b deferred work in dev_docs/71.)",
            file=sys.stderr,
        )
        return 2

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"❌ CSV not found: {csv_path}", file=sys.stderr)
        print(
            "   Run `olav --agent netops \"/export_netbox_csv\"` first.",
            file=sys.stderr,
        )
        return 1

    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            print("❌ empty CSV (no header row)", file=sys.stderr)
            return 1
        actual_cols = tuple(reader.fieldnames)
        if actual_cols == EXPECTED_COLUMNS:
            col_check = (
                f"✓ Header columns match the canonical contract "
                f"({len(EXPECTED_COLUMNS)} columns, exact order)."
            )
        else:
            missing = [c for c in EXPECTED_COLUMNS if c not in actual_cols]
            extra = [c for c in actual_cols if c not in EXPECTED_COLUMNS]
            order_drift = (
                tuple(c for c in actual_cols if c in EXPECTED_COLUMNS)
                != tuple(c for c in EXPECTED_COLUMNS if c in actual_cols)
            )
            bullets = []
            if missing:
                bullets.append(f"- missing: `{missing}`")
            if extra:
                bullets.append(f"- extra: `{extra}`")
            if order_drift:
                bullets.append("- present columns are out of canonical order")
            col_check = (
                "⚠ Header mismatch vs canonical contract:\n"
                + "\n".join(bullets)
                + f"\n\nExpected: `{list(EXPECTED_COLUMNS)}`\n"
                f"Actual:   `{list(actual_cols)}`"
            )

        verdicts = [
            _validate_row(row, line_no=i + 2)  # +2: 1-indexed + header line
            for i, row in enumerate(reader)
        ]

    report = _render_report(verdicts, csv_path, col_check)
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")

    n_total = len(verdicts)
    n_skip = sum(1 for v in verdicts if v.verdict == "skip")
    n_ok = n_total - n_skip

    print(f"✓ dry-run complete: {n_total} rows | {n_ok} would create | {n_skip} skipped")
    print(f"  source : {csv_path}")
    print(f"  report : {report_path}")
    if n_skip:
        # Surface first 3 failure rows inline so operators don't have to
        # open the file just to see what's wrong.
        print(f"  first failures:")
        for v in verdicts:
            if v.verdict == "skip":
                print(f"    line {v.line_no} ({v.name}): {'; '.join(v.errors)}")
                if not any(False for _ in []):  # placeholder
                    pass
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
