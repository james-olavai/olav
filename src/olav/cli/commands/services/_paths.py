"""Shared workspace-root resolver for service lifecycle commands.

Why this module exists
----------------------
Pre-rc4, every service module (``web.py`` / ``daemon_svc.py`` / ``logs.py``)
defined its own ``_find_project_root()`` that walked up from
``Path(__file__)`` looking for ``pyproject.toml``.  Two failure modes hit
production demos in v0.21.0-rc3:

1. Wheel installs have no ``pyproject.toml`` anywhere in the venv tree.
   The walk reaches ``/`` and falls back to ``Path.cwd()`` *at module
   import time*.  Whichever cwd the first ``olav service`` call had
   becomes the frozen project root for the rest of the process — even
   if the user later ``cd`` somewhere else.

2. Worse, when the user happens to run ``olav`` from inside another
   project (e.g. testing the demo install while standing in the dev
   source repo), the walk **does** find a ``pyproject.toml`` — the
   wrong one.  Spawned uvicorn/daemon processes inherit cwd from
   the parent, so they end up reading the *dev* repo's
   ``.olav/databases/users.duckdb``.  Login then 401s with no useful
   diagnostic.

See gitea issue #12 for the verified repro.

Resolution policy
-----------------
A workspace is identified by the presence of ``.olav/`` (the runtime
control plane: databases, config, logs).  ``find_workspace_root()``
walks up from ``Path.cwd()`` (re-resolved on every call, never cached
at import time) and stops at the first ancestor with ``.olav/``.  If
no ancestor matches, it returns ``Path.cwd()`` so callers still get a
sensible fallback for fresh ``olav init`` runs.

Callers should:

1. Import ``find_workspace_root`` (the function), not a module-level
   constant.  Re-resolving on every operation makes the cwd-coupling
   visible at the call site instead of hidden in import order.

2. Pass ``cwd=str(find_workspace_root())`` explicitly to every
   ``subprocess.Popen`` that launches a long-running service.  Even if
   the resolver is wrong, the spawned process must not be left to
   inherit cwd by accident — that's how rc3's symptom reproduced.
"""

from __future__ import annotations

from pathlib import Path

_WORKSPACE_MARKER = ".olav"
"""Directory whose presence identifies an OLAV workspace root.  Same
marker every olav command uses — keep in sync with ``olav init``'s
scaffolding logic."""


def find_workspace_root(start: Path | str | None = None) -> Path:
    """Return the OLAV workspace root for *start* (defaults to ``Path.cwd()``).

    Walks up from *start* until an ancestor containing ``.olav/`` is
    found.  Falls back to *start* itself when no ``.olav/`` ancestor
    exists (typical for the moments before the first ``olav init``).

    Args:
        start: Directory to start the search from.  ``None`` means
            "use the current working directory at call time".  Pass an
            explicit path in tests to avoid global-state coupling.

    Returns:
        Absolute :class:`~pathlib.Path` to the workspace root.

    Notes:
        Resolved on **every call**, never cached.  Service start/stop
        operations need the value re-derived against current cwd; a
        cached module-level constant is what made issue #12 hard to
        diagnose.
    """
    here = Path(start).resolve() if start is not None else Path.cwd().resolve()
    p = here
    while p != p.parent:
        if (p / _WORKSPACE_MARKER).is_dir():
            return p
        p = p.parent
    return here


__all__ = ["find_workspace_root"]
