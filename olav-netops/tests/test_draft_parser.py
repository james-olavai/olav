"""Unit tests for command_learner/tools/draft_parser (R71b).

Covers:
  * build_prompt structure (marker instruction, samples, retry context)
  * parse_response marker extraction + fence stripping
  * heuristic fallback when marker missing
  * draft_parser returns (None, "") on LLM unavailable
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SKILL_TOOLS = Path(__file__).resolve().parents[1] / ".olav/workspace/command_learner/tools"
sys.path.insert(0, str(_SKILL_TOOLS))

import draft_parser as dp  # noqa: E402


class TestParseResponse:
    def test_textfsm_marker(self):
        dsl, body = dp.parse_response(
            "# OLAV_DSL: textfsm\n\nValue NAME (\\S+)\n\nStart\n  ^${NAME} -> Record\n"
        )
        assert dsl == "textfsm"
        assert body.startswith("Value NAME")

    def test_python_marker(self):
        dsl, body = dp.parse_response(
            "# OLAV_DSL: python\n\ndef parse(raw):\n    return []\n"
        )
        assert dsl == "python"
        assert body.startswith("def parse(raw)")

    def test_marker_with_fenced_block(self):
        dsl, body = dp.parse_response(
            "```\n# OLAV_DSL: python\ndef parse(raw):\n    return []\n```"
        )
        assert dsl == "python"
        assert "def parse" in body
        assert "```" not in body

    def test_marker_with_language_tagged_fence(self):
        dsl, body = dp.parse_response(
            "```python\n# OLAV_DSL: python\ndef parse(raw):\n    pass\n```"
        )
        assert dsl == "python"
        assert "def parse" in body

    def test_heuristic_python_fallback(self):
        """No marker but `def parse(` present → detect as python."""
        dsl, body = dp.parse_response("def parse(raw):\n    return []\n")
        assert dsl == "python"
        assert body.startswith("def parse")

    def test_heuristic_textfsm_fallback(self):
        dsl, body = dp.parse_response("Value A (\\S+)\n\nStart\n  ^${A}\n")
        assert dsl == "textfsm"

    def test_no_marker_no_heuristic(self):
        """Plain prose (no marker, no detectable DSL) → (None, body)."""
        dsl, body = dp.parse_response("I cannot learn this output, sorry.")
        assert dsl is None
        assert body == "I cannot learn this output, sorry."

    def test_case_insensitive_dsl(self):
        dsl, _ = dp.parse_response("# OLAV_DSL: PYTHON\n\ndef parse(raw): pass")
        assert dsl == "python"

    def test_trailing_whitespace_in_marker(self):
        dsl, _ = dp.parse_response("# OLAV_DSL:   python   \ndef parse(raw): pass")
        assert dsl == "python"


class TestBuildPrompt:
    def test_prompt_contains_marker_instruction(self):
        prompt = dp.build_prompt(
            "cisco_ios", "show x",
            [{"device": "R1", "raw_output": "abc"}],
            "- aligned table",
        )
        assert "# OLAV_DSL: textfsm" in prompt
        assert "# OLAV_DSL: python" in prompt
        assert "abc" in prompt

    def test_prompt_includes_retry_context(self):
        prompt = dp.build_prompt(
            "cisco_ios", "show x",
            [{"device": "R1", "raw_output": "abc"}],
            "- hint",
            prev_code="def parse(raw): pass",
            prev_error="no records produced",
        )
        assert "Previous attempt failed" in prompt
        assert "no records produced" in prompt
        assert "def parse(raw): pass" in prompt

    def test_sample_cap(self):
        """With >5 samples, the prompt truncates and notes overflow."""
        samples = [{"device": f"R{i}", "raw_output": f"raw{i}"} for i in range(10)]
        prompt = dp.build_prompt("cisco_ios", "show x", samples, "- ")
        assert "more samples omitted" in prompt
        # First 5 should be present
        for i in range(5):
            assert f"raw{i}" in prompt
        # 6th and beyond should be omitted
        assert "raw6" not in prompt

    def test_short_sample_list(self):
        prompt = dp.build_prompt(
            "cisco_ios", "show x",
            [{"device": "R1", "raw_output": "line1\nline2"}],
            "- hint",
        )
        assert "Samples : 1" in prompt
        assert "line1" in prompt
        assert "omitted" not in prompt


class TestDraftParser:
    def test_llm_unavailable_returns_empty(self):
        dsl, body = dp.draft_parser(
            None, "cisco_ios", "show x", [{"device": "R1", "raw_output": "a"}], "- hint",
        )
        assert dsl is None
        assert body == ""

    def test_llm_with_response(self):
        class _FakeLLM:
            def invoke(self, prompt):
                class _Resp:
                    content = "# OLAV_DSL: textfsm\n\nValue A (\\S+)\n\nStart\n  ^${A} -> Record\n"
                return _Resp()
        dsl, body = dp.draft_parser(
            _FakeLLM(), "cisco_ios", "show x",
            [{"device": "R1", "raw_output": "a b c"}], "- hint",
        )
        assert dsl == "textfsm"
        assert "Value A" in body

    def test_llm_raises(self):
        class _Boom:
            def invoke(self, prompt):
                raise RuntimeError("connection dropped")
        dsl, body = dp.draft_parser(
            _Boom(), "cisco_ios", "show x",
            [{"device": "R1", "raw_output": "a"}], "- hint",
        )
        assert dsl is None
        assert body == ""
