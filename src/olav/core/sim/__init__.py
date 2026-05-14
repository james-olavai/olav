"""olav.core.sim — Batfish-backed sim primitives.

Replaces the legacy ``olav.core.cab.sim`` Python pipeline (deleted
2026-05-14, commit b4045d69).  Per dev_docs/77 §2 the new sim is a
2-tool LLM sub-agent that delegates feasibility / reachability /
differential questions to a Batfish service via ``batfish_q``.
"""

from .batfish_capability import BATFISH_VENDOR_SUPPORT, batfish_capability
from .batfish_q import batfish_q

__all__ = ["batfish_q", "batfish_capability", "BATFISH_VENDOR_SUPPORT"]
