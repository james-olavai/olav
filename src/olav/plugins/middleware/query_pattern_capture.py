"""Query Pattern Capture — store successful (intent → SQL) tuples for recall.

R83.2 (P0): OLAV is designed for small models that can't always follow a
written introspection workflow.  Cache + memory are the fallbacks.  This
middleware captures the SQL queries that just produced a useful answer
and writes them to LanceDB memory; the existing :class:`AutoRecallMiddleware`
will then surface them as ``<relevant-memories>`` context the next time
a similar question comes in — letting the agent imitate a prior
success rather than re-derive the introspection workflow.

Why a new middleware vs extending :class:`MemoryCapturePlugin`?  The
existing AutoCapture relies on an LLM to extract "facts/decisions/
preferences" from the conversation — that's unreliable for SQL
templates on small models (they often paraphrase the answer instead
of copying the SQL verbatim).  This middleware is **deterministic**:
it walks the message log, finds ``execute_sql`` tool calls + their
results, and stores them by pattern-match — no LLM in the loop.

Capture criteria (all must hold):

1. The user asked a question (at least one ``human``/``user`` message).
2. At least one ``execute_sql`` tool call ran successfully (returned
   a list of rows, even an empty one — empty doesn't count as
   "successful answer", see #4).
3. The final ``assistant`` message has non-empty content (i.e. agent
   produced an answer for the user).
4. The execute_sql result was non-empty (skipping captures of "no
   rows found" results — those are not useful templates to imitate).

Stored memory shape::

    text: "Question: {user_query}\nWorking SQL: {sql}"
    category: "query_pattern"
    tags: extracted keywords from user_query
    metadata.intent: user_query
    metadata.sql: the actual SQL
    metadata.tool_count: number of execute_sql calls in the chain
"""
from __future__ import annotations

import logging
import re
import uuid as _uuid
from typing import TYPE_CHECKING, Any

from olav.plugins.base import OLAVMiddlewarePlugin

if TYPE_CHECKING:
    from langgraph.runtime import Runtime

    from olav.core.memory import LanceDBStore

logger = logging.getLogger(__name__)

_KEYWORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
_STOPWORDS = frozenset({
    "the", "and", "are", "for", "with", "from", "that", "this", "those",
    "these", "have", "has", "had", "what", "which", "where", "when",
    "show", "list", "get", "tell", "all", "any", "some", "our", "your",
    "their", "into", "onto", "into", "between", "across", "every",
})


def _extract_keywords(text: str, max_n: int = 6) -> list[str]:
    """Return up to *max_n* salient keywords from a user query.

    Lower-cased, stop-words removed, dedup, ordered by first occurrence.
    Used as memory tags so AutoRecall's hybrid search can match similar
    intents semantically AND by tag.
    """
    seen: list[str] = []
    for tok in _KEYWORD_RE.findall(text.lower()):
        if tok in _STOPWORDS:
            continue
        if tok in seen:
            continue
        seen.append(tok)
        if len(seen) >= max_n:
            break
    return seen


def _msg_role(msg: Any) -> str:
    if isinstance(msg, dict):
        return msg.get("role") or msg.get("type") or ""
    return getattr(msg, "type", "") or getattr(msg, "role", "")


def _msg_content(msg: Any) -> str:
    if isinstance(msg, dict):
        return str(msg.get("content") or "")
    return str(getattr(msg, "content", "") or "")


def _msg_tool_calls(msg: Any) -> list[dict]:
    if isinstance(msg, dict):
        return msg.get("tool_calls") or []
    return getattr(msg, "tool_calls", None) or []


def _msg_tool_name(msg: Any) -> str:
    """Tool-result messages carry the tool name for matching back to args."""
    if isinstance(msg, dict):
        return msg.get("name") or ""
    return getattr(msg, "name", "") or ""


class QueryPatternCapturePlugin(OLAVMiddlewarePlugin):
    """Store successful execute_sql patterns in memory after each agent run."""

    name = "query_pattern_capture"
    version = "1.0.0"
    description = "捕获成功 SQL 查询为可召回模板（小模型 few-shot 兜底）"
    tags = ["memory", "builtin"]

    def __init__(self, store: "LanceDBStore | None" = None, scope: str = "global") -> None:
        self._store = store
        self._scope = scope

    def _get_store(self):
        if self._store is not None:
            return self._store
        from olav.core.memory import get_store
        return get_store()

    def _embed(self, text: str):
        try:
            from olav.core.embedder import embed_text
            return embed_text(text)
        except Exception as exc:
            logger.debug("query_pattern_capture: embed failed: %s", exc)
            return None

    async def aafter_agent(
        self, state: dict[str, Any], runtime: "Runtime",
    ) -> dict[str, Any] | None:
        messages = state.get("messages") or []
        if not messages:
            return None

        # 1. user query — first human/user message.  AutoRecallMiddleware
        # wraps the user input with a ``<relevant-memories>...
        # </relevant-memories>`` block — strip it back out before we
        # store/embed the query, otherwise memory entries reference
        # earlier memories and the embedding drifts away from the real
        # intent.
        user_query = ""
        for m in messages:
            if _msg_role(m) in ("human", "user"):
                raw = _msg_content(m).strip()
                user_query = re.sub(
                    r"<relevant-memories>.*?</relevant-memories>",
                    "", raw, flags=re.DOTALL,
                ).strip()
                if user_query:
                    break
        if not user_query or len(user_query) < 5:
            return None

        # 2. final assistant message — must be non-empty
        final_assistant = ""
        for m in reversed(messages):
            if _msg_role(m) in ("ai", "assistant"):
                final_assistant = _msg_content(m).strip()
                break
        if not final_assistant:
            return None

        # 3. execute_sql tool calls.  The ``execute_sql`` tool returns a
        # JSON dict with both ``data`` (rows) and ``sql`` (echo of the
        # query that ran).  Walk every ``role=tool, name=execute_sql``
        # message, parse its JSON content, and collect (sql, row_count)
        # tuples.  This is robust to the exact LangGraph message shape
        # — no dependency on AIMessage.tool_calls / args propagation.
        import json as _json
        sql_calls: list[dict] = []  # [{sql, row_count}]
        for m in messages:
            if _msg_role(m) != "tool":
                continue
            if _msg_tool_name(m) != "execute_sql":
                continue
            content = _msg_content(m)
            if not content:
                continue
            try:
                payload = _json.loads(content) if isinstance(content, str) else content
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            sql = (payload.get("sql") or "").strip()
            if not sql:
                continue
            data = payload.get("data")
            row_count = len(data) if isinstance(data, list) else 0
            sql_calls.append({"sql": sql, "row_count": row_count})
        if not sql_calls:
            return None

        # 4. Score each SQL by row count: data-fetch queries score high,
        # exploration / DESCRIBE / information_schema / COUNT checks
        # score low (≤1 row).  Keep the top-scoring SQL.  Skip
        # introspection queries (e.g. DESCRIBE / information_schema /
        # SHOW) and aggregations (COUNT) so they don't pollute memory
        # — they're not patterns the agent should imitate, they're
        # exploration steps.
        _BORING_RE = re.compile(
            r"\b(DESCRIBE|information_schema|SHOW\s+TABLES|json_keys|json_structure|"
            r"PRAGMA|SELECT\s+COUNT\s*\()",
            re.IGNORECASE,
        )

        def _score(call: dict) -> int:
            sql = call.get("sql") or ""
            if _BORING_RE.search(sql):
                return 0
            return int(call.get("row_count") or 0)

        winner = max(sql_calls, key=_score, default=None)
        if winner is None or _score(winner) == 0:
            return None

        # 5. write memory entry (deterministic, no LLM)
        try:
            store = self._get_store()
            text = (
                f"Q: {user_query}\n"
                f"Working SQL: {winner['sql']}"
            )
            vec = self._embed(text)
            if not vec:
                return None
            tags = _extract_keywords(user_query)
            mem_id = f"qp_{_uuid.uuid4().hex[:12]}"
            import json as _json
            store.add_memory(
                id=mem_id,
                text=text,
                vector=vec,
                category="query_pattern",
                scope=self._scope,
                metadata={
                    "intent": user_query[:512],
                    "sql": winner["sql"][:4096],
                    "tool_count": len(sql_calls),
                },
                origin="agent",
                confidence=0.7,  # higher than auto-extracted facts
                tags=_json.dumps(tags, ensure_ascii=False),
            )
            logger.info(
                "query_pattern_capture: stored intent=%r sql_len=%d tags=%s",
                user_query[:60], len(winner["sql"]), tags,
            )
        except Exception as exc:
            logger.debug("query_pattern_capture: write failed: %s", exc)

        return None
