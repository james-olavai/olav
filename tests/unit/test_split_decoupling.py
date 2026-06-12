"""Tests for repo-split decoupling preparation sprint.

Covers:
  TD-28  — config evolve --approve must require admin permission
  split_api_rw_5 — introduce read / submit-write / approve-write permission semantics
  CORE-1 — enterprise imports in main.py must be conditional (try/except ImportError)
  CORE-1 (bridge) — enterprise CLI commands dispatched via optional bridge module, not inline imports
  CORE-2 — tink + PyJWT must live in [project.optional-dependencies] enterprise
  NETOPS-1 — netops workspace asset manifest must exist
  ENT-1 — olav-ent package boundary metadata must exist
  ENT-1 (bridge) — olav-ent/pyproject.toml declares olav.enterprise_commands entry point
  DOCS-1 — docs/ ownership attribution must exist
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parents[2]
_SRC = _ROOT / "src"
_MAIN_PY = _SRC / "olav" / "cli" / "main.py"
_AUTHZ_PY = _SRC / "olav" / "core" / "auth" / "authz.py"
_API_ACTION_SVC_PY = _SRC / "olav" / "core" / "api_action_service.py"
_CONFIG_EVOLVE_PY = _SRC / "olav" / "cli" / "commands" / "config_evolve.py"
_PYPROJECT = _ROOT / "pyproject.toml"
_ENT_PYPROJECT = _ROOT / "olav-ent" / "pyproject.toml"


# ===========================================================================
# TD-28: cmd_evolve_approve must require admin permission
# ===========================================================================


class TestTD28ConfigEvolveAuthGate:
    """cmd_evolve_approve() must enforce admin-only via require_permission()."""

    def test_config_evolve_source_imports_require_permission(self):
        """config_evolve.py must import require_permission from authz."""
        src = _CONFIG_EVOLVE_PY.read_text(encoding="utf-8")
        assert "require_permission" in src, (
            "config_evolve.py must import/use require_permission from authz"
        )

    def test_config_evolve_source_imports_authorization_error(self):
        """config_evolve.py must reference AuthorizationError."""
        src = _CONFIG_EVOLVE_PY.read_text(encoding="utf-8")
        assert "AuthorizationError" in src, "config_evolve.py must handle AuthorizationError"

    def test_cmd_evolve_approve_has_role_parameter(self):
        """cmd_evolve_approve() must accept a role parameter."""
        import inspect

        from olav.cli.commands.config_evolve import cmd_evolve_approve

        sig = inspect.signature(cmd_evolve_approve)
        assert "role" in sig.parameters, (
            "cmd_evolve_approve() must have a 'role' parameter for RBAC enforcement"
        )

    def test_cmd_evolve_approve_non_admin_denied(self, tmp_path):
        """cmd_evolve_approve() must deny non-admin roles."""
        from olav.cli.commands.config_evolve import cmd_evolve_approve
        from olav.core.auth.authz import AuthorizationError

        db_path = tmp_path / "test.duckdb"
        with pytest.raises(AuthorizationError) as exc_info:
            cmd_evolve_approve(
                evolution_id="some-id",
                domain_db_path=db_path,
                role="user",
            )
        assert exc_info.value.role == "user"

    def test_cmd_evolve_approve_readonly_denied(self, tmp_path):
        """cmd_evolve_approve() must deny readonly role."""
        from olav.cli.commands.config_evolve import cmd_evolve_approve
        from olav.core.auth.authz import AuthorizationError

        db_path = tmp_path / "test.duckdb"
        with pytest.raises(AuthorizationError):
            cmd_evolve_approve(
                evolution_id="some-id",
                domain_db_path=db_path,
                role="readonly",
            )

    def test_cmd_evolve_approve_admin_passes_auth(self, tmp_path):
        """cmd_evolve_approve() must allow admin role (no AuthorizationError)."""
        from olav.cli.commands.config_evolve import cmd_evolve_approve
        from olav.core.auth.authz import AuthorizationError

        db_path = tmp_path / "test.duckdb"
        # admin role should not raise AuthorizationError
        # (it will raise KeyError or return error about not finding the evolution_id)
        try:
            result = cmd_evolve_approve(
                evolution_id="nonexistent-id",
                domain_db_path=db_path,
                role="admin",
            )
            # Either returns an error dict about not finding the row, or passes
            assert result.get("status") in ("error", "approved", "already_approved"), (
                f"Unexpected status: {result.get('status')}"
            )
        except AuthorizationError:
            pytest.fail("Admin role must NOT raise AuthorizationError")

    def test_cmd_evolve_approve_default_role_is_admin(self):
        """cmd_evolve_approve() default role must be admin (safe default)."""
        import inspect

        from olav.cli.commands.config_evolve import cmd_evolve_approve

        sig = inspect.signature(cmd_evolve_approve)
        default = sig.parameters["role"].default
        assert default == "admin", (
            f"cmd_evolve_approve() role default must be 'admin', got {default!r}"
        )


# ===========================================================================
# split_api_rw_5: read / submit-write / approve-write permission semantics
# ===========================================================================


class TestSplitApiRw5NewPermissionSemantics:
    """DEFAULT_PERMISSIONS must include read/submit-write/approve-write actions."""

    def test_authz_has_read_action(self):
        """DEFAULT_PERMISSIONS must include 'read' action rules."""
        from olav.core.auth.authz import DEFAULT_PERMISSIONS

        actions = {r.action for r in DEFAULT_PERMISSIONS}
        assert "read" in actions, "DEFAULT_PERMISSIONS missing 'read' action (API-RW-5)"

    def test_authz_has_submit_write_action(self):
        """DEFAULT_PERMISSIONS must include 'submit-write' action rules."""
        from olav.core.auth.authz import DEFAULT_PERMISSIONS

        actions = {r.action for r in DEFAULT_PERMISSIONS}
        assert "submit-write" in actions, (
            "DEFAULT_PERMISSIONS missing 'submit-write' action (API-RW-5)"
        )

    def test_authz_has_approve_write_action(self):
        """DEFAULT_PERMISSIONS must include 'approve-write' action rules."""
        from olav.core.auth.authz import DEFAULT_PERMISSIONS

        actions = {r.action for r in DEFAULT_PERMISSIONS}
        assert "approve-write" in actions, (
            "DEFAULT_PERMISSIONS missing 'approve-write' action (API-RW-5)"
        )

    def test_admin_can_read(self):
        """admin must be allowed to 'read'."""
        from olav.core.auth.authz import check_permission

        assert check_permission("admin", "*", "*", "read") is True

    def test_user_can_read(self):
        """user must be allowed to 'read'."""
        from olav.core.auth.authz import check_permission

        assert check_permission("user", "*", "*", "read") is True

    def test_readonly_can_read(self):
        """readonly must be allowed to 'read'."""
        from olav.core.auth.authz import check_permission

        assert check_permission("readonly", "*", "*", "read") is True

    def test_admin_can_submit_write(self):
        """admin must be allowed to 'submit-write'."""
        from olav.core.auth.authz import check_permission

        assert check_permission("admin", "*", "*", "submit-write") is True

    def test_user_can_submit_write(self):
        """user must be allowed to 'submit-write'."""
        from olav.core.auth.authz import check_permission

        assert check_permission("user", "*", "*", "submit-write") is True

    def test_readonly_cannot_submit_write(self):
        """readonly must NOT be allowed to 'submit-write'."""
        from olav.core.auth.authz import check_permission

        assert check_permission("readonly", "*", "*", "submit-write") is False

    def test_admin_can_approve_write(self):
        """admin must be allowed to 'approve-write'."""
        from olav.core.auth.authz import check_permission

        assert check_permission("admin", "*", "*", "approve-write") is True

    def test_user_cannot_approve_write(self):
        """user must NOT be allowed to 'approve-write'."""
        from olav.core.auth.authz import check_permission

        assert check_permission("user", "*", "*", "approve-write") is False

    def test_readonly_cannot_approve_write(self):
        """readonly must NOT be allowed to 'approve-write'."""
        from olav.core.auth.authz import check_permission

        assert check_permission("readonly", "*", "*", "approve-write") is False

    def test_api_action_service_stage_uses_submit_write(self):
        """ApiActionService.stage_request must check 'submit-write' not 'mutate'."""
        src = _API_ACTION_SVC_PY.read_text(encoding="utf-8")
        assert '"submit-write"' in src or "'submit-write'" in src, (
            "api_action_service.py stage_request must use 'submit-write' action (API-RW-5)"
        )

    def test_api_action_service_approve_uses_approve_write(self):
        """ApiActionService.approve_request must check 'approve-write' not 'admin'."""
        src = _API_ACTION_SVC_PY.read_text(encoding="utf-8")
        assert '"approve-write"' in src or "'approve-write'" in src, (
            "api_action_service.py approve_request must use 'approve-write' action (API-RW-5)"
        )

    def test_api_action_service_stage_readonly_denied(self, tmp_path):
        """stage_request must deny readonly role via submit-write check."""
        from olav.core.api_action_service import ApiActionRequest, ApiActionService

        svc = ApiActionService(staging_dir=tmp_path)
        req = ApiActionRequest(domain="test", operation_id="op1", method="POST", path="/test")
        result = svc.stage_request(req, role="readonly")
        assert result["status"] == "denied", "readonly must be denied by stage_request"

    def test_api_action_service_approve_user_denied(self, tmp_path):
        """approve_request must deny user role via approve-write check."""
        from olav.core.api_action_service import ApiActionService

        svc = ApiActionService(staging_dir=tmp_path)
        result = svc.approve_request("some-id", role="user")
        assert result["status"] == "denied", (
            "user must be denied by approve_request (only admin can approve-write)"
        )


# ===========================================================================
# CORE-1: Enterprise imports in main.py must be conditional
# ===========================================================================


class TestCore1EnterpriseImportsConditional:
    """All enterprise imports in main.py must be wrapped in try/except ImportError."""

    def _main_src(self) -> str:
        return _MAIN_PY.read_text(encoding="utf-8")

    def _main_ast(self) -> ast.Module:
        return ast.parse(self._main_src())

    def test_no_bare_enterprise_audit_dataset_export_import(self):
        """main.py must not have a zero-indented 'from olav.enterprise...' import line."""
        src = self._main_src()
        lines = src.splitlines()
        for i, line in enumerate(lines):
            if "from olav.enterprise" in line and not line[0].isspace():
                pytest.fail(
                    f"Line {i + 1}: bare (zero-indented) enterprise import found: {line.strip()!r}\n"
                    "All enterprise imports must be inside try/except ImportError blocks"
                )

    def test_enterprise_imports_wrapped_in_try_except(self):
        """Every 'from olav.enterprise' in main.py must be inside a try/except block."""
        src = self._main_src()
        lines = src.splitlines()
        # Find all enterprise import line numbers
        enterprise_import_lines = [
            (i + 1, lines[i].strip())
            for i, line in enumerate(lines)
            if "from olav.enterprise" in line
        ]
        assert enterprise_import_lines, "No enterprise imports found in main.py — verify paths"

        # For each enterprise import, scan backwards for try:
        for lineno, stmt in enterprise_import_lines:
            found_try = False
            for j in range(lineno - 2, max(lineno - 20, -1), -1):
                if lines[j].strip() == "try:":
                    found_try = True
                    break
            assert found_try, f"Line {lineno}: enterprise import not wrapped in try block: {stmt!r}"

    def test_enterprise_imports_have_importerror_handler(self):
        """Each try block with enterprise import must catch ImportError."""
        src = self._main_src()
        lines = src.splitlines()
        enterprise_import_lines = [
            i + 1 for i, line in enumerate(lines) if "from olav.enterprise" in line
        ]

        for lineno in enterprise_import_lines:
            # Scan forward for except ImportError
            found_handler = False
            for j in range(lineno, min(lineno + 20, len(lines))):
                if "except ImportError" in lines[j]:
                    found_handler = True
                    break
            assert found_handler, (
                f"Line {lineno}: enterprise import has no 'except ImportError' handler nearby"
            )

    def test_sft_export_import_is_conditional(self):
        bridge_src = _ENT_CLI_BRIDGE.read_text(encoding="utf-8")
        assert "audit_to_sft_jsonl" in bridge_src, "cli_bridge.py missing audit_to_sft_jsonl"

    def test_trajectory_export_import_is_conditional(self):
        bridge_src = _ENT_CLI_BRIDGE.read_text(encoding="utf-8")
        assert "audit_to_tool_trajectory" in bridge_src, (
            "cli_bridge.py missing audit_to_tool_trajectory"
        )

    def test_atif_export_import_is_conditional(self):
        bridge_src = _ENT_CLI_BRIDGE.read_text(encoding="utf-8")
        assert "audit_to_atif" in bridge_src, "cli_bridge.py missing audit_to_atif"

    def test_one_time_token_import_is_conditional(self):
        bridge_src = _ENT_CLI_BRIDGE.read_text(encoding="utf-8")
        assert "OneTimeTokenManager" in bridge_src, "cli_bridge.py missing OneTimeTokenManager"


# ===========================================================================
# CORE-2: tink + PyJWT must be in optional enterprise extra, not main deps
# ===========================================================================


class TestCore2EnterpriseDepsOptional:
    """tink and PyJWT must live in [project.optional-dependencies] enterprise."""

    def _pyproject_src(self) -> str:
        return _PYPROJECT.read_text(encoding="utf-8")

    def test_tink_not_in_main_dependencies(self):
        """tink must NOT appear under [project.dependencies]."""
        src = self._pyproject_src()
        # Find the [project.dependencies] block
        in_main_deps = False
        for line in src.splitlines():
            stripped = line.strip()
            if stripped == "[project.dependencies]" or stripped == "dependencies = [":
                in_main_deps = True
            elif stripped.startswith("[") and stripped != "[project.dependencies]":
                in_main_deps = False
            if in_main_deps and stripped.startswith('"tink') and stripped.startswith('"tink>='):
                pytest.fail(
                    "tink found in [project.dependencies] — must be moved to enterprise optional"
                )
        # Simpler check: verify tink is NOT in the main deps block
        # Parse TOML sections manually
        lines = src.splitlines()
        in_deps = False
        for line in lines:
            stripped = line.strip()
            if "dependencies = [" in stripped or stripped == "dependencies = [":
                in_deps = True
            if in_deps and "tink" in stripped and ">=" in stripped and '"tink' in stripped:
                pytest.fail(
                    "tink found in main [project] dependencies block — must be in enterprise optional"
                )
            if in_deps and stripped == "]":
                in_deps = False

    def test_pyjwt_not_in_main_dependencies(self):
        """PyJWT must NOT appear under [project.dependencies]."""
        lines = self._pyproject_src().splitlines()
        in_deps = False
        for line in lines:
            stripped = line.strip()
            if "dependencies = [" in stripped:
                in_deps = True
            if in_deps and "PyJWT" in stripped and '"PyJWT' in stripped:
                pytest.fail(
                    "PyJWT found in main [project] dependencies block — must be in enterprise optional"
                )
            if in_deps and stripped == "]":
                in_deps = False

    def test_enterprise_optional_dep_section_exists(self):
        """[project.optional-dependencies] must have an 'enterprise' key."""
        src = self._pyproject_src()
        assert "enterprise" in src, (
            "pyproject.toml missing 'enterprise' in [project.optional-dependencies]"
        )

    def test_no_enterprise_extra_in_platform(self):
        """v0.21.0-rc5 removed the [enterprise] extra — its deps were only
        consumed by modules excluded from the wheel, so the extra installed
        packages that could never load. olav-ent owns them now (asserted by
        TestEnt1PackageBoundary). The extra must NOT come back."""
        src = self._pyproject_src()
        for line in src.splitlines():
            stripped = line.strip()
            assert not (
                stripped.startswith("enterprise = [") or stripped.startswith("enterprise=[")
            ), "platform pyproject must not re-grow an [enterprise] extra (v0.21.0-rc5)"

    def test_tink_only_in_dev_group(self):
        """tink belongs to olav-ent at runtime. The platform pyproject may
        keep it ONLY in the dev test group (enterprise unit tests import
        it); any other section means the runtime leak came back."""
        src = self._pyproject_src()
        section = None
        for line in src.splitlines():
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                section = stripped
            elif "= [" in stripped and not stripped.startswith('"'):
                section = stripped.split("=")[0].strip()
            if stripped.startswith('"tink'):
                assert section == "dev", (
                    f"tink declared under {section!r} — runtime/extra use belongs to olav-ent"
                )


# ===========================================================================
# ENT-1: olav-ent package boundary metadata
# ===========================================================================


class TestEnt1PackageBoundary:
    def test_ent_pyproject_exists(self):
        assert _ENT_PYPROJECT.exists(), "olav-ent/pyproject.toml not found"

    def test_ent_pyproject_declares_correct_name(self):
        src = _ENT_PYPROJECT.read_text(encoding="utf-8")
        assert 'name = "olav-ent"' in src

    def test_ent_pyproject_depends_on_olav_core(self):
        src = _ENT_PYPROJECT.read_text(encoding="utf-8")
        assert "olav>=" in src, "olav-ent must declare a dependency on olav core"

    def test_ent_pyproject_includes_tink_dep(self):
        src = _ENT_PYPROJECT.read_text(encoding="utf-8")
        assert "tink>=" in src, "olav-ent must own the tink dependency"

    def test_ent_pyproject_includes_pyjwt_dep(self):
        src = _ENT_PYPROJECT.read_text(encoding="utf-8")
        assert "PyJWT>=" in src, "olav-ent must own the PyJWT dependency"

    def test_ent_pyproject_points_to_enterprise_src(self):
        src = _ENT_PYPROJECT.read_text(encoding="utf-8")
        assert "olav/enterprise" in src, "olav-ent wheel build must reference src/olav/enterprise"

    def test_enterprise_src_dir_exists(self):
        # 55c9356b: enterprise source lives in the olav-ent subrepo, not src/olav
        assert (_ROOT / "olav-ent" / "src" / "olav" / "enterprise").is_dir()

    def test_enterprise_init_exists(self):
        assert (_ROOT / "olav-ent" / "src" / "olav" / "enterprise" / "__init__.py").exists()


# ===========================================================================
# TD-32: tracking §6 design doc index paths must exist on disk
# ===========================================================================


# TD-32 (TestTD32TrackingDocIndexPaths) removed 2026-06-12: it inspected
# ``dev_docs/01. tracking.md``, which has been retired from the repo —
# the first test crashed on FileNotFoundError and the second was already
# a permanent xfail noting the doc section no longer existed.


# ===========================================================================
# CORE-1 (bridge) + ENT-1 (bridge): enterprise CLI bridge module
# ===========================================================================


# 55c9356b moved enterprise out of the platform package; the bridge
# (and all of olav.enterprise) now ships from the olav-ent subrepo.
_ENT_CLI_BRIDGE = _ROOT / "olav-ent" / "src" / "olav" / "enterprise" / "cli_bridge.py"


class TestCore1EnterpriseBridge:
    def test_cli_bridge_module_exists(self):
        assert _ENT_CLI_BRIDGE.exists(), (
            "src/olav/enterprise/cli_bridge.py must exist — "
            "CORE-1 requires an optional bridge module, not inline imports"
        )

    def test_cli_bridge_exports_dispatch_log_export(self):
        src = _ENT_CLI_BRIDGE.read_text(encoding="utf-8")
        assert "dispatch_log_export" in src, (
            "cli_bridge.py must define dispatch_log_export(format, args, console) function"
        )

    def test_cli_bridge_exports_supported_formats(self):
        src = _ENT_CLI_BRIDGE.read_text(encoding="utf-8")
        assert "SUPPORTED_FORMATS" in src, (
            "cli_bridge.py must define SUPPORTED_FORMATS — list of supported export format names"
        )

    def test_cli_bridge_covers_all_four_formats(self):
        src = _ENT_CLI_BRIDGE.read_text(encoding="utf-8")
        for fmt in ("sft", "trajectory", "atif", "grant-local-train"):
            assert fmt in src, f"cli_bridge.py must handle export format '{fmt}'"

    def test_main_py_uses_bridge_not_inline_imports(self):
        src = _MAIN_PY.read_text(encoding="utf-8")
        assert "cli_bridge" in src, (
            "main.py must import from olav.enterprise.cli_bridge (optional bridge), "
            "not individual olav.enterprise.* functions inline"
        )

    def test_main_py_has_single_enterprise_import_guard(self):
        src = _MAIN_PY.read_text(encoding="utf-8")
        lines = src.splitlines()
        enterprise_imports = [ln for ln in lines if "from olav.enterprise" in ln]
        assert len(enterprise_imports) == 1, (
            f"main.py should have exactly 1 enterprise import (the bridge), "
            f"found {len(enterprise_imports)}: {enterprise_imports}"
        )

    def test_ent_pyproject_declares_enterprise_commands_entry_point(self):
        src = _ENT_PYPROJECT.read_text(encoding="utf-8")
        assert "olav.enterprise_commands" in src, (
            "olav-ent/pyproject.toml must declare [project.entry-points.'olav.enterprise_commands'] "
            "so the platform can discover enterprise CLI extensions without hard imports"
        )

    def test_ent_pyproject_entry_point_references_cli_bridge(self):
        src = _ENT_PYPROJECT.read_text(encoding="utf-8")
        assert "cli_bridge" in src, (
            "olav-ent/pyproject.toml entry point must reference cli_bridge module"
        )
