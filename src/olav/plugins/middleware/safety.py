"""OLAVSafetyMiddleware — Conditional HITL gate for FilesystemMiddleware tool calls.

Intercepts two tools injected unconditionally by deepagents' FilesystemMiddleware:
  - ``write_file`` — interrupted when path is outside the project root
  - ``execute``    — interrupted when command matches a dangerous pattern

Safe calls pass through without any human prompt. Only genuinely risky calls raise
a LangGraph ``interrupt()``, pausing the agent until the user approves, edits, or
rejects the action.

Registration: auto-discovered by ``load_builtin_plugins()`` — no manual wiring needed.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, ToolCall, ToolMessage
from langgraph.runtime import Runtime
from langgraph.types import interrupt

from langchain.agents.middleware.human_in_the_loop import (
    ActionRequest,
    HITLRequest,
    ReviewConfig,
)
from olav.plugins.base import OLAVMiddlewarePlugin

logger = logging.getLogger(__name__)

from olav.platform.safety.patterns import BLOCKED_WRITE_PREFIXES, DANGEROUS_EXEC_PATTERNS

_DANGEROUS_EXEC_PATTERNS = DANGEROUS_EXEC_PATTERNS
_BLOCKED_WRITE_PREFIXES = BLOCKED_WRITE_PREFIXES


def _find_project_root() -> Path:
    p = Path(__file__).resolve()
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


_PROJECT_ROOT: Path = _find_project_root()


def _check_write_file(path: str) -> tuple[bool, str]:
    """Return (is_dangerous, reason) for a write_file call."""
    if not path:
        return False, ""
    p = Path(path)
    # Absolute path outside project root
    if p.is_absolute():
        for blocked in _BLOCKED_WRITE_PREFIXES:
            if str(p).startswith(blocked):
                return True, f"blocked system path: {path}"
        if not str(p).startswith(str(_PROJECT_ROOT)):
            return True, f"outside project root ({_PROJECT_ROOT}): {path}"
    return False, ""


def _check_execute(command: str) -> tuple[bool, str]:
    """Return (is_dangerous, reason) for an execute call."""
    if not command:
        return False, ""
    cmd_lower = command.lower().strip()
    for pat in _DANGEROUS_EXEC_PATTERNS:
        if pat in cmd_lower:
            return True, f"dangerous pattern {pat!r}"
    return False, ""


def _make_description(tool_name: str, args: dict, reason: str) -> str:
    import json
    args_str = json.dumps(args, ensure_ascii=False, indent=2)
    return (
        f"⚠️  Potentially unsafe operation — {reason}\n\n"
        f"Tool : {tool_name}\n"
        f"Args :\n{args_str}"
    )


class OLAVSafetyMiddleware(OLAVMiddlewarePlugin):
    """Conditional HITL gate: intercepts dangerous write_file / execute calls.

    Passes safe calls through without interruption. Only raises a LangGraph
    ``interrupt()`` for calls that are genuinely risky (writing outside the
    project root, or running known-dangerous shell patterns).
    """

    name = "safety"
    version = "1.0.0"
    description = "HITL gate: interrupt dangerous write_file / execute tool calls"
    tags = ["safety", "hitl", "builtin"]

    # Tools to watch (injected by FilesystemMiddleware, can't be removed)
    _WATCHED: frozenset[str] = frozenset({"write_file", "execute"})

    def _classify(self, tool_name: str, args: dict) -> tuple[bool, str]:
        """Return (needs_approval, reason)."""
        if tool_name == "write_file":
            return _check_write_file(args.get("path", "") or args.get("file_path", ""))
        if tool_name == "execute":
            return _check_execute(args.get("command", ""))
        return False, ""

    def _process_decision(
        self,
        decision: dict,
        tool_call: ToolCall,
    ) -> tuple[ToolCall | None, ToolMessage | None]:
        """Convert a human decision into a (revised_tool_call, optional_error_msg)."""
        dtype = decision.get("type")
        if dtype == "approve":
            return tool_call, None
        if dtype == "edit":
            edited = decision["edited_action"]
            return (
                ToolCall(
                    type="tool_call",
                    name=edited["name"],
                    args=edited["args"],
                    id=tool_call["id"],
                ),
                None,
            )
        if dtype == "reject":
            msg = decision.get("message") or (
                f"User rejected `{tool_call['name']}` (id={tool_call['id']})"
            )
            return None, ToolMessage(
                content=msg,
                name=tool_call["name"],
                tool_call_id=tool_call["id"],
                status="error",
            )
        raise ValueError(f"Unexpected decision type: {dtype!r}")

    def after_model(
        self, state: dict[str, Any], runtime: Runtime
    ) -> dict[str, Any] | None:
        """Conditionally interrupt dangerous tool calls before execution."""
        messages = state.get("messages", [])
        if not messages:
            return None

        last_ai = next(
            (m for m in reversed(messages) if isinstance(m, AIMessage)), None
        )
        if not last_ai or not last_ai.tool_calls:
            return None

        # --- Phase 1: classify each tool call ---
        action_requests: list[ActionRequest] = []
        review_configs: list[ReviewConfig] = []
        interrupt_indices: list[int] = []

        for idx, tc in enumerate(last_ai.tool_calls):
            if tc["name"] not in self._WATCHED:
                continue
            dangerous, reason = self._classify(tc["name"], tc["args"])
            if not dangerous:
                continue

            action_requests.append(
                ActionRequest(
                    name=tc["name"],
                    args=tc["args"],
                    description=_make_description(tc["name"], tc["args"], reason),
                )
            )
            review_configs.append(
                ReviewConfig(
                    action_name=tc["name"],
                    allowed_decisions=["approve", "edit", "reject"],
                )
            )
            interrupt_indices.append(idx)
            logger.info(
                "OLAVSafetyMiddleware: flagging %s — %s", tc["name"], reason
            )

        if not action_requests:
            return None  # all safe — no interrupt

        # --- Phase 2: pause and wait for human decisions ---
        hitl_request = HITLRequest(
            action_requests=action_requests,
            review_configs=review_configs,
        )
        decisions: list[dict] = interrupt(hitl_request)["decisions"]

        if len(decisions) != len(interrupt_indices):
            raise ValueError(
                f"Expected {len(interrupt_indices)} decisions, got {len(decisions)}"
            )

        # --- Phase 3: rebuild tool call list ---
        revised_calls: list[ToolCall] = []
        error_messages: list[ToolMessage] = []
        decision_idx = 0

        for idx, tc in enumerate(last_ai.tool_calls):
            if idx in interrupt_indices:
                decision = decisions[decision_idx]
                decision_idx += 1
                revised, err = self._process_decision(decision, tc)
                if revised is not None:
                    revised_calls.append(revised)
                if err is not None:
                    error_messages.append(err)
            else:
                revised_calls.append(tc)

        last_ai.tool_calls = revised_calls
        return {"messages": [last_ai, *error_messages]}

    async def aafter_model(
        self, state: dict[str, Any], runtime: Runtime
    ) -> dict[str, Any] | None:
        return self.after_model(state, runtime)
