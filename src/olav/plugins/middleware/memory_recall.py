"""Memory Recall Plugin — injects LanceDB historical context before model calls."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langgraph.runtime import Runtime
from langgraph.types import Overwrite

from olav.plugins.base import OLAVMiddlewarePlugin

if TYPE_CHECKING:
    from olav.core.memory import LanceDBStore

logger = logging.getLogger(__name__)


class MemoryRecallPlugin(OLAVMiddlewarePlugin):
    """Enriches the last user message with recalled LanceDB memories.

    Runs in ``abefore_model`` so every model call gets the most relevant
    historical context prepended as a ``<relevant-memories>`` XML block.
    """

    name = "memory_recall"
    version = "1.0.0"
    description = "在每次模型调用前注入 LanceDB 历史记忆"
    tags = ["memory", "builtin"]

    def __init__(self, store: LanceDBStore | None = None, scope: str = "global") -> None:
        self._store = store
        self._scope = scope
        self._recall_mw = None  # lazy

    def _get_store(self):
        if self._store is not None:
            return self._store
        from olav.core.memory import get_store
        return get_store()

    def _get_recall_mw(self):
        if self._recall_mw is None:
            from olav.core.memory.middleware import AutoRecallMiddleware
            self._recall_mw = AutoRecallMiddleware(self._get_store())
        return self._recall_mw

    async def abefore_model(
        self, state: dict[str, Any], runtime: Runtime
    ) -> dict[str, Any] | None:
        """Enrich messages with recalled memories before each model call."""
        messages = state.get("messages", [])
        if not messages:
            return None

        input_dict = {"messages": list(messages)}
        try:
            recall = self._get_recall_mw()
            enriched = await recall.enrich(input_dict, scope=self._scope)
        except Exception as exc:
            logger.warning("MemoryRecallPlugin: enrich failed (non-fatal): %s", exc)
            return None

        enriched_msgs = enriched.get("messages", messages) if isinstance(enriched, dict) else messages
        if enriched_msgs is messages or enriched_msgs == messages:
            return None  # nothing changed

        return {"messages": Overwrite(enriched_msgs)}
