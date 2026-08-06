"""The relayed sub-agent answer must read as prose, not as a Python literal.

Tier 0 relays a stranded sub-agent answer by digging it out of a stringified
message list. It used to regex the middle out and undo `\\n` only, so every
other escape survived into the terminal. Real Ch5 output, round 3:

    > ⚠️ **Results truncated**: showing 50 of 27523 findings. Raise the
    profile\\'s `max_findings_per_job` to see more.\\

Both defects are visible there: `\\'` for the apostrophe, and a trailing
backslash where a `\\n` had been consumed mid-literal. The apostrophe is also
what makes the case tricky — `repr` switches to double quotes when the content
contains one, so a pattern anchored on single quotes misses the whole message.
"""

from __future__ import annotations

import pytest

from olav.cli.main import _decode_relayed_content


def _msg(content_literal: str, name: str = "runner") -> str:
    """Shape the CLI actually receives: str() of a list of message objects."""
    return f"[AIMessage(content={content_literal}, name='{name}', id='x')]"


class TestEscapesAreDecoded:
    def test_newlines_become_real_line_breaks(self):
        out = _decode_relayed_content(_msg(r"'line one\nline two'"))
        assert out == "line one\nline two"

    def test_escaped_apostrophe_does_not_reach_the_operator(self):
        """The Ch5 defect: `the profile\\'s` printed verbatim."""
        out = _decode_relayed_content(_msg(r"'raise the profile\'s limit'"))
        assert out == "raise the profile's limit"
        assert "\\" not in out

    def test_double_quoted_repr_is_matched(self):
        """repr uses double quotes when the content holds an apostrophe — the
        single-quote-only pattern returned nothing for exactly the messages
        most likely to contain one."""
        out = _decode_relayed_content(_msg("\"it's down\\nrecheck Gi0/0\""))
        assert out == "it's down\nrecheck Gi0/0"

    def test_backslashes_in_content_survive_intact(self):
        # In the wire form a literal backslash is doubled, so `C:\\tmp` in the
        # repr decodes to a single-backslash path.
        out = _decode_relayed_content(_msg(r"'path C:\\tmp\\out'"))
        assert out == r"path C:\tmp\out"

    def test_real_ch5_line_decodes_cleanly(self):
        raw = _msg(
            r"'> ⚠️ **Results truncated**: showing 50 of 27523 findings. "
            r"Raise the profile\'s `max_findings_per_job` to see more.\n"
            r"📄 Report saved: exports/audit_reports/interface_health.md'"
        )
        out = _decode_relayed_content(raw)
        assert "profile's" in out
        assert not any(ln.endswith("\\") for ln in out.splitlines()), (
            "a trailing backslash is the visible残 of an undecoded escape"
        )
        assert out.count("\n") == 1


class TestTheRealDeepagentsPayload:
    """Built by the library, not hand-written — the shape the fixtures missed.

    `_build_task_tool` returns `Command(update={..., "messages":
    [ToolMessage(content, tool_call_id=tool_call_id)]})`. No `name` is passed,
    so `name=` never appears in the repr — and both the original pattern and
    its first replacement anchored on `\\s*,?\\s*name=`. Tier 0 therefore
    returned "" for every `task` result: the one tool it exists to relay.
    Hand-written fixtures all carried `name='task'`, so nothing caught it.
    """

    @staticmethod
    def _payload(body: str) -> str:
        from langchain_core.messages import ToolMessage
        from langgraph.types import Command

        return str(
            Command(
                update={
                    "files": {},
                    "messages": [ToolMessage(body, tool_call_id="abc")],
                }
            )
        )

    def test_answer_is_recovered_from_a_library_built_payload(self):
        body = "Total Devices: 339\nPlatforms: cisco_ios"
        assert _decode_relayed_content(self._payload(body)) == body

    def test_mixed_quotes_survive_the_round_trip(self):
        """Both quote characters present is what forces repr to escape — and
        it is the ordinary case for audit output (`the profile's` next to
        `"🔴 down"`)."""
        body = 'the profile\'s limit, with "🔴 down" interfaces\nsecond line'
        assert _decode_relayed_content(self._payload(body)) == body


class TestNonAnswersFallThrough:
    @pytest.mark.parametrize("raw", ["", "no message here", "[ToolMessage(x=1)]"])
    def test_nothing_relayable_returns_empty(self, raw):
        """The caller treats "" as "try the next tier" — returning garbage
        would print it as the answer instead."""
        assert _decode_relayed_content(raw) == ""

    def test_an_unterminated_literal_is_declined_rather_than_half_printed(self):
        """The pattern admits only well-formed literals, so a truncated payload
        yields "" and Tier 1 gets its turn — printing half a message as the
        answer would be worse than deferring."""
        assert _decode_relayed_content("[AIMessage(content='unterminated, name=") == ""

    def test_last_message_wins(self):
        """The answer is the final assistant message, not the first."""
        raw = (
            "[AIMessage(content='thinking', name='a', id='1'), "
            "AIMessage(content='the answer', name='b', id='2')]"
        )
        assert _decode_relayed_content(raw) == "the answer"


def test_tier0_uses_the_decoder():
    """Wiring proof — the helper is worthless if the relay still regexes
    inline (dev_docs Definition of Done)."""
    from pathlib import Path

    import olav.cli.main as _m

    src = Path(_m.__file__).read_text(encoding="utf-8")
    tier0 = src[src.index("Tier 0: relay"): src.index("Tier 1: LLM synthesis")]
    assert "_decode_relayed_content(_raw)" in tier0
    assert "replace(\"\\\\n\", \"\\n\")" not in tier0, (
        "the hand-rolled unescape is back — it only ever handled one escape"
    )


class TestBothCallSitesShareTheDecoder:
    """Two copies of the same extraction drifted apart once already.

    Tier 0 and the NL-CLI-TERMINAL-TOOL banner block each carried their own
    `content='(.*?)'...name=` regex plus a `\\n`-only unescape. Both missed the
    real payload for the same reason, and the banner block's miss printed the
    raw repr — which is what put `profile\\'s` on screen in Ch5.
    """

    def _src(self) -> str:
        from pathlib import Path

        import olav.cli.main as _m

        return Path(_m.__file__).read_text(encoding="utf-8")

    def test_the_banner_block_decodes_via_the_shared_helper(self):
        src = self._src()
        start = src.index("NL-CLI-TERMINAL-TOOL")
        # End at the first use of the decoded payload — "Report saved:" also
        # appears in this block's own explanatory comment, which sliced the
        # region off before the code under test.
        block = src[start: src.index("_terminal_tool_lines.append", start)]
        assert "_decode_relayed_content(content)" in block

    def test_no_hand_rolled_extraction_survives_anywhere(self):
        """The specific pattern that was wrong, in any of its spellings."""
        src = self._src()
        assert "name=" not in src.split("_RELAYED_CONTENT_RE")[1].split("\n\n")[0]
        offenders = [
            ln.strip()
            for ln in src.splitlines()
            if "content='(.*?)'" in ln and not ln.strip().startswith("#")
        ]
        assert not offenders, f"a private copy of the extraction is back: {offenders}"

    def test_banner_survives_a_real_payload(self):
        """End to end for the exact Ch5 shape: banner + path inside a Command."""
        from langchain_core.messages import ToolMessage
        from langgraph.types import Command

        body = (
            "> ⚠️ **Results truncated**: showing 50 of 27523 findings. "
            "Raise the profile's `max_findings_per_job` to see more.\n\n"
            "📄 Report saved: exports/audit_reports/interface_health.md"
        )
        raw = str(Command(update={"messages": [ToolMessage(body, tool_call_id="a")]}))
        out = _decode_relayed_content(raw) or raw
        assert "profile's" in out and "\\'" not in out
        import re as _re

        assert _re.search(r"Report saved:\s+(\S+)", out).group(1).endswith(".md")
