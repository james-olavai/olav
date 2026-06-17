"""Deterministic, zero-LLM synthesis grader middleware (dev_docs/97).

Loop-engineering L2 verification done *deterministically*. Where
``RubricMiddleware`` spins up a separate grader sub-agent (an extra LLM
round-trip on every natural stop), this middleware runs a Python
predicate over the final assistant message and, on failure, loops back
to the model **once** with feedback. Zero LLM calls, zero added
context-budget cost.

It is a faithful port of the netops ``synthesis_rubric`` criterion —
*"the final message must contain at least one natural-language sentence,
not be pure raw tool output"* (ISSUE-NO-SYNTHESIS) — which is a
deterministic predicate and therefore does not need an LLM judge.

Design notes (small-model-first, per CLAUDE.md):
- **Pass-biased.** FAIL only when the final message is *entirely* raw
  output (tables / JSON / tool echo / code). Any prose sentence passes.
  Never fail for brevity or language choice.
- **Bounded.** At most ``max_iterations`` revision jumps; a private
  state counter prevents loops.
- Activated per-agent via ``deterministic_synthesis_grader: true`` in
  SKILL.md frontmatter; wired in ``agent.py`` next to the
  ``rubric_middleware`` branch.
"""

from __future__ import annotations

import logging
import re
from typing import Annotated, Any, NotRequired

from langchain.agents.middleware.types import (
    AgentMiddleware,
    AgentState,
    PrivateStateAttr,
    hook_config,
)
from langchain_core.messages import AIMessage, HumanMessage

logger = logging.getLogger(__name__)

DET_GRADER_SOURCE = "deterministic_synthesis_grader"
"""``lc_source`` tag on the synthetic feedback message (mirrors the rubric
middleware convention so UIs/evals can attribute the turn)."""

_REVISION_FEEDBACK = (
    "Your last message is entirely raw tool output (table rows, JSON, "
    "code, or tool-echo lines) with no natural-language summary. Add at "
    "least one plain-language sentence that states the answer or what the "
    "result means, then respond again."
)

# Lines that are NOT prose on their own.
_TABLE_LINE = re.compile(r"^\s*\|")              # markdown table row
_FENCE_LINE = re.compile(r"^\s*```")             # code fence
_TOOL_ECHO = re.compile(r"^\s*(📁|\[tool|<tool|\{|\}|\[|\])")
_TABLE_SEP = re.compile(r"^\s*[:\-\|\s]+$")      # |---|---| separator
_PROSE_TOKEN = re.compile(r"[A-Za-z一-鿿]")  # latin or CJK char


def has_prose(text: str) -> bool:
    """Return True if ``text`` contains at least one natural-language line.

    Pass-biased: strips fenced code blocks, markdown tables/separators,
    and tool-echo/JSON lines, then asks whether any remaining line carries
    real words (>= 3 word-ish tokens with a latin/CJK character). Empty
    input is treated as non-prose (nothing to show the user).
    """
    if not text or not text.strip():
        return False

    in_fence = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if _FENCE_LINE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if _TABLE_LINE.match(line) or _TABLE_SEP.match(line) or _TOOL_ECHO.match(line):
            continue
        # A "prose" line: has a latin/CJK char and reads like a phrase.
        if _PROSE_TOKEN.search(line):
            # CJK: a single char can be a sentence; require >=4 chars.
            # Latin: require >= 3 whitespace-separated tokens.
            if re.search(r"[一-鿿]", line):
                if len(re.findall(r"[一-鿿]", line)) >= 4:
                    return True
            elif len(line.split()) >= 3:
                return True
    return False


def _last_ai_text(messages: list[Any]) -> str:
    """Plain-text body of the most recent AIMessage (text blocks only)."""
    for msg in reversed(messages):
        if not isinstance(msg, AIMessage):
            continue
        parts: list[str] = []
        try:
            for block in msg.content_blocks:
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
        except Exception:
            if isinstance(msg.content, str):
                parts.append(msg.content)
        return "\n".join(p for p in parts if p)
    return ""


class _DetGraderState(AgentState):
    _det_synth_iters: NotRequired[Annotated[int, PrivateStateAttr]]


class DeterministicSynthesisMiddleware(AgentMiddleware):
    """Zero-LLM grader enforcing "prose synthesis present" via Python."""

    state_schema = _DetGraderState

    def __init__(
        self,
        *,
        agent_name: str = "",
        max_iterations: int = 1,
        on_evaluation: Any = None,
    ) -> None:
        self.agent_name = agent_name
        self.max_iterations = max(1, int(max_iterations))
        self._on_evaluation = on_evaluation

    @hook_config(can_jump_to=["model"])
    def after_agent(self, state: _DetGraderState, runtime: Any) -> dict[str, Any] | None:  # noqa: ARG002
        return self._evaluate(state)

    @hook_config(can_jump_to=["model"])
    async def aafter_agent(self, state: _DetGraderState, runtime: Any) -> dict[str, Any] | None:  # noqa: ARG002
        return self._evaluate(state)

    def _evaluate(self, state: _DetGraderState) -> dict[str, Any] | None:
        messages = state.get("messages", []) or []
        text = _last_ai_text(messages)
        passed = has_prose(text)
        iters = int(state.get("_det_synth_iters", 0) or 0)

        self._log(passed, iters)

        if passed:
            return None  # fall through to END
        if iters >= self.max_iterations:
            logger.warning(
                "deterministic_synthesis agent=%s exhausted max_iterations=%d without prose",
                self.agent_name,
                self.max_iterations,
            )
            return None
        # FAIL within budget → loop back once with feedback.
        return {
            "_det_synth_iters": iters + 1,
            "messages": [
                HumanMessage(
                    content=_REVISION_FEEDBACK,
                    name=DET_GRADER_SOURCE,
                    additional_kwargs={"lc_source": DET_GRADER_SOURCE},
                )
            ],
            "jump_to": "model",
        }

    def _log(self, passed: bool, iters: int) -> None:
        logger.info(
            "deterministic_synthesis agent=%s verdict=%s iteration=%d llm_calls=0",
            self.agent_name,
            "satisfied" if passed else "needs_revision",
            iters,
        )
        if self._on_evaluation is not None:
            try:
                self._on_evaluation(
                    {
                        "result": "satisfied" if passed else "needs_revision",
                        "iteration": iters,
                        "criteria": [{"name": "prose_synthesis_present", "passed": passed}],
                        "explanation": "deterministic (zero-LLM) synthesis check",
                    }
                )
            except Exception:
                logger.debug("deterministic_synthesis on_evaluation callback raised")
