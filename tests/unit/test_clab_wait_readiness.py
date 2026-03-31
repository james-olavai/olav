"""Tests for wait_readiness.py — uses CLabClient.exec_command('hostname')."""
from __future__ import annotations

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

from models import DeployResult, NodeInfo, ReadinessResult
from wait_readiness import wait_readiness

from clab_client import CLABAPIError


def _make_deploy(nodes: dict[str, NodeInfo] | None = None) -> DeployResult:
    if nodes is None:
        nodes = {
            "R1": NodeInfo(
                name="R1",
                platform="cisco_ios",
                mgmt_cloud_ip="192.168.100.110",
            ),
        }
    return DeployResult(
        test_run_id="test-run-001",
        lab_name="lab1",
        api_server="http://192.168.100.12:8080/api/v1",
        nodes=nodes,
        timestamp="2026-01-01T00:00:00Z",
        status="success",
    )


def _exec_ok(*node_names) -> dict:
    """Return exec response with rc=0 for all named nodes."""
    return {n: [{"return-code": 0, "stdout": n, "stderr": ""}] for n in node_names}


def _exec_fail(*node_names) -> dict:
    """Return exec response with rc=1 for all named nodes."""
    return {n: [{"return-code": 1, "stdout": "", "stderr": "error"}] for n in node_names}


def _mock_clab_cls(exec_side_effect=None, exec_return=None):
    """Return mock CLabClient class."""
    mock_instance = AsyncMock()
    if exec_side_effect is not None:
        mock_instance.exec_command = AsyncMock(side_effect=exec_side_effect)
    else:
        mock_instance.exec_command = AsyncMock(return_value=exec_return or {})
    mock_cls = AsyncMock()
    mock_cls.build = AsyncMock(return_value=mock_instance)
    return mock_cls, mock_instance


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_wait_readiness_single_node_success(tmp_path):
    deploy = _make_deploy()
    mock_cls, _ = _mock_clab_cls(exec_return=_exec_ok("R1"))
    with patch("clab_client.CLabClient", mock_cls):
        result = await wait_readiness(
            deploy, ssh_timeout=5, protocol_timeout=5, evidence_dir=tmp_path
        )

    assert result.status == "success"
    assert result.test_run_id == "test-run-001"
    assert "R1" in result.nodes
    assert result.nodes["R1"].ssh_reachable is True
    assert result.nodes["R1"].protocol_converged is True


async def test_wait_readiness_writes_evidence_json(tmp_path):
    deploy = _make_deploy()
    mock_cls, _ = _mock_clab_cls(exec_return=_exec_ok("R1"))
    with patch("clab_client.CLabClient", mock_cls):
        await wait_readiness(deploy, ssh_timeout=5, protocol_timeout=5, evidence_dir=tmp_path)

    evidence_file = tmp_path / "readiness.json"
    assert evidence_file.exists()
    data = json.loads(evidence_file.read_text())
    assert data["status"] == "success"
    assert "R1" in data["nodes"]


async def test_wait_readiness_timeout_on_exec_failure(tmp_path):
    """exec_command always raises → timeout, ssh_reachable=False."""
    deploy = _make_deploy()
    mock_cls, _ = _mock_clab_cls(exec_side_effect=CLABAPIError(500, "exec failed"))
    with patch("clab_client.CLabClient", mock_cls):
        result = await wait_readiness(
            deploy, ssh_timeout=1, protocol_timeout=1, evidence_dir=tmp_path
        )

    assert result.status == "timeout"
    assert result.nodes["R1"].ssh_reachable is False
    assert result.nodes["R1"].protocol_converged is False
    assert result.nodes["R1"].error is not None


async def test_wait_readiness_timeout_writes_evidence(tmp_path):
    deploy = _make_deploy()
    mock_cls, _ = _mock_clab_cls(exec_side_effect=CLABAPIError(500, "exec failed"))
    with patch("clab_client.CLabClient", mock_cls):
        await wait_readiness(deploy, ssh_timeout=1, protocol_timeout=1, evidence_dir=tmp_path)

    evidence_file = tmp_path / "readiness.json"
    assert evidence_file.exists()
    data = json.loads(evidence_file.read_text())
    assert data["status"] == "timeout"


async def test_wait_readiness_multiple_nodes(tmp_path):
    nodes = {
        "R1": NodeInfo(name="R1", platform="cisco_ios", mgmt_cloud_ip="192.168.100.110"),
        "R2": NodeInfo(name="R2", platform="juniper_junos", mgmt_cloud_ip="192.168.100.111"),
    }
    deploy = _make_deploy(nodes=nodes)
    mock_cls, _ = _mock_clab_cls(exec_return=_exec_ok("R1", "R2"))
    with patch("clab_client.CLabClient", mock_cls):
        result = await wait_readiness(
            deploy, ssh_timeout=5, protocol_timeout=5, evidence_dir=tmp_path
        )

    assert result.status == "success"
    assert "R1" in result.nodes
    assert "R2" in result.nodes
    assert result.nodes["R1"].ssh_reachable is True
    assert result.nodes["R2"].ssh_reachable is True


async def test_wait_readiness_retries_with_backoff(tmp_path):
    """exec_command fails twice, then succeeds → success, retries>=2."""
    deploy = _make_deploy()
    call_count = 0

    async def _fail_then_succeed(lab_name, cmd, timeout=None):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise CLABAPIError(500, "not ready")
        return _exec_ok("R1")

    mock_instance = AsyncMock()
    mock_instance.exec_command = AsyncMock(side_effect=_fail_then_succeed)
    mock_cls = AsyncMock()
    mock_cls.build = AsyncMock(return_value=mock_instance)

    with patch("clab_client.CLabClient", mock_cls):
        result = await wait_readiness(
            deploy, ssh_timeout=30, protocol_timeout=5, evidence_dir=tmp_path
        )

    assert result.status == "success"
    assert result.nodes["R1"].ssh_reachable is True
    assert result.nodes["R1"].retries >= 2


async def test_wait_readiness_duration_ms_positive(tmp_path):
    deploy = _make_deploy()
    mock_cls, _ = _mock_clab_cls(exec_return=_exec_ok("R1"))
    with patch("clab_client.CLabClient", mock_cls):
        result = await wait_readiness(
            deploy, ssh_timeout=5, protocol_timeout=5, evidence_dir=tmp_path
        )

    assert result.nodes["R1"].duration_ms >= 0


async def test_wait_readiness_no_evidence_dir():
    deploy = _make_deploy()
    mock_cls, _ = _mock_clab_cls(exec_return=_exec_ok("R1"))
    with patch("clab_client.CLabClient", mock_cls):
        result = await wait_readiness(deploy, ssh_timeout=5, protocol_timeout=5, evidence_dir=None)

    assert result.status == "success"
    assert isinstance(result, ReadinessResult)


async def test_wait_readiness_result_has_timestamp(tmp_path):
    deploy = _make_deploy()
    mock_cls, _ = _mock_clab_cls(exec_return=_exec_ok("R1"))
    with patch("clab_client.CLabClient", mock_cls):
        result = await wait_readiness(
            deploy, ssh_timeout=5, protocol_timeout=5, evidence_dir=tmp_path
        )

    assert result.timestamp is not None
    assert len(result.timestamp) > 0


async def test_wait_readiness_mixed_node_outcomes(tmp_path):
    """One node responds, one is absent from exec response → one success, one timeout."""
    nodes = {
        "OK": NodeInfo(name="OK", platform="cisco_ios", mgmt_cloud_ip="192.168.100.110"),
        "FAIL": NodeInfo(name="FAIL", platform="cisco_ios", mgmt_cloud_ip="192.168.100.111"),
    }
    deploy = _make_deploy(nodes=nodes)
    # exec returns result only for "OK", not "FAIL"
    mock_cls, _ = _mock_clab_cls(exec_return={"OK": [{"return-code": 0, "stdout": "OK"}]})
    with patch("clab_client.CLabClient", mock_cls):
        result = await wait_readiness(
            deploy, ssh_timeout=1, protocol_timeout=1, evidence_dir=tmp_path
        )

    assert result.status == "timeout"
    assert result.nodes["OK"].ssh_reachable is True
    assert result.nodes["FAIL"].ssh_reachable is False


async def test_wait_readiness_empty_nodes(tmp_path):
    deploy = _make_deploy(nodes={})
    mock_cls, _ = _mock_clab_cls(exec_return={})
    with patch("clab_client.CLabClient", mock_cls):
        result = await wait_readiness(
            deploy, ssh_timeout=5, protocol_timeout=5, evidence_dir=tmp_path
        )

    assert result.status == "success"
    assert len(result.nodes) == 0


async def test_wait_readiness_client_build_failure(tmp_path):
    """CLabClient.build() fails → all nodes marked failed."""
    deploy = _make_deploy()
    mock_cls = AsyncMock()
    mock_cls.build = AsyncMock(side_effect=RuntimeError("registry bootstrap failed"))
    with patch("clab_client.CLabClient", mock_cls):
        result = await wait_readiness(
            deploy, ssh_timeout=5, protocol_timeout=5, evidence_dir=tmp_path
        )

    assert result.status == "failed"
    assert "R1" in result.nodes
    assert result.nodes["R1"].ssh_reachable is False
