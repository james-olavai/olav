"""
Auto-correction and HITL rules for NetBox reconciliation.
"""

from olav.sync.rules.auto_correct import (
    AUTO_CORRECT_RULES,
    is_safe_auto_correct,
    get_auto_correct_handler,
)
from olav.sync.rules.hitl_required import (
    HITL_REQUIRED_RULES,
    requires_hitl_approval,
    get_hitl_prompt,
    get_hitl_summary,
)

__all__ = [
    "AUTO_CORRECT_RULES",
    "HITL_REQUIRED_RULES",
    "is_safe_auto_correct",
    "requires_hitl_approval",
    "get_auto_correct_handler",
    "get_hitl_prompt",
    "get_hitl_summary",
]
