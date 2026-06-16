"""R99/S1 regression: query_pattern memory text must NOT contain the
verbatim user_query.

Why this test exists: the prior shape ``"Q: {user_query}\\nWorking SQL:
{sql}"`` caused captured query_pattern rows to self-match future
similar user prompts at ~0.88-0.95 cosine, drowning out directive
and expert_knowledge entries in AutoRecall.  See dev_docs/63 for the
A/B evidence.  The fix anchors the embedded text on extracted
keywords + the SQL, keeping the verbatim query only in
``metadata.intent`` for L2 distillation.

If a future refactor re-introduces the verbatim user_query into the
``text`` field, this test fails.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from olav.plugins.middleware.query_pattern_capture import (
    QueryPatternCapturePlugin,
)


class _UserMsg:
    type = "human"
    def __init__(self, content): self.content = content


class _AIMsg:
    type = "ai"
    def __init__(self, content="", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class _ToolMsg:
    type = "tool"
    def __init__(self, name, content):
        self.name = name
        self.content = content


VERBATIM_QUERY = (
    "Write a bash script to backup running-config from all routers. "
    "Use real device names/IPs from the database. Save to exports/."
)
SQL = "SELECT name, ip_address FROM devices WHERE role = 'router' ORDER BY name"
TOOL_PAYLOAD = (
    '{"data": [{"name":"R1","ip_address":"192.168.100.101"},'
    '{"name":"R2","ip_address":"192.168.100.102"}], '
    f'"sql": "{SQL}"}}'
)


def _state():
    return {
        "messages": [
            _UserMsg(VERBATIM_QUERY),
            _AIMsg(tool_calls=[{"name": "execute_sql"}]),
            _ToolMsg("execute_sql", TOOL_PAYLOAD),
            _AIMsg(content="Here's the script: #!/bin/bash ..."),
        ]
    }


def _run(plugin, state):
    return asyncio.run(plugin.aafter_agent(state, runtime=MagicMock()))


def test_text_does_not_contain_verbatim_user_query():
    """Embedded text must not echo the user's prose — that's what causes
    self-pollution of AutoRecall."""
    captured: dict = {}

    fake_store = MagicMock()
    fake_store.add_memory = lambda **kw: captured.update(kw) or {"status": "ok"}

    plugin = QueryPatternCapturePlugin(store=fake_store, scope="global")

    with patch(
        "olav.plugins.middleware.query_pattern_capture.QueryPatternCapturePlugin._embed",
        return_value=[0.1] * 32,
    ):
        _run(plugin, _state())

    text = captured.get("text", "")
    assert text, "expected store.add_memory to be called"
    # The hard regression check — verbatim query string must not appear.
    assert "Write a bash script to backup running-config" not in text, (
        f"Regression: verbatim user_query leaked into embedded text:\n{text!r}"
    )
    # Old prefix must be gone.
    assert not text.startswith("Q: "), f"Old shape leaked: {text!r}"
    # New shape must include keywords + SQL.
    assert "Working SQL for queries about:" in text, (
        f"New shape header missing: {text!r}"
    )
    assert SQL in text, f"SQL missing from text: {text!r}"


def test_metadata_intent_still_has_verbatim_query():
    """L2 distillation still needs the original query — preserved in
    metadata.intent (not in the embedded text)."""
    captured: dict = {}

    fake_store = MagicMock()
    fake_store.add_memory = lambda **kw: captured.update(kw) or {"status": "ok"}

    plugin = QueryPatternCapturePlugin(store=fake_store, scope="global")

    with patch(
        "olav.plugins.middleware.query_pattern_capture.QueryPatternCapturePlugin._embed",
        return_value=[0.1] * 32,
    ):
        _run(plugin, _state())

    md = captured.get("metadata") or {}
    assert md.get("intent", "").startswith(
        "Write a bash script to backup running-config"
    ), f"intent metadata lost: {md!r}"
    assert md.get("sql") == SQL


def test_text_includes_extracted_keywords():
    """Keywords act as the lightweight intent signal in the embedding."""
    captured: dict = {}

    fake_store = MagicMock()
    fake_store.add_memory = lambda **kw: captured.update(kw) or {"status": "ok"}

    plugin = QueryPatternCapturePlugin(store=fake_store, scope="global")

    with patch(
        "olav.plugins.middleware.query_pattern_capture.QueryPatternCapturePlugin._embed",
        return_value=[0.1] * 32,
    ):
        _run(plugin, _state())

    text = captured["text"]
    # _extract_keywords lowercases + strips stopwords; "write", "bash",
    # "script", "backup", "running", "config" should be in the first 6.
    for kw in ("bash", "script", "backup"):
        assert kw in text, f"expected keyword {kw!r} in text:\n{text!r}"
