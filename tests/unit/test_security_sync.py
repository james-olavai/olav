"""Test Security Sync - Security Guardrails.

This test verifies:
1. Security policies can be loaded from YAML
2. sync_security_rules tool can sync to LanceDB
3. Security violation detection works

TDD: Tests should FAIL until security module is properly implemented.
"""

import tempfile
from pathlib import Path

import pytest
import yaml


class TestSecurityPolicies:
    """Test security policy loading and checking."""

    @pytest.fixture
    def temp_policy_file(self):
        """Create a temporary policy file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            policy_path = Path(tmpdir) / "security_policies.yaml"
            policies = {
                "version": "1.0",
                "categories": {
                    "destructive": {
                        "description": "Test destructive",
                        "action": "BLOCK",
                        "patterns": ["delete all", "删除全部"],
                    },
                    "high_risk": {
                        "description": "Test high risk",
                        "action": "CONFIRM",
                        "patterns": ["restart", "reboot"],
                    },
                },
                "guardrail": {
                    "enabled": True,
                    "threshold": 0.85,
                    "fallback_to_llm": False,
                },
            }
            with open(policy_path, "w") as f:
                yaml.dump(policies, f)
            yield policy_path

    def test_load_default_policies(self):
        """Test loading default policies."""
        from olav.core.security import DEFAULT_POLICIES, load_security_policies

        policies = load_security_policies()

        assert policies is not None
        assert "categories" in policies
        assert "destructive" in policies["categories"]
        assert "high_risk" in policies["categories"]

    def test_load_policies_from_file(self, temp_policy_file):
        """Test loading policies from custom file."""
        from olav.core.security import load_security_policies

        policies = load_security_policies(temp_policy_file)

        assert policies is not None
        assert "categories" in policies
        assert "destructive" in policies["categories"]
        assert policies["categories"]["destructive"]["action"] == "BLOCK"

    def test_get_policy_action(self):
        """Test getting policy action for category."""
        from olav.core.security import get_policy_action, DEFAULT_POLICIES

        action = get_policy_action("destructive", DEFAULT_POLICIES)
        assert action == "BLOCK"

        action = get_policy_action("high_risk", DEFAULT_POLICIES)
        assert action == "CONFIRM"

        action = get_policy_action("unknown", DEFAULT_POLICIES)
        assert action == "WARN"  # Default action

    def test_check_query_policy_exact_match(self):
        """Test exact pattern matching."""
        from olav.core.security import check_query_policy, DEFAULT_POLICIES

        # Test destructive pattern
        result = check_query_policy("delete all devices", DEFAULT_POLICIES)
        assert result["category"] == "destructive"
        assert result["action"] == "BLOCK"
        assert result["match_type"] == "exact"

        # Test high_risk pattern
        result = check_query_policy("restart the router", DEFAULT_POLICIES)
        assert result["category"] == "high_risk"
        assert result["action"] == "CONFIRM"

    def test_check_query_policy_no_match(self):
        """Test query with no policy match."""
        from olav.core.security import check_query_policy, DEFAULT_POLICIES

        result = check_query_policy("show me the device list", DEFAULT_POLICIES)
        assert result["category"] is None
        assert result["action"] == "ALLOW"

    def test_guardrail_disabled(self):
        """Test guardrail being disabled."""
        from olav.core.security import check_query_policy

        policies = {
            "categories": {
                "destructive": {
                    "action": "BLOCK",
                    "patterns": ["delete all"],
                },
            },
            "guardrail": {
                "enabled": False,
            },
        }

        result = check_query_policy("delete all", policies)
        assert result["action"] == "ALLOW"


class TestSecuritySyncTool:
    """Test sync_security_rules tool."""

    def test_sync_tool_import(self):
        """Test that sync_security_rules can be imported."""
        from olav.tools import sync_security_rules

        assert sync_security_rules is not None


class TestSecurityMiddleware:
    """Test security middleware integration."""

    def test_security_check_import(self):
        """Test that security module can be imported."""
        from olav.core.security import check_query_policy

        assert check_query_policy is not None

    def test_default_policy_file_creation(self):
        """Test default policy file can be created."""
        from olav.core.security import create_default_policy_file, DEFAULT_POLICIES

        with tempfile.TemporaryDirectory() as tmpdir:
            policy_path = Path(tmpdir) / "security_policies.yaml"
            create_default_policy_file(policy_path)

            assert policy_path.exists()

            with open(policy_path) as f:
                loaded = yaml.safe_load(f)

            assert loaded["version"] == DEFAULT_POLICIES["version"]


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
