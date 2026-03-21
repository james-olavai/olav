"""API Action Service — staged execution for write operations (HMITL).

Design reference: dev_docs/api_discovery.md §4.7–4.8

Write API operations are never executed directly. Instead:
1. Agent stages an ``ApiActionRequest`` (status: pending)
2. Operator reviews and approves (status: approved)
3. Platform executes the approved action (status: executed)

This implements the Human-in-the-Loop (HMITL) pattern for API mutations.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from olav.core.auth.authz import check_permission
from olav.core.config import DATABASES_DIR


@dataclass(frozen=True)
class ApiActionRequest:
    """A staged API write action request.

    Attributes
    ----------
    request_id:      Unique identifier.
    domain:          Domain namespace.
    operation_id:    OpenAPI operationId.
    method:          HTTP method.
    path:            API path.
    intent:          Always "write" for staged actions.
    approval_policy: Always "required" for staged actions.
    params_summary:  Summary of request parameters.
    requested_by:    User ID who requested.
    requested_at:    ISO timestamp.
    status:          Current status in the lifecycle.
    """

    domain: str
    operation_id: str
    method: str
    path: str
    intent: Literal["write"] = "write"
    approval_policy: Literal["required"] = "required"
    params_summary: dict = field(default_factory=dict)  # type: ignore[type-arg]
    requested_by: str = "system"
    request_id: str = field(default_factory=lambda: str(uuid4()))
    requested_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    status: Literal["pending", "approved", "executed", "rejected"] = "pending"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ApiActionService:
    """Stage, approve, and execute API write operations with HMITL."""

    def __init__(
        self,
        staging_dir: str | Path | None = None,
        staging_file_name: str = "api_actions.pending.jsonl",
    ) -> None:
        self.staging_dir = Path(staging_dir or DATABASES_DIR)
        self.staging_file_name = staging_file_name
        self.staging_dir.mkdir(parents=True, exist_ok=True)

    @property
    def staging_file(self) -> Path:
        return self.staging_dir / self.staging_file_name

    @property
    def approved_file(self) -> Path:
        return self.staging_dir / "api_actions.approved.jsonl"

    # ── Stage ─────────────────────────────────────────────────────────────

    def stage_request(
        self,
        request: ApiActionRequest,
        *,
        role: str = "user",
    ) -> dict[str, Any]:
        """Stage a write action request. Requires 'mutate' permission.

        API-RW-4: user and admin can submit write requests.
        readonly cannot.
        """
        if not check_permission(role, "api", request.domain, "submit-write"):
            return {
                "status": "denied",
                "reason": f"Role '{role}' cannot submit write operations",
            }

        self._validate_request(request)
        self._append_to_file(self.staging_file, request.to_dict())
        return {
            "status": "staged",
            "request_id": request.request_id,
            "staging_file": str(self.staging_file),
        }

    # ── Review ────────────────────────────────────────────────────────────

    def list_pending(self) -> list[dict[str, Any]]:
        """Return all pending action requests."""
        return self._read_jsonl(self.staging_file)

    def approve_request(
        self,
        request_id: str,
        *,
        role: str = "admin",
    ) -> dict[str, Any]:
        """Approve a pending action request. Requires 'admin' permission.

        API-RW-4: Only admin can approve write operations.
        """
        if not check_permission(role, "api", "*", "approve-write"):
            return {
                "status": "denied",
                "reason": f"Role '{role}' cannot approve write operations",
            }

        pending = self.list_pending()
        match = next((r for r in pending if r["request_id"] == request_id), None)
        if match is None:
            raise KeyError(f"No pending action request with id={request_id!r}")

        remaining = [r for r in pending if r["request_id"] != request_id]
        self._write_jsonl(self.staging_file, remaining)

        match["status"] = "approved"
        self._append_to_file(self.approved_file, match)

        return {"status": "approved", "request_id": request_id}

    def reject_request(
        self,
        request_id: str,
        *,
        role: str = "admin",
        reason: str = "",
    ) -> dict[str, Any]:
        """Reject a pending action request. Requires 'approve-write' permission."""
        if not check_permission(role, "api", "*", "approve-write"):
            return {
                "status": "denied",
                "reason": f"Role '{role}' cannot reject write operations",
            }

        pending = self.list_pending()
        match = next((r for r in pending if r["request_id"] == request_id), None)
        if match is None:
            raise KeyError(f"No pending action request with id={request_id!r}")

        remaining = [r for r in pending if r["request_id"] != request_id]
        self._write_jsonl(self.staging_file, remaining)

        return {"status": "rejected", "request_id": request_id, "reason": reason}

    # ── Execute ───────────────────────────────────────────────────────────

    def list_approved(self) -> list[dict[str, Any]]:
        """Return all approved action requests waiting for execution."""
        return self._read_jsonl(self.approved_file)

    def execute_approved(self) -> dict[str, Any]:
        """Execute all approved actions.

        Returns summary of executed/errors. The actual execution is a no-op
        placeholder — real execution will be wired to domain-specific handlers.
        """
        approved = self.list_approved()
        executed = 0
        errors: list[str] = []

        for record in approved:
            try:
                record["status"] = "executed"
                executed += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{record.get('request_id', '?')}: {exc}")

        if self.approved_file.exists():
            self.approved_file.write_text("", encoding="utf-8")

        return {"executed": executed, "errors": errors}

    # ── Internal ──────────────────────────────────────────────────────────

    def _validate_request(self, request: ApiActionRequest) -> None:
        if not request.domain.strip():
            raise ValueError("domain must not be empty")
        if not request.operation_id.strip():
            raise ValueError("operation_id must not be empty")
        if not request.method.strip():
            raise ValueError("method must not be empty")
        if not request.path.strip():
            raise ValueError("path must not be empty")

    def _append_to_file(self, path: Path, record: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    def _read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
        return rows

    def _write_jsonl(self, path: Path, records: list[dict[str, Any]]) -> None:
        with path.open("w", encoding="utf-8") as fh:
            for record in records:
                fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
