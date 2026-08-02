"""Embedding circuit breaker — a dead endpoint must not hang the run.

Every embed call is already bounded (``OLAV_EMBED_TIMEOUT`` × retries). The
*batch* was not: `olav init` / `olav skill install` embed every ``*.guide.yaml``
one at a time, so an unresponsive endpoint cost N × the per-call bound. That is
the 2026-06-14 CI setup hang, and it reappeared on 2026-08-02 as a local unit
run that blocked for ~40 minutes inside `prime_guides_from_dir`.

A per-call timeout stops one call from hanging. Only a breaker stops the run.
"""
from __future__ import annotations

import pytest

import olav.core.embedder as E


@pytest.fixture(autouse=True)
def _clean_breaker(monkeypatch):
    monkeypatch.setenv("OLAV_EMBED_FAILURE_THRESHOLD", "3")
    monkeypatch.setenv("OLAV_EMBED_BREAKER_COOLDOWN", "60")
    E.reset_embed_breaker()
    yield
    E.reset_embed_breaker()


def _always_fails(monkeypatch, exc=None):
    """Make every embed attempt raise, and count the attempts.

    Defaults to an error that is NOT "endpoint unreachable", so the
    consecutive-failure path is what is under test.
    """
    calls = {"n": 0}

    def _boom(*_a, **_k):
        calls["n"] += 1
        raise exc or RuntimeError("model rejected the input")

    monkeypatch.setattr(E, "_get_api_client", _boom)
    monkeypatch.setattr(E, "_cache_get", lambda _t: None)
    monkeypatch.setattr(E, "_cache_put", lambda _t, _v: None)

    class _Cfg:
        mode = "api"

    monkeypatch.setattr("olav.core.config.get_embedding_config", lambda: _Cfg())
    return calls


def test_a_dead_endpoint_stops_being_called_after_the_threshold(monkeypatch):
    """The whole point: attempt count is bounded by the threshold, not by how
    many things the caller wanted to embed."""
    calls = _always_fails(monkeypatch)

    for _ in range(50):
        assert E.embed_text(f"guide {_}") is None

    assert calls["n"] == 3, (
        f"endpoint was called {calls['n']} times for 50 embeds — the breaker "
        f"did not open"
    )


def test_callers_degrade_rather_than_raise(monkeypatch):
    """Skipping an entry is the contract; a breaker that raised would turn a
    slow endpoint into a broken install."""
    _always_fails(monkeypatch)
    for _ in range(5):
        assert E.embed_text("x") is None


def test_a_working_endpoint_is_never_broken_by_earlier_failures(monkeypatch):
    """Two failures then a success must not leave the counter armed — a slow
    but working endpoint has to keep working."""
    state = {"fail": 2}
    monkeypatch.setattr(E, "_cache_get", lambda _t: None)
    monkeypatch.setattr(E, "_cache_put", lambda _t, _v: None)

    class _Cfg:
        mode = "api"

    monkeypatch.setattr("olav.core.config.get_embedding_config", lambda: _Cfg())

    class _Resp:
        data = [type("D", (), {"embedding": [0.1, 0.2]})()]

    class _Client:
        class embeddings:
            @staticmethod
            def create(**_k):
                if state["fail"] > 0:
                    state["fail"] -= 1
                    raise RuntimeError("transient model error")
                return _Resp()

    monkeypatch.setattr(E, "_get_api_client", lambda: (_Client(), "m"))

    assert E.embed_text("a") is None
    assert E.embed_text("b") is None
    assert E.embed_text("c") == [0.1, 0.2]
    # ...and the breaker is disarmed, so the next blips start a fresh count
    assert not E._breaker_is_open()
    assert E._embed_failures == 0


def test_the_breaker_reopens_the_endpoint_after_the_cooldown(monkeypatch):
    """Self-healing: a transient outage must not disable embedding for the life
    of the process."""
    calls = _always_fails(monkeypatch)
    for _ in range(10):
        E.embed_text("x")
    assert calls["n"] == 3
    assert E._breaker_is_open()  # noqa: S101

    # travel past the cool-off
    monkeypatch.setattr(E.time, "monotonic", lambda: E._breaker_open_until + 1)
    assert not E._breaker_is_open()
    E.embed_text("x")
    assert calls["n"] == 4, "the endpoint was never retried after the cool-off"


def test_the_cache_still_answers_while_the_breaker_is_open(monkeypatch):
    """An open breaker means "do not call the endpoint", not "forget what we
    already know"."""
    _always_fails(monkeypatch)
    for _ in range(5):
        E.embed_text("x")
    assert E._breaker_is_open()

    monkeypatch.setattr(E, "_cache_get", lambda _t: [0.9])
    assert E.embed_text("known") == [0.9]


def test_thresholds_are_tunable(monkeypatch):
    monkeypatch.setenv("OLAV_EMBED_FAILURE_THRESHOLD", "1")
    E.reset_embed_breaker()
    calls = _always_fails(monkeypatch)
    for _ in range(10):
        E.embed_text("x")
    assert calls["n"] == 1


# --- the batch caller that motivated this -----------------------------------


def test_guide_priming_is_bounded_by_the_breaker(monkeypatch):
    """`prime_guides_from_dir` embeds one guide at a time through
    ``guide_kb._embed`` → ``embed_text``. With a dead endpoint that used to cost
    N × the per-call bound; the breaker makes it cost the threshold.

    The endpoint is what fails here, not ``embed_text`` — patching the function
    that *contains* the breaker would test nothing.
    """
    import olav.core.memory.guide_kb as G

    calls = _always_fails(monkeypatch)
    for i in range(40):
        assert G._embed(f"guide body {i}") is None

    assert calls["n"] == 3, (
        f"a dead endpoint was reached {calls['n']} times while priming 40 guides"
    )


# --- an endpoint that does not answer is not the same as one that says no ---


def test_an_unreachable_endpoint_opens_the_breaker_on_the_first_failure(monkeypatch):
    """A timeout means the service did not answer — and one recorded failure is
    already two attempts, because the SDK client retries internally. Two more
    at the full per-call bound buy nothing and cost the caller minutes; that is
    what left one test still over 120s after the first version of this fix."""
    calls = _always_fails(monkeypatch, exc=TimeoutError("no response"))
    for _ in range(20):
        assert E.embed_text("x") is None
    assert calls["n"] == 1


def test_a_refused_connection_counts_the_same_way(monkeypatch):
    class APIConnectionError(Exception):
        pass

    calls = _always_fails(monkeypatch, exc=APIConnectionError("refused"))
    for _ in range(20):
        E.embed_text("x")
    assert calls["n"] == 1


def test_an_error_from_a_reachable_endpoint_still_needs_evidence(monkeypatch):
    """A 4xx may be about this one input, not about the service. Opening on the
    first of those would disable embedding because one guide was malformed."""
    calls = _always_fails(monkeypatch, exc=ValueError("input too long"))
    for _ in range(20):
        E.embed_text("x")
    assert calls["n"] == 3


def test_a_wrapped_timeout_is_still_recognised(monkeypatch):
    """Clients wrap the cause; matching only the outermost type would miss it."""
    def _raise(*_a, **_k):
        try:
            raise TimeoutError("read timed out")
        except TimeoutError as inner:
            raise RuntimeError("embedding call failed") from inner

    calls = {"n": 0}

    def _counted(*a, **k):
        calls["n"] += 1
        _raise()

    monkeypatch.setattr(E, "_get_api_client", _counted)
    monkeypatch.setattr(E, "_cache_get", lambda _t: None)

    class _Cfg:
        mode = "api"

    monkeypatch.setattr("olav.core.config.get_embedding_config", lambda: _Cfg())
    for _ in range(10):
        E.embed_text("x")
    assert calls["n"] == 1
