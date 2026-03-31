"""
tests/unit/test_rbac.py
────────────────────────
TDD tests for RBAC-1 / RBAC-2 / RBAC-3: Role-based access control.

Tests verify:
  1. authz module is importable from olav.core.auth.authz
  2. DEFAULT_PERMISSIONS constant defines the baseline permission matrix
  3. check_permission(role, agent_id, skill_name, action) returns bool
  4. admin can do everything (use, mutate, install, admin)
  5. user can use and mutate non-lifecycle skills, cannot install/admin
  6. readonly can only use, cannot mutate/install/admin
  7. workspace lifecycle actions (install, upgrade, remove, rollback) are admin-only
  8. config.discovery is use-accessible by all roles
  9. config.creator is mutate-restricted (admin + user only)
 10. AuthorizationError is raised by require_permission on denial
 11. role_skill_permissions migration creates the table
 12. get_default_permissions returns list of PermissionRule tuples
"""

import pytest


# ── 1. Module importable ──────────────────────────────────────────────────────


def test_authz_importable():
    """RBAC-1: authz module must be importable."""
    from olav.core.auth.authz import check_permission, require_permission


def test_authorization_error_importable():
    """RBAC-1: AuthorizationError must be importable."""
    from olav.core.auth.authz import AuthorizationError

    err = AuthorizationError("test", "admin", "ops", "skill", "use")
    assert "test" in str(err)


# ── 2. Default permission matrix ─────────────────────────────────────────────


def test_default_permissions_exists():
    """RBAC-1: DEFAULT_PERMISSIONS must be importable and non-empty."""
    from olav.core.auth.authz import DEFAULT_PERMISSIONS

    assert isinstance(DEFAULT_PERMISSIONS, list)
    assert len(DEFAULT_PERMISSIONS) > 0


def test_default_permissions_has_admin_entries():
    """RBAC-1: admin role must have broad permissions in defaults."""
    from olav.core.auth.authz import DEFAULT_PERMISSIONS

    admin_perms = [p for p in DEFAULT_PERMISSIONS if p.role == "admin"]
    assert len(admin_perms) > 0


def test_default_permissions_has_user_entries():
    """RBAC-1: user role must have permissions in defaults."""
    from olav.core.auth.authz import DEFAULT_PERMISSIONS

    user_perms = [p for p in DEFAULT_PERMISSIONS if p.role == "user"]
    assert len(user_perms) > 0


def test_default_permissions_has_readonly_entries():
    """RBAC-1: readonly role must have permissions in defaults."""
    from olav.core.auth.authz import DEFAULT_PERMISSIONS

    ro_perms = [p for p in DEFAULT_PERMISSIONS if p.role == "readonly"]
    assert len(ro_perms) > 0


# ── 3. PermissionRule dataclass ───────────────────────────────────────────────


def test_permission_rule_importable():
    """RBAC-1: PermissionRule must be importable."""
    from olav.core.auth.authz import PermissionRule

    rule = PermissionRule(role="admin", agent_id="*", skill_name="*", action="*", is_allowed=True)
    assert rule.role == "admin"
    assert rule.is_allowed is True


# ── 4. check_permission — admin ───────────────────────────────────────────────


def test_admin_can_use_any_skill():
    """RBAC-1: admin can use any agent/skill."""
    from olav.core.auth.authz import check_permission

    assert check_permission("admin", "ops", "topology", "use") is True
    assert check_permission("admin", "config", "discovery", "use") is True
    assert check_permission("admin", "query", "*", "use") is True


def test_admin_can_mutate_any_skill():
    """RBAC-1: admin can mutate any agent/skill."""
    from olav.core.auth.authz import check_permission

    assert check_permission("admin", "config", "creator", "mutate") is True
    assert check_permission("admin", "ops", "simulator", "mutate") is True


def test_admin_can_install():
    """RBAC-1: admin can perform install/admin actions."""
    from olav.core.auth.authz import check_permission

    assert check_permission("admin", "workspace", "*", "install") is True
    assert check_permission("admin", "workspace", "*", "admin") is True


# ── 5. check_permission — user ────────────────────────────────────────────────


def test_user_can_use_skills():
    """RBAC-1: user can use agent skills."""
    from olav.core.auth.authz import check_permission

    assert check_permission("user", "ops", "topology", "use") is True
    assert check_permission("user", "query", "*", "use") is True
    assert check_permission("user", "config", "discovery", "use") is True


def test_user_can_mutate_non_lifecycle_skills():
    """RBAC-1: user can mutate non-lifecycle skills."""
    from olav.core.auth.authz import check_permission

    assert check_permission("user", "config", "sync", "mutate") is True
    assert check_permission("user", "ops", "topology", "mutate") is True


def test_user_cannot_install():
    """RBAC-1: user cannot install/admin."""
    from olav.core.auth.authz import check_permission

    assert check_permission("user", "workspace", "*", "install") is False
    assert check_permission("user", "workspace", "*", "admin") is False


# ── 6. check_permission — readonly ────────────────────────────────────────────


def test_readonly_can_use():
    """RBAC-1: readonly can use (read-only) skills."""
    from olav.core.auth.authz import check_permission

    assert check_permission("readonly", "query", "*", "use") is True
    assert check_permission("readonly", "audit", "*", "use") is True
    assert check_permission("readonly", "config", "discovery", "use") is True


def test_readonly_cannot_mutate():
    """RBAC-1: readonly cannot mutate."""
    from olav.core.auth.authz import check_permission

    assert check_permission("readonly", "config", "creator", "mutate") is False
    assert check_permission("readonly", "ops", "topology", "mutate") is False


def test_readonly_cannot_install():
    """RBAC-1: readonly cannot install/admin."""
    from olav.core.auth.authz import check_permission

    assert check_permission("readonly", "workspace", "*", "install") is False
    assert check_permission("readonly", "workspace", "*", "admin") is False


# ── 7. Workspace lifecycle is admin-only ──────────────────────────────────────


def test_workspace_install_admin_only():
    """RBAC-2: workspace install action is admin-only."""
    from olav.core.auth.authz import check_permission

    assert check_permission("admin", "workspace", "*", "install") is True
    assert check_permission("user", "workspace", "*", "install") is False
    assert check_permission("readonly", "workspace", "*", "install") is False


def test_workspace_admin_action_admin_only():
    """RBAC-2: workspace admin action is admin-only."""
    from olav.core.auth.authz import check_permission

    assert check_permission("admin", "workspace", "*", "admin") is True
    assert check_permission("user", "workspace", "*", "admin") is False
    assert check_permission("readonly", "workspace", "*", "admin") is False


# ── 8. Config agent skill-level authz ─────────────────────────────────────────


def test_config_discovery_readable_by_all():
    """RBAC-3: config.discovery use is open to all roles."""
    from olav.core.auth.authz import check_permission

    assert check_permission("admin", "config", "discovery", "use") is True
    assert check_permission("user", "config", "discovery", "use") is True
    assert check_permission("readonly", "config", "discovery", "use") is True


def test_config_creator_mutate_restricted():
    """RBAC-3: config.creator mutate is admin + user only, not readonly."""
    from olav.core.auth.authz import check_permission

    assert check_permission("admin", "config", "creator", "mutate") is True
    assert check_permission("user", "config", "creator", "mutate") is True
    assert check_permission("readonly", "config", "creator", "mutate") is False


# ── 9. require_permission raises AuthorizationError ───────────────────────────


def test_require_permission_passes_for_allowed():
    """RBAC-1: require_permission does not raise for allowed action."""
    from olav.core.auth.authz import require_permission

    # Should not raise
    require_permission("admin", "ops", "topology", "use")


def test_require_permission_raises_for_denied():
    """RBAC-1: require_permission raises AuthorizationError for denied action."""
    from olav.core.auth.authz import AuthorizationError, require_permission

    with pytest.raises(AuthorizationError):
        require_permission("readonly", "config", "creator", "mutate")


def test_require_permission_includes_details():
    """RBAC-1: AuthorizationError includes role, agent, skill, action."""
    from olav.core.auth.authz import AuthorizationError, require_permission

    with pytest.raises(AuthorizationError) as exc_info:
        require_permission("user", "workspace", "*", "install")

    err = exc_info.value
    assert err.role == "user"
    assert err.agent_id == "workspace"
    assert err.action == "install"


# ── 10. RBAC migration ───────────────────────────────────────────────────────


def test_rbac_migration_importable():
    """RBAC-1: v0_13_rbac migration module must be importable."""
    from olav.core.migrations.v0_13_rbac import apply_migration


def test_rbac_migration_creates_table():
    """RBAC-1: Migration creates role_skill_permissions table."""
    import duckdb
    from olav.core.migrations.v0_13_rbac import apply_migration

    conn = duckdb.connect(":memory:")
    apply_migration(conn)

    # Table must exist and have expected columns
    result = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'role_skill_permissions' ORDER BY column_name"
    ).fetchall()
    columns = [r[0] for r in result]
    assert "role" in columns
    assert "agent_id" in columns
    assert "skill_name" in columns
    assert "action" in columns
    assert "is_allowed" in columns
    conn.close()


def test_rbac_migration_is_idempotent():
    """RBAC-1: Running migration twice must not fail."""
    import duckdb
    from olav.core.migrations.v0_13_rbac import apply_migration

    conn = duckdb.connect(":memory:")
    apply_migration(conn)
    apply_migration(conn)  # second run must not raise
    conn.close()


def test_rbac_migration_seeds_defaults():
    """RBAC-1: Migration seeds the default permission rows."""
    import duckdb
    from olav.core.migrations.v0_13_rbac import apply_migration

    conn = duckdb.connect(":memory:")
    apply_migration(conn)

    count = conn.execute("SELECT COUNT(*) FROM role_skill_permissions").fetchone()[0]
    assert count > 0  # Should have seeded default rows

    # admin wildcard must exist
    admin_rows = conn.execute(
        "SELECT * FROM role_skill_permissions WHERE role = 'admin'"
    ).fetchall()
    assert len(admin_rows) > 0
    conn.close()


# ── 11. Config creator install is admin-only (RBAC-3) ────────────────────────


def test_config_creator_install_admin_only():
    from olav.core.auth.authz import check_permission

    assert check_permission("admin", "config", "creator", "install") is True
    assert check_permission("user", "config", "creator", "install") is False
    assert check_permission("readonly", "config", "creator", "install") is False
