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


def test_write_flag_needs_endpoint(tmp_path: Path) -> None:
    """--write without --endpoint (and no services.yaml) errors out."""
    csv_p = _happy_csv(tmp_path)
    res = subprocess.run(
        [sys.executable, str(IMPORT_SCRIPT), "--csv", str(csv_p),
         "--report", str(tmp_path / "r.md"), "--write",
         "--token", "dummy"],
        capture_output=True, text=True, cwd=tmp_path,  # cwd has no services.yaml
    )
    assert res.returncode == 2
    assert "endpoint" in (res.stderr + res.stdout).lower()


def test_write_flag_needs_token(tmp_path: Path) -> None:
    """--write without --token (and no $NETBOX_TOKEN) errors out."""
    csv_p = _happy_csv(tmp_path)
    env = {k: v for k, v in __import__("os").environ.items() if k != "NETBOX_TOKEN"}
    res = subprocess.run(
        [sys.executable, str(IMPORT_SCRIPT), "--csv", str(csv_p),
         "--report", str(tmp_path / "r.md"), "--write",
         "--endpoint", "http://localhost:9999"],
        capture_output=True, text=True, env=env, cwd=tmp_path,
    )
    assert res.returncode == 2
    assert "token" in (res.stderr + res.stdout).lower()


def test_write_path_calls_netbox_api(tmp_path: Path, monkeypatch) -> None:
    """In-process test of NetboxClient: mock urlopen, verify the
    lookup-or-create chain hits the right endpoints in the right order."""
    import sys as _sys
    _sys.path.insert(0, str(IMPORT_SCRIPT.parent))
    import importlib
    if "run" in _sys.modules:
        del _sys.modules["run"]
    run_mod = importlib.import_module("run")

    calls: list[tuple[str, str, dict | None]] = []
    next_id = {"v": 100}

    class _MockResp:
        def __init__(self, status: int, body: dict | None):
            self.status = status
            self._body = body
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self): return __import__("json").dumps(self._body).encode("utf-8") if self._body is not None else b""

    def _fake_urlopen(req, timeout=None):
        method = req.get_method()
        url = req.full_url
        data = None
        if req.data:
            data = __import__("json").loads(req.data.decode())
        calls.append((method, url, data))
        # GET = no hits; POST = returns the created object with a fresh id.
        if method == "GET":
            return _MockResp(200, {"count": 0, "results": []})
        if method == "POST":
            next_id["v"] += 1
            return _MockResp(201, {"id": next_id["v"], "name": (data or {}).get("name", "x")})
        return _MockResp(405, {"detail": "method not allowed"})

    monkeypatch.setattr(run_mod.urllib.request, "urlopen", _fake_urlopen)
    client = run_mod.NetboxClient("http://nb.test", "tok")
    row = {
        "name": "R1", "site": "lab", "manufacturer": "Juniper",
        "device_type": "vsrx", "device_role": "border",
        "status": "active",
    }
    verdict, notes = run_mod._push_row(client, row)
    assert verdict == "created", notes
    # 5-step chain: site GET → site POST → manuf GET → manuf POST → ...
    methods = [c[0] for c in calls]
    assert methods.count("GET") == 5     # one per resource
    assert methods.count("POST") == 5    # creation per resource
    # First POST should be the site
    first_post = next(c for c in calls if c[0] == "POST")
    assert "sites" in first_post[1]
    assert first_post[2]["name"] == "lab"


def test_slugify_round_trip() -> None:
    """Slugs need to be safe for NetBox (lowercase, dash-separated alnum)."""
    import sys as _sys
    _sys.path.insert(0, str(IMPORT_SCRIPT.parent))
    if "run" in _sys.modules:
        del _sys.modules["run"]
    run_mod = __import__("importlib").import_module("run")
    assert run_mod._slugify("DC1") == "dc1"
    assert run_mod._slugify("border-leaf 01") == "border-leaf-01"
    assert run_mod._slugify("juniper-vsrx") == "juniper-vsrx"
    assert run_mod._slugify("***") == "unnamed"


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
