"""Tests for deploy_lab.py — uses CLabClient (mocked via clab_client.CLabClient)."""
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

_SKILL_DIR = (
    Path(__file__).resolve().parents[2] / ".olav" / "workspace" / "ops" / "lab"
)
if str(_SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(_SKILL_DIR / "scripts"))

from deploy_lab import deploy_lab
from models import ExecutionPlan, NodeInfo, PlannedNode
from clab_client import CLABAPIError


def _make_plan(nodes=None):
    if nodes is None:
        nodes = {
            "R1": PlannedNode(name="R1", platform="cisco_ios", mgmt_cloud_ip="192.168.100.110"),
            "R2": PlannedNode(name="R2", platform="juniper_junos", mgmt_cloud_ip="192.168.100.111"),
        }
    return ExecutionPlan(
        test_run_id="abc12345_test",
        scenario_name="test_scenario",
        topology_file="test.clab.yml",
        nodes=nodes,
        links=[],
        addressing={},
        assertions=[],
        defaults={},
        timestamp="2024-01-01T00:00:00Z",
    )


def _mock_clab_cls(deploy_return=None, deploy_exc=None):
    """Return mock CLabClient class for patching clab_client.CLabClient."""
    mock_instance = AsyncMock()
    if deploy_exc:
        mock_instance.deploy = AsyncMock(side_effect=deploy_exc)
    else:
        # CLAB API returns {lab_name: [container_list]}
        default = {"lab123": []} if deploy_return is None else deploy_return
        mock_instance.deploy = AsyncMock(return_value=default)
    mock_cls = AsyncMock()
    mock_cls.build = AsyncMock(return_value=mock_instance)
    return mock_cls, mock_instance


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_successful_deploy(tmp_path):
    plan = _make_plan()
    mock_cls, _ = _mock_clab_cls({"lab123": []})
    with patch("clab_client.CLabClient", mock_cls):
        result = await deploy_lab(plan, evidence_dir=tmp_path)

    assert result.status == "success"
    assert result.lab_name == "lab123"
    assert result.test_run_id == "abc12345_test"


async def test_nodes_match_plan(tmp_path):
    plan = _make_plan()
    mock_cls, _ = _mock_clab_cls({"lab1": []})
    with patch("clab_client.CLabClient", mock_cls):
        result = await deploy_lab(plan, evidence_dir=tmp_path)

    assert len(result.nodes) == 2
    assert result.nodes["R1"].mgmt_cloud_ip == "192.168.100.110"
    assert result.nodes["R2"].mgmt_cloud_ip == "192.168.100.111"
    assert result.nodes["R1"].platform == "cisco_ios"


async def test_deploy_json_written_on_success(tmp_path):
    plan = _make_plan()
    mock_cls, _ = _mock_clab_cls({"lab1": []})
    with patch("clab_client.CLabClient", mock_cls):
        await deploy_lab(plan, evidence_dir=tmp_path)

    assert (tmp_path / "deploy.json").exists()
    data = json.loads((tmp_path / "deploy.json").read_text())
    assert data["status"] == "success"


async def test_deploy_json_written_on_failure(tmp_path):
    plan = _make_plan()
    mock_cls, _ = _mock_clab_cls(deploy_exc=CLABAPIError(500, "server error"))
    with patch("clab_client.CLabClient", mock_cls):
        await deploy_lab(plan, evidence_dir=tmp_path)

    assert (tmp_path / "deploy.json").exists()
    data = json.loads((tmp_path / "deploy.json").read_text())
    assert data["status"] == "failed"


async def test_http_error_returns_failed(tmp_path):
    plan = _make_plan()
    mock_cls, _ = _mock_clab_cls(deploy_exc=CLABAPIError(500, "internal server error"))
    with patch("clab_client.CLabClient", mock_cls):
        result = await deploy_lab(plan, evidence_dir=tmp_path)

    assert result.status == "failed"
    assert result.error is not None


async def test_connection_error_returns_failed(tmp_path):
    plan = _make_plan()
    mock_cls, _ = _mock_clab_cls(deploy_exc=ConnectionError("connection refused"))
    with patch("clab_client.CLabClient", mock_cls):
        result = await deploy_lab(plan, evidence_dir=tmp_path)

    assert result.status == "failed"
    assert result.error is not None


async def test_default_api_server(tmp_path):
    from models import DEFAULT_API_SERVER
    plan = _make_plan()
    mock_cls, _ = _mock_clab_cls({"lab1": []})
    with patch("clab_client.CLabClient", mock_cls):
        result = await deploy_lab(plan, evidence_dir=tmp_path)

    assert result.api_server == DEFAULT_API_SERVER


async def test_custom_api_server(tmp_path):
    plan = _make_plan()
    mock_cls, _ = _mock_clab_cls({"lab1": []})
    with patch("clab_client.CLabClient", mock_cls):
        result = await deploy_lab(plan, api_server="http://custom:9090", evidence_dir=tmp_path)

    assert result.api_server == "http://custom:9090"


async def test_lab_name_extracted_from_response_key(tmp_path):
    """deploy() response is {<lab_name>: [nodes]}; first key is the lab name."""
    plan = _make_plan()
    mock_cls, _ = _mock_clab_cls({"my-actual-lab": [{"name": "r1"}]})
    with patch("clab_client.CLabClient", mock_cls):
        result = await deploy_lab(plan, evidence_dir=tmp_path)

    assert result.lab_name == "my-actual-lab"


async def test_empty_response_falls_back_to_scenario_name(tmp_path):
    """Empty deploy response → lab_name falls back to plan.scenario_name."""
    plan = _make_plan()
    mock_cls, _ = _mock_clab_cls({})  # empty dict
    with patch("clab_client.CLabClient", mock_cls):
        result = await deploy_lab(plan, evidence_dir=tmp_path)

    assert result.lab_name == plan.scenario_name


async def test_empty_nodes_plan(tmp_path):
    plan = _make_plan(nodes={})
    mock_cls, _ = _mock_clab_cls({"empty-lab": []})
    with patch("clab_client.CLabClient", mock_cls):
        result = await deploy_lab(plan, evidence_dir=tmp_path)

    assert result.status == "success"
    assert len(result.nodes) == 0


async def test_client_build_failure_returns_failed(tmp_path):
    plan = _make_plan()
    mock_cls = AsyncMock()
    mock_cls.build = AsyncMock(side_effect=RuntimeError("registry bootstrap failed"))
    with patch("clab_client.CLabClient", mock_cls):
        result = await deploy_lab(plan, evidence_dir=tmp_path)

    assert result.status == "failed"
    assert result.error is not None
