"""Entry-point hook for platform ``olav audit selftest``.

Mirrors the pattern in ``diff_hook.py``: the platform CLI dispatches
audit operations through the ``olav.cli_tools`` entry-point group so
``src/olav/`` never reaches into the netops workspace directly.

This hook locates the workspace-vendored ``map_engine.py`` and returns
its ``selftest_profile`` callable.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Callable


def load_selftest_profile() -> Callable | None:
    """Walk parents for ``audit/runner/tools/map_engine.py``; return its
    ``selftest_profile`` callable or None if unavailable.

    Candidates checked, in order:
      * <anc>/.olav/workspace/audit/runner/tools/map_engine.py
        (post-rev-259 Run/Author split — current shape)
      * <anc>/.olav/workspace/audit/auditor/tools/map_engine.py
        (pre-rev-259 — fallback for older installs)
    """
    here = Path(__file__).resolve()
    suffixes = [
        (".olav", "workspace", "audit", "runner", "tools", "map_engine.py"),
        (".olav", "workspace", "audit", "auditor", "tools", "map_engine.py"),
    ]
    for anc in here.parents:
        for suffix in suffixes:
            candidate = anc.joinpath(*suffix)
            if not candidate.exists():
                continue
            spec = importlib.util.spec_from_file_location(
                "_olav_netops_audit_map_engine", candidate
            )
            if spec is None or spec.loader is None:
                continue
            mod = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(mod)
            except Exception:
                continue
            fn = getattr(mod, "selftest_profile", None)
            if fn is not None:
                return fn
    return None
