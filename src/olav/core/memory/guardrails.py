"""Security guardrail injection for OLAV agents.

GuardrailsPlugin / GuardrailInjector handle ONE category of memory:
``category="audit"`` — **security hard constraints** that must be injected
into the system message before every model call, regardless of quota or
relevance ranking.  Examples:
  - "Never execute DROP TABLE or DELETE without explicit user confirmation."
  - "Do not write to /etc or system directories via shell tools."

This is intentionally narrow.  Failure-learning constraints (operational
lessons from past runs) are NOT stored here.  They belong to the normal
AutoRecallMiddleware path:
  - ``trace_learner`` → ``category="reflection"``, ``scope="shared:audit"`` (ADR-0015)
  - ``AutoRecallMiddleware`` injects them ranked + quota-controlled into the
    user message for audit sub-agents only.

Why two paths:
  - Security constraints: must fire on every LLM call, not subject to
    quota, injected into system message (hard enforcement).
  - Failure-learning: optional context, quota-managed, injected into user
    message (soft guidance via AutoRecallMiddleware).
"""

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from olav.core.memory import LanceDBStore

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

GUARDRAIL_TOP_K = 5  # Max constraints to inject per invocation
GUARDRAIL_SECTION_HEADER = "=== LEARNED CONSTRAINTS (from past experience) ==="
GUARDRAIL_SECTION_FOOTER = "=== END CONSTRAINTS ==="

_FAILURE_AUDIT_CATEGORY = "audit"  # Security hard constraints only (not failure learning)
_FAILURE_FLAG_KEY = "failure"  # Metadata key indicating a security constraint entry


# ─────────────────────────────────────────────────────────────────────────────
# Failure Memory Store (helper for Auto-Capture to record failures)
# ─────────────────────────────────────────────────────────────────────────────


def store_failure_memory(
    store: "LanceDBStore",
    description: str,
    scope: str = "global",
    embedder=None,
    table_name: str | None = None,
) -> dict:
    """Store a security hard constraint into the guardrail memory (category='audit').

    Use this ONLY for security rules that must be injected into the system
    message before every model call (e.g. "never DROP TABLE without confirmation").

    For failure-learning constraints from past runs, use trace_learner instead —
    it writes category='reflection' scope='shared:audit' (ADR-0015) so AutoRecallMiddleware
    delivers them ranked and quota-controlled to audit sub-agents only.

    Args:
        store:       LanceDBStore instance.
        description: Security constraint text (max 200 chars).
        scope:       Memory scope (agent name or "global").
        embedder:    Optional sentence-transformers model (SentenceTransformer).
                     If None, fallback zero-vector is used.
        table_name:  Optional table name override.

    Returns:
        Result dict from LanceDBStore.add_memory().
    """
    import uuid

    from olav.core.memory import MEMORY_TABLE

    tname = table_name or MEMORY_TABLE
    if not store.table_exists(tname):
        store.create_table(tname)

    # Embed the description
    vector: list[float]
    if embedder is not None:
        try:
            vector = embedder.encode(description, normalize_embeddings=True).tolist()
        except Exception:
            vector = [0.0] * store.embedding_dim
    else:
        vector = [0.0] * store.embedding_dim

    memory_id = f"fail-{uuid.uuid4().hex[:8]}"
    result = store.add_memory(
        id=memory_id,
        text=description,
        vector=vector,
        category=_FAILURE_AUDIT_CATEGORY,
        scope=scope,
        metadata={
            _FAILURE_FLAG_KEY: True,
            "source": "failure_record",
        },
        table_name=tname,
    )
    logger.info(f"Stored failure memory: {description[:60]} (scope={scope})")
    return result


# ─────────────────────────────────────────────────────────────────────────────
# GuardrailInjector
# ─────────────────────────────────────────────────────────────────────────────


class GuardrailInjector:
    """Injects historical failure/success patterns as constraints into agent prompts.

    Queries LanceDB for ``audit`` category memories that contain failure flags
    or actionable patterns, then formats them as a constraint block and appends
    to the agent's system prompt.

    Usage::

        injector = GuardrailInjector(store)
        enriched_prompt = injector.inject(system_prompt, query=user_query, scope="ops")
    """

    def __init__(
        self,
        store: "LanceDBStore",
        top_k: int = GUARDRAIL_TOP_K,
        table_name: str | None = None,
    ) -> None:
        self._store = store
        self._top_k = top_k
        self._table_name = table_name
        self._embedder = None  # lazy-loaded

    def _embed(self, text: str) -> list[float] | None:
        """Embed text via the process-wide shared embedder."""
        from olav.core.embedder import get_embedder

        embedder = get_embedder()
        if embedder is None:
            return None
        try:
            return embedder.encode(text, normalize_embeddings=True).tolist()
        except Exception:
            return None

    def _get_relevant_audit_memories(self, query: str, scope: str) -> list[dict]:
        """Retrieve relevant audit memories, query-aware when embedder available."""
        from olav.core.memory import MEMORY_TABLE

        tname = self._table_name or MEMORY_TABLE

        if not self._store.table_exists(tname):
            return []

        try:
            # Try vector-guided retrieval first
            vector = self._embed(query)
            if vector:
                results = self._store.search_by_vector(
                    query_vector=vector,
                    limit=self._top_k,
                    category=_FAILURE_AUDIT_CATEGORY,
                    scope=scope,
                    table_name=tname,
                )
            else:
                # Fallback: just get recent audit memories
                results = self._store.get_memories(
                    category=_FAILURE_AUDIT_CATEGORY,
                    scope=scope,
                    limit=self._top_k,
                    table_name=tname,
                )
            return results
        except Exception as e:
            logger.debug(f"GuardrailInjector: memory query failed: {e}")
            return []

    @staticmethod
    def _format_constraint_line(memory: dict) -> str | None:
        """Format a single memory into a constraint bullet line."""
        text = memory.get("text", "").strip()
        if not text:
            return None

        # Parse metadata to determine failure vs success
        meta_raw = memory.get("metadata", "{}")
        try:
            meta = json.loads(meta_raw) if isinstance(meta_raw, str) else (meta_raw or {})
        except Exception:
            meta = {}

        is_failure = meta.get(_FAILURE_FLAG_KEY, False)
        prefix = "⚠" if is_failure else "✓"
        return f"  {prefix} {text}"

    def _format_guardrail_block(self, memories: list[dict]) -> str:
        """Format all audit memories into a constraints block."""
        lines = []
        for mem in memories:
            line = self._format_constraint_line(mem)
            if line:
                lines.append(line)

        if not lines:
            return ""

        return (
            f"\n\n{GUARDRAIL_SECTION_HEADER}\n" + "\n".join(lines) + f"\n{GUARDRAIL_SECTION_FOOTER}"
        )

    def inject(
        self,
        system_prompt: str,
        query: str = "",
        scope: str = "global",
    ) -> str:
        """Inject learned constraints into a system prompt.

        Args:
            system_prompt: The original system prompt string.
            query:         The current user query (used for relevance ranking).
            scope:         Memory scope to search (agent name or "global").

        Returns:
            System prompt with constraint block appended (or unchanged if no memories).
        """
        try:
            if not system_prompt:
                return system_prompt

            memories = self._get_relevant_audit_memories(query, scope)
            if not memories:
                return system_prompt

            block = self._format_guardrail_block(memories)
            if not block:
                return system_prompt

            logger.info(
                f"GuardrailInjector: injected {len(memories)} constraints "
                f"into system prompt (scope={scope})"
            )
            return system_prompt + block

        except Exception as e:
            logger.warning(f"GuardrailInjector.inject failed (non-fatal): {e}")
            return system_prompt  # Always return original on error

    def get_block(
        self,
        query: str = "",
        scope: str = "global",
    ) -> str:
        """Return just the constraint text block (without modifying any prompt).

        Useful for injecting into a human message rather than the system prompt.

        Args:
            query: The current user query (for relevance ranking).
            scope: Memory scope to search.

        Returns:
            Formatted constraint block string, or "" if no memories found.
        """
        try:
            memories = self._get_relevant_audit_memories(query, scope)
            return self._format_guardrail_block(memories)
        except Exception as e:
            logger.debug(f"GuardrailInjector.get_block failed: {e}")
            return ""

    def record_failure(
        self,
        description: str,
        scope: str = "global",
    ) -> dict:
        """Convenience method to store a failure memory directly.

        Args:
            description: What failed (e.g. "collect inventory on host-3 timed out").
            scope:       Memory scope.

        Returns:
            Result dict.
        """
        return store_failure_memory(
            store=self._store,
            description=description,
            scope=scope,
            embedder=self._embedder if (self._embedder and self._embedder is not False) else None,
        )
