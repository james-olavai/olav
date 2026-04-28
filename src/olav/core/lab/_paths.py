"""Path resolution for the lab module.

Replaces the brittle ``Path(__file__).resolve().parents[4]`` pattern
that worked in the editable / dev tree but broke on wheel install
(``parents[4]`` from ``site-packages/olav/core/lab`` lands on the
Python lib dir, not the project root).

Resolution order for ``olav_root()``:

  1. ``OLAV_HOME`` env var — explicit caller override (highest priority)
  2. Walk upward from ``Path.cwd()`` for a dir containing
     ``.olav/workspace/ops/lab/config/config.json`` — works for any
     install style as long as the user runs from inside their workspace
  3. Walk upward from this file's ``__file__`` looking for the same
     marker — catches editable / source-tree installs even when cwd is
     elsewhere
  4. Fall back to ``Path.cwd()`` — caller hits FileNotFoundError on
     subsequent file ops, which is a clearer failure mode than wrong
     path

The marker file is ``.olav/workspace/ops/lab/config/config.json``
specifically because that's the one this module's callers always need;
its presence is a strong signal that the surrounding ``.olav/`` tree
is the "real" workspace, not a stale or partial copy.
"""

from __future__ import annotations

import os
from pathlib import Path

# Marker file used to identify the .olav workspace root. Chosen because
# ops-lab is what this module serves and config.json must exist for
# CLAB deploy to work — so its presence is a strong-enough signal.
_MARKER = Path(".olav") / "workspace" / "ops" / "lab" / "config" / "config.json"


def _ascend_until_marker(start: Path) -> Path | None:
    """Walk upward from ``start`` (inclusive) for a dir containing _MARKER.
    Returns the matching dir, or None if no parent has the marker."""
    start = start.resolve()
    candidates = [start, *start.parents]
    for cand in candidates:
        if (cand / _MARKER).exists():
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


def lab_config_path() -> Path:
    """Path to ``.olav/workspace/ops/lab/config/config.json``.

    Existence not guaranteed — caller handles ``FileNotFoundError``.
    """
    return olav_root() / ".olav" / "workspace" / "ops" / "lab" / "config" / "config.json"


def lab_workspace_tools_dir() -> Path:
    """Path to ``.olav/workspace/ops/lab/tools/`` — vendored helper
    modules loaded via ``importlib.util.spec_from_file_location``.

    Returns the dir even when not present so callers can format clear
    error messages.
    """
    return olav_root() / ".olav" / "workspace" / "ops" / "lab" / "tools"
