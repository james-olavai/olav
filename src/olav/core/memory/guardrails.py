"""Guardrail Synthesis Module.

This module provides guardrail synthesis for self-learning:
- Retrieve historical failures
- Synthesize guardrails for agent context
- Inject guardrails into prompts
"""

import logging

logger = logging.getLogger(__name__)


class GuardrailSynthesizer:
    """Synthesizes guardrails from memory for agent context."""

    def __init__(self, memory_middleware=None):
        """Initialize GuardrailSynthesizer.

        Args:
            memory_middleware: Optional MemoryMiddleware instance
        """
        self.memory_middleware = memory_middleware

    def get_guardrails_for_task(
        self,
        task_query: str,
        query_vector: list[float] | None = None,
        limit: int = 5,
    ) -> str:
        """Get guardrails relevant to a task.

        Args:
            task_query: Natural language task description
            query_vector: Optional embedding vector
            limit: Maximum number of guardrails

        Returns:
            Guardrail context string
        """
        try:
            if self.memory_middleware:
                # Use middleware to search
                context = self.memory_middleware.recall(
                    query=task_query,
                    query_vector=query_vector,
                    limit=limit,
                )

                # Filter to only failures/lessons
                if context:
                    return self._filter_guardrails(context)

            return ""

        except Exception as e:
            logger.error(f"Failed to get guardrails: {e}")
            return ""

    def _filter_guardrails(self, context: str) -> str:
        """Filter context to relevant guardrails.

        Args:
            context: Full context string

        Returns:
            Filtered guardrail context
        """
        # In a real implementation, this would filter by metadata
        # For now, just return the context
        return context

    def inject_guardrails(
        self,
        base_prompt: str,
        task_query: str,
        query_vector: list[float] | None = None,
    ) -> str:
        """Inject guardrails into a prompt.

        Args:
            base_prompt: Base prompt to inject into
            task_query: Task description
            query_vector: Optional embedding vector

        Returns:
            Prompt with guardrails injected
        """
        guardrails = self.get_guardrails_for_task(task_query, query_vector)

        if not guardrails:
            return base_prompt

        # Inject guardrails
        injection = "\n\n## Guardrails from Past Experience\n"
        injection += guardrails
        injection += "\n\nUse these guardrails to avoid repeating past mistakes.\n"

        return base_prompt + injection


def synthesize_guardrails_from_memories(memories: list[dict]) -> list[str]:
    """Synthesize guardrail lessons from memories.

    Args:
        memories: List of memory dicts

    Returns:
        List of lesson strings
    """
    lessons = []

    for mem in memories:
        metadata_str = mem.get("metadata", "{}")

        # Check if this is a failure
        if "failure" in metadata_str.lower():
            # Extract lesson
            import json

            try:
                metadata = json.loads(metadata_str)
                if "lesson" in metadata:
                    lessons.append(metadata["lesson"])
                elif "command" in metadata:
                    lessons.append(f"Avoid issues with: {metadata['command']}")
            except:
                # Use text as lesson
                lessons.append(mem.get("text", "")[:100])

    return list(set(lessons))  # Unique lessons


def build_guardrail_injection(
    memories: list[dict],
    format: str = "bullet",
) -> str:
    """Build guardrail injection string.

    Args:
        memories: List of memory dicts (failures)
        format: Format style (bullet, paragraph, json)

    Returns:
        Formatted guardrail string
    """
    if not memories:
        return ""

    if format == "bullet":
        lines = ["Guardrails from past experience:"]
        for mem in memories:
            text = mem.get("text", "")
            if len(text) > 100:
                text = text[:100] + "..."
            lines.append(f"- Warning: {text}")
        return "\n".join(lines)

    elif format == "paragraph":
        texts = [m.get("text", "") for m in memories]
        return "Past failures: " + " | ".join(texts[:3])

    else:
        # JSON format
        import json

        return json.dumps(memories[:3], indent=2)


def create_guardrail_influence(
    memories: list[dict],
    default_params: dict,
) -> dict:
    """Create parameter modifications based on guardrails.

    Args:
        memories: List of failure memories
        default_params: Default parameters

    Returns:
        Modified parameters dict
    """
    params = default_params.copy()

    for mem in memories:
        text = mem.get("text", "").lower()
        metadata_str = mem.get("metadata", "{}")

        # Check for timeout-related failures
        if "timeout" in text or "timed out" in text:
            if "limit" in default_params:
                params["limit"] = min(default_params.get("limit", 100), 10)
            params.setdefault("warnings", []).append(
                "Historical failure: commands may timeout, consider reducing limit"
            )

        # Check for ACL failures
        if "acl" in text:
            params.setdefault("warnings", []).append(
                "Historical failure: check ACLs before proceeding"
            )

        # Check for MTU failures
        if "mtu" in text:
            params.setdefault("warnings", []).append("Historical failure: verify MTU compatibility")

    return params
