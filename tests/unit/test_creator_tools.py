"""Unit tests for Creator Agent tools.

Tests cover all 4 new bridge tools + read_api_schema.
No real network calls or LLM invocations.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MINIMAL_OPENAPI = {
    "openapi": "3.0.0",
    "info": {"title": "Test API", "version": "1.0.0"},
    "paths": {
        "/api/circuits/circuits/": {
            "get": {
                "operationId": "circuits_circuits_list",
                "summary": "List circuits",
                "tags": ["circuits"],
                "parameters": [],
            },
            "post": {
                "operationId": "circuits_circuits_create",
                "summary": "Create circuit",
                "tags": ["circuits"],
            },
        },
        "/api/circuits/circuits/{id}/": {
            "get": {
                "operationId": "circuits_circuits_retrieve",
                "summary": "Retrieve circuit",
                "tags": ["circuits"],
            },
        },
    },
    "components": {
        "securitySchemes": {
            "tokenAuth": {"type": "apiKey", "in": "header", "name": "Authorization"},
        },
        "schemas": {},
    },
}


@pytest.fixture()
def services_yaml(tmp_path: Path) -> Path:
    """Write a minimal services.yaml and return its path."""
    cfg = {
        "services": {
            "existing_service": {
                "display_name": "Existing",
                "description": "Already registered",
                "endpoint": "http://existing.local",
                "auth": {"type": "bearer", "token_env": "EXISTING_TOKEN"},
                "readonly_only": True,
                "schema_url": "",
                "tool_generation": {
                    "output_dir": ".olav/workspace/ops/tools/_generated",
                    "groups": [
                        {"tag": "things", "tool_prefix": "existing_things", "description": "things"},
                    ],
                },
            }
        }
    }
    p = tmp_path / "services.yaml"
    p.write_text(yaml.dump(cfg))
    return p


# ---------------------------------------------------------------------------
# list_platform_services
# ---------------------------------------------------------------------------

class TestListPlatformServices:
    def test_returns_registered_services(self, tmp_path: Path, monkeypatch, services_yaml: Path):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".olav" / "config").mkdir(parents=True)
        (tmp_path / ".olav" / "config" / "services.yaml").write_text(services_yaml.read_text())

        import importlib, sys
        tool_path = Path("/home/yhvh/Olav/.olav/workspace/config/creator/tools/list_platform_services.py")
        spec = importlib.util.spec_from_file_location("list_platform_services", tool_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        result = mod.list_platform_services.invoke({})
        assert result["status"] == "ok"
        assert result["total"] == 1
        service = result["services"][0]
        assert service["name"] == "existing_service"
        assert service["endpoint"] == "http://existing.local"
        assert service["auth_type"] == "bearer"
        assert len(service["tag_groups"]) == 1
        assert service["tag_groups"][0]["tag"] == "things"

    def test_missing_yaml_returns_error(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        import importlib
        tool_path = Path("/home/yhvh/Olav/.olav/workspace/config/creator/tools/list_platform_services.py")
        spec = importlib.util.spec_from_file_location("list_platform_services", tool_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        result = mod.list_platform_services.invoke({})
        assert result["status"] == "error"
        assert "not found" in result["error"]


# ---------------------------------------------------------------------------
# create_service_config
# ---------------------------------------------------------------------------

class TestCreateServiceConfig:
    def _load_tool(self):
        import importlib
        tool_path = Path("/home/yhvh/Olav/.olav/workspace/config/creator/tools/create_service_config.py")
        spec = importlib.util.spec_from_file_location("create_service_config", tool_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_creates_new_service_entry(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".olav" / "config").mkdir(parents=True)
        # Start with empty services.yaml
        (tmp_path / ".olav" / "config" / "services.yaml").write_text("services: {}")

        mod = self._load_tool()
        result = mod.create_service_config.invoke({
            "service_name": "testapi",
            "endpoint": "http://test.local",
            "auth_type": "bearer",
            "tag_groups": [
                {"tag": "items", "tool_prefix": "testapi_items", "description": "Item management"},
            ],
            "token_env": "TESTAPI_TOKEN",
        })

        assert result["status"] == "ok"
        assert result["action"] == "created"

        # Verify file content
        written = yaml.safe_load((tmp_path / ".olav" / "config" / "services.yaml").read_text())
        svc = written["services"]["testapi"]
        assert svc["endpoint"] == "http://test.local"
        assert svc["auth"]["type"] == "bearer"
        assert svc["auth"]["token_env"] == "TESTAPI_TOKEN"
        assert len(svc["tool_generation"]["groups"]) == 1
        assert svc["tool_generation"]["groups"][0]["tag"] == "items"

    def test_updates_existing_service_idempotent(self, tmp_path: Path, monkeypatch, services_yaml: Path):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".olav" / "config").mkdir(parents=True)
        (tmp_path / ".olav" / "config" / "services.yaml").write_text(services_yaml.read_text())

        mod = self._load_tool()
        result = mod.create_service_config.invoke({
            "service_name": "existing_service",
            "endpoint": "http://updated.local",
            "auth_type": "bearer",
            "tag_groups": [],
        })

        assert result["status"] == "ok"
        assert result["action"] == "updated"
        written = yaml.safe_load((tmp_path / ".olav" / "config" / "services.yaml").read_text())
        assert written["services"]["existing_service"]["endpoint"] == "http://updated.local"
        # Original service preserved
        assert "existing_service" in written["services"]

    def test_trailing_slash_stripped_from_endpoint(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".olav" / "config").mkdir(parents=True)
        (tmp_path / ".olav" / "config" / "services.yaml").write_text("services: {}")

        mod = self._load_tool()
        result = mod.create_service_config.invoke({
            "service_name": "api",
            "endpoint": "http://api.local/",
            "auth_type": "none",
            "tag_groups": [],
        })
        assert result["config"]["endpoint"] == "http://api.local"


# ---------------------------------------------------------------------------
# register_api_service
# ---------------------------------------------------------------------------

class TestRegisterApiService:
    def _load_tool(self):
        import importlib
        tool_path = Path("/home/yhvh/Olav/.olav/workspace/config/creator/tools/register_api_service.py")
        spec = importlib.util.spec_from_file_location("register_api_service", tool_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_calls_register_service_and_returns_files(self):
        mod = self._load_tool()

        mock_result = {
            "status": "ok",
            "service": "testapi",
            "ops_loaded": 12,
            "files_written": [".olav/workspace/ops/tools/_generated/testapi_items.py"],
        }

        import olav.platform.services.tool_generator as _tg
        with patch.object(_tg, "register_service", return_value=mock_result):
            result = mod.register_api_service.invoke({
                "service_name": "testapi",
                "force": True,
            })

        assert result["status"] == "ok"
        assert result["ops_loaded"] == 12
        assert len(result["files_written"]) == 1
        assert result["files_count"] == 1

    def test_propagates_error_from_register_service(self):
        mod = self._load_tool()

        import olav.platform.services.tool_generator as _tg
        with patch.object(
            _tg, "register_service",
            return_value={"status": "error", "error": "Schema fetch failed"},
        ):
            result = mod.register_api_service.invoke({"service_name": "broken"})

        assert result["status"] == "error"
        assert "Schema fetch failed" in result["error"]

    def test_handles_import_error_gracefully(self):
        import importlib
        tool_path = Path("/home/yhvh/Olav/.olav/workspace/config/creator/tools/register_api_service.py")
        spec = importlib.util.spec_from_file_location("register_api_service_import_test", tool_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        with patch.dict("sys.modules", {"olav.platform.services.tool_generator": None}):
            # Remove cached import so the tool re-imports
            import sys
            sys.modules.pop("olav.platform.services.tool_generator", None)

            # Simulate ImportError by patching builtins
            with patch("builtins.__import__", side_effect=ImportError("no module")):
                result = mod.register_api_service.func("broken")

        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# create_skill_workspace
# ---------------------------------------------------------------------------

class TestCreateSkillWorkspace:
    def _load_tool(self):
        import importlib
        tool_path = Path("/home/yhvh/Olav/.olav/workspace/config/creator/tools/create_skill_workspace.py")
        spec = importlib.util.spec_from_file_location("create_skill_workspace", tool_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_creates_skill_md_and_agent_md(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".olav" / "workspace").mkdir(parents=True)

        mod = self._load_tool()
        result = mod.create_skill_workspace.invoke({
            "workspace_name": "test-circuits",
            "description": "Circuit management tools",
            "tool_file_paths": [".olav/workspace/ops/tools/_generated/netbox_circuits.py"],
        })

        assert result["status"] == "ok"
        ws = tmp_path / ".olav" / "workspace" / "test-circuits"
        assert (ws / "SKILL.md").exists()
        assert (ws / "AGENT.md").exists()

        skill_content = (ws / "SKILL.md").read_text()
        assert "test-circuits" in skill_content or "Test Circuits" in skill_content
        assert "netbox_circuits.py" in skill_content

    def test_skill_md_has_valid_frontmatter(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".olav" / "workspace").mkdir(parents=True)

        mod = self._load_tool()
        mod.create_skill_workspace.invoke({
            "workspace_name": "myws",
            "description": "Test workspace",
            "tool_file_paths": ["path/to/tool.py"],
        })

        skill_md = (tmp_path / ".olav" / "workspace" / "myws" / "SKILL.md").read_text()
        # Should have frontmatter delimiters
        assert skill_md.startswith("---\n")
        # Frontmatter should be valid YAML
        fm_end = skill_md.index("---\n", 4)
        fm_data = yaml.safe_load(skill_md[4:fm_end])
        assert fm_data["name"] == "myws"
        assert isinstance(fm_data["tools"], list)
        assert fm_data["tools"][0]["path"] == "path/to/tool.py"

    def test_registers_in_platform_md(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ws_root = tmp_path / ".olav" / "workspace"
        ws_root.mkdir(parents=True)

        # Create a minimal PLATFORM.md with frontmatter
        platform_md = ws_root / "PLATFORM.md"
        platform_md.write_text("---\nagents:\n- existing\n---\n\n# Platform\n")

        mod = self._load_tool()
        result = mod.create_skill_workspace.invoke({
            "workspace_name": "new-ws",
            "description": "New workspace",
            "tool_file_paths": [],
        })

        assert result["registered_in_platform"] is True
        platform_content = platform_md.read_text()
        assert "new-ws" in platform_content

    def test_idempotent_platform_registration(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ws_root = tmp_path / ".olav" / "workspace"
        ws_root.mkdir(parents=True)

        platform_md = ws_root / "PLATFORM.md"
        platform_md.write_text("---\nagents:\n- already-there\n---\n\n# Platform\n")

        mod = self._load_tool()
        mod.create_skill_workspace.invoke({
            "workspace_name": "already-there",
            "description": "Already registered",
            "tool_file_paths": [],
        })

        content = platform_md.read_text()
        # Should not have duplicate entry
        assert content.count("already-there") == 1


# ---------------------------------------------------------------------------
# read_api_schema (existing tool — regression)
# ---------------------------------------------------------------------------

class TestReadApiSchema:
    def _load_tool(self):
        import importlib
        tool_path = Path("/home/yhvh/Olav/.olav/workspace/config/creator/tools/read_api_schema.py")
        spec = importlib.util.spec_from_file_location("read_api_schema", tool_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_parses_openapi_from_url(self):
        mod = self._load_tool()

        mock_response = MagicMock()
        mock_response.text = json.dumps(MINIMAL_OPENAPI)
        mock_response.status_code = 200

        with patch("requests.get", return_value=mock_response):
            result = mod.read_api_schema.invoke({
                "source": "http://test.local/api/schema/?format=json",
            })

        assert result["status"] == "success"
        assert result["title"] == "Test API"
        assert result["total_endpoints"] == 3  # 3 path+method combos
        # tags_summary should have "circuits" with 3 endpoints
        assert "circuits" in result["tags_summary"]
        assert result["tags_summary"]["circuits"]["endpoint_count"] == 3

    def test_tag_filter_returns_only_matching_endpoints(self):
        mod = self._load_tool()
        mock_response = MagicMock()
        mock_response.text = json.dumps(MINIMAL_OPENAPI)

        with patch("requests.get", return_value=mock_response):
            result = mod.read_api_schema.invoke({
                "source": "http://test.local/schema",
                "tag_filter": "circuits",
            })

        assert result["status"] == "success"
        assert all("circuits" in e["tags"] for e in result["endpoints"])
        assert result.get("tag_filter_applied") == "circuits"

    def test_parses_openapi_from_file(self, tmp_path: Path):
        mod = self._load_tool()
        schema_file = tmp_path / "schema.json"
        schema_file.write_text(json.dumps(MINIMAL_OPENAPI))

        result = mod.read_api_schema.invoke({"source": str(schema_file)})
        assert result["status"] == "success"
        assert result["title"] == "Test API"

    def test_extracts_security_schemes(self):
        mod = self._load_tool()
        mock_response = MagicMock()
        mock_response.text = json.dumps(MINIMAL_OPENAPI)

        with patch("requests.get", return_value=mock_response):
            result = mod.read_api_schema.invoke({
                "source": "http://test.local/schema",
            })

        assert "tokenAuth" in result["authentication"]
        assert result["authentication"]["tokenAuth"]["type"] == "apiKey"

    def test_returns_error_on_network_failure(self):
        mod = self._load_tool()
        with patch("requests.get", side_effect=Exception("Connection refused")):
            result = mod.read_api_schema.invoke({"source": "http://unreachable.local/schema"})
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# TestExtractSchemaReference
# ---------------------------------------------------------------------------

class TestExtractSchemaReference:
    def _load_tool(self):
        import importlib.util
        tool_path = Path("/home/yhvh/Olav/.olav/workspace/config/creator/tools/extract_schema_reference.py")
        spec = importlib.util.spec_from_file_location("extract_schema_reference", tool_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_writes_schema_reference_json(self, tmp_path: Path):
        mod = self._load_tool()
        mock_ref = {
            "service": "testapi",
            "endpoint": "http://test.local",
            "readonly_only": True,
            "tag_filter": "circuits",
            "operations": {
                "GET /api/circuits/": {
                    "summary": "List circuits",
                    "query_params": [
                        {"name": "status", "type": "string", "description": "Filter by status", "required": False},
                        {"name": "site", "type": "string", "description": "Filter by site", "required": False},
                    ],
                },
                "GET /api/circuits/{id}/": {
                    "summary": "Retrieve circuit",
                    "query_params": [],
                },
            },
        }
        import olav.platform.services.tool_generator as _tg
        with patch.object(_tg, "generate_schema_reference", return_value=mock_ref):
            result = mod.extract_schema_reference.invoke({
                "service_name": "testapi",
                "workspace_path": str(tmp_path),
                "tag": "circuits",
            })

        assert result["status"] == "ok"
        assert result["total_operations"] == 2
        assert result["operations_with_query_params"] == 1
        assert result["total_query_params"] == 2

        out_file = tmp_path / "schema_reference.json"
        assert out_file.exists()
        import json
        written = json.loads(out_file.read_text())
        assert written["service"] == "testapi"
        assert "GET /api/circuits/" in written["operations"]

    def test_handles_import_error(self, tmp_path: Path):
        mod = self._load_tool()
        with patch.dict("sys.modules", {"olav.platform.services.tool_generator": None}):
            import sys
            sys.modules.pop("olav.platform.services.tool_generator", None)
            with patch("builtins.__import__", side_effect=ImportError("no module")):
                result = mod.extract_schema_reference.func(
                    service_name="x", workspace_path=str(tmp_path)
                )
        assert result["status"] == "error"

    def test_next_step_mentions_static_context(self, tmp_path: Path):
        mod = self._load_tool()
        mock_ref = {
            "service": "s", "endpoint": "http://x", "readonly_only": True,
            "tag_filter": None, "operations": {},
        }
        import olav.platform.services.tool_generator as _tg
        with patch.object(_tg, "generate_schema_reference", return_value=mock_ref):
            result = mod.extract_schema_reference.invoke({
                "service_name": "s",
                "workspace_path": str(tmp_path),
            })
        assert "static_context" in result["next_step"]
