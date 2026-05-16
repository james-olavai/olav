"""OLAV harness profiles — model-specific behavior overrides.

Profiles are deepagents `HarnessProfile` objects keyed by the
``provider:model`` spec.  They let us encode per-model discipline
(tool whitelist, prompt suffix, middleware excludes) without scattering
``if model.startswith("gemma")`` branches across ``agent.py``.

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

    Idempotent — subsequent calls are no-ops (registration merge would
    still work but emits redundant info logs).  Called once from
    :class:`OLAVAgent.__init__` before ``create_deep_agent``.
    """
    global _REGISTERED
    if _REGISTERED:
        return
    try:
        from olav.agents.profiles import gemma4
        gemma4.register()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "OLAV harness-profile registration failed (non-fatal — "
            "falls back to deepagents stock behavior): %s: %s",
            type(exc).__name__, exc,
        )
        return
    _REGISTERED = True
    logger.info("✓ OLAV harness profiles registered: [gemma4]")
