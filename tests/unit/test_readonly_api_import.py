"""TDD — readonly_only API import filter + sandbox external write guard.

Two features:
  1. ServiceConfig.readonly_only=True  → tool_generator only imports GET ops
     ServiceConfig.readonly_only=False → all methods imported (e.g. clab)
  2. sandbox_guard.scan_sandbox_code() → detects HTTP/DB external write ops
     execute_in_sandbox returns requires_approval dict when detected
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path


# ── 1. ServiceConfig.readonly_only ───────────────────────────────────────────

class TestServiceConfigReadonlyOnly:
    def test_default_readonly_only_is_true(self):
        """ServiceConfig defaults to readonly_only=True."""
        from olav.platform.services.registry import ServiceConfig
        svc = ServiceConfig(name="netbox")
        assert svc.readonly_only is True

    def test_readonly_only_false_for_lab_systems(self):
        """readonly_only can be set to False for lab/simulation systems."""
        from olav.platform.services.registry import ServiceConfig
        svc = ServiceConfig(name="containerlab", readonly_only=False)
        assert svc.readonly_only is False

    def test_registry_loads_readonly_only_from_yaml(self, tmp_path, monkeypatch):
        """ServiceRegistry parses readonly_only from services.yaml."""
        import yaml
        cfg = {
            "services": {
                "netbox": {"endpoint": "http://localhost:8000", "readonly_only": True},
                "clab":   {"endpoint": "http://localhost:8080", "readonly_only": False},
            }
        }
        (tmp_path / "services.yaml").write_text(yaml.dump(cfg))
        monkeypatch.setenv("OLAV_SERVICES_PATH", str(tmp_path / "services.yaml"))

        from olav.platform.services.registry import ServiceRegistry
        ServiceRegistry._instance = None
        reg = ServiceRegistry.get_instance()
        assert reg.get("netbox").readonly_only is True
        assert reg.get("clab").readonly_only is False
        ServiceRegistry._instance = None

    def test_registry_defaults_readonly_only_true_when_missing(self, tmp_path, monkeypatch):
        """readonly_only defaults to True when not specified in services.yaml."""
        import yaml
        cfg = {"services": {"myapi": {"endpoint": "http://localhost:9000"}}}
        (tmp_path / "services.yaml").write_text(yaml.dump(cfg))
        monkeypatch.setenv("OLAV_SERVICES_PATH", str(tmp_path / "services.yaml"))

        from olav.platform.services.registry import ServiceRegistry
        ServiceRegistry._instance = None
        reg = ServiceRegistry.get_instance()
        assert reg.get("myapi").readonly_only is True
        ServiceRegistry._instance = None


# ── 2. tool_generator filters methods by readonly_only ───────────────────────

class TestToolGeneratorReadonlyFilter:
    def _make_svc(self, readonly_only: bool, output_dir: str):
        from olav.platform.services.registry import (
            ServiceConfig, ToolGenerationConfig, ToolGroupConfig,
        )
        return ServiceConfig(
            name="testsvc",
            display_name="Test",
            endpoint="http://localhost",
            readonly_only=readonly_only,
            tool_generation=ToolGenerationConfig(
                output_dir=output_dir,
                groups=[ToolGroupConfig(tag="labs", tool_prefix="clab")],
            ),
        )

    def _fake_rows(self):
        """Simulate api_registry rows: GET + POST + DELETE (includes query_params column)."""
        return [
            ("GET",    "/api/v1/labs",       "List labs",   None, None, "[]"),
            ("POST",   "/api/v1/labs",       "Create lab",  "{}", None, "[]"),
            ("DELETE", "/api/v1/labs/{name}","Delete lab",  None, None, "[]"),
        ]

    def test_readonly_true_reference_contains_only_get(self, tmp_path):
        """When readonly_only=True, reference markdown only includes GET endpoints."""
        from olav.platform.services.tool_generator import _render_markdown_reference

        svc = self._make_svc(readonly_only=True, output_dir=str(tmp_path))
        # Filter rows to GET-only (simulating readonly_only behavior in register_service)
        rows = [r for r in self._fake_rows() if r[0].upper() == "GET"]
        ops_by_tag = {"labs": rows}

        md = _render_markdown_reference(svc, ops_by_tag)
        assert "GET" in md
        assert "POST" not in md
        assert "DELETE" not in md

    def test_readonly_false_reference_contains_all_methods(self, tmp_path):
        """When readonly_only=False, reference includes all methods."""
        from olav.platform.services.tool_generator import _render_markdown_reference

        svc = self._make_svc(readonly_only=False, output_dir=str(tmp_path))
        ops_by_tag = {"labs": self._fake_rows()}

        md = _render_markdown_reference(svc, ops_by_tag)
        assert "GET" in md
        assert "POST" in md or "Create" in md
        assert "DELETE" in md or "Delete" in md


# ── 3. sandbox_guard: scan_sandbox_code ──────────────────────────────────────

class TestSandboxGuard:
    """scan_sandbox_code returns ApprovalResult."""

    def _scan(self, code: str):
        from olav.platform.safety.sandbox_guard import scan_sandbox_code
        return scan_sandbox_code(code)

    # ── HTTP mutations ───────────────────────────────────────────────────────

    def test_httpx_delete_requires_approval(self):
        result = self._scan("httpx.delete('http://api.example.com/labs/prod')")
        assert result.requires_approval is True
        assert "delete" in result.reason.lower() or "http" in result.reason.lower()

    def test_httpx_post_requires_approval(self):
        result = self._scan("resp = httpx.post('http://clab:8080/api/v1/labs', json=data)")
        assert result.requires_approval is True

    def test_httpx_put_requires_approval(self):
        result = self._scan("httpx.put('http://netbox/api/dcim/devices/1/', json=payload)")
        assert result.requires_approval is True

    def test_requests_delete_requires_approval(self):
        result = self._scan("requests.delete('http://api/resource/1')")
        assert result.requires_approval is True

    def test_client_request_delete_requires_approval(self):
        result = self._scan('client.request("DELETE", "http://clab/api/v1/labs/prod")')
        assert result.requires_approval is True

    def test_service_call_delete_requires_approval(self):
        result = self._scan('service_call("clab", "DELETE", "/api/v1/labs/prod")')
        assert result.requires_approval is True

    def test_service_call_post_requires_approval(self):
        result = self._scan('service_call("netbox", "POST", "/api/dcim/devices/")')
        assert result.requires_approval is True

    # ── DB mutations ─────────────────────────────────────────────────────────

    def test_duckdb_delete_requires_approval(self):
        result = self._scan('con.execute("DELETE FROM netops.devices WHERE 1=1")')
        assert result.requires_approval is True

    def test_duckdb_drop_requires_approval(self):
        result = self._scan("con.execute('DROP TABLE netops.topology_links')")
        assert result.requires_approval is True

    def test_duckdb_insert_requires_approval(self):
        result = self._scan('con.execute("INSERT INTO netops.devices VALUES (1, \'R99\')")')
        assert result.requires_approval is True

    # ── local filesystem — allowed ────────────────────────────────────────────

    def test_local_file_write_is_allowed(self):
        result = self._scan("open('/tmp/output.csv', 'w').write(data)")
        assert result.requires_approval is False

    def test_local_file_delete_is_allowed(self):
        result = self._scan("import os; os.remove('/tmp/old_file.txt')")
        assert result.requires_approval is False

    def test_shutil_rmtree_local_is_allowed(self):
        result = self._scan("shutil.rmtree('/tmp/work_dir')")
        assert result.requires_approval is False

    def test_httpx_get_is_allowed(self):
        result = self._scan("resp = httpx.get('http://api.example.com/labs')")
        assert result.requires_approval is False

    def test_read_only_sql_is_allowed(self):
        result = self._scan('con.execute("SELECT * FROM netops.devices")')
        assert result.requires_approval is False

    def test_duckdb_connect_read_only_is_allowed(self):
        result = self._scan(
            'con = duckdb.connect(".olav/databases/olav.duckdb", read_only=True)\n'
            'con.execute("SELECT count(*) FROM netops.devices")'
        )
        assert result.requires_approval is False


# ── 4. execute_in_sandbox returns requires_approval ──────────────────────────

class TestSandboxGuardIntegration:
    def test_execute_in_sandbox_blocks_http_delete(self, tmp_path, monkeypatch):
        """execute_in_sandbox returns requires_approval dict for HTTP DELETE code."""
        monkeypatch.chdir(tmp_path)
        from olav.platform.sandbox import execute_in_sandbox

        result = execute_in_sandbox(
            "import httpx\nhttpx.delete('http://clab:8080/api/v1/labs/prod')",
            timeout=5,
        )
        assert result.get("status") == "requires_approval"
        assert "reason" in result

    def test_execute_in_sandbox_allows_get(self, tmp_path, monkeypatch):
        """execute_in_sandbox runs normally for safe GET-only code."""
        monkeypatch.chdir(tmp_path)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="__OLAV_RESULT__:42", stderr=""
            )
            from olav.platform.sandbox import execute_in_sandbox
            result = execute_in_sandbox("_result = 42", timeout=5)

        assert result.get("status") == "success"
