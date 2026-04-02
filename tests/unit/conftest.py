"""Shared fixtures for unit tests."""
import os
import pytest


@pytest.fixture(autouse=True)
def _clear_bypass_env(monkeypatch):
    """Ensure OLAV_DANGEROUSLY_SKIP_PERMISSIONS is cleared before and after each test.

    set_bypass(True) writes directly to os.environ, bypassing monkeypatch tracking.
    This fixture guarantees no bypass state leaks between tests.
    """
    monkeypatch.delenv("OLAV_DANGEROUSLY_SKIP_PERMISSIONS", raising=False)
    yield
    monkeypatch.delenv("OLAV_DANGEROUSLY_SKIP_PERMISSIONS", raising=False)
