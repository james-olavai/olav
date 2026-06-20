"""Variance-aware behavioral assertion for LLM e2e (dev_docs/97 §test-strategy P1).

LLM output varies on identical input (CLAUDE.md: "one run made 0 tool calls, the
next 31"), so a single-shot e2e assertion is noise — a one-off red gets dismissed
as flakiness, and a real regression hides behind that dismissal. Run the check
N≥3 times and assert a success *rate*: a one-off variance blip passes; a genuine
regression (most runs fail) does not. This is what makes a nightly behavioral
failure actionable instead of "probably infra, ignore".

Usage in a behavioral e2e::

    from tests.e2e._variance import assert_success_rate

    def _ask_once() -> bool:
        out = run_agent("netops", "how many devices?")
        return "348" in out                      # the behavioural success check

    assert_success_rate(_ask_once, n=3, threshold=2/3, label="netops device count")

The closure runs the full real path (real entry point + real model); the harness
only repeats it and scores the rate. Exceptions in a run count as a failed run
(captured, not propagated) so one transient error doesn't abort the rate.
"""

from __future__ import annotations

import logging
from typing import Callable

logger = logging.getLogger(__name__)


def run_success_rate(
    run_once: Callable[[], object],
    *,
    n: int = 3,
) -> tuple[int, int, list[str]]:
    """Run ``run_once`` ``n`` times; return ``(successes, n, details)``.

    ``run_once`` returns a truthy value / ``True`` for success, falsy for
    failure, or ``(ok, detail)``. A raised exception is recorded as a failed
    run (captured, not propagated).
    """
    n = max(1, int(n))
    successes = 0
    details: list[str] = []
    for i in range(n):
        try:
            res = run_once()
            ok, detail = (res[0], res[1]) if isinstance(res, tuple) and len(res) == 2 else (res, "")
            ok = bool(ok)
        except Exception as exc:  # a thrown run is a failed run, not an abort
            ok, detail = False, f"raised {type(exc).__name__}: {exc}"
        successes += int(ok)
        details.append(f"  run {i + 1}/{n}: {'OK' if ok else 'FAIL'}{(' — ' + str(detail)) if detail else ''}")
        logger.info("variance run %d/%d: %s %s", i + 1, n, "OK" if ok else "FAIL", detail)
    return successes, n, details


def assert_success_rate(
    run_once: Callable[[], object],
    *,
    n: int = 3,
    threshold: float = 2 / 3,
    min_successes: int | None = None,
    label: str = "",
) -> None:
    """Assert the success rate of ``run_once`` over ``n`` runs meets the bar.

    Pass when ``successes >= min_successes`` (if given) else
    ``successes / n >= threshold``. On failure the AssertionError carries the
    per-run outcomes so a nightly red is diagnosable, not just "flaky".
    """
    successes, n, details = run_success_rate(run_once, n=n)
    required = min_successes if min_successes is not None else _ceil_threshold(threshold, n)
    if successes < required:
        raise AssertionError(
            f"behavioural success rate below bar"
            f"{f' [{label}]' if label else ''}: {successes}/{n} succeeded "
            f"(need ≥ {required}; threshold={threshold:g}). Per-run:\n"
            + "\n".join(details)
            + "\nA low rate is a real regression; a one-off red is LLM variance."
        )


def _ceil_threshold(threshold: float, n: int) -> int:
    """Smallest integer success count satisfying ``count/n >= threshold``."""
    import math

    return max(1, math.ceil(threshold * n - 1e-9))
