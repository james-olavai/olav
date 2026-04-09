"""
permission_generator.py — Generate RBAC PermissionRules from services.yaml permissions

Converts the services.yaml permissions section into PermissionRule objects
compatible with olav.core.auth.authz.check_permission().

Reference: dev_docs/16. SERVICE_REGISTRY_DESIGN.md §Phase1
"""

from __future__ import annotations

from olav.core.auth.authz import PermissionRule
from olav.platform.services.registry import ServiceConfig


def generate_permission_rules(
    svc: ServiceConfig,
    agent_id: str = "*",
) -> list[PermissionRule]:
    """Build PermissionRule list from a ServiceConfig's permissions section.

    Args:
        svc:      The registered service config.
        agent_id: Agent to scope rules to (default: wildcard "*").

    Returns:
        List of PermissionRule objects ready for use with check_permission().

    Example::

        rules = generate_permission_rules(registry.get("containerlab"))
        # rules → [PermissionRule(role="admin", agent_id="*", skill_name="clab_*", ...), ...]
    """
    rules: list[PermissionRule] = []

    # Derive skill name prefix from reference_generation (preferred) or tool_generation (legacy)
    ref_groups = getattr(svc, "reference_generation", None)
    tool_groups = getattr(svc, "tool_generation", None)
    groups = (ref_groups.groups if ref_groups and ref_groups.groups else
              tool_groups.groups if tool_groups and tool_groups.groups else [])
    tool_prefixes = {g.tool_prefix for g in groups if g.tool_prefix}
    # Use service name as fallback skill scope
    skill_scope = f"{next(iter(tool_prefixes))}_*" if tool_prefixes else f"{svc.name}_*"

    for role, entry in svc.permissions.items():
        for action in entry.actions:
            rules.append(
                PermissionRule(
                    role=role,
                    agent_id=agent_id,
                    skill_name=skill_scope,
                    action=action,
                    is_allowed=True,
                )
            )

        # Roles with operation_filter get explicit deny for mutating actions
        if entry.operation_filter:
            for denied_action in ("mutate", "install", "admin"):
                if denied_action not in entry.actions:
                    rules.append(
                        PermissionRule(
                            role=role,
                            agent_id=agent_id,
                            skill_name=skill_scope,
                            action=denied_action,
                            is_allowed=False,
                        )
                    )

    return rules
