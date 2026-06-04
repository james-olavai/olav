"""Root test conftest — automatic pytest marker registration.

Markers are applied based on file path + content inspection so individual
test files don't need manual decoration:

  platform    — touches only src/olav/** or platform workspace paths
                (core/admin/audit/devops/services); safe to run without
                olav-netops installed.
  netops      — touches olav-netops/** paths; requires olav-netops wheel
                + `olav skill install olav-netops` to be deployed.
  integration — touches BOTH platform and netops paths; needs full setup.
  (no marker) — generic tests with no delivery-unit-specific path refs.

Usage:
  pytest tests/governance/                        # full suite
  pytest tests/governance/ -m "not netops"        # platform changes only
  pytest tests/governance/ -m netops              # netops changes only
  pytest tests/governance/ -m "platform or integration"  # needs both
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


def _classify(fspath: str, src: str) -> str | None:
    """Return marker name for a test file, or None for generic tests."""
    has_netops = (
        "netops" in fspath.lower()
        or bool(re.search(
            r"\bolav[-_]netops\b|netops[/.]|[/.]netops\b|olav_netops",
            src,
        ))
    )
    has_platform = bool(re.search(
        r"src/olav(?!/data/workspace/.*netops)"
        r"|workspace/(?:core|admin|audit|devops|services)\b"
        r"|from olav\.|import olav\.",
        src,
    ))
    if has_netops and has_platform:
        return "integration"
    if has_netops:
        return "netops"
    if has_platform:
        return "platform"
    return None


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Auto-apply delivery-unit markers without touching individual test files."""
    _cache: dict[str, str | None] = {}
    for item in items:
        fspath = str(item.fspath)
        if fspath not in _cache:
            try:
                src = Path(fspath).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                src = ""
            _cache[fspath] = _classify(fspath, src)
        marker = _cache[fspath]
        if marker:
            item.add_marker(getattr(pytest.mark, marker))


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers so pytest --markers shows them."""
    config.addinivalue_line(
        "markers",
        "platform: test touches only olav platform code "
        "(safe without olav-netops installed)",
    )
    config.addinivalue_line(
        "markers",
        "netops: test touches olav-netops workspace paths "
        "(requires skill install olav-netops)",
    )
    config.addinivalue_line(
        "markers",
        "integration: test touches both platform and netops paths "
        "(requires full setup)",
    )
