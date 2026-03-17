"""Guardrails Plugin — injects learned failure constraints into the system prompt."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain_core.messages import SystemMessage
from langgraph.runtime import Runtime
from langgraph.types import Overwrite

from olav.plugins.base import OLAVMiddlewarePlugin

if TYPE_CHECKING:
    from olav.core.memory import LanceDBStore

logger = logging.getLogger(__name__)


class GuardrailsPlugin(OLAVMiddlewarePlugin):
    """Dynamically injects learned failure/audit constraints into the system prompt.

    Queries LanceDB for historical failure memories before each model call and
    appends a ``=== LEARNED CONSTRAINTS ===`` block to the system message so the
    model avoids previously-seen failure patterns.
    """

    name = "guardrails"
    version = "1.0.0"
    description = "将历史失败记录作为约束注入 system prompt"
    tags = ["memory", "builtin"]

    def __init__(
        self,
        store: LanceDBStore | None = None,
        scope: str = "global",
    ) -> None:
        self._store = store
        self._scope = scope
        self._injector = None  # lazy

    def _get_store(self):
        if self._store is not None:
            return self._store
        from olav.core.memory import get_store
        return get_store()

    def _get_injector(self):
        if self._injector is None:
            from olav.core.memory.guardrails import GuardrailInjector
            self._injector = GuardrailInjector(self._get_store())
        return self._injector

    async def abefore_model(
        self, state: dict[str, Any], runtime: Runtime
    ) -> dict[str, Any] | None:
        """Inject guardrail constraints into the system message before model call."""
        messages = list(state.get("messages", []))
        if not messages:
            return None

        # Find the system message (usually first)
        sys_idx = next(
            (i for i, m in enumerate(messages)
             if getattr(m, "type", None) == "system"
             or (isinstance(m, dict) and m.get("role") == "system")),
            None,
        )
        if sys_idx is None:
            return None

        sys_msg = messages[sys_idx]
        original_content = (
            sys_msg.content if hasattr(sys_msg, "content") else sys_msg.get("content", "")
        )

        # Get query from last human message for relevance scoring
        query = ""
        for m in reversed(messages):
            msg_type = getattr(m, "type", None) or (
                m.get("role", "") if isinstance(m, dict) else ""
            )
            if msg_type in ("human", "user"):
                query = getattr(m, "content", None) or m.get("content", "") if isinstance(m, dict) else ""
                break

        try:
            injector = self._get_injector()
            enriched_content = injector.inject(original_content, query=query, scope=self._scope)
        except Exception as exc:
            logger.warning("GuardrailsPlugin: inject failed (non-fatal): %s", exc)
            return None

        if enriched_content == original_content:
            return None  # no constraints to inject

        updated_messages = list(messages)
        updated_messages[sys_idx] = SystemMessage(content=enriched_content)
        return {"messages": Overwrite(updated_messages)}
