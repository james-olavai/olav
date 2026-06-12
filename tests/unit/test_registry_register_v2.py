"""
Phase B tests — registry enhancement for reference generation.

Doc 39 §3, §4, §10: replace tool_generation with reference_generation.
These tests are written BEFORE implementation (TDD red phase).
"""

from __future__ import annotations

import importlib
import textwrap
import warnings
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _registry_module() -> ModuleType:
    import olav.platform.services.registry as m
    return importlib.reload(m)


def _tool_generator_module() -> ModuleType:
    import olav.platform.services.tool_generator as m
    return importlib.reload(m)


# ---------------------------------------------------------------------------
# B1: Model — ReferenceGenerationConfig
# ---------------------------------------------------------------------------


class TestReferenceGenerationConfig:
    def test_dataclass_exists_in_registry(self):
        m = _registry_module()
        assert hasattr(m, "ReferenceGenerationConfig"), \
            "ReferenceGenerationConfig not found in registry module"

    def test_has_output_dir_field(self):
        m = _registry_module()
        cfg = m.ReferenceGenerationConfig()
        assert hasattr(cfg, "output_dir")
        assert isinstance(cfg.output_dir, str)

    def test_has_groups_field(self):
        m = _registry_module()
        cfg = m.ReferenceGenerationConfig()
        assert hasattr(cfg, "groups")
        assert isinstance(cfg.groups, list)

    def test_default_output_dir(self):
        """Default output dir should be the infra references directory."""
        m = _registry_module()
        cfg = m.ReferenceGenerationConfig()
        assert "infra" in cfg.output_dir or "references" in cfg.output_dir, \
            f"Expected infra/references in default output_dir, got: {cfg.output_dir}"

    def test_service_config_has_reference_generation_field(self):
        m = _registry_module()
        svc = m.ServiceConfig(name="test")
        assert hasattr(svc, "reference_generation"), \
            "ServiceConfig missing reference_generation field"
        assert isinstance(svc.reference_generation, m.ReferenceGenerationConfig)


# ---------------------------------------------------------------------------
# B1: Model — _parse_service() backward compat
# ---------------------------------------------------------------------------


class TestParseServiceBackwardCompat:
    def _make_yaml_services(self, raw_services: dict) -> Path:
        import yaml, tempfile, os
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        )
        yaml.dump({"services": raw_services}, tmp)
        tmp.close()
        return Path(tmp.name)

    def test_parse_service_reads_reference_generation(self, tmp_path):
        """services.yaml with reference_generation → ServiceConfig.reference_generation populated."""
        import yaml
        svc_yaml = tmp_path / "services.yaml"
        svc_yaml.write_text(yaml.dump({
            "services": {
                "netbox": {
                    "endpoint": "http://localhost:8000",
                    "reference_generation": {
                        "output_dir": ".olav/workspace/infra/references",
                        "groups": [{"tag": "dcim", "description": "DCIM"}],
                    },
                }
            }
        }))

        m = _registry_module()
        m.ServiceRegistry.reset()
        with patch.dict("os.environ", {"OLAV_SERVICES_PATH": str(svc_yaml)}):
            registry = m.ServiceRegistry.get_instance()
            svc = registry.get("netbox")

        assert svc.reference_generation.output_dir == ".olav/workspace/infra/references"
        assert len(svc.reference_generation.groups) == 1
        assert svc.reference_generation.groups[0].tag == "dcim"

    def test_tool_generation_only_emits_deprecation_warning(self, tmp_path):
        """Old services.yaml with only tool_generation → emits DeprecationWarning."""
        import yaml
        svc_yaml = tmp_path / "services.yaml"
        svc_yaml.write_text(yaml.dump({
            "services": {
                "netbox": {
                    "endpoint": "http://localhost:8000",
                    "tool_generation": {
                        "output_dir": ".olav/workspace/ops/tools/_generated",
                        "groups": [{"tag": "dcim"}],
                    },
                }
            }
        }))

        m = _registry_module()
        m.ServiceRegistry.reset()
        with patch.dict("os.environ", {"OLAV_SERVICES_PATH": str(svc_yaml)}):
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                registry = m.ServiceRegistry.get_instance()
                registry.get("netbox")

        deprecation_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert len(deprecation_warnings) > 0, \
            "Expected DeprecationWarning when only tool_generation is present"
        assert "tool_generation" in str(deprecation_warnings[0].message).lower()

    def test_tool_generation_only_populates_reference_generation(self, tmp_path):
        """Old tool_generation block → reference_generation populated via fallback."""
        import yaml
        svc_yaml = tmp_path / "services.yaml"
        svc_yaml.write_text(yaml.dump({
            "services": {
                "netbox": {
                    "endpoint": "http://localhost:8000",
                    "tool_generation": {
                        "output_dir": ".olav/workspace/ops/tools/_generated",
                        "groups": [{"tag": "dcim"}],
                    },
                }
            }
        }))

        m = _registry_module()
        m.ServiceRegistry.reset()
        with patch.dict("os.environ", {"OLAV_SERVICES_PATH": str(svc_yaml)}):
            with warnings.catch_warnings(record=True):
                warnings.simplefilter("always")
                registry = m.ServiceRegistry.get_instance()
                svc = registry.get("netbox")

        assert svc.reference_generation is not None
        assert len(svc.reference_generation.groups) == 1
        assert svc.reference_generation.groups[0].tag == "dcim"


# ---------------------------------------------------------------------------
# B2: _render_markdown_reference()
# ---------------------------------------------------------------------------


class TestRenderMarkdownReference:
    def _make_svc(self, **kwargs) -> Any:
        import olav.platform.services.registry as m
        defaults = dict(
            name="netbox",
            display_name="NetBox",
            endpoint="http://localhost:8000",
            readonly_only=True,
        )
        defaults.update(kwargs)
        return m.ServiceConfig(**defaults)

    def _mock_ops(self) -> list[tuple]:
        """Sample rows: (method, path, summary, req_def, resp_def, qp_raw)"""
        import json
        return [
            ("GET", "/api/dcim/devices/", "List devices",
             None, None,
             json.dumps([{"name": "limit", "type": "integer", "required": False, "description": "Page limit"}])),
            ("GET", "/api/dcim/devices/{id}/", "Retrieve device",
             None, None, json.dumps([])),
        ]

    def test_function_exists_in_tool_generator(self):
        m = _tool_generator_module()
        assert hasattr(m, "_render_markdown_reference"), \
            "_render_markdown_reference not found in tool_generator"

    def test_returns_string(self):
        import olav.platform.services.tool_generator as m
        svc = self._make_svc()
        ops_by_tag = {"dcim": self._mock_ops()}
        result = m._render_markdown_reference(svc, ops_by_tag)
        assert isinstance(result, str)

    def test_header_contains_service_display_name(self):
        import olav.platform.services.tool_generator as m
        svc = self._make_svc()
        result = m._render_markdown_reference(svc, {"dcim": self._mock_ops()})
        assert "NetBox" in result

    def test_header_contains_endpoint(self):
        import olav.platform.services.tool_generator as m
        svc = self._make_svc()
        result = m._render_markdown_reference(svc, {"dcim": self._mock_ops()})
        assert "http://localhost:8000" in result

    def test_contains_tag_section(self):
        import olav.platform.services.tool_generator as m
        svc = self._make_svc()
        result = m._render_markdown_reference(svc, {"dcim": self._mock_ops()})
        assert "dcim" in result.lower() or "## dcim" in result.lower()

    def test_get_operations_listed(self):
        import olav.platform.services.tool_generator as m
        svc = self._make_svc()
        result = m._render_markdown_reference(svc, {"dcim": self._mock_ops()})
        assert "/api/dcim/devices/" in result

    def test_query_params_listed(self):
        import olav.platform.services.tool_generator as m
        svc = self._make_svc()
        result = m._render_markdown_reference(svc, {"dcim": self._mock_ops()})
        assert "limit" in result

    def test_max_8_params_per_operation(self):
        """Operations with more than 8 params should be truncated."""
        import json
        import olav.platform.services.tool_generator as m
        svc = self._make_svc()
        many_params = json.dumps([
            {"name": f"param_{i}", "type": "string", "required": False, "description": ""}
            for i in range(12)
        ])
        ops = [("GET", "/api/test/", "Test", None, None, many_params)]
        result = m._render_markdown_reference(svc, {"test": ops})
        # Count how many param lines appear — should be capped at 8
        param_count = result.count("param_")
        assert param_count <= 8, f"Expected ≤8 params listed, got {param_count}"

    def test_empty_ops_produces_skeleton(self):
        """No operations → produce a skeleton file with ⚠️ notice."""
        import olav.platform.services.tool_generator as m
        svc = self._make_svc()
        result = m._render_markdown_reference(svc, {})
        assert "⚠️" in result or "no operations" in result.lower() or "skeleton" in result.lower()


# ---------------------------------------------------------------------------
# B3: register_service() — reference files output
# ---------------------------------------------------------------------------


class TestRegisterServiceV2:
    def _mock_schema_fetch(self):
        return {
            "openapi": "3.0.0",
            "info": {"title": "NetBox API", "version": "3.0"},
            "paths": {
                "/api/dcim/devices/": {
                    "get": {
                        "tags": ["dcim"],
                        "summary": "List devices",
                        "parameters": [],
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
        }

    def test_returns_reference_files_key(self, tmp_path):
        """register_service() result must have 'reference_files' key."""
        import yaml
        import olav.platform.services.tool_generator as m
        import olav.platform.services.registry as reg_m

        ref_dir = tmp_path / "infra" / "references"
        svc_yaml = tmp_path / "services.yaml"
        svc_yaml.write_text(yaml.dump({
            "services": {
                "netbox": {
                    "endpoint": "http://localhost:8000",
                    "reference_generation": {
                        "output_dir": str(ref_dir),
                        "groups": [{"tag": "dcim"}],
                    },
                }
            }
        }))

        reg_m.ServiceRegistry.reset()
        with patch.dict("os.environ", {"OLAV_SERVICES_PATH": str(svc_yaml)}):
            with patch.object(m, "_discover_schema_url", return_value="http://localhost:8000/api/schema/"), \
                 patch.object(m, "_fetch_openapi_schema", return_value=self._mock_schema_fetch()), \
                 patch.object(m, "_store_schema", return_value=5), \
                 patch.object(m, "_query_tag_operations", return_value=[
                     ("GET", "/api/dcim/devices/", "List devices", None, None, "[]")
                 ]):
                result = m.register_service("netbox")

        assert "reference_files" in result, \
            f"Expected 'reference_files' key, got: {list(result.keys())}"

    def test_writes_markdown_file(self, tmp_path):
        """register_service() should write a .md file to reference_generation.output_dir."""
        import yaml
        import olav.platform.services.tool_generator as m
        import olav.platform.services.registry as reg_m

        ref_dir = tmp_path / "infra" / "references"
        svc_yaml = tmp_path / "services.yaml"
        svc_yaml.write_text(yaml.dump({
            "services": {
                "netbox": {
                    "endpoint": "http://localhost:8000",
                    "reference_generation": {
                        "output_dir": str(ref_dir),
                        "groups": [{"tag": "dcim"}],
                    },
                }
            }
        }))

        reg_m.ServiceRegistry.reset()
        with patch.dict("os.environ", {"OLAV_SERVICES_PATH": str(svc_yaml)}):
            with patch.object(m, "_discover_schema_url", return_value="http://localhost:8000/api/schema/"), \
                 patch.object(m, "_fetch_openapi_schema", return_value=self._mock_schema_fetch()), \
                 patch.object(m, "_store_schema", return_value=5), \
                 patch.object(m, "_query_tag_operations", return_value=[
                     ("GET", "/api/dcim/devices/", "List devices", None, None, "[]")
                 ]):
                result = m.register_service("netbox")

        assert result.get("status") == "ok", f"Expected status=ok, got {result}"
        md_files = list(ref_dir.glob("*.md"))
        assert len(md_files) >= 1, f"Expected at least one .md file in {ref_dir}, found {md_files}"

    def test_no_longer_writes_python_files(self, tmp_path):
        """register_service() must NOT write .py tool files."""
        import yaml
        import olav.platform.services.tool_generator as m
        import olav.platform.services.registry as reg_m

        ref_dir = tmp_path / "infra" / "references"
        svc_yaml = tmp_path / "services.yaml"
        svc_yaml.write_text(yaml.dump({
            "services": {
                "netbox": {
                    "endpoint": "http://localhost:8000",
                    "reference_generation": {
                        "output_dir": str(ref_dir),
                        "groups": [{"tag": "dcim"}],
                    },
                }
            }
        }))

        reg_m.ServiceRegistry.reset()
        with patch.dict("os.environ", {"OLAV_SERVICES_PATH": str(svc_yaml)}):
            with patch.object(m, "_discover_schema_url", return_value="http://localhost:8000/api/schema/"), \
                 patch.object(m, "_fetch_openapi_schema", return_value=self._mock_schema_fetch()), \
                 patch.object(m, "_store_schema", return_value=5), \
                 patch.object(m, "_query_tag_operations", return_value=[
                     ("GET", "/api/dcim/devices/", "List devices", None, None, "[]")
                 ]):
                result = m.register_service("netbox")

        py_files = list(ref_dir.glob("*.py"))
        assert len(py_files) == 0, f"Expected no .py files written, found: {py_files}"


# ---------------------------------------------------------------------------
# B5: migrate_services_yaml.py
# ---------------------------------------------------------------------------


class TestMigrateServicesYaml:
    def test_script_exists(self):
        assert Path("scripts/migrate_services_yaml.py").exists(), \
            "scripts/migrate_services_yaml.py not found"

    def test_dry_run_by_default(self, tmp_path):
        """Running the script without --write must not modify the file."""
        import yaml, subprocess, sys
        svc_yaml = tmp_path / "services.yaml"
        svc_yaml.write_text(yaml.dump({
            "services": {
                "netbox": {
                    "endpoint": "http://localhost:8000",
                    "tool_generation": {
                        "output_dir": ".olav/workspace/ops/tools/_generated",
                        "groups": [{"tag": "dcim"}],
                    },
                }
            }
        }))
        original = svc_yaml.read_text()

        result = subprocess.run(
            [sys.executable, "scripts/migrate_services_yaml.py", str(svc_yaml)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        assert svc_yaml.read_text() == original, \
            "Dry-run should NOT modify the file"

    def test_write_flag_migrates_tool_generation(self, tmp_path):
        """--write flag should replace tool_generation with reference_generation."""
        import yaml, subprocess, sys
        svc_yaml = tmp_path / "services.yaml"
        svc_yaml.write_text(yaml.dump({
            "services": {
                "netbox": {
                    "endpoint": "http://localhost:8000",
                    "tool_generation": {
                        "output_dir": ".olav/workspace/ops/tools/_generated",
                        "groups": [{"tag": "dcim"}],
                    },
                }
            }
        }))

        result = subprocess.run(
            [sys.executable, "scripts/migrate_services_yaml.py", "--write", str(svc_yaml)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr

        updated = yaml.safe_load(svc_yaml.read_text())
        netbox_cfg = updated["services"]["netbox"]
        assert "tool_generation" not in netbox_cfg, \
            "tool_generation should have been removed after migration"
        assert "reference_generation" in netbox_cfg, \
            "reference_generation should be present after migration"

    def test_idempotent_already_migrated(self, tmp_path):
        """Running --write on an already-migrated file should be a no-op."""
        import yaml, subprocess, sys
        svc_yaml = tmp_path / "services.yaml"
        svc_yaml.write_text(yaml.dump({
            "services": {
                "netbox": {
                    "endpoint": "http://localhost:8000",
                    "reference_generation": {
                        "output_dir": ".olav/workspace/infra/references",
                        "groups": [{"tag": "dcim"}],
                    },
                }
            }
        }))
        original = yaml.safe_load(svc_yaml.read_text())

        result = subprocess.run(
            [sys.executable, "scripts/migrate_services_yaml.py", "--write", str(svc_yaml)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        updated = yaml.safe_load(svc_yaml.read_text())
        assert updated == original, "Already-migrated file should be unchanged"
