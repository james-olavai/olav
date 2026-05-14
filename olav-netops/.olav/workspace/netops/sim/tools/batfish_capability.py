"""Workspace wrapper — re-export ``batfish_capability`` for sim's
SKILL.md whitelist resolver.  Canonical impl in olav.core.sim.
"""
from olav.core.sim.batfish_capability import batfish_capability

__all__ = ["batfish_capability"]
