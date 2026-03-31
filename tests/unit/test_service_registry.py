"""Unit tests for olav.platform.services (M4 Service Registry)."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from olav.platform.services.registry import (
    AuthConfig,
    ExecutionConfig,
    ServiceConfig,
    ServiceRegistry,
    ToolGroupConfig,
    ToolGenerationConfig,
    _parse_service,
)
from olav.platform.services.permission_generator import generate_permission_rules


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def services_yaml(tmp_path: Path) -> Path:
    """Write a minimal services.yaml for testing."""
    content = textwrap.dedent("""\
        services:
          testlab:
            display_name: "Test Lab API"
            description: "Unit test service"
            endpoint: "http://localhost:9090"
            schema_url: "http://localhost:9090/swagger/doc.json"
            auth:
              type: jwt
              login_path: "/login"
              username_env: "TL_USER"
              password_env: "TL_PASS"
              token_env: "TL_TOKEN"
            execution:
              backend: ssh
              host_env: "TL_SSH_HOST"
              user_env: "TL_SSH_USER"
            lifecycle:
              health_check: "GET /api/v1/labs"
              health_timeout: 10
            tool_generation:
              output_dir: "_test_generated"
              groups:
                - tag: "labs"
                  tool_prefix: "tl"
                  description: "Lab management"
            permissions:
              admin:
                actions: [use, mutate, install, admin]
              user:
                actions: [use]
              readonly:
                actions: [use]
                operation_filter: "^GET "

          simpleapi:
            display_name: "Simple API"
            endpoint: "http://simple.local"
            auth:
              type: bearer
              token_env: "SIMPLE_TOKEN"
    """)
    p = tmp_path / "services.yaml"
    p.write_text(content)
    return p


@pytest.fixture(autouse=True)
def reset_registry():
    """Reset the ServiceRegistry singleton between tests."""
    ServiceRegistry.reset()
    yield
    ServiceRegistry.reset()


# ── ServiceRegistry loading ───────────────────────────────────────────────────

class TestServiceRegistryLoading:
    def test_load_services(self, services_yaml):
        reg = ServiceRegistry(config_path=services_yaml)
        services = reg.list()
        assert len(services) == 2

    def test_get_service(self, services_yaml):
        reg = ServiceRegistry(config_path=services_yaml)
        svc = reg.get("testlab")
        assert svc.name == "testlab"
        assert svc.display_name == "Test Lab API"
        assert svc.endpoint == "http://localhost:9090"

    def test_get_unknown_raises(self, services_yaml):
        reg = ServiceRegistry(config_path=services_yaml)
        with pytest.raises(KeyError, match="unknown"):
            reg.get("unknown")

    def test_missing_config_returns_empty(self, tmp_path):
        reg = ServiceRegistry(config_path=tmp_path / "nonexistent.yaml")
        assert reg.list() == []

    def test_singleton_pattern(self, services_yaml):
        reg1 = ServiceRegistry.get_instance(services_yaml)
        reg2 = ServiceRegistry.get_instance(services_yaml)
        assert reg1 is reg2

    def test_reload(self, services_yaml):
        reg = ServiceRegistry(config_path=services_yaml)
        _ = reg.list()  # prime cache
        reg.reload()
        assert len(reg.list()) == 2


# ── ServiceConfig field parsing ───────────────────────────────────────────────

class TestServiceConfigParsing:
    def test_auth_fields(self, services_yaml):
        reg = ServiceRegistry(config_path=services_yaml)
        svc = reg.get("testlab")
        assert svc.auth.type == "jwt"
        assert svc.auth.username_env == "TL_USER"
        assert svc.auth.token_env == "TL_TOKEN"

    def test_execution_fields(self, services_yaml):
        reg = ServiceRegistry(config_path=services_yaml)
        svc = reg.get("testlab")
        assert svc.execution.backend == "ssh"
        assert svc.execution.host_env == "TL_SSH_HOST"

    def test_lifecycle_fields(self, services_yaml):
        reg = ServiceRegistry(config_path=services_yaml)
        svc = reg.get("testlab")
        assert svc.lifecycle.health_check == "GET /api/v1/labs"
        assert svc.lifecycle.health_timeout == 10

    def test_tool_generation_fields(self, services_yaml):
        reg = ServiceRegistry(config_path=services_yaml)
        svc = reg.get("testlab")
        assert svc.tool_generation.output_dir == "_test_generated"
        assert len(svc.tool_generation.groups) == 1
        grp = svc.tool_generation.groups[0]
        assert grp.tag == "labs"
        assert grp.tool_prefix == "tl"

    def test_permissions_parsed(self, services_yaml):
        reg = ServiceRegistry(config_path=services_yaml)
        svc = reg.get("testlab")
        assert "admin" in svc.permissions
        assert "use" in svc.permissions["admin"].actions
        assert "mutate" in svc.permissions["admin"].actions
        assert svc.permissions["readonly"].operation_filter == "^GET "

    def test_minimal_service_defaults(self, services_yaml):
        reg = ServiceRegistry(config_path=services_yaml)
        svc = reg.get("simpleapi")
        assert svc.auth.type == "bearer"
        assert svc.execution.backend == "local"  # default
        assert svc.tool_generation.groups == []


# ── ServiceConfig env var accessors ──────────────────────────────────────────

class TestServiceConfigAccessors:
    def test_get_token_from_env(self, services_yaml, monkeypatch):
        monkeypatch.setenv("TL_TOKEN", "mytoken123")
        reg = ServiceRegistry(config_path=services_yaml)
        svc = reg.get("testlab")
        assert svc.get_token() == "mytoken123"

    def test_get_token_missing_env(self, services_yaml, monkeypatch):
        monkeypatch.delenv("TL_TOKEN", raising=False)
        reg = ServiceRegistry(config_path=services_yaml)
        svc = reg.get("testlab")
        assert svc.get_token() is None

    def test_get_ssh_host(self, services_yaml, monkeypatch):
        monkeypatch.setenv("TL_SSH_HOST", "192.168.100.12")
        reg = ServiceRegistry(config_path=services_yaml)
        svc = reg.get("testlab")
        assert svc.get_ssh_host() == "192.168.100.12"

    def test_get_ssh_user_with_default(self, services_yaml, monkeypatch):
        monkeypatch.delenv("TL_SSH_USER", raising=False)
        reg = ServiceRegistry(config_path=services_yaml)
        svc = reg.get("testlab")
        # Falls back to "olav"
        assert svc.get_ssh_user() == "olav"

    def test_get_credentials(self, services_yaml, monkeypatch):
        monkeypatch.setenv("TL_USER", "admin")
        monkeypatch.setenv("TL_PASS", "secret")
        reg = ServiceRegistry(config_path=services_yaml)
        svc = reg.get("testlab")
        assert svc.get_credentials() == ("admin", "secret")


# ── PermissionGenerator ───────────────────────────────────────────────────────

class TestPermissionGenerator:
    def test_generates_rules_for_all_roles(self, services_yaml):
        reg = ServiceRegistry(config_path=services_yaml)
        svc = reg.get("testlab")
        rules = generate_permission_rules(svc)
        roles = {r.role for r in rules}
        assert "admin" in roles
        assert "user" in roles
        assert "readonly" in roles

    def test_admin_gets_all_actions(self, services_yaml):
        reg = ServiceRegistry(config_path=services_yaml)
        svc = reg.get("testlab")
        rules = generate_permission_rules(svc)
        admin_actions = {r.action for r in rules if r.role == "admin" and r.is_allowed}
        assert {"use", "mutate", "install", "admin"} == admin_actions

    def test_readonly_only_gets_use(self, services_yaml):
        reg = ServiceRegistry(config_path=services_yaml)
        svc = reg.get("testlab")
        rules = generate_permission_rules(svc)
        readonly_allowed = {r.action for r in rules if r.role == "readonly" and r.is_allowed}
        assert "use" in readonly_allowed
        assert "mutate" not in readonly_allowed

    def test_rules_use_tool_prefix_scope(self, services_yaml):
        reg = ServiceRegistry(config_path=services_yaml)
        svc = reg.get("testlab")
        rules = generate_permission_rules(svc)
        # All rules should scope to tl_* (the tool_prefix from tool_generation groups)
        for rule in rules:
            assert rule.skill_name == "tl_*"

    def test_rules_are_permission_rule_instances(self, services_yaml):
        from olav.core.auth.authz import PermissionRule
        reg = ServiceRegistry(config_path=services_yaml)
        svc = reg.get("testlab")
        rules = generate_permission_rules(svc)
        for rule in rules:
            assert isinstance(rule, PermissionRule)


# ── Tool name generation (internal) ──────────────────────────────────────────

class TestToolNameGeneration:
    def test_basic_func_name(self):
        from olav.platform.services.tool_generator import _to_func_name
        assert _to_func_name("clab", "GET", "/api/v1/labs") == "clab_get_labs"

    def test_path_param_becomes_by_name(self):
        from olav.platform.services.tool_generator import _to_func_name
        name = _to_func_name("clab", "GET", "/api/v1/labs/{name}")
        assert "by_name" in name

    def test_post_method(self):
        from olav.platform.services.tool_generator import _to_func_name
        name = _to_func_name("clab", "POST", "/api/v1/labs")
        assert name.startswith("clab_post")

    def test_nested_path(self):
        from olav.platform.services.tool_generator import _to_func_name
        name = _to_func_name("nb", "GET", "/api/dcim/devices/{id}/interfaces/")
        assert name.startswith("nb_get")
        assert "interfaces" in name
