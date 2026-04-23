"""Sprint 0a budget_models: soft-warning context budget monitor.

Aggregates token usage over a single agent run and emits a single
``logger.warning`` + ``budget_warning`` audit event when cumulative
consumption crosses a tier-defined threshold. Never raises, never
aborts — the aim is operational visibility, not gating.

Typical wiring::

    monitor = ContextBudgetMonitor()                 # picks up model_tier
    callback = TokenUsageCallback(budget_monitor=monitor, ...)
    model = init_chat_model(..., callbacks=[callback])

Each ``on_llm_end`` ticks ``monitor.add_usage(total_tokens)`` so the
monitor gradually learns how much of the tier budget a run has eaten.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ContextBudgetMonitor:
    """Per-run token budget tracker (soft warning only).

    The tier-specific budget is pulled from
    :data:`olav.core.config.TIER_DEFAULTS` so a small-model (8K) run will
    warn after ~6.4K tokens (at the default 0.8 threshold) while a large
    tier (200K) won't warn on the same absolute usage.
    """

    def __init__(
        self,
        *,
        tier: str | None = None,
        budget: int | None = None,
        warn_threshold: float = 0.8,
        recorder: Any = None,
        run_id: str | None = None,
    ) -> None:
        if budget is not None:
            self._tier = tier or "custom"
            self._budget = int(budget)
        else:
            # Resolve tier lazily so imports aren't ordered by call-site.
            from olav.core.config import get_llm_config, tier_default

            self._tier = tier or get_llm_config().model_tier
            self._budget = int(tier_default(self._tier, "context_budget", 200_000))
        self._warn_threshold = max(0.0, min(1.0, float(warn_threshold)))
        self._recorder = recorder
        self._run_id = run_id
        self._used: int = 0
        self._warned: bool = False

    # ── mutators ─────────────────────────────────────────────────────────

    def add_usage(self, total_tokens: int) -> None:
        """Record ``total_tokens`` from a single LLM call and warn once
        if cumulative usage crosses ``warn_threshold`` of the budget."""
        if total_tokens <= 0:
            return
        self._used += int(total_tokens)
        ratio = self._used / max(self._budget, 1)
        if ratio >= self._warn_threshold and not self._warned:
            logger.warning(
                "context budget %.0f%% used (%d/%d, tier=%s) — compact "
                "tool returns or delegate via olav_delegate",
                ratio * 100,
                self._used,
                self._budget,
                self._tier,
            )
            self._warned = True
            self._emit_audit(ratio)

    def reset(self) -> None:
        """Clear accumulated usage and the one-shot warn latch."""
        self._used = 0
        self._warned = False

    # ── readers ──────────────────────────────────────────────────────────

    def snapshot(self) -> dict[str, Any]:
        return {
            "tier": self._tier,
            "budget": self._budget,
            "used": self._used,
            "ratio": self._used / max(self._budget, 1),
            "warned": self._warned,
            "warn_threshold": self._warn_threshold,
        }

    @property
    def used(self) -> int:
        return self._used

    @property
    def warned(self) -> bool:
        return self._warned

    # ── helpers ──────────────────────────────────────────────────────────

    def _emit_audit(self, ratio: float) -> None:
        if self._recorder is None:
            return
        try:
            self._recorder.record(
                event_type="budget_warning",
                run_id=self._run_id,
                payload={
                    "tier": self._tier,
                    "budget": self._budget,
                    "used": self._used,
                    "ratio": round(ratio, 4),
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("budget audit record failed: %s", exc)
