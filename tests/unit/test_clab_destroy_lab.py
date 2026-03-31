"""Tests for destroy_lab.py — uses CLabClient (mocked via clab_client.CLabClient)."""
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

from destroy_lab import destroy_lab
from models import DeployResult, NodeInfo

# ---------------------------------------------------------------------------
# CLABAPIError — imported from skill scripts path
# ---------------------------------------------------------------------------
from clab_client import CLABAPIError


def _make_deploy(nodes=None, lab_name="test-lab"):
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
        test_run_id="destroy_test_001",
        lab_name=lab_name,
        api_server="http://localhost:8080/api/v1",
        nodes=nodes,
        timestamp="2024-01-01T00:00:00Z",
        status="success",
    )


def _mock_clab_client(destroy_exc=None, inspect_exc=None, inspect_return=None):
    """Return (mock_cls, mock_instance) for patching clab_client.CLabClient."""
    mock_instance = AsyncMock()

    if destroy_exc:
        mock_instance.destroy = AsyncMock(side_effect=destroy_exc)
    else:
        mock_instance.destroy = AsyncMock(return_value={})

    if inspect_exc:
        mock_instance.inspect = AsyncMock(side_effect=inspect_exc)
    elif inspect_return is not None:
        mock_instance.inspect = AsyncMock(return_value=inspect_return)
    else:
        # Default: 404 after destroy (lab gone)
        mock_instance.inspect = AsyncMock(side_effect=CLABAPIError(404, "not found"))

    mock_cls = AsyncMock()
    mock_cls.build = AsyncMock(return_value=mock_instance)
    return mock_cls, mock_instance


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_successful_destroy(tmp_path):
    deploy = _make_deploy()
    mock_cls, _ = _mock_clab_client()
    with patch("clab_client.CLabClient", mock_cls):
        result = await destroy_lab(deploy, output_dir=tmp_path)

    assert result.status == "success"
    assert result.lab_name == "test-lab"


async def test_containers_removed_list(tmp_path):
    deploy = _make_deploy()
    mock_cls, _ = _mock_clab_client()
    with patch("clab_client.CLabClient", mock_cls):
        result = await destroy_lab(deploy, output_dir=tmp_path)

    assert "R1" in result.containers_removed


async def test_destroy_json_written(tmp_path):
    deploy = _make_deploy()
    mock_cls, _ = _mock_clab_client()
    with patch("clab_client.CLabClient", mock_cls):
        await destroy_lab(deploy, output_dir=tmp_path)

    assert (tmp_path / "destroy.json").exists()
    data = json.loads((tmp_path / "destroy.json").read_text())
    assert data["status"] == "success"


async def test_delete_failure_returns_failed(tmp_path):
    """CLABAPIError on destroy → status=failed."""
    deploy = _make_deploy()
    mock_cls, _ = _mock_clab_client(destroy_exc=CLABAPIError(500, "internal error"))
    with patch("clab_client.CLabClient", mock_cls):
        result = await destroy_lab(deploy, output_dir=tmp_path)

    assert result.status == "failed"
    assert result.error is not None


async def test_http_error_returns_failed(tmp_path):
    """Generic exception on destroy → status=failed."""
    deploy = _make_deploy()
    mock_cls, _ = _mock_clab_client(destroy_exc=ConnectionError("refused"))
    with patch("clab_client.CLabClient", mock_cls):
        result = await destroy_lab(deploy, output_dir=tmp_path)

    assert result.status == "failed"
    assert result.error is not None


async def test_lab_still_exists_after_destroy_is_partial(tmp_path):
    """inspect() returns 200 (not 404) after destroy → status=partial."""
    deploy = _make_deploy(lab_name="mylab")
    mock_cls, _ = _mock_clab_client(inspect_return={"containers": [{"name": "clab-mylab-R1"}]})
    with patch("clab_client.CLabClient", mock_cls):
        result = await destroy_lab(deploy, output_dir=tmp_path)

    assert result.status == "partial"


async def test_no_residuals_means_success(tmp_path):
    """inspect() returns 404 after destroy → success, no residuals."""
    deploy = _make_deploy()
    mock_cls, _ = _mock_clab_client()  # default: inspect raises 404
    with patch("clab_client.CLabClient", mock_cls):
        result = await destroy_lab(deploy, output_dir=tmp_path)

    assert result.status == "success"
    assert result.residual_resources == []


async def test_destroy_json_written_on_failure(tmp_path):
    deploy = _make_deploy()
    mock_cls, _ = _mock_clab_client(destroy_exc=ConnectionError("timeout"))
    with patch("clab_client.CLabClient", mock_cls):
        await destroy_lab(deploy, output_dir=tmp_path)

    assert (tmp_path / "destroy.json").exists()
    data = json.loads((tmp_path / "destroy.json").read_text())
    assert data["status"] == "failed"


async def test_client_build_failure_returns_failed(tmp_path):
    """CLabClient.build() failing → result.status=failed, error set."""
    deploy = _make_deploy()
    mock_cls = AsyncMock()
    mock_cls.build = AsyncMock(side_effect=RuntimeError("registry bootstrap failed"))
    with patch("clab_client.CLabClient", mock_cls):
        result = await destroy_lab(deploy, output_dir=tmp_path)

    assert result.status == "failed"
    assert "registry bootstrap failed" in result.error
