"""E2E test config — scale per-test pytest-timeout markers by OLAV_E2E_TIMEOUT_FACTOR.

The e2e helpers already scale their *subprocess* timeouts by
``OLAV_E2E_TIMEOUT_FACTOR`` (e.g. ``_run`` computes
``effective = int(timeout * factor)``), but the per-test
``@pytest.mark.timeout(N)`` decorators are hardcoded and were NOT scaled.
On a slow LLM endpoint the unscaled pytest-timeout fires first and kills
the test even though the subprocess was granted the scaled budget — so
dispatching the workflow with ``timeout_factor=2.0`` had no effect on the
tests that actually time out (observed 2026-06-14: CH3 core query took
>540s and was killed by the unscaled marker while _run had ~960s).

This hook makes the documented knob real: every ``timeout`` marker is
multiplied by the same factor at collection time. Factor 1.0 (the
default) is a no-op.
"""

from __future__ import annotations

import os

import pytest

_FACTOR = float(os.environ.get("OLAV_E2E_TIMEOUT_FACTOR", "1.0"))


def pytest_collection_modifyitems(config, items):  # noqa: ARG001
    if _FACTOR == 1.0:
        return
    for item in items:
        marker = item.get_closest_marker("timeout")
        if marker is None:
            continue
        base = marker.args[0] if marker.args else marker.kwargs.get("timeout")
        if not base:
            continue
        # Drop any own-level timeout marker so the scaled one we add becomes
        # the closest (own markers outrank class/module markers).
        item.own_markers = [m for m in item.own_markers if m.name != "timeout"]
        item.add_marker(pytest.mark.timeout(int(base * _FACTOR)))


@pytest.fixture(scope="session", autouse=True)
def _plain_text_subprocess_output():
    """Strip ANSI styling from every e2e subprocess's output.

    These tests assert on *content* (`"0.25.1" in out`, a regex for the agent
    count), but the CLI renders through rich, which colourises numbers. rich
    normally emits no escapes into a captured (non-tty) pipe — unless the
    ambient environment says otherwise. With ``FORCE_COLOR`` set, `olav version`
    prints ``v0.\x1b[1;36m25.1\x1b[0m`` and the literal ``0.25.1`` is no longer
    in the output, so test_m1_platform_e2e fails with a baffling "Expected
    '0.25.1' ... got: Version: v0.25.1".

    Not hypothetical: this shell had ``FORCE_COLOR=3`` exported, and several CI
    providers set it too — a red that has nothing to do with the code under
    test is the most expensive kind. Fixed here rather than in each ``_run``
    helper because a dozen e2e modules spawn subprocesses and inherit
    ``os.environ``.

    Session-scoped, and therefore an explicit ``pytest.MonkeyPatch`` rather than
    the function-scoped ``monkeypatch`` fixture: several of these modules run
    their subprocess from a **class-scoped** fixture, which executes before any
    function-scoped fixture, so a per-test patch would apply too late to matter.
    Still undone on teardown (CLAUDE.md: never leak env across the session).
    """
    mp = pytest.MonkeyPatch()
    mp.delenv("FORCE_COLOR", raising=False)
    mp.delenv("COLORTERM", raising=False)
    mp.setenv("NO_COLOR", "1")
    mp.setenv("TERM", "dumb")
    yield
    mp.undo()
