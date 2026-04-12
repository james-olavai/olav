"""Memory Middleware for OLAV Agentic Memory System.

.. deprecated::
    This module is superseded by the plugin framework.
    Use ``olav.plugins.middleware.memory_recall.MemoryRecallPlugin`` and
    ``olav.plugins.middleware.memory_capture.MemoryCapturePlugin`` instead.
    This file will be removed in the next major release.


Implements Phase 2 of the LANCEDB_MEMORY_SYSTEM_INTEGRATION plan:
  - AutoRecallMiddleware:  Pre-processor — injects relevant historical context
                           into the user prompt *before* agent thinking.
  - AutoCaptureMiddleware: Post-processor — extracts key facts/decisions from
                           the conversation and stores them into LanceDB after
                           a successful task execution.
  - apply_time_decay():    Applies temporal weight decay to all memory entries.
                           Formula: weight = max(0.1, 0.5 + 0.5 * exp(-age_days / half_life))
  - schedule_time_decay(): Optional background scheduler (requires apscheduler).
"""

import json
import logging
import math
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from olav.core.memory import MEMORY_TABLE, hybrid_search

if TYPE_CHECKING:
    from olav.core.memory import LanceDBStore

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

RECALL_TOP_K = 3  # Max memories to inject per query
CAPTURE_MAX_ITEMS = 3  # Max fact/decision items to extract per conversation
DECAY_HALF_LIFE_DAYS = 60  # Time-decay half-life (days)
DECAY_WEIGHT_FLOOR = 0.1  # Minimum weight after full decay

_EXTRACT_PROMPT = """\
You are a precise fact extractor. Given the following conversation between a user and an AI assistant,
extract at most {max_items} key items worth remembering for future sessions.
Output ONLY a JSON array. Each item must have:
  - "text": A concise human-readable statement of the fact/decision (max 120 chars).
  - "category": One of "fact", "decision", or "preference".
  - "importance": A float 0.0–1.0 indicating how important this is to remember.
  - "tags": A list of 2-5 entity/topic tags relevant to this item.
    Tags should be specific identifiers (device names, protocol names,
    IP addresses, tool names) rather than generic words.

Rules:
- Only extract genuinely useful, non-trivial information.
- If nothing worth remembering occurred, return: []
- Do not include generic greetings or error messages.
- Do not duplicate information already covered by obvious conversation context.
- Tags must be lowercase, no spaces (use hyphens for multi-word).

Conversation:
{conversation}

JSON array only, no extra text:"""


# ─────────────────────────────────────────────────────────────────────────────
# Auto-Recall
# ─────────────────────────────────────────────────────────────────────────────


class AutoRecallMiddleware:
    """Pre-processor that injects relevant memories into the user prompt.

    Queries LanceDB with the incoming user query (vector + text hybrid) and
    prepends a ``<relevant-memories>`` XML block to the last user message,
    giving the agent historical context before it starts reasoning.

    Usage::

        recall = AutoRecallMiddleware(store)
        augmented_input = await recall.enrich(user_input, scope="ops")
    """

    def __init__(
        self,
        store: "LanceDBStore",
        top_k: int = RECALL_TOP_K,
        min_score_threshold: float = 0.0,
    ) -> None:
        self._store = store
        self._top_k = top_k
        self._min_score = min_score_threshold

    def _embed(self, text: str) -> list[float] | None:
        """Embed text via the configured embedding backend (api or local)."""
        from olav.core.embedder import embed_text

        return embed_text(text)

    def _format_memory_block(self, memories: list[dict]) -> str:
        """Format recalled memories as an XML context block."""
        if not memories:
            return ""
        lines = ["<relevant-memories>"]
        for i, m in enumerate(memories, 1):
            cat = m.get("category", "fact")
            text = m.get("text", "").strip()
            ts = m.get("timestamp")
            date_str = ""
            if ts:
                try:
                    if isinstance(ts, datetime):
                        date_str = f" [{ts.strftime('%Y-%m-%d')}]"
                    else:
                        date_str = f" [{str(ts)[:10]}]"
                except Exception:
                    pass
            lines.append(f"  <memory id='{i}' category='{cat}'{date_str}>{text}</memory>")
        lines.append("</relevant-memories>")
        return "\n".join(lines)

    async def enrich(
        self,
        input_: str | dict,
        scope: str = "global",
    ) -> str | dict:
        """Enrich the input with recalled memories.

        Args:
            input_: The user input (str or LangGraph messages dict).
            scope: Memory scope to query (e.g. agent name or "global").

        Returns:
            Enriched input with memory context prepended to the last user message.
        """
        try:
            # Extract query text from input
            if isinstance(input_, str):
                query_text = input_
            elif isinstance(input_, dict):
                messages = input_.get("messages", [])
                # Get the last user message content
                query_text = ""
                for m in reversed(messages):
                    content = (
                        m.get("content", "") if isinstance(m, dict) else getattr(m, "content", "")
                    )
                    role = m.get("role", "") if isinstance(m, dict) else getattr(m, "type", "")
                    if role in ("human", "user") and content:
                        query_text = content
                        break
            else:
                return input_

            if not query_text:
                return input_

            # Check if memory table exists and has rows
            if not self._store.table_exists(MEMORY_TABLE):
                return input_
            try:
                if self._store.get_table(MEMORY_TABLE).count_rows() == 0:
                    return input_
            except Exception:
                return input_

            # Hybrid search: vector + text
            query_vector = self._embed(query_text)

            if query_vector:
                memories = hybrid_search(
                    store=self._store,
                    query=query_text,
                    query_vector=query_vector,
                    limit=self._top_k,
                    scope=scope,
                )
            else:
                memories = self._store.search_by_text(
                    query=query_text,
                    limit=self._top_k,
                    scope=scope,
                )

            if not memories:
                return input_

            context_block = self._format_memory_block(memories)
            if not context_block:
                return input_

            # Bump access_count for every recalled memory (non-blocking)
            for mem in memories:
                try:
                    self._store.update_memory(
                        mem["id"],
                        access_count=(mem.get("access_count") or 0) + 1,
                    )
                except Exception:
                    pass

            # Prepend to user message
            enriched_text = f"{context_block}\n\n{query_text}"
            logger.info(
                f"AutoRecall: injected {len(memories)} memories into prompt (scope={scope})"
            )

            if isinstance(input_, str):
                return enriched_text
            else:
                # Mutate the last user message in the messages list
                messages = list(input_.get("messages", []))
                for i in range(len(messages) - 1, -1, -1):
                    m = messages[i]
                    role = m.get("role", "") if isinstance(m, dict) else getattr(m, "type", "")
                    if role in ("human", "user"):
                        if isinstance(m, dict):
                            messages[i] = {**m, "content": enriched_text}
                        else:
                            m.content = enriched_text
                        break
                return {**input_, "messages": messages}

        except Exception as e:
            logger.warning(f"AutoRecall.enrich failed (non-fatal): {e}")
            return input_  # Always return original on error


# ─────────────────────────────────────────────────────────────────────────────
# Auto-Capture
# ─────────────────────────────────────────────────────────────────────────────


class AutoCaptureMiddleware:
    """Post-processor that extracts facts/decisions and stores them in LanceDB.

    After a successful agent invocation, this middleware:
    1. Extracts the conversation from the result.
    2. Calls a compact LLM prompt to identify ≤3 key facts/decisions.
    3. Embeds and stores each item in LanceDB (with deduplication).

    Usage::

        capture = AutoCaptureMiddleware(store, llm)
        await capture.process(original_input, agent_result, scope="ops")
    """

    def __init__(
        self,
        store: "LanceDBStore",
        llm,  # LangChain BaseChatModel
        max_items: int = CAPTURE_MAX_ITEMS,
        similarity_dedup_threshold: float | None = None,
    ) -> None:
        self._store = store
        self._llm = llm
        self._max_items = max_items
        # Read threshold from config if not explicitly provided, so it can be
        # overridden via api.json["memory"]["dedup_threshold"] or the
        # OLAV_MEMORY_DEDUP_THRESHOLD env var without touching code.
        if similarity_dedup_threshold is not None:
            self._dedup_threshold = similarity_dedup_threshold
        else:
            try:
                from olav.core.config import get_memory_config

                self._dedup_threshold = get_memory_config().dedup_threshold
            except Exception:
                self._dedup_threshold = 0.92

    def _embed(self, text: str) -> list[float] | None:
        """Embed text via the configured embedding backend (api or local)."""
        from olav.core.embedder import embed_text

        return embed_text(text)

    def _build_conversation_text(self, original_input, result: dict) -> str:
        """Build a text representation of the conversation from input + result."""
        parts = []

        # Original user message
        if isinstance(original_input, str):
            parts.append(f"User: {original_input}")
        elif isinstance(original_input, dict):
            for m in original_input.get("messages", []):
                role = (
                    m.get("role", "unknown")
                    if isinstance(m, dict)
                    else getattr(m, "type", "unknown")
                )
                content = m.get("content", "") if isinstance(m, dict) else getattr(m, "content", "")
                parts.append(f"{role.capitalize()}: {content}")

        # Agent result messages
        result_messages = result.get("messages", [])
        for m in result_messages[-6:]:  # Last 6 messages
            role = getattr(m, "type", None) or (
                m.get("role", "unknown") if isinstance(m, dict) else "unknown"
            )
            content = getattr(m, "content", None) or (
                m.get("content", "") if isinstance(m, dict) else ""
            )
            if content and role in ("ai", "assistant", "human", "user"):
                parts.append(f"{role.capitalize()}: {str(content)[:500]}")

        return "\n".join(parts)

    def _is_duplicate(self, text: str, scope: str) -> bool:
        """Check if a very similar memory already exists (vector similarity)."""
        vector = self._embed(text)
        if vector is None:
            return False
        try:
            existing = self._store.search_by_vector(
                query_vector=vector,
                limit=1,
                scope=scope,
            )
            if existing:
                score = existing[0].get("score")
                # LanceDB returns distance (lower = more similar)
                if score is not None and score < (1.0 - self._dedup_threshold):
                    logger.debug(f"AutoCapture: dedup hit (score={score:.3f}): {text[:60]}")
                    return True
        except Exception:
            pass
        return False

    async def process(
        self,
        original_input,
        result: dict,
        scope: str = "global",
    ) -> None:
        """Extract and store key facts/decisions from the conversation.

        Args:
            original_input: The original agent input (str or dict).
            result: The agent result dict (from ainvoke).
            scope: Memory scope for storage.
        """
        try:
            if not result or result.get("status") == "error":
                return  # Don't capture from failed runs

            conversation = self._build_conversation_text(original_input, result)
            if len(conversation.strip()) < 50:
                return  # Nothing to extract

            # Use LLM to extract facts/decisions
            prompt = _EXTRACT_PROMPT.format(
                max_items=self._max_items,
                conversation=conversation[:3000],  # truncate to avoid huge context
            )

            try:
                from langchain_core.messages import HumanMessage

                response = await self._llm.ainvoke([HumanMessage(content=prompt)])
                raw = response.content.strip()
            except Exception as e:
                logger.warning(f"AutoCapture: LLM extraction failed: {e}")
                return

            # Parse JSON response
            try:
                # Strip markdown code fences if any
                if raw.startswith("```"):
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                items = json.loads(raw.strip())
                if not isinstance(items, list):
                    return
            except Exception as e:
                logger.debug(f"AutoCapture: JSON parse failed: {e}. Raw: {raw[:100]}")
                return

            # Store each extracted item
            stored_count = 0
            for item in items[: self._max_items]:
                text = item.get("text", "").strip()
                category = item.get("category", "fact")
                importance = float(item.get("importance", 0.5))

                if not text or len(text) < 10:
                    continue

                # Validate category
                if category not in ("fact", "decision", "preference", "audit"):
                    category = "fact"

                # Deduplicate
                if self._is_duplicate(text, scope):
                    continue

                # Embed
                vector = self._embed(text)
                if vector is None:

                    # Fallback: zero vector (will be text-searched only)
                    vector = [0.0] * self._store.embedding_dim

                # Store
                import uuid

                memory_id = f"cap-{uuid.uuid4().hex[:8]}"
                tags_list = item.get("tags", [])
                if not isinstance(tags_list, list):
                    tags_list = []
                self._store.add_memory(
                    id=memory_id,
                    text=text,
                    vector=vector,
                    category=category,
                    scope=scope,
                    origin="agent",
                    confidence=importance,
                    tags=json.dumps(tags_list),
                    metadata={
                        "source": "auto_capture",
                        "importance": importance,
                        "captured_at": datetime.now(UTC).isoformat(),
                    },
                )
                stored_count += 1
                logger.debug(f"AutoCapture: stored '{text[:60]}' (cat={category}, scope={scope})")

            if stored_count:
                logger.info(f"AutoCapture: stored {stored_count} memory items (scope={scope})")

        except Exception as e:
            logger.warning(f"AutoCapture.process failed (non-fatal): {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Time-Decay
# ─────────────────────────────────────────────────────────────────────────────


def apply_time_decay(
    store: "LanceDBStore",
    half_life_days: float = DECAY_HALF_LIFE_DAYS,
    weight_floor: float = DECAY_WEIGHT_FLOOR,
    table_name: str | None = None,
) -> dict:
    """Apply time-based weight decay to all memories in the store.

    Formula (mirrors memory-lancedb-pro TypeScript implementation):
        new_weight = max(floor, 0.5 + 0.5 * exp(-age_days / half_life))

    At half_life_days age: ~0.68×
    At 2×half_life:        ~0.59×
    At 4×half_life:        ~0.52×

    Args:
        store:           LanceDBStore instance.
        half_life_days:  Half-life period in days (default: 60).
        weight_floor:    Minimum weight value (default: 0.1).
        table_name:      Optional table name override.

    Returns:
        Summary dict: {"updated": int, "skipped": int, "errors": int}.
    """
    tname = table_name or MEMORY_TABLE

    if not store.table_exists(tname):
        logger.info(f"apply_time_decay: table '{tname}' does not exist, skipping.")
        return {"updated": 0, "skipped": 0, "errors": 0}

    try:
        memories = store.get_memories(limit=10000, table_name=tname)
    except Exception as e:
        logger.error(f"apply_time_decay: failed to fetch memories: {e}")
        return {"updated": 0, "skipped": 0, "errors": 1}

    now = datetime.now(UTC)
    updated = skipped = errors = 0

    for mem in memories:
        mem_id = mem.get("id")
        if not mem_id:
            skipped += 1
            continue

        # ── Origin-based differentiation (C-KB-06/07) ────────────────────────
        origin = mem.get("origin", "agent") or "agent"
        if origin in ("document", "user"):
            # Never decay documents or user knowledge
            skipped += 1
            continue

        if origin == "audit":
            effective_half_life = 365.0
        else:
            effective_half_life = half_life_days

        # ── access_count boost (C-KB-08): high-recall memories decay slower ──
        access_count = mem.get("access_count", 0) or 0
        if access_count >= 5:
            effective_half_life *= 2.0

        ts = mem.get("timestamp")
        if ts is None:
            skipped += 1
            continue

        # Normalize timestamp to UTC-aware datetime
        try:
            if isinstance(ts, datetime):
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
            else:
                ts = datetime.fromisoformat(str(ts)).replace(tzinfo=UTC)
            age_days = (now - ts).total_seconds() / 86400.0
        except Exception:
            skipped += 1
            continue

        new_weight = max(weight_floor, 0.5 + 0.5 * math.exp(-age_days / effective_half_life))
        result = store.update_weight(id=mem_id, weight=new_weight, table_name=tname)

        if result.get("status") == "success":
            updated += 1
        else:
            errors += 1

    summary = {"updated": updated, "skipped": skipped, "errors": errors}
    logger.info(f"apply_time_decay: {summary} (half_life={half_life_days}d)")
    return summary


def schedule_time_decay(
    store: "LanceDBStore",
    interval_hours: float = 24.0,
    half_life_days: float = DECAY_HALF_LIFE_DAYS,
) -> object | None:
    """Start a background APScheduler job for periodic time-decay.

    Requires ``apscheduler`` to be installed (optional dependency).
    If unavailable, logs a warning and returns None.

    Args:
        store:           LanceDBStore instance.
        interval_hours:  How often to run decay (default: every 24h).
        half_life_days:  Half-life passed to apply_time_decay.

    Returns:
        APScheduler BackgroundScheduler instance, or None if unavailable.
    """
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        logger.warning(
            "schedule_time_decay: apscheduler not installed. "
            "Run `uv add apscheduler` to enable automatic time-decay scheduling. "
            "You can still call apply_time_decay() manually."
        )
        return None

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        func=apply_time_decay,
        trigger="interval",
        hours=interval_hours,
        args=[store],
        kwargs={"half_life_days": half_life_days},
        id="memory_time_decay",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        f"✓ Time-decay scheduler started: every {interval_hours}h, half_life={half_life_days}d"
    )
    return scheduler
