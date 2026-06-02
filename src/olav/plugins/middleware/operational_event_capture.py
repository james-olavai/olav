"""OperationalEventCapturePlugin — Layer 1 of agentic memory growth.

After each agent run, scan messages for write-class tool calls
(register_service, deploy_*, push_*, save_*, destroy_*, write_*,
record_*, emit_*, ...) and record one ``operational_event`` memory
per unique action. The aim: re-run a similar request next time
and have AutoRecall surface concrete prior context — "last time you
registered a service of kind X, you used auth=api_key with
TOKEN_ENV=..." rather than starting from zero.

Layer 2 (pattern abstraction across N samples) is **NOT** here — it
runs as a curator agent task on schedule (see
``audit/curator/skills/extract_operational_patterns``). Splitting
keeps the hot-path cheap and the LLM-extract path auditable /
optional.

Design choices:

* **Heuristic detection**, not @tool metadata: matches names by
  prefix patterns. Avoids forcing every tool author to remember
  to flag "this is a write". Pattern list is conservative;
  false-negatives just mean the action isn't captured (no harm).
  False-positives would create noise — addressed by the
  ``_REDACT_FIELD_PATTERNS`` strict list and a min-length filter
  on the captured summary.

* **Secret redaction** before embed/write. Match a small allowlist
  of obvious secret-bearing keys (``token``, ``password``,
  ``api_key``, ...) anywhere in the args/result and replace the
  value with ``"<redacted>"``. Conservative — won't catch domain-
  specific secrets but handles the 80% case.

* **Idempotent** by content hash: if the exact same captured
  summary already exists for this scope, skip writing duplicate.

* **One memory per tool call**, not per agent run. Multi-tool runs
  (e.g. save_lab_config × 4 nodes) write 4 memories — operators
  can verify "yes, all 4 nodes saved" by retrieval.
"""

from __future__ import annotations

import hashlib
import json as _json
import logging
from typing import TYPE_CHECKING, Any

from olav.plugins.base import OLAVMiddlewarePlugin

if TYPE_CHECKING:
    from langgraph.runtime import Runtime
    from olav.core.memory import LanceDBStore

logger = logging.getLogger(__name__)


# Tool name segments matching these verb roots count as "write"
# operations worth capturing. Match is on snake_case segments —
# ``tcf_emit_from_sim`` → ["tcf", "emit", "from", "sim"] → "emit"
# matches → write. Conservative list — extend as new tools are added.
_WRITE_VERB_ROOTS = frozenset({
    "register",   # register_service
    "deploy",     # deploy_and_push_lab, deploy_lab
    "push",       # push_node_config
    "save",       # save_lab_config, save_profile, save_recipe
    "destroy",    # destroy_lab
    "write",      # write_workspace_file
    "record",     # tcf_record_lab_run, record_network_event
    "emit",       # tcf_emit_from_sim
    "export",     # format_and_export (writes file artefacts)
    "ingest",     # bulk_ingest, *_ingest
    "stop",       # stop_service (state change)
    "create",     # create_*
    "update",     # update_*
    "delete",     # delete_*
    "exec",       # exec_on_node — remote command execution
})

# Full tool names whose write nature isn't captured by verb-in-segments.
_WRITE_TOOL_FULL: frozenset[str] = frozenset()


# Substrings of arg/result keys whose values get redacted before
# memory write. Conservative allowlist — names like "secret_recipe"
# would also match "secret" but that's acceptable over-redaction.
_REDACT_KEY_SUBSTRINGS = (
    "token", "password", "api_key", "apikey", "secret",
    "credential", "passwd", "auth_header",
)


def _msg_role(msg: Any) -> str:
    if hasattr(msg, "type"):
        return getattr(msg, "type", "")
    if isinstance(msg, dict):
        return msg.get("role") or msg.get("type") or ""
    return ""


def _msg_content(msg: Any) -> Any:
    if hasattr(msg, "content"):
        return msg.content
    if isinstance(msg, dict):
        return msg.get("content")
    return None


def _msg_tool_name(msg: Any) -> str:
    if hasattr(msg, "name"):
        return getattr(msg, "name", "") or ""
    if isinstance(msg, dict):
        return msg.get("name") or msg.get("tool_call_id") or ""
    return ""


def _is_write_tool(tool_name: str) -> bool:
    """True if any snake_case segment of the tool name is a write verb,
    or the full name is in the explicit write-tool allowlist."""
    if not tool_name:
        return False
    name = tool_name.lower()
    if name in _WRITE_TOOL_FULL:
        return True
    segments = name.split("_")
    return any(seg in _WRITE_VERB_ROOTS for seg in segments)


def _redact_value(v: Any) -> Any:
    """Recursively walk a value; redact dict values whose key matches a
    secret substring. Lists and primitives pass through."""
    if isinstance(v, dict):
        out = {}
        for k, val in v.items():
            klow = str(k).lower()
            if any(sub in klow for sub in _REDACT_KEY_SUBSTRINGS):
                out[k] = "<redacted>"
            else:
                out[k] = _redact_value(val)
        return out
    if isinstance(v, list):
        return [_redact_value(x) for x in v]
    return v


def _summarize_call(tool_name: str, args: dict | None, result: Any) -> str:
    """Produce a short, embeddable text summary of a tool call.

    Format pinned for AutoRecall ranking — embed quality drops if
    structure varies wildly across captures."""
    args = _redact_value(args or {})
    # Cap result size — long lists / blobs make embeddings useless
    res = result
    try:
        if isinstance(res, str) and len(res) > 400:
            res = res[:400] + "...(truncated)"
        elif isinstance(res, (list, dict)):
            res_text = _json.dumps(_redact_value(res), default=str)
            if len(res_text) > 400:
                res = res_text[:400] + "...(truncated)"
            else:
                res = res_text
    except Exception:
        res = str(res)[:400]
    args_text = _json.dumps(args, default=str, ensure_ascii=False)
    if len(args_text) > 600:
        args_text = args_text[:600] + "...(truncated)"
    return (
        f"Action: {tool_name}\n"
        f"Args: {args_text}\n"
        f"Result: {res}"
    )


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class OperationalEventCapturePlugin(OLAVMiddlewarePlugin):
    """Capture write-class tool invocations as ``operational_event`` memories."""

    name = "operational_event_capture"
    version = "1.0.0"
    description = "捕获写操作（部署/注册/推送/保存）为 operational_event memory；为 L2 模式抽取喂数据"
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
            logger.debug("operational_event_capture: embed failed: %s", exc)
            return None

    async def aafter_agent(
        self,
        state: dict[str, Any],
        runtime: "Runtime",
    ) -> dict[str, Any] | None:
        """Walk messages, find write-tool ToolMessages, write one memory each.

        Idempotent on content hash — repeated runs of the same op
        won't duplicate. Failures are silent (debug-logged) so a
        broken capture never tanks an agent flow.
        """
        messages = state.get("messages") or []
        if not messages:
            return None

        # AIMessage.tool_calls carries the args; ToolMessage carries the
        # name + result. We pair them by walking the message list.
        # Pattern: AIMessage(tool_calls=[{name,args,id}]) immediately
        # followed by ToolMessage(name=..., tool_call_id=...).
        pending_args: dict[str, dict] = {}  # tool_call_id → args
        captures: list[dict] = []
        for m in messages:
            # AIMessage with tool_calls
            tc_list = getattr(m, "tool_calls", None) or (
                m.get("tool_calls") if isinstance(m, dict) else None
            )
            if tc_list:
                for tc in tc_list:
                    if isinstance(tc, dict):
                        tcid = tc.get("id", "")
                        pending_args[tcid] = tc.get("args", {})
            # ToolMessage with result
            if _msg_role(m) == "tool":
                name = _msg_tool_name(m)
                if not _is_write_tool(name):
                    continue
                tcid = (
                    getattr(m, "tool_call_id", "")
                    or (m.get("tool_call_id", "") if isinstance(m, dict) else "")
                )
                args = pending_args.get(tcid, {})
                content = _msg_content(m)
                # Try to JSON-parse content; fall back to raw string
                result: Any = content
                if isinstance(content, str):
                    try:
                        result = _json.loads(content)
                    except Exception:
                        result = content
                # Skip if the result indicates a failure (don't pollute
                # memory with broken examples). Heuristic: dict with
                # status=error OR string starting with "Error:".
                if isinstance(result, dict) and result.get("status") == "error":
                    continue
                if isinstance(result, str) and result.lower().startswith(("error:", "exception")):
                    continue
                summary = _summarize_call(name, args, result)
                if len(summary) < 30:  # too short to embed meaningfully
                    continue
                captures.append({
                    "tool": name,
                    "summary": summary,
                    "hash": _content_hash(summary),
                })

        if not captures:
            return None

        store = self._get_store()
        try:
            from olav.core.memory import MEMORY_TABLE
            # Pre-fetch existing hashes for this scope to skip duplicates
            existing: set[str] = set()
            try:
                tbl = store.get_table(MEMORY_TABLE)
                rows = tbl.search().where(
                    f"scope = '{self._scope}' AND category = 'operational_event'",
                    prefilter=True,
                ).limit(1000).to_list()
                for r in rows:
                    md = r.get("metadata") or "{}"
                    try:
                        md_dict = _json.loads(md) if isinstance(md, str) else (md or {})
                    except Exception:
                        md_dict = {}
                    h = md_dict.get("content_hash")
                    if h:
                        existing.add(h)
            except Exception as exc:
                logger.debug("op_event: existing-hash prefetch failed: %s", exc)
        except Exception:
            existing = set()

        written = 0
        for cap in captures:
            if cap["hash"] in existing:
                continue
            vec = self._embed(cap["summary"])
            if vec is None:
                continue
            try:
                store.add_memory(
                    id=f"opev-{cap['hash']}",
                    text=cap["summary"],
                    vector=vec,
                    category="operational_event",
                    scope=self._scope,
                    metadata={
                        "tool": cap["tool"],
                        "content_hash": cap["hash"],
                    },
                    origin="agent",
                    confidence=0.8,
                    # 2026-05-14: weight=0.5 for L1 auto-captured operational
                    # events.  These are illustrative ("last time you did X")
                    # not normative — the ranker multiplies score by weight,
                    # so usage_guide entries (weight=1.0+) sort above prior-
                    # example noise.  Adjustable via OLAV_OPEV_WEIGHT env.
                    weight=0.5,
                    tags=_json.dumps([cap["tool"]]),
                )
                written += 1
            except Exception as exc:
                logger.debug("op_event: add_memory failed for %s: %s", cap["tool"], exc)

        if written:
            logger.info(
                "operational_event_capture: wrote %d events for scope=%s",
                written, self._scope,
            )
        return None
