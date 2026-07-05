"""batfish_q @tool — re-export for in-process tool discovery.

The canonical implementation (with module-level session + snapshot cache)
lives in ``olav_netops.core.sim.batfish_q``.  Importing it here makes
``discover_tools`` find the StructuredTool without re-wrapping it, so
``_BF_SESSION`` and ``_LOADED_SNAPSHOTS`` persist across calls within the
same agent process — the whole point of promoting this from scripts: to tools:.
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

from olav_netops.core.sim.batfish_q import batfish_q  # noqa: F401
