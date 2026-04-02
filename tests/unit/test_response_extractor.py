"""
tests/unit/test_response_extractor.py
───────────────────────────────────────
TDD guard for src/olav/platform/services/response_extractor.py

Tests verify:
  1. truncate_list — no-op when under limit
  2. truncate_list — appends sentinel for oversized lists
  3. schema_trim — filters unknown fields when registry returns known set
  4. schema_trim — passthrough when def_name is None
  5. auto_extract — unwraps NetBox envelope and trims fields
  6. auto_extract — truncates oversized list to token_budget
  7. auto_extract — returns non-list unchanged
  8. auto_extract — graceful passthrough when registry unavailable
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


# ── 1. truncate_list no-op ────────────────────────────────────────────────────


def test_truncate_list_noop_when_under_limit():
    from olav.platform.services.response_extractor import truncate_list

    data = [{"id": i} for i in range(5)]
    result = truncate_list(data, max_items=10)
    assert result == data


# ── 2. truncate_list appends sentinel ─────────────────────────────────────────


def test_truncate_list_appends_sentinel():
    from olav.platform.services.response_extractor import truncate_list

    data = [{"id": i} for i in range(20)]
    result = truncate_list(data, max_items=5)

    assert len(result) == 6  # 5 items + sentinel
    sentinel = result[-1]
    assert sentinel["_truncated"] is True
    assert sentinel["total_returned"] == 5
    assert sentinel["total_available"] == 20


# ── 3. schema_trim filters unknown fields ─────────────────────────────────────


def test_schema_trim_filters_fields():
    from olav.platform.services.response_extractor import schema_trim

    data = [{"id": 1, "name": "sw1", "_noise": "x", "vendor": "cisco"}]
    known = {"id", "name", "vendor"}

    with patch("olav.core.api_registry.field_names", return_value=known):
        result = schema_trim(data, "netbox", "Device")

    assert result == [{"id": 1, "name": "sw1", "vendor": "cisco"}]


# ── 4. schema_trim passthrough when no def_name ───────────────────────────────


def test_schema_trim_passthrough_no_def_name():
    from olav.platform.services.response_extractor import schema_trim

    data = {"id": 1, "extra": "field"}
    result = schema_trim(data, "netbox", None)
    assert result == data


# ── 5. auto_extract unwraps NetBox envelope ───────────────────────────────────


def test_auto_extract_unwraps_pagination_envelope():
    from olav.platform.services.response_extractor import auto_extract

    data = {
        "count": 2,
        "next": None,
        "previous": None,
        "results": [
            {"id": 1, "name": "sw1", "_noise": "x"},
            {"id": 2, "name": "sw2", "_noise": "y"},
        ],
    }
    known = {"id", "name"}
    with patch("olav.platform.services.response_extractor._lookup_response_def", return_value="Device"):
        with patch("olav.core.api_registry.field_names", return_value=known):
            result = auto_extract(data, "netbox", "GET", "/api/dcim/devices/")

    assert result["count"] == 2
    assert result["results"] == [{"id": 1, "name": "sw1"}, {"id": 2, "name": "sw2"}]
    assert "next" in result


# ── 6. auto_extract truncates oversized list ──────────────────────────────────


def test_auto_extract_truncates_oversized_list():
    from olav.platform.services.response_extractor import auto_extract

    # Build a list where each item serialises to ~100 chars
    data = [{"id": i, "name": f"device-{i:04d}", "padding": "x" * 80} for i in range(100)]

    with patch("olav.platform.services.response_extractor._lookup_response_def", return_value=None):
        result = auto_extract(data, "netbox", "GET", "/api/dcim/devices/",
                              token_budget=500, max_items=50)

    # Result should be a list ending with sentinel
    assert isinstance(result, list)
    sentinel = result[-1]
    assert sentinel.get("_truncated") is True


# ── 7. auto_extract passthrough non-list ─────────────────────────────────────


def test_auto_extract_passthrough_dict():
    from olav.platform.services.response_extractor import auto_extract

    data = {"id": 1, "name": "sw1"}
    with patch("olav.platform.services.response_extractor._lookup_response_def", return_value=None):
        result = auto_extract(data, "netbox", "GET", "/api/dcim/devices/1/")

    assert result == data


# ── 8. auto_extract graceful when registry unavailable ───────────────────────


def test_auto_extract_graceful_fallback():
    """If api_registry raises, auto_extract returns original data unchanged."""
    from olav.platform.services.response_extractor import auto_extract

    data = [{"id": 1}, {"id": 2}]
    with patch(
        "olav.platform.services.response_extractor._lookup_response_def",
        side_effect=Exception("db gone"),
    ):
        result = auto_extract(data, "netbox", "GET", "/api/dcim/devices/")

    # Should fall back to original in the caller (auto_extract catches all exc)
    assert isinstance(result, list)
