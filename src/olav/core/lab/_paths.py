"""Path resolution for the lab module.

Replaces the brittle ``Path(__file__).resolve().parents[4]`` pattern
that worked in the editable / dev tree but broke on wheel install
(``parents[4]`` from ``site-packages/olav/core/lab`` lands on the
Python lib dir, not the project root).

Resolution order for ``olav_root()``:

  1. ``OLAV_HOME`` env var — explicit caller override (highest priority)
  2. Walk upward from ``Path.cwd()`` for a dir containing a
     ``.olav/workspace/<agent>/lab/config/config.json`` — works for
     any install style as long as the user runs from inside their
     workspace.  The ``<agent>`` segment is a glob so the
     resolver works under any agent naming (``ops``,
     ``netops``, future renames).
  3. Walk upward from this file's ``__file__`` looking for the same
     marker — catches editable / source-tree installs even when cwd is
     elsewhere
  4. Fall back to ``Path.cwd()`` — caller hits FileNotFoundError on
     subsequent file ops, which is a clearer failure mode than wrong
     path

Anything matching ``.olav/workspace/*/lab/config/config.json`` is a
strong-enough signal that the surrounding ``.olav/`` tree is the
"real" workspace, not a stale or partial copy.

History (Fix #1, 2026-05-07): the original ``_MARKER`` hard-coded
``ops/lab/config/config.json`` and broke after the agent rename
(commit ``b3c7da5``) that moved the workspace from ``ops/`` to
``netops_ops/``, then again on R-AGENT-HIERARCHY Phase A which
collapsed the dir to ``netops/``.  Switched to a glob so any
future rename keeps working.
"""

from __future__ import annotations

import os
from pathlib import Path

# Glob pattern for marker file.  Matches under any agent dir so
# rename-of-agent doesn't break path resolution.
_MARKER_GLOB = ".olav/workspace/*/lab/config/config.json"


def _has_marker(candidate: Path) -> bool:
    """True iff ``candidate`` contains a file matching _MARKER_GLOB.

    Uses ``Path.glob`` (single-level) since the pattern has only one
    wildcard; cheaper than rglob and avoids descending into other
    repos that happen to live under the candidate root.
    """
    try:
        return any(candidate.glob(_MARKER_GLOB))
    except OSError:
        return False


def _ascend_until_marker(start: Path) -> Path | None:
    """Walk upward from ``start`` (inclusive) for a dir whose subtree
    contains _MARKER_GLOB.  Returns the matching dir, or None on miss.
    """
    start = start.resolve()
    for cand in [start, *start.parents]:
        if _has_marker(cand):
            return cand
    return None


def olav_root() -> Path:
    """Resolve the OLAV project/workspace root.

    See module docstring for full resolution order. Returns an absolute
    path. Never raises — falls back to ``Path.cwd().resolve()`` on
    total miss so subsequent file operations get a clear "file not
    found" rather than a confusing wrong-dir error.
    """
    env = os.environ.get("OLAV_HOME")
    if env:
        return Path(env).expanduser().resolve()

    cwd_hit = _ascend_until_marker(Path.cwd())
    if cwd_hit is not None:
        return cwd_hit

    here_hit = _ascend_until_marker(Path(__file__).resolve())
    if here_hit is not None:
        return here_hit

    return Path.cwd().resolve()


def _lab_workspace_dir() -> Path:
    """Return the actual ``.olav/workspace/<agent>/lab/`` dir for the
    workspace rooted at :func:`olav_root`.

    Picks the first match if multiple agent dirs ship a lab subtree;
    real OLAV deployments only ever have one (per ADR-0002 lab is a
    network-domain concern owned by one agent at a time).
    """
    root = olav_root()
    matches = sorted(root.glob(".olav/workspace/*/lab"))
    if matches:
        return matches[0]
    # Last-resort default — keeps callers from breaking if marker
    # exists but the lab dir was deleted between calls.
    return root / ".olav" / "workspace" / "ops" / "lab"


def lab_config_path() -> Path:
    """Path to the active workspace's
    ``.olav/workspace/<agent>/lab/config/config.json``.

    Existence not guaranteed — caller handles ``FileNotFoundError``.
    """
    return _lab_workspace_dir() / "config" / "config.json"


def lab_workspace_tools_dir() -> Path:
    """Path to ``.olav/workspace/<agent>/lab/tools/`` — vendored helper
    modules loaded via ``importlib.util.spec_from_file_location``.

    Returns the dir even when not present so callers can format clear
    error messages.
    """
    return _lab_workspace_dir() / "tools"
