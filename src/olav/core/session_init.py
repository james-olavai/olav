"""Per-agent session-init hooks — generic domain launch callback.

A domain package (e.g. olav-presales) sometimes needs to set up in-process
session state when its agent launches — state that a subprocess script cannot
set for the parent agent process. The canonical case (ADR-0017, dev_docs/100
§4.6) is presales exporting ``OLAV_ACTIVE_PROJECT`` so the memory-layer project
predicate is actually active in a live session.

The platform stays generic: it calls every callable registered under the
``olav.session_init`` entry-point group with the resolved ``agent_id``; the hook
decides whether it applies. Failures are swallowed (a hook must never break
agent construction).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def run_session_init(agent_id: str) -> None:
    """Invoke every ``olav.session_init`` hook with ``agent_id`` (best-effort)."""
    try:
        from importlib.metadata import entry_points

        for ep in entry_points(group="olav.session_init"):
            try:
                ep.load()(agent_id)
            except Exception as exc:  # noqa: BLE001 — a hook must not break launch
                logger.debug("session_init hook %r failed: %s", ep.name, exc)
    except Exception as exc:  # noqa: BLE001
        logger.debug("session_init discovery failed: %s", exc)
