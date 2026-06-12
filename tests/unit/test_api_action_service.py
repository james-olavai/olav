"""Tests for API Action Service (API-RW-3 + API-RW-4).

Covers: staging, approval, rejection, execution, and RBAC integration.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# ── Imports & construction ────────────────────────────────────────────────────


def test_api_action_service_importable() -> None:
    from olav.core.api_action_service import ApiActionService

    assert ApiActionService is not None


def test_api_action_request_importable() -> None:
    from olav.core.api_action_service import ApiActionRequest

    req = ApiActionRequest(
        domain="netops",
        operation_id="createVlan",
        method="POST",
        path="/api/v1/vlans",
    )
    assert req.domain == "netops"
    assert req.intent == "write"
    assert req.approval_policy == "required"
    assert req.status == "pending"


# ── Stage flow (API-RW-3) ────────────────────────────────────────────────────


def test_stage_request_creates_pending_file(tmp_path: Path) -> None:
    from olav.core.api_action_service import ApiActionRequest, ApiActionService

    svc = ApiActionService(staging_dir=tmp_path)
    req = ApiActionRequest(
        domain="netops",
        operation_id="createVlan",
        method="POST",
        path="/api/v1/vlans",
    )
    svc.stage_request(req, role="user")

    assert svc.staging_file.exists()
    lines = svc.staging_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1


def test_stage_request_returns_staged_status(tmp_path: Path) -> None:
    from olav.core.api_action_service import ApiActionRequest, ApiActionService

    svc = ApiActionService(staging_dir=tmp_path)
    req = ApiActionRequest(
        domain="netops",
        operation_id="createVlan",
        method="POST",
        path="/api/v1/vlans",
    )
    result = svc.stage_request(req, role="user")

    assert result["status"] == "staged"
    assert result["request_id"] == req.request_id
    assert "staging_file" in result


def test_stage_request_validates_empty_domain(tmp_path: Path) -> None:
    from olav.core.api_action_service import ApiActionRequest, ApiActionService

    svc = ApiActionService(staging_dir=tmp_path)
    req = ApiActionRequest(
        domain="",
        operation_id="createVlan",
        method="POST",
        path="/api/v1/vlans",
    )
    with pytest.raises(ValueError, match="domain"):
        svc.stage_request(req, role="admin")


def test_stage_request_validates_empty_operation_id(tmp_path: Path) -> None:
    from olav.core.api_action_service import ApiActionRequest, ApiActionService

    svc = ApiActionService(staging_dir=tmp_path)
    req = ApiActionRequest(
        domain="netops",
        operation_id="",
        method="POST",
        path="/api/v1/vlans",
    )
    with pytest.raises(ValueError, match="operation_id"):
        svc.stage_request(req, role="admin")


def test_list_pending_returns_staged_requests(tmp_path: Path) -> None:
    from olav.core.api_action_service import ApiActionRequest, ApiActionService

    svc = ApiActionService(staging_dir=tmp_path)
    req = ApiActionRequest(
        domain="netops",
        operation_id="createVlan",
        method="POST",
        path="/api/v1/vlans",
    )
    svc.stage_request(req, role="user")

    pending = svc.list_pending()
    assert len(pending) == 1
    assert pending[0]["request_id"] == req.request_id
    assert pending[0]["domain"] == "netops"


# ── Approve flow (API-RW-3) ──────────────────────────────────────────────────


def test_approve_request_moves_to_approved(tmp_path: Path) -> None:
    from olav.core.api_action_service import ApiActionRequest, ApiActionService

    svc = ApiActionService(staging_dir=tmp_path)
    req = ApiActionRequest(
        domain="netops",
        operation_id="createVlan",
        method="POST",
        path="/api/v1/vlans",
    )
    svc.stage_request(req, role="user")
    svc.approve_request(req.request_id, role="admin")

    approved = svc.list_approved()
    assert len(approved) == 1
    assert approved[0]["request_id"] == req.request_id
    assert approved[0]["status"] == "approved"


def test_approve_request_removes_from_pending(tmp_path: Path) -> None:
    from olav.core.api_action_service import ApiActionRequest, ApiActionService

    svc = ApiActionService(staging_dir=tmp_path)
    req = ApiActionRequest(
        domain="netops",
        operation_id="createVlan",
        method="POST",
        path="/api/v1/vlans",
    )
    svc.stage_request(req, role="user")
    svc.approve_request(req.request_id, role="admin")

    pending = svc.list_pending()
    assert len(pending) == 0


def test_approve_nonexistent_raises_key_error(tmp_path: Path) -> None:
    from olav.core.api_action_service import ApiActionService

    svc = ApiActionService(staging_dir=tmp_path)
    with pytest.raises(KeyError, match="no-such-id"):
        svc.approve_request("no-such-id", role="admin")


# ── Reject flow ──────────────────────────────────────────────────────────────


def test_reject_request_removes_from_pending(tmp_path: Path) -> None:
    from olav.core.api_action_service import ApiActionRequest, ApiActionService

    svc = ApiActionService(staging_dir=tmp_path)
    req = ApiActionRequest(
        domain="netops",
        operation_id="deleteVlan",
        method="DELETE",
        path="/api/v1/vlans/100",
    )
    svc.stage_request(req, role="user")
    svc.reject_request(req.request_id, role="admin", reason="too risky")

    pending = svc.list_pending()
    assert len(pending) == 0


def test_reject_returns_reason(tmp_path: Path) -> None:
    from olav.core.api_action_service import ApiActionRequest, ApiActionService

    svc = ApiActionService(staging_dir=tmp_path)
    req = ApiActionRequest(
        domain="netops",
        operation_id="deleteVlan",
        method="DELETE",
        path="/api/v1/vlans/100",
    )
    svc.stage_request(req, role="user")
    result = svc.reject_request(req.request_id, role="admin", reason="too risky")

    assert result["status"] == "rejected"
    assert result["reason"] == "too risky"


# ── Execute flow (API-RW-3) ──────────────────────────────────────────────────


def test_execute_approved_clears_approved_file(tmp_path: Path) -> None:
    from olav.core.api_action_service import ApiActionRequest, ApiActionService

    svc = ApiActionService(staging_dir=tmp_path)
    req = ApiActionRequest(
        domain="netops",
        operation_id="createVlan",
        method="POST",
        path="/api/v1/vlans",
    )
    svc.stage_request(req, role="user")
    svc.approve_request(req.request_id, role="admin")
    svc.execute_approved()

    assert svc.list_approved() == []


def test_execute_approved_returns_count(tmp_path: Path) -> None:
    from olav.core.api_action_service import ApiActionRequest, ApiActionService

    svc = ApiActionService(staging_dir=tmp_path)
    for i in range(3):
        req = ApiActionRequest(
            domain="netops",
            operation_id=f"op{i}",
            method="POST",
            path=f"/api/v1/resource/{i}",
        )
        svc.stage_request(req, role="user")
        svc.approve_request(req.request_id, role="admin")

    result = svc.execute_approved()
    assert result["executed"] == 3
    assert result["errors"] == []


# ── RBAC integration (API-RW-4) ──────────────────────────────────────────────


def test_stage_denied_for_readonly(tmp_path: Path) -> None:
    from olav.core.api_action_service import ApiActionRequest, ApiActionService

    svc = ApiActionService(staging_dir=tmp_path)
    req = ApiActionRequest(
        domain="netops",
        operation_id="createVlan",
        method="POST",
        path="/api/v1/vlans",
    )
    result = svc.stage_request(req, role="readonly")

    assert result["status"] == "denied"
    assert "readonly" in result["reason"]


def test_stage_allowed_for_user(tmp_path: Path) -> None:
    from olav.core.api_action_service import ApiActionRequest, ApiActionService

    svc = ApiActionService(staging_dir=tmp_path)
    req = ApiActionRequest(
        domain="netops",
        operation_id="createVlan",
        method="POST",
        path="/api/v1/vlans",
    )
    result = svc.stage_request(req, role="user")
    assert result["status"] == "staged"


def test_stage_allowed_for_admin(tmp_path: Path) -> None:
    from olav.core.api_action_service import ApiActionRequest, ApiActionService

    svc = ApiActionService(staging_dir=tmp_path)
    req = ApiActionRequest(
        domain="netops",
        operation_id="createVlan",
        method="POST",
        path="/api/v1/vlans",
    )
    result = svc.stage_request(req, role="admin")
    assert result["status"] == "staged"


def test_approve_denied_for_user(tmp_path: Path) -> None:
    from olav.core.api_action_service import ApiActionRequest, ApiActionService

    svc = ApiActionService(staging_dir=tmp_path)
    req = ApiActionRequest(
        domain="netops",
        operation_id="createVlan",
        method="POST",
        path="/api/v1/vlans",
    )
    svc.stage_request(req, role="user")
    result = svc.approve_request(req.request_id, role="user")

    assert result["status"] == "denied"
    assert "user" in result["reason"]


def test_approve_denied_for_readonly(tmp_path: Path) -> None:
    from olav.core.api_action_service import ApiActionRequest, ApiActionService

    svc = ApiActionService(staging_dir=tmp_path)
    req = ApiActionRequest(
        domain="netops",
        operation_id="createVlan",
        method="POST",
        path="/api/v1/vlans",
    )
    svc.stage_request(req, role="admin")
    result = svc.approve_request(req.request_id, role="readonly")

    assert result["status"] == "denied"
    assert "readonly" in result["reason"]


def test_approve_allowed_for_admin(tmp_path: Path) -> None:
    from olav.core.api_action_service import ApiActionRequest, ApiActionService

    svc = ApiActionService(staging_dir=tmp_path)
    req = ApiActionRequest(
        domain="netops",
        operation_id="createVlan",
        method="POST",
        path="/api/v1/vlans",
    )
    svc.stage_request(req, role="user")
    result = svc.approve_request(req.request_id, role="admin")
    assert result["status"] == "approved"


def test_reject_denied_for_user(tmp_path: Path) -> None:
    from olav.core.api_action_service import ApiActionRequest, ApiActionService

    svc = ApiActionService(staging_dir=tmp_path)
    req = ApiActionRequest(
        domain="netops",
        operation_id="deleteVlan",
        method="DELETE",
        path="/api/v1/vlans/100",
    )
    svc.stage_request(req, role="user")
    result = svc.reject_request(req.request_id, role="user")

    assert result["status"] == "denied"
    assert "user" in result["reason"]
