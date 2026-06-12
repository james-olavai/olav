"""ARCH-22 B: COMPATIBILITY_CUTOFF raised and obsolete migrations removed.

``COMPATIBILITY_CUTOFF`` is the minimum prior-release version we still
support upgrading *from*. Raising it lets us retire migration scripts for
releases that are no longer in the field.

History:
  Round 4: 0.9.0 → 0.13.0 — v0_13_rbac removed (role_skill_permissions
           was never wired into the runtime authz path).
  Round 8: 0.13.0 → 0.15.0 — v0_12_users DDL promoted to baseline module
           ``core.auth.schema`` (ARCH-22 B FULL). Only ``v0_14_sessions``
           remains under ``core/migrations/`` and is still runtime-invoked
           by ``core/audit_recorder.py``.
"""

from __future__ import annotations

import importlib
from pathlib import Path


def test_compatibility_cutoff_value():
    from olav.core.version import COMPATIBILITY_CUTOFF
    assert COMPATIBILITY_CUTOFF == "0.15.0", (
        f"COMPATIBILITY_CUTOFF drift: expected '0.15.0', got {COMPATIBILITY_CUTOFF!r}. "
        "If intentionally raising, update this test AND remove the corresponding "
        "obsolete migration files under src/olav/core/migrations/."
    )


def test_v0_13_rbac_migration_removed():
    migrations_dir = Path(__file__).resolve().parents[2] / "src" / "olav" / "core" / "migrations"
    v0_13 = migrations_dir / "v0_13_rbac.py"
    assert not v0_13.exists(), (
        f"{v0_13} was removed in ARCH-22 B (cutoff raised past v0.13). "
        "If you re-added it, reconsider — role_skill_permissions has no runtime reader."
    )


def test_v0_12_users_migration_removed():
    migrations_dir = Path(__file__).resolve().parents[2] / "src" / "olav" / "core" / "migrations"
    v0_12 = migrations_dir / "v0_12_users.py"
    assert not v0_12.exists(), (
        f"{v0_12} was removed in ARCH-22 B FULL — users DDL moved to "
        "core/auth/schema.apply_baseline(). Callers should import apply_baseline, "
        "not resurrect the migration."
    )


def test_auth_baseline_schema_importable():
    from olav.core.auth.schema import apply_baseline
    assert callable(apply_baseline), "apply_baseline must remain callable"


def test_live_migrations_still_importable():
    # v0_14_sessions creates audit_sessions consumed by audit_recorder.
    mod = importlib.import_module("olav.core.migrations.v0_14_sessions")
    assert hasattr(mod, "apply_migration"), (
        "v0_14_sessions missing apply_migration(); audit_recorder expects it."
    )


def test_is_version_compatible_honors_cutoff():
    from olav.core.version import is_version_compatible

    # Below cutoff → incompatible
    assert is_version_compatible("0.14.0") is False
    assert is_version_compatible("0.12.0") is False
    assert is_version_compatible("0.9.0") is False

    # At-or-above cutoff → compatible
    assert is_version_compatible("0.15.0") is True
    assert is_version_compatible("0.18.0") is True
