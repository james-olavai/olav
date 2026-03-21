"""OLAV Role-Based Access Control (RBAC) — baseline enforcement.

Design reference: dev_docs/olav_aaa.md §D4, §D6, §7.1

Three fixed roles: ``admin``, ``user``, ``readonly``.
Four actions:     ``use``, ``mutate``, ``install``, ``admin``.

Runtime SSOT
------------
:data:`DEFAULT_PERMISSIONS` is the **authoritative runtime source-of-truth** for RBAC
decisions.  The ``role_skill_permissions`` table in the project DuckDB database is only
a migration/seed artefact — it records the same baseline policy but is **not** consulted
at runtime by :func:`check_permission` or :func:`require_permission`.

This distinction matters for the planned ``olav-core`` / ``olav-ent`` repo split:
``DEFAULT_PERMISSIONS`` lives in pure Python and has no DB dependency, making it safe
to vendor into an independent package.  Any future dynamic/per-tenant overrides should
be loaded into a custom ``rules`` list and passed explicitly to the auth functions.

Matching priority (most-specific first):
    1. Exact agent_id + exact skill_name + exact action
    2. Exact agent_id + wildcard skill  + exact action
    3. Wildcard agent + exact skill      + exact action
    4. Wildcard agent + wildcard skill   + exact action
    5. Wildcard agent + wildcard skill   + wildcard action

If no matching rule is found the default policy is **deny**.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PermissionRule:
    """A single RBAC permission rule.

    Attributes
    ----------
    role:        ``"admin"`` | ``"user"`` | ``"readonly"``
    agent_id:    Agent identifier or ``"*"`` for wildcard.
    skill_name:  Skill name or ``"*"`` for wildcard.
    action:      ``"use"`` | ``"mutate"`` | ``"install"`` | ``"admin"`` | ``"*"``.
    is_allowed:  Whether this rule grants (True) or denies (False) access.
    """

    role: str
    agent_id: str
    skill_name: str
    action: str
    is_allowed: bool


class AuthorizationError(Exception):
    """Raised when a role is denied access to an action.

    Attributes
    ----------
    message:     Human-readable description.
    role:        The role that was denied.
    agent_id:    The agent the action targeted.
    skill_name:  The skill the action targeted.
    action:      The denied action.
    """

    def __init__(
        self,
        message: str,
        role: str,
        agent_id: str,
        skill_name: str,
        action: str,
    ) -> None:
        super().__init__(message)
        self.role = role
        self.agent_id = agent_id
        self.skill_name = skill_name
        self.action = action


# ── Default Permission Matrix ─────────────────────────────────────────────────
#
# Runtime SSOT: this list is the authoritative source for all check_permission()
# and require_permission() calls at runtime.  The DB table role_skill_permissions
# is a migration/seed snapshot only — it is NOT consulted at runtime.
#
# Baseline policy per olav_aaa.md §7.1:
#   admin    — full access (wildcard)
#   user     — use all, mutate all, but NO install/admin on workspace
#   readonly — use only, everything else denied
#
# Rule ordering is irrelevant for matching — specificity wins.

DEFAULT_PERMISSIONS: list[PermissionRule] = [
    # ── admin: everything allowed ─────────────────────────────────────────
    PermissionRule(role="admin", agent_id="*", skill_name="*", action="*", is_allowed=True),
    # ── user: use + mutate + read + submit-write allowed; install/admin/approve-write denied on workspace ─────
    PermissionRule(role="user", agent_id="*", skill_name="*", action="use", is_allowed=True),
    PermissionRule(role="user", agent_id="*", skill_name="*", action="mutate", is_allowed=True),
    PermissionRule(role="user", agent_id="*", skill_name="*", action="read", is_allowed=True),
    PermissionRule(
        role="user", agent_id="*", skill_name="*", action="submit-write", is_allowed=True
    ),
    PermissionRule(
        role="user", agent_id="*", skill_name="*", action="approve-write", is_allowed=False
    ),
    PermissionRule(
        role="user", agent_id="workspace", skill_name="*", action="install", is_allowed=False
    ),
    PermissionRule(
        role="user", agent_id="workspace", skill_name="*", action="admin", is_allowed=False
    ),
    # ── readonly: use + read allowed; everything else denied ─────────────────────
    PermissionRule(role="readonly", agent_id="*", skill_name="*", action="use", is_allowed=True),
    PermissionRule(role="readonly", agent_id="*", skill_name="*", action="read", is_allowed=True),
    PermissionRule(
        role="readonly", agent_id="*", skill_name="*", action="mutate", is_allowed=False
    ),
    PermissionRule(
        role="readonly", agent_id="*", skill_name="*", action="install", is_allowed=False
    ),
    PermissionRule(role="readonly", agent_id="*", skill_name="*", action="admin", is_allowed=False),
    PermissionRule(
        role="readonly", agent_id="*", skill_name="*", action="submit-write", is_allowed=False
    ),
    PermissionRule(
        role="readonly", agent_id="*", skill_name="*", action="approve-write", is_allowed=False
    ),
]


def _specificity(rule: PermissionRule, agent_id: str, skill_name: str, action: str) -> int:
    """Return a specificity score for *rule* against the given query.

    Higher is more specific.  Returns -1 if the rule does not match.
    """
    score = 0

    # Agent match
    if rule.agent_id == agent_id:
        score += 4
    elif rule.agent_id == "*":
        score += 0
    else:
        return -1  # no match

    # Skill match
    if rule.skill_name == skill_name:
        score += 2
    elif rule.skill_name == "*":
        score += 0
    else:
        return -1  # no match

    # Action match
    if rule.action == action:
        score += 1
    elif rule.action == "*":
        score += 0
    else:
        return -1  # no match

    return score


def check_permission(
    role: str,
    agent_id: str,
    skill_name: str,
    action: str,
    *,
    rules: list[PermissionRule] | None = None,
) -> bool:
    """Check whether *role* is permitted to perform *action* on *agent_id/skill_name*.

    Parameters
    ----------
    role:        ``"admin"`` / ``"user"`` / ``"readonly"``.
    agent_id:    Target agent identifier (e.g. ``"ops"``, ``"workspace"``).
    skill_name:  Target skill (e.g. ``"topology"``) or ``"*"`` for any.
    action:      ``"use"`` / ``"mutate"`` / ``"install"`` / ``"admin"``.
    rules:       Optional rule list override (defaults to :data:`DEFAULT_PERMISSIONS`).

    Returns
    -------
    bool
        ``True`` if the action is allowed, ``False`` otherwise.
    """
    if rules is None:
        rules = DEFAULT_PERMISSIONS

    best_score = -1
    best_allowed = False  # default deny

    for rule in rules:
        if rule.role != role:
            continue
        score = _specificity(rule, agent_id, skill_name, action)
        if score > best_score:
            best_score = score
            best_allowed = rule.is_allowed

    return best_allowed


def require_permission(
    role: str,
    agent_id: str,
    skill_name: str,
    action: str,
    *,
    rules: list[PermissionRule] | None = None,
) -> None:
    """Like :func:`check_permission` but raises :class:`AuthorizationError` on denial.

    Parameters
    ----------
    Same as :func:`check_permission`.

    Raises
    ------
    AuthorizationError
        If the role is not permitted.
    """
    if not check_permission(role, agent_id, skill_name, action, rules=rules):
        raise AuthorizationError(
            f"Role '{role}' is not permitted to '{action}' on {agent_id}/{skill_name}",
            role=role,
            agent_id=agent_id,
            skill_name=skill_name,
            action=action,
        )
