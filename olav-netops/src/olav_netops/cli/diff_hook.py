"""Entry-point hook for platform ``olav diff`` command.

ADR-0002 P4: the platform CLI dispatches ``olav diff`` through the
``olav.cli_tools`` entry-point group rather than importlib-loading a
file path from ``.olav/workspace/netops/tools/``. The path walk stays in
the domain package so ``src/olav/`` never reaches into the netops
workspace directly.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Callable


def load_diff_snapshots() -> Callable | None:
    """Locate and load the workspace-vendored ``diff_snapshots`` callable.

    Walks from this module up the filesystem looking for the packaged
    workspace copy at ``.olav/workspace/netops/scripts/diff_snapshots.py``
    (canonical since the tools→scripts migration).  Falls back to the
    legacy ``tools/`` subdirectory for backwards compatibility with older
    installs.  That file is shipped inside the olav-netops wheel (and
    mirrored in the repo root during dev) so an installed environment always
    has a copy adjacent to this hook.
    """
    here = Path(__file__).resolve()
    for anc in here.parents:
        # scripts/ is the canonical location post-migration; tools/ kept for compat.
        for subdir in ("scripts", "tools"):
            candidate = anc / ".olav" / "workspace" / "netops" / subdir / "diff_snapshots.py"
            if candidate.exists():
                spec = importlib.util.spec_from_file_location(
                    "_olav_netops_diff_snapshots", candidate
                )
                if spec is None or spec.loader is None:
                    continue
                mod = importlib.util.module_from_spec(spec)
                try:
                    spec.loader.exec_module(mod)
                except Exception:
                    continue
                fn = getattr(mod, "diff_snapshots", None)
                if fn is not None:
                    return fn
    return None
