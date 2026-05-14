"""Workspace wrapper — re-export the canonical `batfish_q` @tool
from `olav.core.sim.batfish_q` so the sim sub-agent's SKILL.md
whitelist resolver picks it up.

The actual implementation lives in the package (testable, importable
outside the workspace).  Per dev_docs/77 §2.1.
"""
from olav.core.sim.batfish_q import batfish_q

__all__ = ["batfish_q"]
