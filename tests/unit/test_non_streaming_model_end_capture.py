"""A non-streaming model produces several depth-0 turns; keep them all.

Traced from a real Ch2 run on gemma4-31b (dev_docs/115 §9). The model never emits
`on_chat_model_stream` at all — everything arrives via `on_chat_model_end`:

    MODEL_END depth=0 len=266   "I will check the netops views ..."
    TOOL_START task depth->1
      ... sub-agent runs 5x execute_sql ...
    MODEL_END depth=1 len=170   (sub-agent's answer, ignored at depth>0)
    TOOL_END   task depth->0
    MODEL_END depth=0 len=154   <- the orchestrator's actual answer
    MODEL_END depth=0 len=14

The guard was `if text and not _chunks and _delegate_depth == 0`, i.e. "nothing
appended anywhere yet", so only the FIRST depth-0 message survived — the
preamble — and the answer was discarded. `not _chunks` was meant to stop
`on_chat_model_end` duplicating text that streaming had already printed; that
question is per-turn, which is what these tests pin.
"""

from __future__ import annotations

import re
from pathlib import Path

_MAIN = Path(__file__).resolve().parents[2] / "src" / "olav" / "cli" / "main.py"
_SRC = _MAIN.read_text(encoding="utf-8")


def _model_end_block() -> str:
    start = _SRC.index('elif kind == "on_chat_model_end":')
    end = _SRC.index('elif kind == "on_tool_start":', start)
    return _SRC[start:end]


class TestPerTurnGuard:
    def test_model_end_no_longer_gated_on_the_global_chunk_list(self):
        block = _model_end_block()
        code = "\n".join(
            l for l in block.splitlines() if not l.strip().startswith("#")
        )
        assert "not _chunks" not in code, (
            "the global guard is what discarded the post-delegation answer"
        )
        assert "_chunks_this_turn == 0" in code

    def test_a_turn_counter_is_reset_when_each_turn_starts(self):
        assert 'elif kind == "on_chat_model_start":' in _SRC
        start = _SRC.index('elif kind == "on_chat_model_start":')
        end = _SRC.index('elif kind == "on_chat_model_end":', start)
        assert "_chunks_this_turn = 0" in _SRC[start:end]

    def test_streaming_still_increments_the_turn_counter(self):
        """Otherwise a streamed turn would be printed twice — once per chunk and
        again in full at on_chat_model_end."""
        start = _SRC.index('if kind == "on_chat_model_stream":')
        end = _SRC.index('elif kind == "on_chat_model_start":', start)
        block = _SRC[start:end]
        assert "_chunks_this_turn += 1" in block
        assert "_chunks.append(text)" in block

    def test_depth_guard_survives(self):
        """Sub-agent turns (depth>0) must never reach the CLI output."""
        block = _model_end_block()
        assert "_delegate_depth == 0" in block


class TestReplayOfTheTracedSequence:
    """Replay the traced events through the same predicate the CLI now uses."""

    # (kind, depth, payload_len) exactly as traced
    TRACE = [
        ("on_chat_model_start", 0, None),
        ("on_chat_model_end", 0, 266),      # preamble
        ("on_tool_start", 1, None),         # task
        ("on_chat_model_start", 1, None),
        ("on_chat_model_end", 1, 0),
        ("on_chat_model_end", 1, 170),      # sub-agent answer (depth>0)
        ("on_tool_end", 0, None),           # task returns
        ("on_chat_model_start", 0, None),
        ("on_chat_model_end", 0, 154),      # THE ANSWER
        ("on_chat_model_start", 0, None),
        ("on_chat_model_end", 0, 14),
    ]

    @staticmethod
    def _replay(trace, streaming: bool):
        """Mirror the CLI predicate: capture depth-0 model_end text when the
        current turn produced no stream chunks."""
        captured: list[int] = []
        chunks_this_turn = 0
        for kind, depth, ln in trace:
            if kind == "on_chat_model_start" and depth == 0:
                chunks_this_turn = 0
            elif kind == "on_chat_model_stream" and depth == 0:
                chunks_this_turn += 1
            elif kind == "on_chat_model_end" and depth == 0:
                if ln and chunks_this_turn == 0:
                    captured.append(ln)
        return captured

    def test_the_answer_is_no_longer_discarded(self):
        captured = self._replay(self.TRACE, streaming=False)
        assert 154 in captured, "the post-delegation answer must be captured"
        assert captured == [266, 154, 14], (
            f"expected every depth-0 turn, got {captured}"
        )

    def test_subagent_turns_are_never_captured(self):
        assert 170 not in self._replay(self.TRACE, streaming=False)

    def test_old_predicate_would_have_dropped_it(self):
        """Proof this is a real regression test, not a tautology."""
        captured, chunks = [], []
        for kind, depth, ln in self.TRACE:
            if kind == "on_chat_model_end" and depth == 0:
                if ln and not chunks:          # the old guard
                    captured.append(ln)
                    chunks.append(ln)
        assert captured == [266], (
            "the old guard should keep only the preamble — if this fails the "
            "trace no longer reproduces the bug"
        )

    def test_streamed_turn_is_not_printed_twice(self):
        streamed = [
            ("on_chat_model_start", 0, None),
            ("on_chat_model_stream", 0, 10),
            ("on_chat_model_stream", 0, 10),
            ("on_chat_model_end", 0, 20),   # same text, already streamed
        ]
        assert self._replay(streamed, streaming=True) == [], (
            "a streamed turn must not be re-printed at model_end"
        )
