"""Governance — NetBox CSV export/import lifecycle (dev_docs/71 Ch10).

Covers:
* The export script + import dry-run share an exact column contract
* import_netbox_csv dry-run rejects rows with empty required fields
* import_netbox_csv dry-run rejects invalid IPv4 + bad status
* --write flag errors out (stub) — protects against accidental real push
* Happy path: a hand-crafted clean CSV passes all validations
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
EXPORT_SCRIPT = REPO / "olav-netops" / ".olav" / "workspace" / "netops" / "export_netbox_csv" / "run.py"
IMPORT_SCRIPT = REPO / "src" / "olav" / "data" / "workspace" / "services" / "import_netbox_csv" / "run.py"


def _read_columns_from(script: Path) -> tuple[str, ...]:
    """Extract EXPECTED_COLUMNS tuple (or the equivalent in the export
    SQL) from the script source.  Best-effort literal scan."""
    text = script.read_text(encoding="utf-8")
    # import script declares EXPECTED_COLUMNS = (...)
    if "EXPECTED_COLUMNS" in text:
        start = text.index("EXPECTED_COLUMNS = (")
        end = text.index(")", start)
        chunk = text[start:end + 1]
        # Eval the literal tuple to get the column list back.
        return eval(chunk.split("=", 1)[1].strip())  # noqa: S307 — test-local trusted source
    raise RuntimeError(f"{script}: no EXPECTED_COLUMNS marker found")


def test_import_script_exists() -> None:
    assert IMPORT_SCRIPT.exists(), f"missing: {IMPORT_SCRIPT}"


def test_export_script_exists() -> None:
    assert EXPORT_SCRIPT.exists(), f"missing: {EXPORT_SCRIPT}"


def test_import_expected_columns_are_the_full_contract() -> None:
    """The 11-column contract documented in
    `netbox_csv_export.guide.yaml` is exact.  If you bump the export
    schema, bump this test too."""
    cols = _read_columns_from(IMPORT_SCRIPT)
    assert cols == (
        "name", "device_role", "manufacturer", "device_type",
        "primary_ip4", "platform", "site", "status", "tenant",
        "snapshot_id", "exported_at",
    )


def _run_import(csv_path: Path, *extra: str, report: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable, str(IMPORT_SCRIPT),
            "--csv", str(csv_path),
            "--report", str(report),
            *extra,
        ],
        capture_output=True, text=True,
    )


def _happy_csv(tmp_path: Path) -> Path:
    """2-row valid CSV."""
    p = tmp_path / "happy.csv"
    p.write_text(
        "name,device_role,manufacturer,device_type,primary_ip4,platform,site,status,tenant,snapshot_id,exported_at\n"
        "R1,border,Juniper,vsrx,10.0.0.1,juniper_junos,lab,active,team-a,snap_x,2026-05-15T16:47:05+10:00\n"
        "R2,border,Cisco,ISRV,10.0.0.2,cisco_ios,lab,active,team-a,snap_x,2026-05-15T16:47:05+10:00\n",
        encoding="utf-8",
    )
    return p


def test_happy_csv_dry_run_passes(tmp_path: Path) -> None:
    csv_p = _happy_csv(tmp_path)
    report = tmp_path / "report.md"
    res = _run_import(csv_p, report=report)
    assert res.returncode == 0, res.stdout + res.stderr
    body = report.read_text(encoding="utf-8")
    assert "✅ ALL ROWS VALID" in body
    assert "would_create | —" in body
    # 2 rows, both would create
    assert body.count("would_create") == 2


def test_missing_required_field_skipped(tmp_path: Path) -> None:
    p = tmp_path / "bad.csv"
    p.write_text(
        "name,device_role,manufacturer,device_type,primary_ip4,platform,site,status,tenant,snapshot_id,exported_at\n"
        "R1,border,Juniper,,10.0.0.1,juniper_junos,lab,active,t,snap_x,2026-05-15T16:47:05+10:00\n",
        encoding="utf-8",
    )
    res = _run_import(p, report=tmp_path / "r.md")
    assert res.returncode == 1, res.stdout
    assert "device_type" in (tmp_path / "r.md").read_text()


def test_invalid_ipv4_rejected(tmp_path: Path) -> None:
    p = tmp_path / "badip.csv"
    p.write_text(
        "name,device_role,manufacturer,device_type,primary_ip4,platform,site,status,tenant,snapshot_id,exported_at\n"
        "R1,border,Juniper,vsrx,not-an-ip,juniper_junos,lab,active,t,snap_x,2026-05-15T16:47:05+10:00\n",
        encoding="utf-8",
    )
    res = _run_import(p, report=tmp_path / "r.md")
    assert res.returncode == 1
    assert "primary_ip4" in (tmp_path / "r.md").read_text()


def test_unknown_status_rejected(tmp_path: Path) -> None:
    p = tmp_path / "badstatus.csv"
    p.write_text(
        "name,device_role,manufacturer,device_type,primary_ip4,platform,site,status,tenant,snapshot_id,exported_at\n"
        "R1,border,Juniper,vsrx,10.0.0.1,juniper_junos,lab,SOMETIME,t,snap_x,2026-05-15T16:47:05+10:00\n",
        encoding="utf-8",
    )
    res = _run_import(p, report=tmp_path / "r.md")
    assert res.returncode == 1
    assert "status" in (tmp_path / "r.md").read_text()


def test_write_flag_is_stub(tmp_path: Path) -> None:
    """--write must fail loud until the real POST path ships."""
    csv_p = _happy_csv(tmp_path)
    res = _run_import(csv_p, "--write", report=tmp_path / "r.md")
    assert res.returncode == 2
    assert "not implemented" in (res.stderr + res.stdout).lower()


def test_missing_csv_errors_helpfully(tmp_path: Path) -> None:
    res = _run_import(tmp_path / "nope.csv", report=tmp_path / "r.md")
    assert res.returncode == 1
    assert "CSV not found" in (res.stderr + res.stdout)


def test_column_drift_surfaced_in_report(tmp_path: Path) -> None:
    """If a future export adds a column, the import report flags it."""
    p = tmp_path / "drift.csv"
    p.write_text(
        # missing exported_at, has an extra column
        "name,device_role,manufacturer,device_type,primary_ip4,platform,site,status,tenant,snapshot_id,vrf\n"
        "R1,border,Juniper,vsrx,10.0.0.1,juniper_junos,lab,active,t,snap_x,default\n",
        encoding="utf-8",
    )
    res = _run_import(p, report=tmp_path / "r.md")
    body = (tmp_path / "r.md").read_text()
    assert "Header mismatch" in body
    assert "missing" in body and "extra" in body
