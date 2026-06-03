"""
Unit tests for the NL-CLI-SILENT-FINAL synthesis fallback (v0.20 SYNTHESIS-NODE).

Tests the two-tier fallback when a model completes tool calls without
emitting a final AIMessage:
  Tier 1 — LLM synthesis call using tool results as context
  Tier 2 — raw path/file preview (write-only tool runs)
"""

from __future__ import annotations

import asyncio
import re
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers — replicate the synthesis filter logic from main.py for unit tests
# ---------------------------------------------------------------------------

_SILENT_DELEGATE = {"olav_delegate", "task"}
_WRITE_TOOLS = {
    "format_and_export", "render_report", "take_snapshot",
    "save_lab_config", "write_file",
}


def _synth_candidates(tool_results: list[dict]) -> list[dict]:
    return [
        tr for tr in tool_results
        if tr["name"] not in _SILENT_DELEGATE
        and tr["name"] not in _WRITE_TOOLS
    ]


def _build_synth_prompt(query: str, candidates: list[dict]) -> str:
    ctx_parts = []
    for tr in candidates[:4]:
        raw = tr.get("content") or ""
        ctx_parts.append(f"[{tr['name']}]:\n{raw[:600]}")
    context = "\n\n".join(ctx_parts)
    return (
        f"User asked: {query}\n\n"
        f"Tool results:\n{context}\n\n"
        "Provide a concise natural-language summary of these results "
        "directly answering the user's question."
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSynthesisCandidateFiltering:
    def test_data_tools_are_candidates(self):
        results = [
            {"name": "execute_sql", "content": '{"count": 282}'},
            {"name": "olav_recall_memory", "content": "some memory"},
        ]
        assert len(_synth_candidates(results)) == 2

    def test_delegate_tools_excluded(self):
        results = [
            {"name": "olav_delegate", "content": "delegated"},
            {"name": "task", "content": "some task"},
        ]
        assert _synth_candidates(results) == []

    def test_write_tools_excluded(self):
        results = [
            {"name": "format_and_export", "content": "path: /exports/report.md"},
            {"name": "render_report", "content": "saved_to: /exports/r.md"},
        ]
        assert _synth_candidates(results) == []

    def test_mixed_results_filters_correctly(self):
        results = [
            {"name": "execute_sql", "content": "rows"},
            {"name": "format_and_export", "content": "path: /x.md"},
            {"name": "olav_delegate", "content": "delegated"},
        ]
        candidates = _synth_candidates(results)
        assert len(candidates) == 1
        assert candidates[0]["name"] == "execute_sql"

    def test_only_first_4_candidates_used_in_prompt(self):
        results = [
            {"name": f"tool_{i}", "content": f"data_{i}"}
            for i in range(6)
        ]
        prompt = _build_synth_prompt("test query", results)
        # Only tools 0-3 should appear; tool_4 and tool_5 should not
        assert "[tool_3]" in prompt
        assert "[tool_4]" not in prompt

    def test_content_truncated_at_600_chars(self):
        long_content = "x" * 900
        results = [{"name": "execute_sql", "content": long_content}]
        prompt = _build_synth_prompt("q", results)
        # The truncated content in the prompt should not contain 900 'x' chars
        assert "x" * 601 not in prompt
        assert "x" * 600 in prompt  # exactly 600 chars of content


class TestSynthesisPromptStructure:
    def test_prompt_includes_user_query(self):
        results = [{"name": "execute_sql", "content": '{"count": 282}'}]
        prompt = _build_synth_prompt("list all cisco devices", results)
        assert "list all cisco devices" in prompt

    def test_prompt_includes_tool_name(self):
        results = [{"name": "execute_sql", "content": '{"count": 282}'}]
        prompt = _build_synth_prompt("q", results)
        assert "[execute_sql]" in prompt

    def test_prompt_includes_tool_content(self):
        results = [{"name": "execute_sql", "content": '{"count": 282}'}]
        prompt = _build_synth_prompt("q", results)
        assert '{"count": 282}' in prompt


class TestTier2RawPreview:
    """Raw path preview (Tier 2) for write-only runs."""

    def _extract_path(self, content: str) -> str | None:
        _PATH_KEYS = ("path", "absolute_path", "saved_to", "file")
        for key in _PATH_KEYS:
            m = re.search(rf"['\"]?{key}['\"]?\s*[:=]\s*['\"]([^'\"]+)['\"]", content)
            if m:
                return f"{key}: {m.group(1)}"
        return None

    def test_extracts_path_from_format_and_export(self):
        content = "{'path': '/exports/reports/net_health.md', 'status': 'ok'}"
        result = self._extract_path(content)
        assert result == "path: /exports/reports/net_health.md"

    def test_extracts_saved_to(self):
        content = "Report saved_to: '/exports/report.md' written."
        result = self._extract_path(content)
        assert result == "saved_to: /exports/report.md"

    def test_no_path_returns_none(self):
        content = "some random content without file paths"
        result = self._extract_path(content)
        assert result is None
