"""olav_netops.first_run.check_netops_data — §7.1 empty-state check.

The netops-owned side of the ``olav.first_run_checks`` contract
(dev_docs/99 §7.1/§7.6): deterministic, local-only, returns a user-facing
finding or None. Covers the full state ladder:
1. netops workspace not deployed → None (not installed, nothing to say)
2. workspace deployed, main DB missing → init finding (/netops_init)
3. DB exists, netops.devices table absent → init finding
4. table exists, zero rows → import finding
5. table has rows → None (healthy — verified live against this repo's
   348-device DB during implementation)
6. undeterminable (DB unreadable) → None, never raises
"""

from __future__ import annotations

import duckdb
import pytest

pytest.importorskip("olav_netops", reason="olav-netops not installed")

from olav.core import config as config_mod
from olav_netops.first_run import check_netops_data


def _deploy_workspace(tmp_path) -> None:
    (tmp_path / ".olav" / "workspace" / "netops").mkdir(parents=True)


def test_workspace_not_deployed_returns_none(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert check_netops_data() is None


def test_db_missing_returns_init_finding(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _deploy_workspace(tmp_path)
    monkeypatch.setattr(config_mod, "MAIN_DB_PATH", tmp_path / "nonexistent.duckdb")

    finding = check_netops_data()
    assert finding is not None
    assert "/netops_init" in finding


def test_table_absent_returns_init_finding(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _deploy_workspace(tmp_path)
    db = tmp_path / "main.duckdb"
    duckdb.connect(str(db)).close()  # empty DB, no netops schema
    monkeypatch.setattr(config_mod, "MAIN_DB_PATH", db)

    finding = check_netops_data()
    assert finding is not None
    assert "/netops_init" in finding


def test_zero_devices_returns_import_finding(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _deploy_workspace(tmp_path)
    db = tmp_path / "main.duckdb"
    with duckdb.connect(str(db)) as conn:
        conn.execute("CREATE SCHEMA netops")
        conn.execute("CREATE TABLE netops.devices (hostname VARCHAR)")
    monkeypatch.setattr(config_mod, "MAIN_DB_PATH", db)

    finding = check_netops_data()
    assert finding is not None
    assert "no device data" in finding
    assert "/netops_init" not in finding  # init already done — different advice


def test_devices_present_returns_none(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _deploy_workspace(tmp_path)
    db = tmp_path / "main.duckdb"
    with duckdb.connect(str(db)) as conn:
        conn.execute("CREATE SCHEMA netops")
        conn.execute("CREATE TABLE netops.devices (hostname VARCHAR)")
        conn.execute("INSERT INTO netops.devices VALUES ('R1')")
    monkeypatch.setattr(config_mod, "MAIN_DB_PATH", db)

    assert check_netops_data() is None


def test_unreadable_db_returns_none_never_raises(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _deploy_workspace(tmp_path)
    corrupt = tmp_path / "corrupt.duckdb"
    corrupt.write_text("this is not a duckdb file", encoding="utf-8")
    monkeypatch.setattr(config_mod, "MAIN_DB_PATH", corrupt)

    assert check_netops_data() is None  # silent, no exception
