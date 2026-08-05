"""The orchestrator must not swallow its sub-agent's answer.

Ch2 of the mini runsheet, twice on the same prompt (dev_docs/115 §1c, §8.4): the
sub-agent answered correctly, the orchestrator emitted no closing message, and
the operator saw *nothing* — no answer, no error, rc=0.

NL-CLI-SILENT-FINAL already had two fallback tiers, but both `continue` on
delegate results (`task` / `olav_delegate`) — which is exactly where the answer
lives when the orchestrator delegates. Tier 0 prints it verbatim, which is also
what ADR-0003/0005/0006 require of a thin router, and unlike Tier 1 it needs no
LLM call so it cannot fail when the endpoint is unhappy.

These tests exercise the extraction and the never-silent guarantee against the
real source, rather than re-implementing the logic.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_MAIN = Path(__file__).resolve().parents[2] / "src" / "olav" / "cli" / "main.py"
_SRC = _MAIN.read_text(encoding="utf-8")

# The shape a delegate tool result actually has, taken from a real audit row.
_DELEGATE_CONTENT = (
    "Command(update={'files': {}, 'messages': [ToolMessage("
    "content='Based on the most recent import in the `netops` database:"
    "\\n\\n*   **Total Devices**: 339\\n*   **Platforms**: cisco_ios', "
    "name='task', tool_call_id='abc')]})"
)


class TestTier0Exists:
    def test_tier0_runs_before_the_llm_synthesis_tier(self):
        i0 = _SRC.index("Tier 0: relay the sub-agent's answer when it was stranded")
        i1 = _SRC.index("Tier 1: LLM synthesis")
        assert i0 < i1, (
            "a deterministic passthrough must be tried before an LLM round-trip"
        )

    def test_tier0_targets_delegate_results_that_both_other_tiers_skip(self):
        block = _SRC[
            _SRC.index("Tier 0: relay the sub-agent's answer when it was stranded"):
            _SRC.index("Tier 1: LLM synthesis")
        ]
        assert 'if tr["name"] not in _SILENT_DELEGATE' in block, (
            "Tier 0 must look at exactly the results the other tiers discard"
        )

    def test_tier0_triggers_on_order_not_on_emptiness(self):
        """The defect that made emptiness useless: the orchestrator streams a
        preamble BEFORE delegating, so final_content is non-empty and every
        `if not final_content` tier is skipped while no answer was ever given.

        Asserted positionally rather than by slicing — Tier 0's own explanatory
        comment mentions `if not final_content`, and the naive checks (substring,
        then comment-stripped slice) both tripped over that.
        """
        t0 = _SRC.index("Tier 0: relay the sub-agent's answer when it was stranded")
        guard = _SRC.index("if _answer_stranded and _tool_results:", t0)
        next_empty_guard = _SRC.index("if not final_content and _tool_results:", t0)
        assert guard < next_empty_guard, (
            "Tier 0's guard must be the stranded check, not an emptiness check"
        )
        assert _SRC.index("_answer_stranded = (", t0) < guard

    def test_stream_position_is_recorded_at_each_delegation(self):
        assert "_chunks_at_last_delegate = len(_chunks)" in _SRC
        assert "_chunks_at_last_delegate: int | None = None" in _SRC

    def test_no_run_can_end_silently(self):
        assert "No final answer was produced" in _SRC, (
            "every tier can come up empty; an empty screen with rc=0 is "
            "indistinguishable from 'no answer exists'"
        )


class TestDelegateContentExtraction:
    """The regex Tier 0 uses, applied to the real delegate payload shape."""

    @staticmethod
    def _extract(raw: str) -> str:
        inner = re.findall(r"content='(.*?)'\s*,?\s*name=", raw, re.DOTALL)
        return (inner[-1] if inner else "").replace("\\n", "\n").strip()

    def test_recovers_the_subagent_answer(self):
        text = self._extract(_DELEGATE_CONTENT)
        assert "Total Devices" in text and "339" in text
        assert "ToolMessage" not in text, "the wrapper must not leak into the answer"
        assert "\\n" not in text, "escaped newlines should be real newlines"

    def test_empty_payload_yields_nothing_so_tier1_still_gets_a_turn(self):
        assert self._extract("Command(update={'messages': []})") == ""

    def test_nested_content_takes_the_last_match(self):
        """A delegate payload can quote an inner tool result before its own
        answer; the sub-agent's closing message is the last one."""
        raw = (
            "Command(update={'messages': [ToolMessage(content='inner sql rows', "
            "name='execute_sql'), ToolMessage(content='the real answer', name='task')]})"
        )
        assert self._extract(raw) == "the real answer"


def test_regex_in_source_matches_the_one_under_test():
    """Guard against the test drifting away from the implementation."""
    block = _SRC[
        _SRC.index("Tier 0: relay the sub-agent's answer when it was stranded"):
        _SRC.index("Tier 1: LLM synthesis")
    ]
    m = re.search(r"re\.findall\(r?\"(.*?)\", _raw", block)
    assert m, "could not find Tier 0's extraction regex in main.py"
    pattern = m.group(1).encode().decode("unicode_escape")
    assert re.findall(pattern, _DELEGATE_CONTENT, re.DOTALL), (
        f"main.py's pattern {pattern!r} does not match the real payload shape"
    )


@pytest.mark.parametrize("tier_marker", [
    "Tier 0: relay the sub-agent's answer when it was stranded",
    "Tier 1: LLM synthesis",
    "Tier 2: raw path preview",
])
def test_all_three_tiers_are_present(tier_marker):
    assert tier_marker in _SRC
