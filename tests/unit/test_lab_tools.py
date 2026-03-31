"""TDD tests for lab skill tools (RED phase).

All tests should FAIL until the tool modules are created.
Tests use mocks — no real network calls, no real DuckDB file.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import duckdb
import pytest
import yaml as pyyaml

# Add lab tools dir to sys.path so tools can be imported directly
_LAB_TOOLS_DIR = Path(__file__).parents[2] / ".olav" / "workspace" / "ops" / "lab" / "tools"
if str(_LAB_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_LAB_TOOLS_DIR))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_registry_db(tmp_path: Path) -> Path:
    """Bootstrap an in-memory registry DB fixture as a file."""
    db_file = tmp_path / "olav_registry.duckdb"
    con = duckdb.connect(str(db_file))
    con.execute("CREATE SCHEMA api_registry")
    con.execute(
        """
        CREATE TABLE api_registry.schemas (
            api_name     VARCHAR PRIMARY KEY,
            base_url     VARCHAR NOT NULL,
            schema_url   VARCHAR NOT NULL,
            fetched_at   VARCHAR NOT NULL,
            spec_version VARCHAR,
            raw_doc      JSON
        )
        """
    )
    con.execute(
        """
        CREATE TABLE api_registry.operations (
            api_name         VARCHAR NOT NULL,
            method           VARCHAR NOT NULL,
            path             VARCHAR NOT NULL,
            summary          VARCHAR,
            tags             VARCHAR[],
            request_body_def VARCHAR,
            response_200_def VARCHAR,
            PRIMARY KEY (api_name, method, path)
        )
        """
    )
    con.execute(
        """
        CREATE TABLE api_registry.definitions (
            api_name  VARCHAR NOT NULL,
            def_name  VARCHAR NOT NULL,
            fields    JSON NOT NULL,
            PRIMARY KEY (api_name, def_name)
        )
        """
    )
    # Seed with one API
    con.execute(
        "INSERT INTO api_registry.schemas VALUES (?, ?, ?, ?, ?, ?)",
        ["clab", "http://192.168.100.12:8080", "http://192.168.100.12:8080/swagger.json",
         "2026-03-28T00:00:00Z", "2.0", "{}"],
    )
    con.execute(
        "INSERT INTO api_registry.operations VALUES (?, ?, ?, ?, ?, ?, ?)",
        ["clab", "GET", "/api/v1/labs", "List labs", ["labs"], None, "LabsResponse"],
    )
    con.execute(
        "INSERT INTO api_registry.operations VALUES (?, ?, ?, ?, ?, ?, ?)",
        ["clab", "POST", "/api/v1/labs", "Deploy lab", ["labs"], "TopologyRequest", "Lab"],
    )
    con.execute(
        "INSERT INTO api_registry.definitions VALUES (?, ?, ?)",
        ["clab", "TopologyRequest", json.dumps({"name": {}, "topology": {}})],
    )
    con.close()
    return db_file


# ---------------------------------------------------------------------------
# query_api_schema
# ---------------------------------------------------------------------------

class TestQueryApiSchema:
    def test_query_api_schema_lists_loaded_apis(self, tmp_path):
        db_file = _make_registry_db(tmp_path)

        from query_api_schema import query_api_schema

        result = json.loads(query_api_schema({"db_path": str(db_file)}))
        assert "apis" in result
        assert any(a["api_name"] == "clab" for a in result["apis"])

    def test_query_api_schema_filters_by_tag(self, tmp_path):
        db_file = _make_registry_db(tmp_path)

        from query_api_schema import query_api_schema

        result = json.loads(query_api_schema({"db_path": str(db_file), "api_name": "clab", "tag": "labs"}))
        assert "operations" in result
        assert len(result["operations"]) >= 1
        assert all(op["api_name"] == "clab" for op in result["operations"])

    def test_query_api_schema_returns_error_if_registry_empty(self, tmp_path):
        db_file = tmp_path / "empty.duckdb"  # does not exist

        from query_api_schema import query_api_schema

        result = json.loads(query_api_schema({"db_path": str(db_file)}))
        # Should not raise — returns empty list or error key
        assert "apis" in result or "error" in result


# ---------------------------------------------------------------------------
# call_api
# ---------------------------------------------------------------------------

class TestCallApi:
    def test_call_api_sends_correct_method_and_path(self, tmp_path):
        db_file = _make_registry_db(tmp_path)

        from call_api import call_api

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"labs": []}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.request", return_value=mock_response) as mock_req:
            result = json.loads(call_api({
                "api_name": "clab",
                "method": "GET",
                "path": "/api/v1/labs",
                "db_path": str(db_file),
            }))

        mock_req.assert_called_once()
        call_kwargs = mock_req.call_args
        assert call_kwargs[0][0] == "GET"
        assert "/api/v1/labs" in call_kwargs[0][1]
        assert result["status_code"] == 200

    def test_call_api_injects_auth_header_from_env(self, tmp_path):
        db_file = _make_registry_db(tmp_path)

        from call_api import call_api

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}
        mock_response.raise_for_status = MagicMock()

        import os
        env = {**os.environ, "CLAB_TOKEN": "test-token-123"}
        with patch.dict("os.environ", {"CLAB_TOKEN": "test-token-123"}):
            with patch("httpx.request", return_value=mock_response) as mock_req:
                call_api({
                    "api_name": "clab",
                    "method": "GET",
                    "path": "/api/v1/labs",
                    "db_path": str(db_file),
                })

        headers = mock_req.call_args[1].get("headers", {})
        assert headers.get("Authorization") == "Bearer test-token-123"

    def test_call_api_returns_json_on_success(self, tmp_path):
        db_file = _make_registry_db(tmp_path)

        from call_api import call_api

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"labs": [{"name": "bgp-lab"}]}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.request", return_value=mock_response):
            result = json.loads(call_api({
                "api_name": "clab",
                "method": "GET",
                "path": "/api/v1/labs",
                "db_path": str(db_file),
            }))

        assert result["status_code"] == 200
        assert result["body"] == {"labs": [{"name": "bgp-lab"}]}

    def test_call_api_returns_error_dict_on_http_error(self, tmp_path):
        db_file = _make_registry_db(tmp_path)

        from call_api import call_api

        with patch("httpx.request", side_effect=Exception("connection refused")):
            result = json.loads(call_api({
                "api_name": "clab",
                "method": "GET",
                "path": "/api/v1/labs",
                "db_path": str(db_file),
            }))

        assert "error" in result

    def test_call_api_empty_token_does_not_crash(self, tmp_path):
        db_file = _make_registry_db(tmp_path)

        from call_api import call_api

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.json.return_value = {"error": "unauthorized"}
        mock_response.raise_for_status = MagicMock()

        with patch.dict("os.environ", {}, clear=False):
            # Remove token if present
            import os
            os.environ.pop("CLAB_TOKEN", None)
            with patch("httpx.request", return_value=mock_response):
                result = json.loads(call_api({
                    "api_name": "clab",
                    "method": "GET",
                    "path": "/api/v1/labs",
                    "db_path": str(db_file),
                }))

        assert result["status_code"] == 401  # returned, not raised


# ---------------------------------------------------------------------------
# get_definition_schema
# ---------------------------------------------------------------------------

class TestGetDefinitionSchema:
    def test_get_definition_schema_returns_field_names(self, tmp_path):
        db_file = _make_registry_db(tmp_path)

        from get_definition_schema import get_definition_schema

        result = json.loads(get_definition_schema({
            "api_name": "clab",
            "def_name": "TopologyRequest",
            "db_path": str(db_file),
        }))

        assert "fields" in result
        assert "name" in result["fields"]
        assert "topology" in result["fields"]

    def test_get_definition_schema_unknown_def_returns_empty(self, tmp_path):
        db_file = _make_registry_db(tmp_path)

        from get_definition_schema import get_definition_schema

        result = json.loads(get_definition_schema({
            "api_name": "clab",
            "def_name": "NonExistentDef",
            "db_path": str(db_file),
        }))

        assert result["fields"] == [] or result["fields"] == {}


# ---------------------------------------------------------------------------
# push_config_api
# ---------------------------------------------------------------------------

class TestPushConfigApi:
    def test_push_config_api_dry_run_does_not_call_http(self, tmp_path):
        from push_config_api import push_config_api

        with patch("httpx.post") as mock_post:
            result = push_config_api(
                lab_name="test-lab",
                configs={"R1": "/ interface ethernet-1/1 admin-state enable"},
                dry_run=True,
            )

        # Auth login may be called, but exec endpoint should not be called with config
        # The result should have dry_run=True and status dry_run
        assert result["dry_run"] is True
        assert result["results"]["R1"]["status"] == "dry_run"

    def test_push_config_api_sends_sr_cli_candidate_transaction(self, tmp_path):
        from push_config_api import push_config_api

        mock_login = MagicMock()
        mock_login.status_code = 200
        mock_login.json.return_value = {"token": "test-token"}
        mock_login.raise_for_status = MagicMock()

        mock_exec = MagicMock()
        mock_exec.status_code = 200
        mock_exec.json.return_value = {"stdout": "commit succeeded", "stderr": ""}
        mock_exec.content = b'{"stdout": "commit succeeded", "stderr": ""}'
        mock_exec.raise_for_status = MagicMock()

        with patch("httpx.post", side_effect=[mock_login, mock_exec]) as mock_post:
            result = push_config_api(
                lab_name="test-lab",
                configs={"R1": "/ interface ethernet-1/1 admin-state enable"},
                dry_run=False,
            )

        assert result["pushed"] == 1
        assert result["results"]["R1"]["status"] == "ok"
        # Verify the exec call had sr_cli candidate transaction
        exec_call = mock_post.call_args_list[-1]
        body = exec_call[1].get("json", exec_call[0][1] if len(exec_call[0]) > 1 else {})
        assert body.get("cmd") == "sr_cli"
        assert "enter candidate" in body.get("stdin", "")
        assert "commit now" in body.get("stdin", "")

    def test_push_config_api_returns_error_on_http_failure(self):
        from push_config_api import push_config_api

        mock_login = MagicMock()
        mock_login.status_code = 200
        mock_login.json.return_value = {"token": "tok"}
        mock_login.raise_for_status = MagicMock()

        with patch("httpx.post", side_effect=[mock_login, Exception("connection refused")]):
            result = push_config_api(
                lab_name="test-lab",
                configs={"R1": "/ interface ethernet-1/1 admin-state enable"},
                dry_run=False,
            )

        assert result["results"]["R1"]["status"] == "error"

    def test_push_config_api_skips_empty_configs(self):
        from push_config_api import push_config_api

        with patch("httpx.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200, json=lambda: {"token": "tok"}, raise_for_status=MagicMock()
            )
            result = push_config_api(
                lab_name="test-lab",
                configs={"R1": "", "R2": "   "},
                dry_run=False,
            )

        assert result["results"]["R1"]["status"] == "skipped"
        assert result["results"]["R2"]["status"] == "skipped"
        assert result["pushed"] == 0

    def test_push_config_api_handles_multiple_devices(self):
        from push_config_api import push_config_api

        mock_login = MagicMock(status_code=200, raise_for_status=MagicMock())
        mock_login.json.return_value = {"token": "tok"}

        def make_exec_resp():
            m = MagicMock(status_code=200, raise_for_status=MagicMock())
            m.json.return_value = {"stdout": "ok", "stderr": ""}
            m.content = b'{"stdout":"ok","stderr":""}'
            return m

        with patch("httpx.post", side_effect=[mock_login, make_exec_resp(), make_exec_resp()]):
            result = push_config_api(
                lab_name="test-lab",
                configs={
                    "R1": "/ interface ethernet-1/1 admin-state enable",
                    "R2": "/ interface ethernet-1/2 admin-state enable",
                },
                dry_run=False,
            )

        assert result["pushed"] == 2
        assert result["total"] == 2


# ---------------------------------------------------------------------------
# TestCallApiAuth
# ---------------------------------------------------------------------------

class TestCallApiAuth:
    """P0 fix: CLAB uses Authorization: Bearer, not X-Auth-Token"""

    def test_call_api_uses_bearer_auth_not_x_auth_token(self, tmp_path):
        # When CLAB_TOKEN env var is set, call_api must send Authorization: Bearer <token>
        # and must NOT send X-Auth-Token header
        import importlib, sys
        db_file = _make_registry_db(tmp_path)
        mod = importlib.import_module("call_api")
        importlib.reload(mod)
        mock_resp = MagicMock(); mock_resp.status_code=200; mock_resp.json.return_value={}; mock_resp.raise_for_status=MagicMock()
        with patch.dict("os.environ", {"CLAB_TOKEN": "my-jwt-token"}):
            with patch("httpx.request", return_value=mock_resp) as mock_req:
                mod.call_api({"api_name":"clab","method":"GET","path":"/api/v1/labs","db_path":str(db_file)})
        headers = mock_req.call_args[1].get("headers", {})
        assert headers.get("Authorization") == "Bearer my-jwt-token"
        assert "X-Auth-Token" not in headers

    def test_call_api_integration_get_version(self):
        """Integration: real CLAB version endpoint with auto-login"""
        import os
        # auto-login: if CLAB_TOKEN not in env, tool should auto-login using CLAB_URL/CLAB_USER/CLAB_PASS
        # OR: test just sets token manually
        import httpx
        login = httpx.post("http://192.168.100.12:8080/login", json={"username":"admin","password":"admin"}, timeout=5)
        token = login.json()["token"]
        os.environ["CLAB_TOKEN"] = token

        from call_api import call_api
        result = json.loads(call_api({"api_name":"clab","method":"GET","path":"/api/v1/version"}))
        assert result["status_code"] == 200
        assert "versionInfo" in result["body"] or "version" in str(result["body"])
        del os.environ["CLAB_TOKEN"]


# ---------------------------------------------------------------------------
# TestBuildTopologyYaml
# ---------------------------------------------------------------------------

class TestBuildTopologyYaml:
    """P0 fix: tool to build CLAB topology YAML from snapshot DB"""

    def _make_topo_db(self, tmp_path):
        """In-memory DB with devices + topology_links like real data"""
        db_file = tmp_path / "main.duckdb"
        con = duckdb.connect(str(db_file))
        con.execute("CREATE SCHEMA netops")
        con.execute("""
            CREATE TABLE netops.devices (
                hostname VARCHAR PRIMARY KEY, platform VARCHAR, ip_address VARCHAR, role VARCHAR, site VARCHAR
            )
        """)
        con.execute("""
            CREATE TABLE netops.topology_links (
                source_device VARCHAR, destination_device VARCHAR,
                source_interface VARCHAR, destination_interface VARCHAR,
                discovery_protocol VARCHAR, link_type VARCHAR, link_status VARCHAR
            )
        """)
        # Real-like data
        for h,p,ip,r in [("R1","juniper_junos","192.168.100.101","border"),
                          ("R2","juniper_junos","192.168.100.102","border"),
                          ("R3","cisco_ios","192.168.100.103","core"),
                          ("R4","cisco_ios","192.168.100.104","core")]:
            con.execute("INSERT INTO netops.devices VALUES (?,?,?,?,?)", [h,p,ip,r,"lab"])
        # Good hostname links
        con.execute("INSERT INTO netops.topology_links VALUES (?,?,?,?,?,?,?)",
                    ["R3","R1","Ethernet0/0","ospf-peer","OSPF","L3","up"])
        con.execute("INSERT INTO netops.topology_links VALUES (?,?,?,?,?,?,?)",
                    ["R4","R2","Ethernet0/0","ospf-peer","OSPF","L3","up"])
        # Bad IP dest link (like real data)
        con.execute("INSERT INTO netops.topology_links VALUES (?,?,?,?,?,?,?)",
                    ["R1","10.1.12.2","BGP:10.1.12.2","BGP:R1","BGP","L3","up"])
        con.close()
        return db_file

    def test_build_topology_yaml_returns_valid_yaml(self, tmp_path):
        db_file = self._make_topo_db(tmp_path)
        from build_topology_yaml import build_topology_yaml
        result = json.loads(build_topology_yaml({"db_path": str(db_file)}))
        assert "yaml" in result or "topology" in result or "error" not in result

    def test_build_topology_yaml_includes_all_devices_as_nodes(self, tmp_path):
        db_file = self._make_topo_db(tmp_path)
        from build_topology_yaml import build_topology_yaml
        result = json.loads(build_topology_yaml({"db_path": str(db_file)}))
        topo = pyyaml.safe_load(result["yaml"])
        nodes = topo["topology"]["nodes"]
        # All devices from netops.devices should be present
        assert "R1" in nodes
        assert "R2" in nodes
        assert "R3" in nodes
        assert "R4" in nodes

    def test_build_topology_yaml_nodes_are_srlinux(self, tmp_path):
        """All nodes use SRL image regardless of production platform"""
        db_file = self._make_topo_db(tmp_path)
        from build_topology_yaml import build_topology_yaml
        result = json.loads(build_topology_yaml({"db_path": str(db_file)}))
        topo = pyyaml.safe_load(result["yaml"])
        # Either defaults or per-node should have srlinux/nokia kind
        defaults = topo["topology"].get("defaults", {})
        kind = defaults.get("kind", "")
        assert "nokia" in kind or "srl" in kind or "srlinux" in kind.lower()

    def test_build_topology_yaml_creates_links_from_ospf(self, tmp_path):
        """OSPF links (which have real interface names) become CLAB links"""
        db_file = self._make_topo_db(tmp_path)
        from build_topology_yaml import build_topology_yaml
        result = json.loads(build_topology_yaml({"db_path": str(db_file)}))
        topo = pyyaml.safe_load(result["yaml"])
        links = topo["topology"].get("links", [])
        assert len(links) >= 1
        # R3-R1 OSPF link should appear
        link_endpoints = [set(lnk["endpoints"]) for lnk in links]
        r3_r1 = any(any("R3" in e for e in ep) and any("R1" in e for e in ep) for ep in link_endpoints)
        assert r3_r1

    def test_build_topology_yaml_resolves_ip_dest_to_hostname(self, tmp_path):
        """IP-only destinations (like 10.1.12.2) are resolved to hostnames when possible"""
        db_file = self._make_topo_db(tmp_path)
        # Add R2's link IP to devices table or parsed_outputs so resolution works
        con = duckdb.connect(str(db_file))
        # Pretend we know 10.1.12.2 is R2 via a helper table or ARP
        # The tool should try to resolve and fall back gracefully
        con.close()
        from build_topology_yaml import build_topology_yaml
        result = json.loads(build_topology_yaml({"db_path": str(db_file)}))
        assert "error" not in result or result.get("yaml")  # at minimum should not crash
        # If R2 can be resolved from IP, check it
        if "yaml" in result:
            assert "10.1.12.2" not in result["yaml"]  # raw IPs should not appear as node names


# ---------------------------------------------------------------------------
# TestExecOnNode
# ---------------------------------------------------------------------------

class TestExecOnNode:
    """P1: exec CLI command on a lab node via CLAB exec API"""

    def test_exec_on_node_posts_to_correct_endpoint(self, tmp_path):
        db_file = _make_registry_db(tmp_path)
        from exec_on_node import exec_on_node
        mock_resp = MagicMock(); mock_resp.status_code=200
        mock_resp.json.return_value = [{"stdout": "SRL R1\n", "returnCode": 0}]
        mock_resp.raise_for_status = MagicMock()
        with patch("httpx.request", return_value=mock_resp) as mock_req:
            result = json.loads(exec_on_node({
                "lab_name": "test-lab", "node": "R1",
                "command": "show version", "db_path": str(db_file),
                "base_url": "http://192.168.100.12:8080"
            }))
        assert mock_req.called
        url = mock_req.call_args[0][1]
        assert "test-lab" in url
        assert "exec" in url
        assert result.get("stdout") is not None or result.get("output") is not None

    def test_exec_on_node_uses_bearer_auth(self, tmp_path):
        db_file = _make_registry_db(tmp_path)
        from exec_on_node import exec_on_node
        mock_resp = MagicMock(); mock_resp.status_code=200
        mock_resp.json.return_value = [{"stdout": "ok", "returnCode": 0}]
        mock_resp.raise_for_status = MagicMock()
        with patch.dict("os.environ", {"CLAB_TOKEN": "bearer-token-abc"}):
            with patch("httpx.request", return_value=mock_resp) as mock_req:
                exec_on_node({"lab_name":"lab","node":"r1","command":"show version","base_url":"http://192.168.100.12:8080"})
        headers = mock_req.call_args[1].get("headers", {})
        assert headers.get("Authorization") == "Bearer bearer-token-abc"

    def test_exec_on_node_returns_error_on_failure(self, tmp_path):
        from exec_on_node import exec_on_node
        with patch("httpx.request", side_effect=Exception("timeout")):
            result = json.loads(exec_on_node({"lab_name":"lab","node":"r1","command":"show version","base_url":"http://x"}))
        assert "error" in result

    @pytest.mark.integration
    def test_exec_on_node_integration_show_version(self):
        """Integration: exec sr_cli show version on R1 in digital-twin lab.
        Requires CLAB_TOKEN env var or will auto-login.
        Skipped if CLAB server is not reachable.
        """
        import os
        import httpx

        # Auto-login if no token
        token = os.environ.get("CLAB_TOKEN", "")
        if not token:
            try:
                r = httpx.post(
                    "http://192.168.100.12:8080/login",
                    json={"username": "admin", "password": "admin"},
                    timeout=5.0,
                )
                token = r.json().get("token", "")
            except Exception:
                pytest.skip("CLAB server not reachable")

        from exec_on_node import exec_on_node
        with patch.dict("os.environ", {"CLAB_TOKEN": token}):
            result = json.loads(exec_on_node({
                "lab_name": "digital-twin",
                "node": "R1",
                "command": "sr_cli show version",
            }))

        assert "error" not in result, f"Got error: {result.get('error')}"
        assert result["return_code"] == 0
        stdout = result["stdout"]
        assert "R1" in stdout or "v25" in stdout or "SR Linux" in stdout


# ---------------------------------------------------------------------------
# TestFixSrlTopology
# ---------------------------------------------------------------------------

class TestFixSrlTopology:
    """Tests for fix_srl_topology tool — workaround for CLAB REST API topology.yml directory bug."""

    def test_fix_srl_topology_builds_correct_content(self):
        """The generated topology.yml content has correct structure."""
        sys.path.insert(0, str(_LAB_TOOLS_DIR))
        from fix_srl_topology import _build_topology_content
        content = _build_topology_content(mac="1a:2b:3c:4d:5e:6f")
        assert "chassis_type" in content
        assert "1a:2b:3c:4d:5e:6f" in content
        assert "slot_configuration" in content
        assert "card_type" in content

    def test_fix_srl_topology_dry_run_returns_plan(self):
        """dry_run=True returns nodes that would be fixed without executing docker commands."""
        sys.path.insert(0, str(_LAB_TOOLS_DIR))
        from fix_srl_topology import fix_srl_topology

        mock_inspect = {"State": {"Pid": 12345}, "NetworkSettings": {"Networks": {"mgmt": {"MacAddress": "aa:bb:cc:dd:ee:ff"}}}}
        with patch("httpx.post") as mock_login, \
             patch("subprocess.run") as mock_run:
            mock_login.return_value = MagicMock(status_code=200)
            mock_login.return_value.json.return_value = {"token": "tok"}
            mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps([mock_inspect]))

            result = json.loads(fix_srl_topology({
                "lab_name": "test-lab",
                "nodes": ["R1"],
                "dry_run": True,
            }))

        assert "error" not in result
        assert result.get("dry_run") is True

    @pytest.mark.integration
    def test_fix_srl_topology_integration_verifies_nodes_operational(self):
        """Integration: verify that digital-twin nodes have functional management plane.
        Uses exec_on_node to check each node responds to 'sr_cli show version'.
        """
        import os
        import httpx

        token = os.environ.get("CLAB_TOKEN", "")
        if not token:
            try:
                r = httpx.post(
                    "http://192.168.100.12:8080/login",
                    json={"username": "admin", "password": "admin"},
                    timeout=5.0,
                )
                token = r.json().get("token", "")
            except Exception:
                pytest.skip("CLAB server not reachable")

        from exec_on_node import exec_on_node
        nodes = ["R1", "R2", "R3", "R4", "SW1", "SW2"]
        results = {}
        with patch.dict("os.environ", {"CLAB_TOKEN": token}):
            for node in nodes:
                r = json.loads(exec_on_node({
                    "lab_name": "digital-twin",
                    "node": node,
                    "command": "sr_cli show version",
                }))
                results[node] = r

        failed = [n for n, r in results.items() if "error" in r or r.get("return_code", 1) != 0]
        assert not failed, f"Nodes not operational: {failed}\nDetails: {results}"
