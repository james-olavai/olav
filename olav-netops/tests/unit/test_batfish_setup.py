"""Batfish self-service: reachability check + guided setup + snapshot default.

software-understands-human gap: on a machine with no Batfish, the simulator
should tell the user how to get one (start a container / point at a remote
API — both via the admin agent) instead of leaking a pybatfish stack trace.
And a caller shouldn't have to hunt for a snapshot id — default to the latest
snapshot that actually has configs. All network-free (probe a closed port).
"""
from __future__ import annotations

import importlib

import pytest

bq = importlib.import_module("olav_netops.core.sim.batfish_q")


def test_endpoint_env_wins(monkeypatch):
    monkeypatch.setenv("OLAV_BATFISH_HOST", "bf.example.com")
    monkeypatch.setenv("OLAV_BATFISH_HTTP_PORT", "19996")
    host, port, ssl = bq._batfish_endpoint()
    assert host == "bf.example.com" and port == 19996 and ssl is False


def test_endpoint_defaults(monkeypatch):
    for v in ("OLAV_BATFISH_HOST", "OLAV_BATFISH_HTTP_PORT", "OLAV_BATFISH_SSL"):
        monkeypatch.delenv(v, raising=False)
    host, port, _ = bq._batfish_endpoint()
    assert host == "localhost" and port == 9996


def test_reachable_false_for_closed_port():
    # 9 = discard; nothing listens on this loopback port in CI.
    assert bq._batfish_reachable("127.0.0.1", 9, timeout=0.5) is False


def test_setup_hint_names_the_fixes():
    hint = bq.batfish_setup_hint("localhost", 9996)
    assert "batfish/allinone" in hint
    assert "--agent services" in hint       # container lifecycle → services agent
    assert "admin agent" in hint            # remote-endpoint config → admin
    assert "OLAV_BATFISH_HOST" in hint


def test_batfish_q_unreachable_returns_guided_error(monkeypatch):
    monkeypatch.setenv("OLAV_BATFISH_HOST", "127.0.0.1")
    monkeypatch.setenv("OLAV_BATFISH_HTTP_PORT", "9")   # closed
    bq._BF_SESSION = None
    # explicit snapshot_id → skip the DB default lookup; exercise the reach gate
    r = bq.batfish_q.func(snapshot_id="snap_x", question="fileParseStatus")
    assert r["status"] == "error"
    assert r["batfish_reachable"] is False
    assert "not reachable" in r["message"] and "--agent services" in r["message"]


# --- batfish_capability arg coercion (small models pass a regex string) -------

import duckdb as _duckdb  # noqa: E402

cap = importlib.import_module("olav_netops.core.sim.batfish_capability")
_cfg = importlib.import_module("olav.core.config")


@pytest.fixture
def _devices_db(tmp_path, monkeypatch):
    """A tiny netops.devices so batfish_capability's query has data.

    batfish_capability does `from olav.core.config import MAIN_DB_PATH` at call
    time, so patching the config module (via its object, not a string path —
    the submodule name is shadowed by the re-exported tool) is enough.
    """
    db = tmp_path / "main.duckdb"
    con = _duckdb.connect(str(db))
    con.execute("CREATE SCHEMA netops")
    con.execute("CREATE TABLE netops.devices (hostname VARCHAR, platform VARCHAR)")
    con.execute("INSERT INTO netops.devices VALUES ('r1','cisco_ios'),('r2','cisco_ios'),('r3','arista_eos')")
    con.close()
    monkeypatch.setattr(_cfg, "MAIN_DB_PATH", db, raising=False)
    return db


@pytest.mark.parametrize("wildcard", [".*", "*", "all", "%", "", None])
def test_capability_wildcard_devices_means_all(_devices_db, wildcard):
    r = cap.batfish_capability.func(devices=wildcard)
    assert r["status"] == "ok", r
    assert r["device_count"] == 3, f"{wildcard!r} should mean ALL devices"


def test_capability_bare_hostname_string_becomes_one(_devices_db):
    r = cap.batfish_capability.func(devices="r1")   # a str, not a list
    assert r["status"] == "ok"
    assert r["device_count"] == 1
