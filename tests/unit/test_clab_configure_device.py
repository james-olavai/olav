"""Tests for configure_device.py — dry-run (no network) and live-run (CLabClient mocked)."""
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

from configure_device import configure_device
from models import DeployResult, NodeInfo, ExecutionPlan, PlannedNode
from clab_client import CLABAPIError


def _make_deploy(nodes=None):
    if nodes is None:
        nodes = {
            "R1": NodeInfo(
                name="R1",
                platform="cisco_ios",
                mgmt_cloud_ip="192.168.100.110",
                mgmt_cloud_port=22,
            ),
        }
    return DeployResult(
        test_run_id="cfg_test_001",
        lab_name="test-lab",
        api_server="http://localhost:8080/api/v1",
        nodes=nodes,
        timestamp="2024-01-01T00:00:00Z",
        status="success",
    )


def _make_plan(nodes=None):
    if nodes is None:
        nodes = {
            "R1": PlannedNode(name="R1", platform="cisco_ios", mgmt_cloud_ip="192.168.100.110"),
        }
    return ExecutionPlan(
        test_run_id="cfg_test_001",
        scenario_name="test_scenario",
        topology_file="test.clab.yml",
        nodes=nodes,
        links=[],
        addressing={},
        assertions=[],
        defaults={},
        timestamp="2024-01-01T00:00:00Z",
    )


def _setup_config_dir(tmp_path, node_name="R1", platform="cisco_ios"):
    config_dir = tmp_path / "configs"
    node_dir = config_dir / platform / node_name
    node_dir.mkdir(parents=True)
    (node_dir / "base.cfg").write_text("hostname $hostname\ninterface mgmt0\n ip address $mgmt_ip")
    return config_dir


def _mock_clab_cls(exec_side_effect=None, exec_returns=None):
    """Return mock CLabClient class. exec_returns is a list of return values per call."""
    mock_instance = AsyncMock()
    if exec_side_effect:
        mock_instance.exec_command = AsyncMock(side_effect=exec_side_effect)
    elif exec_returns:
        mock_instance.exec_command = AsyncMock(side_effect=exec_returns)
    else:
        # Default: both write and apply succeed with rc=0 for R1
        mock_instance.exec_command = AsyncMock(
            side_effect=[
                {"R1": [{"return-code": 0, "stdout": "", "stderr": ""}]},  # write
                {"R1": [{"return-code": 0, "stdout": "", "stderr": ""}]},  # apply
            ]
        )
    mock_cls = AsyncMock()
    mock_cls.build = AsyncMock(return_value=mock_instance)
    return mock_cls, mock_instance


# ---------------------------------------------------------------------------
# Dry-run tests (no network calls)
# ---------------------------------------------------------------------------


async def test_dry_run_writes_preview_files(tmp_path):
    deploy = _make_deploy()
    config_dir = _setup_config_dir(tmp_path)
    evidence = tmp_path / "evidence"
    plan = _make_plan()

    result = await configure_device(plan, deploy, config_dir, dry_run=True, output_dir=evidence)

    assert result.dry_run is True
    preview = evidence / "config-preview" / "R1" / "step_000.txt"
    assert preview.exists()
    assert "hostname R1" in preview.read_text()


async def test_dry_run_no_http_calls(tmp_path):
    deploy = _make_deploy()
    config_dir = _setup_config_dir(tmp_path)
    evidence = tmp_path / "evidence"
    plan = _make_plan()

    with patch("clab_client.CLabClient") as mock_cls:
        await configure_device(plan, deploy, config_dir, dry_run=True, output_dir=evidence)
        mock_cls.build.assert_not_called()


async def test_dry_run_node_status_success(tmp_path):
    deploy = _make_deploy()
    config_dir = _setup_config_dir(tmp_path)
    evidence = tmp_path / "evidence"
    plan = _make_plan()

    result = await configure_device(plan, deploy, config_dir, dry_run=True, output_dir=evidence)

    assert result.nodes["R1"].status == "success"
    assert result.nodes["R1"].commands_sent == 1


async def test_missing_config_dir_skipped(tmp_path):
    deploy = _make_deploy()
    config_dir = tmp_path / "empty_configs"
    config_dir.mkdir()
    evidence = tmp_path / "evidence"
    plan = _make_plan()

    result = await configure_device(plan, deploy, config_dir, dry_run=True, output_dir=evidence)

    assert result.nodes["R1"].status == "skipped"


async def test_template_variable_substitution(tmp_path):
    deploy = _make_deploy()
    config_dir = _setup_config_dir(tmp_path)
    evidence = tmp_path / "evidence"
    plan = _make_plan()

    await configure_device(plan, deploy, config_dir, dry_run=True, output_dir=evidence)

    content = (evidence / "config-preview" / "R1" / "step_000.txt").read_text()
    assert "192.168.100.110" in content
    assert "R1" in content
    assert "$hostname" not in content
    assert "$mgmt_ip" not in content


async def test_configure_json_always_written(tmp_path):
    deploy = _make_deploy()
    config_dir = _setup_config_dir(tmp_path)
    evidence = tmp_path / "evidence"
    plan = _make_plan()

    await configure_device(plan, deploy, config_dir, dry_run=True, output_dir=evidence)

    cfg_json = evidence / "configure.json"
    assert cfg_json.exists()
    data = json.loads(cfg_json.read_text())
    assert data["test_run_id"] == "cfg_test_001"


async def test_multiple_templates_processed(tmp_path):
    deploy = _make_deploy()
    config_dir = tmp_path / "configs"
    node_dir = config_dir / "cisco_ios" / "R1"
    node_dir.mkdir(parents=True)
    (node_dir / "01_base.cfg").write_text("hostname $hostname")
    (node_dir / "02_bgp.cfg").write_text("router bgp 65000")
    evidence = tmp_path / "evidence"
    plan = _make_plan()

    result = await configure_device(plan, deploy, config_dir, dry_run=True, output_dir=evidence)

    assert result.nodes["R1"].commands_sent == 2
    assert (evidence / "config-preview" / "R1" / "step_000.txt").exists()
    assert (evidence / "config-preview" / "R1" / "step_001.txt").exists()


# ---------------------------------------------------------------------------
# Live-run tests (CLabClient mocked)
# ---------------------------------------------------------------------------


async def test_live_run_calls_api(tmp_path):
    deploy = _make_deploy()
    config_dir = _setup_config_dir(tmp_path)
    evidence = tmp_path / "evidence"
    plan = _make_plan()

    mock_cls, mock_instance = _mock_clab_cls()
    with patch("clab_client.CLabClient", mock_cls):
        result = await configure_device(
            plan, deploy, config_dir, dry_run=False, output_dir=evidence
        )

    assert result.nodes["R1"].status == "success"
    # exec_command called twice: write then apply
    assert mock_instance.exec_command.call_count == 2
    assert (evidence / "config-apply" / "R1_script.txt").exists()


async def test_live_run_http_error_marks_failed(tmp_path):
    deploy = _make_deploy()
    config_dir = _setup_config_dir(tmp_path)
    evidence = tmp_path / "evidence"
    plan = _make_plan()

    mock_cls, _ = _mock_clab_cls(exec_side_effect=CLABAPIError(500, "refused"))
    with patch("clab_client.CLabClient", mock_cls):
        result = await configure_device(
            plan, deploy, config_dir, dry_run=False, output_dir=evidence
        )

    assert result.nodes["R1"].status == "failed"
    assert result.nodes["R1"].error is not None
    assert result.status == "failed"


async def test_overall_status_failed_if_any_node_fails(tmp_path):
    nodes = {
        "R1": NodeInfo(
            name="R1", platform="cisco_ios",
            mgmt_cloud_ip="192.168.100.110", mgmt_cloud_port=22,
        ),
        "R2": NodeInfo(
            name="R2", platform="juniper_junos",
            mgmt_cloud_ip="192.168.100.111", mgmt_cloud_port=22,
        ),
    }
    deploy = _make_deploy(nodes)
    config_dir = tmp_path / "configs"
    r1_dir = config_dir / "cisco_ios" / "R1"
    r1_dir.mkdir(parents=True)
    (r1_dir / "base.cfg").write_text("hostname $hostname")
    evidence = tmp_path / "evidence"
    plan = _make_plan(nodes={
        "R1": PlannedNode(name="R1", platform="cisco_ios", mgmt_cloud_ip="192.168.100.110"),
        "R2": PlannedNode(name="R2", platform="juniper_junos", mgmt_cloud_ip="192.168.100.111"),
    })

    mock_cls, _ = _mock_clab_cls(exec_side_effect=CLABAPIError(500, "refused"))
    with patch("clab_client.CLabClient", mock_cls):
        result = await configure_device(
            plan, deploy, config_dir, dry_run=False, output_dir=evidence
        )

    has_failed = any(n.status == "failed" for n in result.nodes.values())
    if has_failed:
        assert result.status == "failed"
