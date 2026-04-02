"""olav_delegate — isolated subagent delegation tool.

Bypasses deepagents' SubAgentMiddleware to guarantee that each named
subagent runs with ONLY the tools declared in its SKILL.md, with no
FilesystemMiddleware or other deepagents-injected tools.

Usage (registered on the orchestrator):
    tools = [olav_delegate, ...]
    graph = create_deep_agent(model=llm, tools=tools, ...)
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.runnables import Runnable
from langchain_core.tools import tool

logger = logging.getLogger(__name__)


def build_delegate_tool(
    subagent_runnables: dict[str, Runnable],
) -> Any:
    """Return an ``olav_delegate`` @tool bound to the compiled subagent runnables.

    Args:
        subagent_runnables: Mapping of subagent name → compiled LangChain runnable.
                            Built by OLAVAgent._build_subagents().

    Returns:
        A LangChain tool callable.  Register it on the orchestrator tool list.
    """

    @tool
    def olav_delegate(subagent_name: str, task_description: str) -> str:
        """Delegate a task to a named OLAV subagent with complete tool isolation.

        Unlike deepagents task(), this guarantees the subagent receives ONLY the
        tools declared in its SKILL.md — no FilesystemMiddleware, no write_todos,
        no generic sandbox tools.  Use this for all cross-agent delegation.

        Args:
            subagent_name: Exact name of the subagent (e.g. 'config-creator',
                           'ops-orchestrator', 'quick-query').  Call
                           list_platform_services() or check PLATFORM.md to
                           discover available names.
            task_description: Complete, self-contained task description.
                              The subagent has NO memory of the current
                              conversation — include all relevant context.
        """
        runnable = subagent_runnables.get(subagent_name)
        if runnable is None:
            available = sorted(subagent_runnables.keys())
            return (
                f"Subagent '{subagent_name}' not found. "
                f"Available subagents: {available}"
            )

        try:
            result = runnable.invoke(
                {"messages": [HumanMessage(content=task_description)]}
            )
        except Exception as exc:
            logger.exception("olav_delegate: subagent '%s' raised", subagent_name)
            return f"Subagent '{subagent_name}' failed: {exc}"

        # Extract final AI response
        messages = result.get("messages", [])
        for msg in reversed(messages):
            content = getattr(msg, "content", None)
            if content and isinstance(content, str):
                return content
            if content and isinstance(content, list):
                # Anthropic structured content blocks
                text_parts = [
                    b.get("text", "") for b in content if isinstance(b, dict)
                ]
                combined = "\n".join(p for p in text_parts if p)
                if combined:
                    return combined

        return f"Subagent '{subagent_name}' completed with no text output."

    return olav_delegate
