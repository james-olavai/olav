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
