"""

# 2026-06-12: imports repointed to olav_netops.core.sim.batfish_q —
# the olav.core.sim.batfish_q shim only re-exports the batfish_q
# function, not PacketHeaderConstraintsArgs (11 tests failed on the
# shim import since the ARCH-20 relocation).Phase E — TDD for ``batfish_q`` Pydantic-validated headers + error chain.

Root cause from Phase D run (2026-05-14 16:30):
- sim called ``batfish_q(reachability, q_args={'headers': {'dstIps': ['192.168.50.0/24']}})``
- Batfish returned 500 because ``PacketHeaderConstraints.dstIps`` is
  a String, not an Array.  Real error chain:
    Cannot deserialize value of type `java.lang.String` from Array value
    -> SpecifiersReachabilityQuestion["headers"]->PacketHeaderConstraints["dstIps"]
- sim's reflection misread "too many 500 error responses" as Batfish bug
  and degraded to ``routes`` question.

Phase E fix:
1. Pydantic model ``PacketHeaderConstraintsArgs`` with field validators
   that coerce ``list[str]`` -> comma-joined specifier string.
2. ``batfish_q`` runs ``q_args['headers']`` through the model.
3. On Batfish HTTPError, extract the deepest ``Caused by:`` chain so
   the envelope ``message`` shows the schema error.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _reset_batfish_session_cache():
    if "olav_netops.core.sim.batfish_q" in sys.modules:
        sys.modules["olav_netops.core.sim.batfish_q"]._BF_SESSION = None
        sys.modules["olav_netops.core.sim.batfish_q"]._LOADED_SNAPSHOTS = set()
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


def _make_mock_session_with_question(question_name: str, rows: list[dict]):
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


# ── Pydantic model standalone tests ──────────────────────────────────────


def test_packet_header_constraints_model_exists():
    from pydantic import BaseModel

    from olav_netops.core.sim.batfish_q import PacketHeaderConstraintsArgs

    assert issubclass(PacketHeaderConstraintsArgs, BaseModel)


def test_dstIps_list_coerced_to_comma_string():
    """The specific bug: ``dstIps=['192.168.50.0/24']`` -> ``'192.168.50.0/24'``."""
    from olav_netops.core.sim.batfish_q import PacketHeaderConstraintsArgs

    h = PacketHeaderConstraintsArgs(dstIps=["192.168.50.0/24"])
    assert h.dstIps == "192.168.50.0/24"


def test_dstIps_multi_list_joined():
    from olav_netops.core.sim.batfish_q import PacketHeaderConstraintsArgs

    h = PacketHeaderConstraintsArgs(dstIps=["10.0.0.0/24", "10.1.0.0/24"])
    assert h.dstIps == "10.0.0.0/24,10.1.0.0/24"


def test_dstIps_string_passes_through():
    from olav_netops.core.sim.batfish_q import PacketHeaderConstraintsArgs

    h = PacketHeaderConstraintsArgs(dstIps="10.0.0.0/24")
    assert h.dstIps == "10.0.0.0/24"


def test_srcIps_list_also_coerced():
    from olav_netops.core.sim.batfish_q import PacketHeaderConstraintsArgs

    h = PacketHeaderConstraintsArgs(srcIps=["1.1.1.1", "2.2.2.2"])
    assert h.srcIps == "1.1.1.1,2.2.2.2"


def test_unknown_field_rejected():
    from pydantic import ValidationError

    from olav_netops.core.sim.batfish_q import PacketHeaderConstraintsArgs

    with pytest.raises(ValidationError):
        PacketHeaderConstraintsArgs(notARealField="x")


# ── Integration into batfish_q ─────────────────────────────────────────────


def test_batfish_q_coerces_headers_list_before_call():
    """``batfish_q`` must run headers through PacketHeaderConstraintsArgs
    so the call to ``bf.q.reachability(...)`` receives a string."""
    mock_session, mock_question = _make_mock_session_with_question(
        "reachability", [{"Flow": "ok"}]
    )

    with (
        patch("pybatfish.client.session.Session", return_value=mock_session),
        patch("olav_netops.core.sim.batfish_q._init_snapshot_if_needed", return_value=None),
    ):
        from olav_netops.core.sim.batfish_q import batfish_q
        result = batfish_q.invoke({
            "snapshot_id": "snap_X",
            "question": "reachability",
            "q_args": {
                "headers": {"dstIps": ["192.168.50.0/24"]},
                "pathConstraints": {"startLocation": "R1"},
            },
        })

    assert result["status"] == "ok", result.get("message", "")
    call_kwargs = mock_question.call_args.kwargs
    assert call_kwargs["headers"]["dstIps"] == "192.168.50.0/24"
    assert call_kwargs["pathConstraints"] == {"startLocation": "R1"}


def test_batfish_q_no_headers_no_coercion():
    """If q_args has no 'headers', batfish_q must NOT inject one."""
    mock_session, mock_question = _make_mock_session_with_question(
        "bgpSessionStatus", [{"Node": "R1"}]
    )

    with (
        patch("pybatfish.client.session.Session", return_value=mock_session),
        patch("olav_netops.core.sim.batfish_q._init_snapshot_if_needed", return_value=None),
    ):
        from olav_netops.core.sim.batfish_q import batfish_q
        batfish_q.invoke({
            "snapshot_id": "snap_X",
            "question": "bgpSessionStatus",
            "q_args": {"nodes": "R1|R3"},
        })

    call_kwargs = mock_question.call_args.kwargs
    assert "headers" not in call_kwargs
    assert call_kwargs["nodes"] == "R1|R3"


def test_batfish_q_invalid_header_field_returns_clean_error():
    """Unknown header field -> clean Pydantic error in envelope."""
    mock_session, _ = _make_mock_session_with_question("reachability", [])

    with (
        patch("pybatfish.client.session.Session", return_value=mock_session),
        patch("olav_netops.core.sim.batfish_q._init_snapshot_if_needed", return_value=None),
    ):
        from olav_netops.core.sim.batfish_q import batfish_q
        result = batfish_q.invoke({
            "snapshot_id": "snap_X",
            "question": "reachability",
            "q_args": {"headers": {"notARealField": "x"}},
        })

    assert result["status"] == "error"
    lower = result["message"].lower()
    assert "headers" in lower or "field" in lower
    assert "notarealfield" in lower


# ── Caused-by chain extraction ─────────────────────────────────────────────


def test_caused_by_chain_extracted_from_http_error_text():
    """When pybatfish raises an HTTPError, the response body usually
    contains the Java exception chain. ``batfish_q`` must surface the
    deepest ``Caused by:`` line in the envelope message."""
    raw_body = (
        "org.batfish.common.BatfishException: Invalid question ...: "
        "Could not parse JSON question: Cannot deserialize value of "
        "type `java.lang.String` from Array value\n"
        "\tat org.glassfish.jersey.internal.Errors$1.call(Errors.java:248)\n"
        "Caused by: org.batfish.common.BatfishException: Could not parse JSON question: "
        "Cannot deserialize value of type `java.lang.String` from Array value "
        "(through reference chain: SpecifiersReachabilityQuestion[\"headers\"]"
        "->PacketHeaderConstraints[\"dstIps\"])\n"
        "Caused by: com.fasterxml.jackson.databind.exc.MismatchedInputException: "
        "Cannot deserialize value of type `java.lang.String` from Array value"
    )

    mock_session = MagicMock(name="Session")
    mock_q = MagicMock(name="bf.q")
    mock_question = MagicMock(name="reachability")

    class FakeResponse:
        text = raw_body
        status_code = 500

    fake_err = Exception("HTTPError 500: Internal Server Error")
    fake_err.response = FakeResponse()

    mock_question.return_value.answer.side_effect = fake_err
    setattr(mock_q, "reachability", mock_question)
    mock_session.q = mock_q

    with (
        patch("pybatfish.client.session.Session", return_value=mock_session),
        patch("olav_netops.core.sim.batfish_q._init_snapshot_if_needed", return_value=None),
    ):
        from olav_netops.core.sim.batfish_q import batfish_q
        result = batfish_q.invoke({
            "snapshot_id": "snap_X",
            "question": "reachability",
            "q_args": {"nodes": "R1"},
        })

    assert result["status"] == "error"
    msg = result["message"].lower()
    assert "deserialize" in msg or "mismatchedinput" in msg or "packetheader" in msg, (
        f"caused-by chain not surfaced: {result['message']!r}"
    )


def test_error_envelope_without_caused_by_still_returns_message():
    """When the exception has no ``.response``, fall back to ``str(exc)``."""
    mock_session = MagicMock(name="Session")
    mock_q = MagicMock(name="bf.q")
    mock_question = MagicMock(name="bgpSessionStatus")
    mock_question.return_value.answer.side_effect = ConnectionError("network unreachable")
    setattr(mock_q, "bgpSessionStatus", mock_question)
    mock_session.q = mock_q

    with (
        patch("pybatfish.client.session.Session", return_value=mock_session),
        patch("olav_netops.core.sim.batfish_q._init_snapshot_if_needed", return_value=None),
    ):
        from olav_netops.core.sim.batfish_q import batfish_q
        result = batfish_q.invoke({
            "snapshot_id": "snap_X",
            "question": "bgpSessionStatus",
        })

    assert result["status"] == "error"
    assert "network unreachable" in result["message"]
