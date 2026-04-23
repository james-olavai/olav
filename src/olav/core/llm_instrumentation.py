"""Sprint 0a token_meter: per-request token usage capture.

A LangChain ``BaseCallbackHandler`` that extracts ``usage_metadata`` from
the LLM response and forwards it to the audit pipeline as a
``token_usage`` event plus an in-process ``ContextBudgetMonitor`` tick.

Failure mode is always soft — if an audit recorder or budget monitor
isn't available the callback silently no-ops. The goal is visibility,
never blocking an LLM invocation.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

logger = logging.getLogger(__name__)


# ── helpers ──────────────────────────────────────────────────────────────────


def _extract_usage(response: Any) -> dict[str, int] | None:
    """Return ``{input_tokens, output_tokens, total_tokens}`` from an LLM result.

    LangChain evolved this shape several times between 0.1 → 0.3; try each
    known location and fall back to ``None`` when nothing parses. All
    fields default to 0 so downstream math is safe.
    """
    # LangChain 0.3+ exposes usage on message.usage_metadata
    generations = getattr(response, "generations", None) or []
    for gen_list in generations:
        for gen in gen_list:
            message = getattr(gen, "message", None)
            if message is not None:
                meta = getattr(message, "usage_metadata", None)
                if isinstance(meta, dict) and any(k in meta for k in
                                                   ("input_tokens", "output_tokens")):
                    return {
                        "input_tokens": int(meta.get("input_tokens", 0)),
                        "output_tokens": int(meta.get("output_tokens", 0)),
                        "total_tokens": int(
                            meta.get("total_tokens", 0)
                            or meta.get("input_tokens", 0) + meta.get("output_tokens", 0)
                        ),
                    }

    # LEGACY-KEEP: LangChain 0.1/0.2 still ships on some deployments and
    # emits usage under llm_output.token_usage instead of message.usage_metadata.
    # Keep this branch until the supported-LC floor moves past 0.3.
    llm_output = getattr(response, "llm_output", None) or {}
    token_usage = llm_output.get("token_usage") or llm_output.get("usage") or {}
    if token_usage:
        prompt = int(
            token_usage.get("input_tokens")
            or token_usage.get("prompt_tokens", 0)
        )
        completion = int(
            token_usage.get("output_tokens")
            or token_usage.get("completion_tokens", 0)
        )
        return {
            "input_tokens": prompt,
            "output_tokens": completion,
            "total_tokens": int(token_usage.get("total_tokens", 0) or prompt + completion),
        }

    return None


# ── callback ─────────────────────────────────────────────────────────────────


class TokenUsageCallback(BaseCallbackHandler):
    """Per-request token meter.

    Attach to ``init_chat_model(callbacks=[TokenUsageCallback(...)])`` or
    pass as the ``config.callbacks`` on ``llm.invoke(...)``. On each
    ``on_llm_end`` the handler:

    * parses ``usage_metadata`` / ``llm_output.token_usage`` (shape-agnostic)
    * records a ``token_usage`` audit event (soft-skips if no recorder)
    * ticks the ``ContextBudgetMonitor`` if one was attached

    Never raises — all exceptions are downgraded to debug logs so a
    telemetry hiccup cannot stop an LLM call.
    """

    def __init__(
        self,
        *,
        recorder: Any = None,
        budget_monitor: Any = None,
        run_id: str | None = None,
        model_name: str | None = None,
        model_tier: str | None = None,
    ) -> None:
        self._recorder = recorder
        self._budget = budget_monitor
        self._run_id = run_id
        self._model_name = model_name
        self._model_tier = model_tier

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        try:
            usage = _extract_usage(response)
        except Exception as exc:
            logger.debug("token_meter: failed to parse usage_metadata: %s", exc)
            return
        if not usage:
            return

        # ── audit event (soft) ────────────────────────────────────────
        if self._recorder is not None:
            try:
                self._recorder.record(
                    event_type="token_usage",
                    run_id=self._run_id,
                    payload={
                        **usage,
                        "model": self._model_name,
                        "tier": self._model_tier,
                    },
                )
            except Exception as exc:
                logger.debug("token_meter: audit record failed: %s", exc)

        # ── budget monitor tick ───────────────────────────────────────
        if self._budget is not None:
            try:
                self._budget.add_usage(int(usage.get("total_tokens", 0)))
            except Exception as exc:
                logger.debug("token_meter: budget tick failed: %s", exc)
