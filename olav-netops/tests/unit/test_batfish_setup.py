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
    assert "docker run" in hint and "batfish/allinone" in hint
    assert "admin" in hint.lower()          # points at the admin agent
    assert "OLAV_BATFISH_HOST" in hint or "batfish" in hint.lower()


def test_batfish_q_unreachable_returns_guided_error(monkeypatch):
    monkeypatch.setenv("OLAV_BATFISH_HOST", "127.0.0.1")
    monkeypatch.setenv("OLAV_BATFISH_HTTP_PORT", "9")   # closed
    bq._BF_SESSION = None
    # explicit snapshot_id → skip the DB default lookup; exercise the reach gate
    r = bq.batfish_q.func(snapshot_id="snap_x", question="fileParseStatus")
    assert r["status"] == "error"
    assert r["batfish_reachable"] is False
    assert "not reachable" in r["message"] and "docker run" in r["message"]
