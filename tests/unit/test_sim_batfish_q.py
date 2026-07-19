"""TDD (dev_docs/73 §2.1, plan Phase 2): `batfish_q` tool — generic
Batfish question runner.  Lazy snapshot init, session caching,
graceful errors, optional differential mode.

All pybatfish calls are mocked; this is a unit test of the wrapper
logic.  Real Batfish reachability is verified by the Phase 2 smoke
step (live call against localhost:9996).
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("pybatfish", reason="pybatfish not installed — install olav-netops[sim]")


# ---------------------------------------------------------------------------
# Fixture: clean module state between tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_batfish_session_cache():
    """Each test gets a fresh module-level session cache."""
    mod_key = "olav_netops.core.sim.batfish_q"
    if mod_key in sys.modules:
        sys.modules[mod_key]._BF_SESSION = None
        sys.modules[mod_key]._LOADED_SNAPSHOTS = set()
    yield


@pytest.fixture(autouse=True)
def _batfish_always_reachable(monkeypatch):
    """The tool fail-fasts on a socket probe to the Batfish endpoint before
    touching the (mocked) Session — stub it so these unit tests don't depend
    on a live Batfish container on the host.

    importlib, not `import … as`: the sim package re-exports the batfish_q
    StructuredTool as a package attribute, shadowing the submodule name."""
    import importlib

    bq = importlib.import_module("olav_netops.core.sim.batfish_q")
    monkeypatch.setattr(bq, "_batfish_reachable", lambda *a, **kw: True)


# ---------------------------------------------------------------------------
# Mock-builder helpers
# ---------------------------------------------------------------------------

def _make_mock_session_with_question(question_name: str, rows: list[dict]):
    """Build a mocked pybatfish.Session whose ``bf.q.<question_name>(...)``
    returns an .answer() that .frame()s to a DataFrame with ``rows``."""
    import pandas as pd

    mock_question = MagicMock(name=f"question_{question_name}")
    mock_answer = MagicMock(name="answer")
    mock_answer.frame.return_value = pd.DataFrame(rows)
    mock_question.return_value.answer.return_value = mock_answer

    mock_q_namespace = MagicMock(name="bf.q")
    setattr(mock_q_namespace, question_name, mock_question)

    mock_session = MagicMock(name="Session")
    mock_session.q = mock_q_namespace
    return mock_session, mock_question


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_api_json_batfish_block_reaches_endpoint_resolution(tmp_path, monkeypatch):
    """Regression: _batfish_endpoint read `getattr(get_config(), "_data", {})`
    — ConfigLoader has no `_data` attr, so the documented api.json `batfish`
    block was dead code (only OLAV_BATFISH_* env ever worked) and the
    setup_hint's 'ask the admin agent to set the batfish host' was
    unfulfillable. Wire a real api.json through the real ConfigLoader."""
    import importlib
    import json

    import olav.core.config as config_mod

    cfg_dir = tmp_path / ".olav" / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "api.json").write_text(
        json.dumps({"batfish": {"host": "bf.example.net", "port": 19996, "ssl": True}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(config_mod, "_CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(config_mod.ConfigLoader, "_loaded", False)
    monkeypatch.setattr(config_mod.ConfigLoader, "_instance", None)
    monkeypatch.setattr(config_mod, "_config", None)
    for var in ("OLAV_BATFISH_HOST", "OLAV_BATFISH_HTTP_PORT", "OLAV_BATFISH_SSL"):
        monkeypatch.delenv(var, raising=False)

    bq = importlib.import_module("olav_netops.core.sim.batfish_q")
    host, port, ssl = bq._batfish_endpoint()
    assert (host, port, ssl) == ("bf.example.net", 19996, True)


def test_question_routing_and_dataframe_to_rows():
    """`batfish_q(question="bgpSessionStatus", args={"nodes": "R1|R3"})`
    must call ``bf.q.bgpSessionStatus(nodes="R1|R3").answer().frame()``
    and return the rows as ``list[dict]``."""
    mock_session, mock_question = _make_mock_session_with_question(
        "bgpSessionStatus",
        [{"Node": "R1", "Remote_Node": "R3", "Established_Status": "ESTABLISHED"}],
    )

    with (
        patch("pybatfish.client.session.Session", return_value=mock_session),
        patch(
            "olav_netops.core.sim.batfish_q._init_snapshot_if_needed",
            return_value=None,
        ) as mock_init,
    ):
        from olav.core.sim.batfish_q import batfish_q
        result = batfish_q.invoke({
            "snapshot_id": "snap_test_1",
            "question": "bgpSessionStatus",
            "q_args": {"nodes": "R1|R3"},
        })

    assert mock_init.called, "must lazy-init the snapshot"
    mock_question.assert_called_once_with(nodes="R1|R3")
    assert result["status"] == "ok"
    assert result["row_count"] == 1
    assert result["rows"] == [
        {"Node": "R1", "Remote_Node": "R3", "Established_Status": "ESTABLISHED"}
    ]


def test_snapshot_init_lazy_and_cached():
    """First call with new snapshot_id triggers init; second call with same id
    must NOT re-export configs."""
    mock_session, _ = _make_mock_session_with_question(
        "bgpSessionStatus", [{"Node": "R1"}]
    )

    with (
        patch("pybatfish.client.session.Session", return_value=mock_session),
        patch(
            "olav_netops.core.sim.batfish_q._do_export_and_init"
        ) as mock_do_init,
    ):
        from olav.core.sim.batfish_q import batfish_q
        batfish_q.invoke({"snapshot_id": "snap_X", "question": "bgpSessionStatus"})
        batfish_q.invoke({"snapshot_id": "snap_X", "question": "bgpSessionStatus"})
        batfish_q.invoke({"snapshot_id": "snap_Y", "question": "bgpSessionStatus"})

    # snap_X exported ONCE; snap_Y exported once
    assert mock_do_init.call_count == 2
    call_snapshot_ids = [c.args[0] for c in mock_do_init.call_args_list]
    assert call_snapshot_ids == ["snap_X", "snap_Y"]


def test_unknown_question_returns_error_envelope():
    """Asking for a question that bf.q doesn't have should fail gracefully."""
    mock_session = MagicMock(name="Session")
    # bf.q is a plain object: getattr raises AttributeError for unknown names
    class _QNamespace:
        bgpSessionStatus = MagicMock()
    mock_session.q = _QNamespace()

    with (
        patch("pybatfish.client.session.Session", return_value=mock_session),
        patch("olav_netops.core.sim.batfish_q._init_snapshot_if_needed", return_value=None),
    ):
        from olav.core.sim.batfish_q import batfish_q
        result = batfish_q.invoke({
            "snapshot_id": "snap_test",
            "question": "doesNotExist_xyz",
        })

    assert result["status"] == "error"
    assert "doesNotExist_xyz" in result["message"]
    assert result.get("rows") in (None, [])


def test_differential_mode_sets_reference_snapshot():
    """When ``reference_snapshot`` is provided, batfish_q must call
    ``bf.set_reference_snapshot(<ref>)`` before running the query."""
    mock_session, mock_question = _make_mock_session_with_question(
        "differentialReachability",
        [{"flow": "R1->R4", "change": "removed"}],
    )

    with (
        patch("pybatfish.client.session.Session", return_value=mock_session),
        patch("olav_netops.core.sim.batfish_q._init_snapshot_if_needed", return_value=None),
    ):
        from olav.core.sim.batfish_q import batfish_q
        result = batfish_q.invoke({
            "snapshot_id": "snap_candidate",
            "question": "differentialReachability",
            "reference_snapshot": "snap_baseline",
        })

    mock_session.set_reference_snapshot.assert_called_once_with("snap_baseline")
    mock_session.set_snapshot.assert_called_with("snap_candidate")
    assert result["status"] == "ok"
    assert result["rows"] == [{"flow": "R1->R4", "change": "removed"}]


def test_fqdn_nodes_fall_back_to_short_hostname():
    """Regression (2026-07-19 orchestration run): Batfish normalises
    hostnames to short form, so nodes='alpha-border-4500x.net.demo.internal'
    silently returned 0 rows while the device WAS in the snapshot (66 rows
    unfiltered). On an empty filtered result, batfish_q must retry once with
    domains stripped."""
    import pandas as pd

    mock_question = MagicMock(name="question_bgpSessionStatus")

    def _answer_for(**kwargs):
        ans = MagicMock()
        if kwargs.get("nodes") == "alpha-border-4500x":
            ans.answer.return_value.frame.return_value = pd.DataFrame(
                [{"Node": "alpha-border-4500x", "Established_Status": "NOT_COMPATIBLE"}]
            )
        else:
            ans.answer.return_value.frame.return_value = pd.DataFrame([])
        return ans

    mock_question.side_effect = lambda **kw: _answer_for(**kw)
    mock_q_namespace = MagicMock(name="bf.q")
    mock_q_namespace.bgpSessionStatus = mock_question
    mock_session = MagicMock(name="Session")
    mock_session.q = mock_q_namespace

    with (
        patch("pybatfish.client.session.Session", return_value=mock_session),
        patch("olav_netops.core.sim.batfish_q._init_snapshot_if_needed", return_value=None),
    ):
        from olav.core.sim.batfish_q import batfish_q
        result = batfish_q.invoke({
            "snapshot_id": "snap_test",
            "question": "bgpSessionStatus",
            "q_args": {"nodes": "alpha-border-4500x.net.demo.internal"},
        })

    assert result["status"] == "ok"
    assert result["row_count"] == 1
    assert result["rows"][0]["Node"] == "alpha-border-4500x"


def test_regex_nodes_specifier_not_domain_stripped():
    """/regex/ node specifiers may legitimately contain dots — the FQDN
    fallback must not rewrite them."""
    import pandas as pd

    mock_question = MagicMock(name="question_routes")
    seen = []

    def _answer_for(**kwargs):
        seen.append(kwargs.get("nodes"))
        ans = MagicMock()
        ans.answer.return_value.frame.return_value = pd.DataFrame([])
        return ans

    mock_question.side_effect = lambda **kw: _answer_for(**kw)
    mock_q_namespace = MagicMock(name="bf.q")
    mock_q_namespace.routes = mock_question
    mock_session = MagicMock(name="Session")
    mock_session.q = mock_q_namespace

    with (
        patch("pybatfish.client.session.Session", return_value=mock_session),
        patch("olav_netops.core.sim.batfish_q._init_snapshot_if_needed", return_value=None),
    ):
        from olav.core.sim.batfish_q import batfish_q
        result = batfish_q.invoke({
            "snapshot_id": "snap_test",
            "question": "routes",
            "q_args": {"nodes": "/alpha.*\\.internal/"},
        })

    assert result["status"] == "ok" and result["row_count"] == 0
    assert seen == ["/alpha.*\\.internal/"], "regex specifier must pass through once, unmodified"


def test_args_none_passes_no_kwargs():
    """`args=None` (or omitted) must call the question with no kwargs."""
    mock_session, mock_question = _make_mock_session_with_question(
        "definedStructures", [{"Structure_Name": "RM-IN"}]
    )

    with (
        patch("pybatfish.client.session.Session", return_value=mock_session),
        patch("olav_netops.core.sim.batfish_q._init_snapshot_if_needed", return_value=None),
    ):
        from olav.core.sim.batfish_q import batfish_q
        result = batfish_q.invoke({
            "snapshot_id": "snap_test",
            "question": "definedStructures",
        })

    mock_question.assert_called_once_with()  # no kwargs
    assert result["status"] == "ok"
