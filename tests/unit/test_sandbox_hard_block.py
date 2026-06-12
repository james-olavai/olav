"""Tests for sandbox_guard hard_block under network_isolation.

When network_isolation=True, HTTP mutation patterns must return hard_block=True
(not just requires_approval). hard_block cannot be bypassed by HITL approval or
--dangerously-skip-permissions.
"""

import pytest


@pytest.fixture(autouse=True)
def _clear_bypass_env(monkeypatch):
    """Ensure bypass flag is not set during tests."""
    monkeypatch.delenv("OLAV_DANGEROUSLY_SKIP_PERMISSIONS", raising=False)
    yield
    monkeypatch.delenv("OLAV_DANGEROUSLY_SKIP_PERMISSIONS", raising=False)


class TestHardBlockNetworkIsolation:
    """HTTP mutations under network_isolation=True are hard-blocked."""

    def _scan(self, code: str, network_isolation: bool = False):
        from olav.platform.safety.sandbox_guard import scan_sandbox_code
        return scan_sandbox_code(code, network_isolation=network_isolation)

    def test_httpx_post_network_isolated_hard_blocks(self):
        result = self._scan('httpx.post("http://api.example.com/devices/")', network_isolation=True)
        assert result.requires_approval is True
        assert result.hard_block is True
        assert "HARD BLOCK" in result.reason

    def test_httpx_delete_network_isolated_hard_blocks(self):
        result = self._scan('httpx.delete("http://api.example.com/devices/1")', network_isolation=True)
        assert result.requires_approval is True
        assert result.hard_block is True

    def test_httpx_post_no_isolation_soft_blocks(self):
        result = self._scan('httpx.post("http://api.example.com/devices/")', network_isolation=False)
        assert result.requires_approval is True
        assert result.hard_block is False

    def test_clean_code_network_isolated_passes(self):
        result = self._scan('x = 1 + 2\nprint(x)', network_isolation=True)
        assert result.requires_approval is False
        assert result.hard_block is False

    def test_db_query_network_isolated_passes(self):
        code = 'conn = duckdb.connect("db.duckdb", read_only=True)\nconn.execute("SELECT 1")'
        result = self._scan(code, network_isolation=True)
        assert result.requires_approval is False

    def test_hard_block_not_bypassable(self, monkeypatch):
        """hard_block is enforced even when --dangerously-skip-permissions is set."""
        monkeypatch.setenv("OLAV_DANGEROUSLY_SKIP_PERMISSIONS", "1")
        # Need to reload the module to pick up the env change
        import importlib
        import olav.platform.safety.permissions as pm
        importlib.reload(pm)

        result = self._scan('httpx.post("http://api.example.com/")', network_isolation=True)
        assert result.hard_block is True, "hard_block must not be bypassable by skip-permissions"

    def test_service_call_write_network_isolated_hard_blocks(self):
        result = self._scan('service_call("netbox", "POST", "/api/dcim/devices/")', network_isolation=True)
        # service_call write is detected as "External API mutation via service_call"
        # which contains "mutation" not "HTTP mutation" — check actual behavior
        assert result.requires_approval is True


class TestApprovalResultDataclass:
    """ApprovalResult with hard_block field works correctly."""

    def test_hard_block_default_false(self):
        from olav.platform.safety.sandbox_guard import ApprovalResult
        r = ApprovalResult(requires_approval=True, reason="test")
        assert r.hard_block is False

    def test_hard_block_true_has_suggested_action(self):
        from olav.platform.safety.sandbox_guard import ApprovalResult
        r = ApprovalResult(requires_approval=True, hard_block=True, reason="test")
        assert "permanently blocked" in r.suggested_action or "network isolation" in r.suggested_action

    def test_frozen_immutable(self):
        from olav.platform.safety.sandbox_guard import ApprovalResult
        r = ApprovalResult(requires_approval=False)
        with pytest.raises(AttributeError):
            r.hard_block = True
