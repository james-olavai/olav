"""Memory Capture Plugin — extracts facts from conversations and stores them in LanceDB."""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from langgraph.runtime import Runtime

from olav.plugins.base import OLAVMiddlewarePlugin

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from olav.core.memory import LanceDBStore

logger = logging.getLogger(__name__)


class MemoryCapturePlugin(OLAVMiddlewarePlugin):
    """Post-processor that extracts key facts/decisions and stores them in LanceDB.

    Runs in ``aafter_agent`` so every successful agent invocation has its
    conversation distilled into persistent memory entries.
    """

    name = "memory_capture"
    version = "1.0.0"
    description = "在每次 agent 调用完成后提取并保存关键事实到 LanceDB"
    tags = ["memory", "builtin"]

    def __init__(
        self,
        store: LanceDBStore | None = None,
        llm: BaseChatModel | None = None,
        scope: str = "global",
    ) -> None:
        self._store = store
        self._llm = llm
        self._scope = scope
        self._capture_mw = None  # lazy

    def _get_store(self):
        if self._store is not None:
            return self._store
        from olav.core.memory import get_store
        return get_store()

    def _get_llm(self):
        if self._llm is not None:
            return self._llm
        from olav.core.llm import get_chat_model
        return get_chat_model()

    def _get_capture_mw(self):
        if self._capture_mw is None:
            from olav.core.memory.middleware import AutoCaptureMiddleware
            self._capture_mw = AutoCaptureMiddleware(self._get_store(), self._get_llm())
        return self._capture_mw

    async def aafter_agent(
        self, state: dict[str, Any], runtime: Runtime
    ) -> dict[str, Any] | None:
        """Fire-and-forget: extract and store memories from the completed conversation."""
        messages = state.get("messages", [])
        if not messages:
            return None

        # Split: first human message is the "original input", rest is the result
        input_messages = []
        result_messages = []
        seen_first_human = False
        for msg in messages:
            msg_type = getattr(msg, "type", None) or (
                msg.get("role", "") if isinstance(msg, dict) else ""
            )
            if not seen_first_human and msg_type in ("human", "user"):
                seen_first_human = True
                input_messages.append(msg)
            else:
                result_messages.append(msg)

        original_input = {"messages": input_messages}
        result = {"messages": result_messages}

        try:
            capture = self._get_capture_mw()
            await capture.process(original_input, result, scope=self._scope)
        except Exception as exc:
            logger.debug("MemoryCapturePlugin: capture failed (non-fatal): %s", exc)

        return None  # capture doesn't modify agent state
