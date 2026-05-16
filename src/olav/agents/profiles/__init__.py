"""OLAV harness profiles — tier-based behavior overrides.

Profiles are deepagents `HarnessProfile` objects keyed by the
``provider:model`` spec.  They let us encode per-tier discipline
(tool whitelist, prompt suffix, middleware excludes) without
scattering ``if model.startswith("gemma")`` branches across
``agent.py``.

Architecture (2026-05-16 refactor):
    Profiles are organised **by tier**, not by model identity, because
    the adherence pattern OLAV actually needs to correct for is a
    function of model size (small / medium / large), not of model
    family.  Truly model-specific overlays (Anthropic prompt caching,
    Codex action-bias, OpenRouter routing) belong in
    ``profiles/overlays/`` and compose on top of tier profiles via
    deepagents' additive registration semantics.

Tier source of truth: ``olav.core.config._TIER_REGEX_SMALL`` /
``_TIER_REGEX_MEDIUM`` — the same patterns the rest of OLAV uses for
context-budget / recall-top-k / summarisation-threshold inference.

Registration is idempotent and side-effect-only — importing this
package once at OLAVAgent construction time is enough.  Re-registering
under the same key merges on top (deepagents 0.5.4+ semantics).

Per dev_docs/77 R88-A / R89 / R90 the architectural fix for small-model
adherence issues is *structural*, not "use a bigger model".  Profiles
are how that structural fix gets declared.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_REGISTERED = False


def register_olav_profiles() -> None:
    """Register all OLAV-owned harness profiles with deepagents.

    Idempotent — subsequent calls are no-ops.  Called once from
    :class:`OLAVAgent.__init__` before ``create_deep_agent``.
    """
    global _REGISTERED
    if _REGISTERED:
        return
    registered: list[str] = []
    try:
        from olav.agents.profiles import tier_small, tier_medium
        tier_small.register()
        registered.append("tier_small")
        tier_medium.register()
        registered.append("tier_medium")
        # tier_large: deepagents stock behavior is fine — large models
        # don't need OLAV-imposed discipline.  No profile registered.
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "OLAV harness-profile registration failed (non-fatal — "
            "falls back to deepagents stock behavior): %s: %s",
            type(exc).__name__, exc,
        )
        return
    _REGISTERED = True
    logger.info("✓ OLAV harness profiles registered: %s", registered)
