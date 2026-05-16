"""Autonomous network audit — external scratchpad primitives.

See ``dev_docs/83. AUTONOMOUS_EXPLORER_SUBAGENT.md`` for the design.

Public API (used by the netops/explorer sub-agent and its @tool wrappers):

  * ``start_exploration(db_path, snapshot_id, ...) → run_id``
  * ``record_finding(db_path, run_id, ...) → finding_id``
  * ``update_exploration_run(db_path, run_id, ...)``

All three are pure Python — no LLM, no agent framework — so they can be
unit tested without spinning up langchain.
"""
from __future__ import annotations

from .promote import promote_finding_to_audit
from .scratchpad import (
    record_finding,
    start_exploration,
    update_exploration_run,
)

__all__ = [
    "promote_finding_to_audit",
    "record_finding",
    "start_exploration",
    "update_exploration_run",
]
