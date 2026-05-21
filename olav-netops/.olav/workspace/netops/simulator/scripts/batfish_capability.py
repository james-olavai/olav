#!/usr/bin/env python3
"""batfish_capability — pre-flight check for Batfish vendor support.

Thin script wrapper around ``olav.core.sim.batfish_capability``.  Call
this FIRST before any ``batfish_q`` when scope includes mixed / unfamiliar
vendors to discover which devices are fully / partially / not supported.

Returns::

    {
      "per_device": {hostname: {"platform": str, "capability": "FULL"|"PARTIAL"|"NONE"|"UNKNOWN"}},
      "summary": "FULL"|"PARTIAL"|"NONE"|"EMPTY",
      "unsupported_devices": [names],
      ...
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

from olav.core.sim.batfish_capability import batfish_capability as _batfish_capability


def batfish_capability(
    devices: list[str] | None = None,
    snapshot_id: str | None = None,
) -> dict:
    """Pre-flight check: which in-scope devices can Batfish evaluate?

    Args:
        devices: list of device hostnames to check.  If empty/None,
            checks ALL devices in netops.devices.
        snapshot_id: optional snapshot context (currently informational
            only — static map is snapshot-agnostic).
    """
    return _batfish_capability.func(devices=devices, snapshot_id=snapshot_id)


if __name__ == "__main__":
    import json as _json, sys as _sys
    _args = _json.loads(_sys.stdin.read() or "{}")
    result = batfish_capability(**_args)
    print(_json.dumps(result, default=str))
