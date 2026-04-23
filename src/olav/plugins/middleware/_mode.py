"""Selector for the dual-path audit mode.

The P3 migration keeps both the legacy ``AuditCallbackPlugin`` and the
new :class:`AuditMiddleware` active in the same build so users can
opt in to either path without rebuilding OLAV.  A single environment
variable, ``OLAV_MIDDLEWARE_MODE``, decides which of the two actually
receives events at graph-invoke time:

==============  ========================================================
Value           Behaviour
==============  ========================================================
``callback``    v0.20.1 default.  ``AuditCallbackPlugin`` audits; the
                ``AuditMiddleware`` is dropped from the middleware list
                so the same events aren't recorded twice.
``middleware``  Audit flows through the :class:`AgentMiddleware`.  The
                callback plugin is skipped.  Required for Phase 6
                (server-subprocess TUI) where callbacks can't cross
                process boundaries.
anything else   Log a warning, fall back to ``callback``.
==============  ========================================================

The selector is a pure function over the plugin registry — no I/O,
no LangGraph types — so it's cheap to unit test and cheap to call at
graph-build time.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Literal, Tuple

logger = logging.getLogger(__name__)

MiddlewareMode = Literal["callback", "middleware"]

_ENV_VAR = "OLAV_MIDDLEWARE_MODE"
"""Environment variable consulted by :func:`resolve_middleware_mode`."""

_DEFAULT_MODE: MiddlewareMode = "middleware"
"""v0.20.3 cutover: middleware is now the default audit path.

History:
* v0.20.1 — introduced ``OLAV_MIDDLEWARE_MODE`` with default ``callback``
* v0.20.2 — infrastructure (tool_loader / migrate), no change here
* v0.20.3 — default flipped to ``middleware``; ``callback`` still
  available via explicit opt-in
* v0.21.x (planned) — ``AuditCallbackPlugin`` deletion once we have
  one full release cycle of confidence in middleware behaviour."""

_AUDIT_MIDDLEWARE_NAME = "audit_middleware"
"""Plugin name registered by :class:`AuditMiddleware`.  The partitioner
drops a plugin by matching this name — keeps the coupling to the
middleware class shallow (no import)."""

_AUDIT_CALLBACK_NAME = "audit"
"""Plugin name registered by :class:`AuditCallbackPlugin`."""


def resolve_middleware_mode() -> MiddlewareMode:
    """Return the effective audit mode for this process.

    Reads the ``OLAV_MIDDLEWARE_MODE`` environment variable once per
    call (OLAVAgent construction is typically once per process, so we
    don't cache).  Unknown values downgrade to the default and log a
    WARNING so misconfigured deployments show up in logs.

    Returns:
        Either ``"callback"`` or ``"middleware"``.
    """
    raw = (os.environ.get(_ENV_VAR) or "").strip().lower()
    if raw in ("callback", "middleware"):
        return raw  # type: ignore[return-value]
    if raw:
        logger.warning(
            "%s=%r is not a recognised value; falling back to %r. "
            "Valid values: 'callback', 'middleware'.",
            _ENV_VAR,
            raw,
            _DEFAULT_MODE,
        )
    return _DEFAULT_MODE


def partition_for_mode(
    registry: Any,
    mode: str,
) -> Tuple[list[Any], list[Any]]:
    """Return (effective_middleware, effective_callbacks) for *mode*.

    The registry carries *all* plugins regardless of mode; this
    function subtracts the opposite path's audit plugin so events
    flow through exactly one observer.  Every other plugin
    (guardrails, memory_capture, safety, output_formatter, security
    sidecar, …) passes through unchanged.

    Args:
        registry: Any object with ``get_middleware_plugins()`` and
            ``get_callback_plugins()`` methods (typed as ``Any`` so
            tests can pass lightweight fakes).
        mode: ``"callback"`` or ``"middleware"`` — anything else
            behaves like ``"callback"`` (defensive fallback matching
            :func:`resolve_middleware_mode`'s policy).

    Returns:
        A tuple ``(middleware_list, callback_list)`` with the opposite
        path's audit plugin removed.  List order preserved — plugin
        ordering is semantically significant for some middleware
        (e.g. guardrails rewrites the system prompt before
        memory_recall reads it).
    """
    all_mw = list(registry.get_middleware_plugins())
    all_cb = list(registry.get_callback_plugins())

    normalised = mode if mode in ("callback", "middleware") else "callback"

    if normalised == "middleware":
        callbacks = [c for c in all_cb if getattr(c, "name", "") != _AUDIT_CALLBACK_NAME]
        middleware = all_mw
    else:
        # callback mode (default + fallback)
        middleware = [
            m for m in all_mw if getattr(m, "name", "") != _AUDIT_MIDDLEWARE_NAME
        ]
        callbacks = all_cb

    return middleware, callbacks


__all__ = [
    "MiddlewareMode",
    "partition_for_mode",
    "resolve_middleware_mode",
]
