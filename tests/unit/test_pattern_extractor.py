"""Tests for L2: olav.core.memory.pattern_extractor.

Pins:
  * groups operational_event memories by tool name from metadata
  * skips groups below ``min_samples`` threshold
  * filters by window_days (events older than window excluded)
  * LLM failures don't tank the whole run (counted in skipped_llm_error)
  * dry_run returns patterns without writing
  * non-dry run writes one reflection memory per processed group (ADR-0015)
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from olav.core.memory.pattern_extractor import extract_operational_patterns


class _FakeChat:
    def __init__(self, body: str = "- pattern bullet 1\n- pattern bullet 2"):
        self.body = body
        self.calls: list[str] = []

    def invoke(self, prompt: str):
        self.calls.append(prompt)
        return type("R", (), {"content": self.body})()


class _FailingChat:
    def invoke(self, prompt: str):
        raise RuntimeError("model down")


def _make_event(tool: str, text: str, days_ago: int = 1) -> dict:
    """Shape matching what LanceDB returns from .search().to_list()."""
    return {
        "id": f"opev-{tool}-{days_ago}",
        "text": text,
        "metadata": json.dumps({"tool": tool}),
        "created_at": (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(),
    }


def _make_store_with_events(events: list[dict]):
    store = MagicMock()
    tbl = MagicMock()
    tbl.search.return_value.where.return_value.limit.return_value.to_list.return_value = events
    store.get_table.return_value = tbl
    return store


def test_skips_groups_below_min_samples():
    events = [_make_event("register_service", f"Action: register_service\n#{i}") for i in range(3)]
    store = _make_store_with_events(events)
    chat = _FakeChat()
    out = extract_operational_patterns(
        scope="services", min_samples=5, store=store, chat_model=chat, dry_run=True,
    )
    assert out["groups_seen"] == 1
    assert out["skipped_low_samples"] == 1
    assert out["groups_processed"] == 0
    assert out["patterns"] == []
    assert chat.calls == []


def test_processes_group_at_threshold():
    events = [_make_event("register_service", f"Action: register_service\n#{i}") for i in range(5)]
    store = _make_store_with_events(events)
    chat = _FakeChat(body="- AS_naming convention\n- auth pattern api_key")
    out = extract_operational_patterns(
        scope="services", min_samples=5, store=store, chat_model=chat, dry_run=True,
    )
    assert out["groups_processed"] == 1
    assert len(out["patterns"]) == 1
    assert out["patterns"][0]["tool"] == "register_service"
    assert out["patterns"][0]["sample_count"] == 5
    assert "AS_naming" in out["patterns"][0]["body"]


def test_groups_separately_per_tool():
    events = (
        [_make_event("register_service", f"R{i}") for i in range(5)]
        + [_make_event("save_lab_config", f"S{i}") for i in range(5)]
    )
    store = _make_store_with_events(events)
    chat = _FakeChat()
    out = extract_operational_patterns(
        scope="services", min_samples=5, store=store, chat_model=chat, dry_run=True,
    )
    assert out["groups_seen"] == 2
    assert out["groups_processed"] == 2
    assert {p["tool"] for p in out["patterns"]} == {"register_service", "save_lab_config"}


def test_filters_old_events_by_window():
    """Events older than window_days excluded from the count."""
    fresh = [_make_event("register_service", f"fresh {i}", days_ago=1) for i in range(3)]
    stale = [_make_event("register_service", f"stale {i}", days_ago=60) for i in range(5)]
    store = _make_store_with_events(fresh + stale)
    chat = _FakeChat()
    # Window = 30d → only 3 fresh events count → below threshold of 5
    out = extract_operational_patterns(
        scope="services", min_samples=5, window_days=30,
        store=store, chat_model=chat, dry_run=True,
    )
    assert out["skipped_low_samples"] == 1
    assert out["groups_processed"] == 0


def test_llm_failure_is_isolated_per_group():
    """One LLM failure on a group doesn't taint other groups."""
    events = (
        [_make_event("register_service", f"R{i}") for i in range(5)]
        + [_make_event("save_profile", f"S{i}") for i in range(5)]
    )
    store = _make_store_with_events(events)

    class _MixedChat:
        def __init__(self):
            self._n = 0
        def invoke(self, prompt):
            self._n += 1
            if "register_service" in prompt:
                raise RuntimeError("flaky for this tool")
            return type("R", (), {"content": "- ok pattern"})()

    out = extract_operational_patterns(
        scope="services", min_samples=5, store=store,
        chat_model=_MixedChat(), dry_run=True,
    )
    assert out["skipped_llm_error"] == 1
    assert out["groups_processed"] == 1


def test_non_dry_run_writes_one_memory_per_pattern():
    events = [_make_event("register_service", f"R{i}") for i in range(5)]
    store = _make_store_with_events(events)
    chat = _FakeChat()

    from unittest.mock import patch
    with patch("olav.core.embedder.embed_text", return_value=[0.0] * 768):
        out = extract_operational_patterns(
            scope="services", min_samples=5, store=store, chat_model=chat,
        )
    assert out["patterns_written"] == 1
    assert store.add_memory.call_count == 1
    call = store.add_memory.call_args
    assert call.kwargs["category"] == "reflection"
    assert call.kwargs["scope"] == "services"
    md = call.kwargs["metadata"]
    assert md["source"] == "pattern_extractor"
    assert md["sample_count"] == 5


def test_skips_events_missing_tool_metadata():
    """Events without a 'tool' key in metadata are silently skipped
    (don't crash the extractor)."""
    weird_events = [
        {"id": "x1", "text": "no tool", "metadata": "{}"},
        {"id": "x2", "text": "stranger", "metadata": json.dumps({"other_key": "x"})},
    ]
    valid_events = [_make_event("register_service", f"R{i}") for i in range(5)]
    store = _make_store_with_events(weird_events + valid_events)
    chat = _FakeChat()
    out = extract_operational_patterns(
        scope="services", min_samples=5, store=store, chat_model=chat, dry_run=True,
    )
    # weird events ignored; valid group of 5 still processes
    assert out["groups_processed"] == 1


def test_returns_zero_when_no_events():
    store = _make_store_with_events([])
    out = extract_operational_patterns(
        scope="services", min_samples=5,
        store=store, chat_model=_FakeChat(), dry_run=True,
    )
    assert out["groups_seen"] == 0
    assert out["patterns_written"] == 0
