"""TDD — --dangerously-skip-permissions mode.

When OLAV_DANGEROUSLY_SKIP_PERMISSIONS=1 (or set via set_bypass(True)):
  - check_approval()     → always safe (requires_approval=False)
  - scan_sandbox_code()  → always safe (requires_approval=False)
  - service_call()       → write methods proceed (no requires_approval gate)

execute_sql read_only=True is NOT bypassed — data integrity constraint, not approval gate.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch


# ── permissions module ────────────────────────────────────────────────────────


class TestPermissionsModule:
    def test_bypass_inactive_by_default(self, monkeypatch):
        monkeypatch.delenv("OLAV_DANGEROUSLY_SKIP_PERMISSIONS", raising=False)
        from importlib import reload
        import olav.platform.safety.permissions as pm
        reload(pm)
        assert pm.is_bypass_active() is False

    def test_bypass_active_when_env_var_set(self, monkeypatch):
        monkeypatch.setenv("OLAV_DANGEROUSLY_SKIP_PERMISSIONS", "1")
        from olav.platform.safety.permissions import is_bypass_active
        assert is_bypass_active() is True

    def test_set_bypass_true_sets_env_var(self, monkeypatch):
        monkeypatch.delenv("OLAV_DANGEROUSLY_SKIP_PERMISSIONS", raising=False)
        from olav.platform.safety.permissions import set_bypass, is_bypass_active
        set_bypass(True)
        assert is_bypass_active() is True

    def test_set_bypass_false_clears_env_var(self, monkeypatch):
        monkeypatch.setenv("OLAV_DANGEROUSLY_SKIP_PERMISSIONS", "1")
        from olav.platform.safety.permissions import set_bypass, is_bypass_active
        set_bypass(False)
        assert is_bypass_active() is False

    def test_env_var_value_must_be_1(self, monkeypatch):
        """Only '1' activates bypass — 'true', 'yes', 'on' do not."""
        for val in ("true", "yes", "on", "True", "TRUE", "0", ""):
            monkeypatch.setenv("OLAV_DANGEROUSLY_SKIP_PERMISSIONS", val)
            from olav.platform.safety.permissions import is_bypass_active
            assert is_bypass_active() is False, f"Expected False for value={val!r}"


# ── check_approval bypass ─────────────────────────────────────────────────────


class TestCheckApprovalBypass:
    def test_dangerous_command_blocked_without_bypass(self, monkeypatch):
        monkeypatch.delenv("OLAV_DANGEROUSLY_SKIP_PERMISSIONS", raising=False)
        from olav.platform.safety.approval import check_approval
        result = check_approval("no router bgp 65000", device="R1")
        assert result.requires_approval is True

    def test_dangerous_command_allowed_with_bypass(self, monkeypatch):
        monkeypatch.setenv("OLAV_DANGEROUSLY_SKIP_PERMISSIONS", "1")
        from olav.platform.safety.approval import check_approval
        result = check_approval("no router bgp 65000", device="R1")
        assert result.requires_approval is False

    def test_reload_command_allowed_with_bypass(self, monkeypatch):
        monkeypatch.setenv("OLAV_DANGEROUSLY_SKIP_PERMISSIONS", "1")
        from olav.platform.safety.approval import check_approval
        result = check_approval("reload", device="R1")
        assert result.requires_approval is False

    def test_write_erase_allowed_with_bypass(self, monkeypatch):
        monkeypatch.setenv("OLAV_DANGEROUSLY_SKIP_PERMISSIONS", "1")
        from olav.platform.safety.approval import check_approval
        result = check_approval("write erase", device="R1")
        assert result.requires_approval is False

    def test_readonly_commands_still_pass_without_bypass(self, monkeypatch):
        """show commands always pass regardless of bypass state."""
        monkeypatch.delenv("OLAV_DANGEROUSLY_SKIP_PERMISSIONS", raising=False)
        from olav.platform.safety.approval import check_approval
        result = check_approval("show ip bgp summary", device="R1")
        assert result.requires_approval is False


# ── sandbox_guard bypass ──────────────────────────────────────────────────────


class TestSandboxGuardBypass:
    def test_http_delete_blocked_without_bypass(self, monkeypatch):
        monkeypatch.delenv("OLAV_DANGEROUSLY_SKIP_PERMISSIONS", raising=False)
        from olav.platform.safety.sandbox_guard import scan_sandbox_code
        result = scan_sandbox_code("httpx.delete('http://clab/api/v1/labs/prod')")
        assert result.requires_approval is True

    def test_http_delete_allowed_with_bypass(self, monkeypatch):
        monkeypatch.setenv("OLAV_DANGEROUSLY_SKIP_PERMISSIONS", "1")
        from olav.platform.safety.sandbox_guard import scan_sandbox_code
        result = scan_sandbox_code("httpx.delete('http://clab/api/v1/labs/prod')")
        assert result.requires_approval is False

    def test_db_mutation_blocked_without_bypass(self, monkeypatch):
        monkeypatch.delenv("OLAV_DANGEROUSLY_SKIP_PERMISSIONS", raising=False)
        from olav.platform.safety.sandbox_guard import scan_sandbox_code
        result = scan_sandbox_code("con.execute('DELETE FROM netops.devices')")
        assert result.requires_approval is True

    def test_db_mutation_allowed_with_bypass(self, monkeypatch):
        monkeypatch.setenv("OLAV_DANGEROUSLY_SKIP_PERMISSIONS", "1")
        from olav.platform.safety.sandbox_guard import scan_sandbox_code
        result = scan_sandbox_code("con.execute('DELETE FROM netops.devices')")
        assert result.requires_approval is False

    def test_service_call_post_blocked_without_bypass(self, monkeypatch):
        monkeypatch.delenv("OLAV_DANGEROUSLY_SKIP_PERMISSIONS", raising=False)
        from olav.platform.safety.sandbox_guard import scan_sandbox_code
        result = scan_sandbox_code("service_call('clab', 'POST', '/api/v1/labs')")
        assert result.requires_approval is True

    def test_service_call_post_allowed_with_bypass(self, monkeypatch):
        monkeypatch.setenv("OLAV_DANGEROUSLY_SKIP_PERMISSIONS", "1")
        from olav.platform.safety.sandbox_guard import scan_sandbox_code
        result = scan_sandbox_code("service_call('clab', 'POST', '/api/v1/labs')")
        assert result.requires_approval is False


# ── service_call write gate bypass ───────────────────────────────────────────


class TestServiceCallWriteBypass:
    def _make_svc_registry(self, monkeypatch):
        from olav.platform.services.registry import ServiceConfig, AuthConfig
        mock_svc = ServiceConfig(
            name="clab",
            endpoint="http://localhost:8080",
            readonly_only=False,
            auth=AuthConfig(type="none"),
        )
        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_svc
        monkeypatch.setattr(
            "olav.platform.services.client.ServiceRegistry.get_instance",
            lambda: mock_registry,
        )

    def test_delete_blocked_without_bypass(self, monkeypatch):
        self._make_svc_registry(monkeypatch)
        monkeypatch.delenv("OLAV_DANGEROUSLY_SKIP_PERMISSIONS", raising=False)
        from olav.platform.services.client import service_call
        result = service_call("clab", "DELETE", "/api/v1/labs/prod")
        assert result["status"] == "requires_approval"

    def test_delete_proceeds_with_bypass(self, monkeypatch):
        self._make_svc_registry(monkeypatch)
        monkeypatch.setenv("OLAV_DANGEROUSLY_SKIP_PERMISSIONS", "1")
        with patch("httpx.Client") as mock_cls:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status.return_value = None
            mock_resp.json.return_value = {"status": "deleted"}
            mock_cls.return_value.__enter__.return_value.request.return_value = mock_resp
            from olav.platform.services.client import service_call
            result = service_call("clab", "DELETE", "/api/v1/labs/prod")
        # Should reach HTTP layer — NOT requires_approval
        assert not (isinstance(result, dict) and result.get("status") == "requires_approval")

    def test_post_proceeds_with_bypass(self, monkeypatch):
        self._make_svc_registry(monkeypatch)
        monkeypatch.setenv("OLAV_DANGEROUSLY_SKIP_PERMISSIONS", "1")
        with patch("httpx.Client") as mock_cls:
            mock_resp = MagicMock()
            mock_resp.status_code = 201
            mock_resp.raise_for_status.return_value = None
            mock_resp.json.return_value = {"id": "lab-1"}
            mock_cls.return_value.__enter__.return_value.request.return_value = mock_resp
            from olav.platform.services.client import service_call
            result = service_call("clab", "POST", "/api/v1/labs", body={"name": "test"})
        assert not (isinstance(result, dict) and result.get("status") == "requires_approval")

    def test_write_methods_reach_httpx_when_bypassed(self, monkeypatch):
        """With bypass, httpx.Client IS instantiated for write methods."""
        self._make_svc_registry(monkeypatch)
        monkeypatch.setenv("OLAV_DANGEROUSLY_SKIP_PERMISSIONS", "1")
        with patch("httpx.Client") as mock_cls:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status.return_value = None
            mock_resp.json.return_value = {}
            mock_cls.return_value.__enter__.return_value.request.return_value = mock_resp
            from olav.platform.services.client import service_call
            service_call("clab", "DELETE", "/api/v1/labs/prod")
        mock_cls.assert_called_once()
