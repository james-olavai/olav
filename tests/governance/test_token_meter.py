"""Sprint 0a: TokenUsageCallback records per-request usage.

The callback must handle both the LangChain 0.3+ ``message.usage_metadata``
shape and the legacy ``llm_output.token_usage`` shape, forward the
numbers to the audit recorder, tick the budget monitor, and soft-fail
when either downstream isn't attached.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from olav.core.llm_instrumentation import TokenUsageCallback, _extract_usage


# ── usage extraction -----------------------------------------------------------


def test_extract_usage_from_message_usage_metadata():
    msg = SimpleNamespace(usage_metadata={
        "input_tokens": 120,
        "output_tokens": 45,
        "total_tokens": 165,
    })
    gen = SimpleNamespace(message=msg)
    resp = SimpleNamespace(generations=[[gen]])
    usage = _extract_usage(resp)
    assert usage == {"input_tokens": 120, "output_tokens": 45, "total_tokens": 165}


def test_extract_usage_from_legacy_llm_output():
    resp = SimpleNamespace(
        generations=[[]],
        llm_output={"token_usage": {"prompt_tokens": 50, "completion_tokens": 20}},
    )
    usage = _extract_usage(resp)
    # legacy names map into the canonical keys
    assert usage["input_tokens"] == 50
    assert usage["output_tokens"] == 20
    assert usage["total_tokens"] == 70


def test_extract_usage_returns_none_when_missing():
    resp = SimpleNamespace(generations=[[SimpleNamespace(message=SimpleNamespace())]])
    assert _extract_usage(resp) is None


# ── callback wiring -----------------------------------------------------------


class _StubRecorder:
    def __init__(self):
        self.calls: list[dict] = []

    def record(self, *, event_type, run_id=None, payload=None):
        self.calls.append({"event_type": event_type, "run_id": run_id, "payload": payload})


class _StubBudget:
    def __init__(self):
        self.ticks: list[int] = []

    def add_usage(self, tokens: int) -> None:
        self.ticks.append(tokens)


def _make_response(total: int = 50, inp: int = 30, out: int = 20):
    msg = SimpleNamespace(usage_metadata={
        "input_tokens": inp, "output_tokens": out, "total_tokens": total,
    })
    return SimpleNamespace(generations=[[SimpleNamespace(message=msg)]])


def test_callback_records_audit_event_and_ticks_budget():
    recorder = _StubRecorder()
    budget = _StubBudget()
    cb = TokenUsageCallback(
        recorder=recorder,
        budget_monitor=budget,
        run_id="run-42",
        model_name="gemma-7b",
        model_tier="small",
    )

    cb.on_llm_end(_make_response(total=123, inp=80, out=43))

    assert recorder.calls == [
        {
            "event_type": "token_usage",
            "run_id": "run-42",
            "payload": {
                "input_tokens": 80,
                "output_tokens": 43,
                "total_tokens": 123,
                "model": "gemma-7b",
                "tier": "small",
            },
        }
    ]
    assert budget.ticks == [123]


def test_callback_soft_fails_without_recorder_or_budget():
    cb = TokenUsageCallback(recorder=None, budget_monitor=None)
    # Must not raise even without any downstream attached.
    cb.on_llm_end(_make_response())


def test_callback_silently_skips_when_no_usage_metadata():
    recorder = _StubRecorder()
    cb = TokenUsageCallback(recorder=recorder)
    resp = SimpleNamespace(generations=[[SimpleNamespace(message=SimpleNamespace())]])
    cb.on_llm_end(resp)
    assert recorder.calls == []


def test_callback_swallows_recorder_errors():
    @dataclass
    class _Boom:
        def record(self, **kwargs):
            raise RuntimeError("database offline")

    cb = TokenUsageCallback(recorder=_Boom())
    # A recorder outage should never bubble out of on_llm_end.
    cb.on_llm_end(_make_response())


def test_llm_factory_attaches_token_callback():
    """LLMFactory.get_chat_model wires in TokenUsageCallback by default."""
    import inspect

    from olav.core import llm as llm_mod

    src = inspect.getsource(llm_mod.LLMFactory.get_chat_model)
    assert "TokenUsageCallback" in src, (
        "LLMFactory no longer attaches TokenUsageCallback — Sprint 0a regression."
    )
    assert 'params["callbacks"]' in src
