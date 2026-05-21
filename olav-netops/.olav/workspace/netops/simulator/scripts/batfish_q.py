#!/usr/bin/env python3
"""batfish_q — generic Batfish question runner.

Thin script wrapper around ``olav.core.sim.batfish_q``.  The canonical
implementation lives in the package; this script exposes it for
subprocess / stdin-JSON invocation by the sim sub-agent.

Returned envelope::

    {
      "status": "ok" | "error",
      "rows":   list[dict] | None,
      "row_count": int,
      "snapshot_id": "<the snapshot used>",
      "reference_snapshot": "<if differential>" | None,
      "message": "<error detail when status=error>",
    }
"""
from __future__ import annotations

import sys
from pathlib import Path


def _find_project_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


sys.path.insert(0, str(_find_project_root() / "src"))

from olav.core.sim.batfish_q import batfish_q as _batfish_q


def batfish_q(
    snapshot_id: str,
    question: str,
    q_args: dict | None = None,
    reference_snapshot: str | None = None,
) -> dict:
    """Run a Batfish question against a netops snapshot.

    Args:
        snapshot_id: netops snapshot identifier.
        question: Batfish question name (e.g. ``bgpSessionStatus``,
            ``reachability``, ``routes``, ``differentialReachability``).
        q_args: optional kwargs forwarded to ``bf.q.<question>(**q_args)``.
        reference_snapshot: optional reference snapshot for differential
            questions.
    """
    return _batfish_q.func(
        snapshot_id=snapshot_id,
        question=question,
        q_args=q_args,
        reference_snapshot=reference_snapshot,
    )


if __name__ == "__main__":
    import json as _json, sys as _sys
    _args = _json.loads(_sys.stdin.read() or "{}")
    result = batfish_q(**_args)
    print(_json.dumps(result, default=str))
