"""TDD (dev_docs/77 §2.1, plan Phase 2): `batfish_q` tool — generic
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
