"""Per-invocation run context carried through LangGraph's ``Runtime``.

Why this module exists
----------------------
Before v0.20.1, the :class:`olav.plugins.callbacks.audit.AuditCallbackPlugin`
shared a mutable ``_bound_run_id`` between the CLI and the callback by
calling ``bind_run(run_id, recorder)`` before every invocation and
``unbind_run()`` after.  That pattern does not translate to
``AgentMiddleware`` — middleware instances are created at graph-build
time and receive no per-invocation hook.

LangGraph 1.x instead lets the caller attach a typed ``context`` object
to each ``ainvoke`` / ``astream``; every middleware hook can then read
it as ``runtime.context``.  This module defines the carrier
:class:`OlavRunContext` and a small helper API so audit/guardrails/
memory middleware can all agree on how to get the current ``run_id``.

Immutability rationale
----------------------
``OlavRunContext`` is a frozen dataclass.  Two concurrent turns on the
same agent instance must each carry their own ``run_id``; mutating a
shared object would guarantee audit-trail cross-contamination.
``with_run_id()`` returns a fresh instance so mutation is impossible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class OlavRunContext:
    """Read-only snapshot of the current invocation's run metadata.

    Attach to a graph call via
    ``graph.ainvoke(inputs, config=..., context=ctx)`` so every
    middleware hook can access ``runtime.context`` to tag its events
    with the same ``run_id`` the CLI/API recorded at turn start.

    Attributes:
        run_id: Stable UUID string identifying this turn.  ``None``
            means "no caller-supplied run context" — middleware should
            fall back to its own UUID or skip the event.
        recorder: Pre-opened ``AuditEventRecorder`` the caller wants
            events written to.  ``Any`` instead of a concrete type so
            this module stays import-cheap — no audit-layer imports
            at this level.  ``None`` means "use the middleware's own
            default recorder or skip".
        agent_id: Which top-level OLAV agent is running (``core`` /
            ``ops`` / ``audit`` / …).  Populated from the ``-a`` CLI
            flag or the API route.
        user_id: Authenticated username for audit dataset joins.
            ``None`` when auth is off.
        source_channel: Origin tag used by :class:`AuditEventRecorder`:
            ``cli`` (single-query), ``cli_interactive`` (TUI),
            ``api`` (web), ``cli_token`` (silent auth).  Defaults to
            ``"cli"`` so bare code paths without explicit context
            still get sensible attribution.
    """

    run_id: str | None = None
    recorder: Any = None
    agent_id: str | None = None
    user_id: str | None = None
    source_channel: str = "cli"

    def with_run_id(self, run_id: str) -> OlavRunContext:
        """Return a new context with *run_id* replaced.

        All other fields are preserved.  Frozen-dataclass semantics
        ensure the original instance is untouched — callers can hold
        ``base_ctx`` and derive per-turn contexts without a lock.

        Args:
            run_id: The new run identifier (typically a UUID).

        Returns:
            A new :class:`OlavRunContext` that differs only in its
            ``run_id`` field.
        """
        from dataclasses import replace

        return replace(self, run_id=run_id)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-safe dict for embedding in audit payloads.

        Intentionally:

        * **excludes** the ``recorder`` field — the recorder is a live
          DB-connected object, not serialisable, and including it
          would pull the audit-layer types into every log line.
        * **omits** fields whose value is ``None`` — keeps payloads
          compact and makes the recipient distinguish "missing" from
          "empty string".

        Returns:
            A plain dict containing at most ``run_id``, ``agent_id``,
            ``user_id``, ``source_channel``.
        """
        payload: dict[str, Any] = {"source_channel": self.source_channel}
        if self.run_id is not None:
            payload["run_id"] = self.run_id
        if self.agent_id is not None:
            payload["agent_id"] = self.agent_id
        if self.user_id is not None:
            payload["user_id"] = self.user_id
        return payload


__all__ = ["OlavRunContext"]
