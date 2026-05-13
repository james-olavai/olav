"""Wrap LLMFactory output as the (str) -> str callable staged_fill expects."""
from __future__ import annotations

from typing import Callable


def make_llm_callable(*, agent_id: str = "analyzer") -> Callable[[str], str]:
    """Build an LLMCallable backed by the current LLMFactory configuration.

    Each invocation creates a fresh ChatModel via the cached LLMFactory.
    Caller-side keeps it simple: one string in, one string out.
    """
    from olav.core.llm import LLMFactory

    llm = LLMFactory.get_chat_model(temperature=0, agent_id=agent_id)

    def call(prompt: str) -> str:
        resp = llm.invoke(prompt)
        content = getattr(resp, "content", resp)
        if isinstance(content, list):
            # langchain-anthropic returns list of content blocks
            content = "".join(
                str(b.get("text", "")) if isinstance(b, dict) else str(b)
                for b in content
            )
        return str(content or "")

    return call
