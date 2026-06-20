"""Deterministic tests for the variance-aware e2e harness (dev_docs/97 P1).

The harness itself must be deterministic and CI-runnable (no LLM) — it only
repeats a caller-supplied check and scores the rate. Here we feed it controlled
run_once sequences to pin the rate logic.
"""

from __future__ import annotations

import pytest

from tests.e2e._variance import assert_success_rate, run_success_rate


def _seq(results):
    """A run_once that yields the given sequence of outcomes, one per call."""
    it = iter(results)

    def _once():
        return next(it)

    return _once


def test_run_success_rate_counts():
    s, n, details = run_success_rate(_seq([True, False, True]), n=3)
    assert (s, n) == (2, 3)
    assert len(details) == 3


def test_exception_counts_as_failed_run_not_abort():
    def _boom():
        raise RuntimeError("transient")

    s, n, _ = run_success_rate(_boom, n=3)
    assert (s, n) == (0, 3)  # captured, not propagated


def test_tuple_ok_detail_form():
    s, n, details = run_success_rate(_seq([(True, "found 348"), (False, "empty")]), n=2)
    assert s == 1
    assert "found 348" in details[0]


# --- assert_success_rate: threshold semantics ---

def test_passes_at_two_thirds_with_one_blip():
    # 2/3 success, default threshold 2/3 → pass (one variance blip tolerated)
    assert_success_rate(_seq([True, False, True]), n=3, threshold=2 / 3)


def test_fails_when_majority_fail():
    with pytest.raises(AssertionError) as ei:
        assert_success_rate(_seq([True, False, False]), n=3, threshold=2 / 3, label="demo")
    msg = str(ei.value)
    assert "1/3" in msg and "demo" in msg
    assert "real regression" in msg  # diagnostic, not just "flaky"


def test_min_successes_overrides_threshold():
    # 2/3 would pass on threshold, but min_successes=3 (strict) fails it
    with pytest.raises(AssertionError):
        assert_success_rate(_seq([True, True, False]), n=3, min_successes=3)


def test_full_pass():
    assert_success_rate(_seq([True, True, True]), n=3, threshold=2 / 3)


def test_n_one_strict():
    # n=1, threshold default → need 1 success
    assert_success_rate(_seq([True]), n=1)
    with pytest.raises(AssertionError):
        assert_success_rate(_seq([False]), n=1)


def test_ceil_threshold_examples():
    from tests.e2e._variance import _ceil_threshold

    assert _ceil_threshold(2 / 3, 3) == 2   # need 2 of 3
    assert _ceil_threshold(0.5, 4) == 2     # need 2 of 4
    assert _ceil_threshold(1.0, 3) == 3     # all must pass
    assert _ceil_threshold(0.0, 3) == 1     # floor is always ≥1
