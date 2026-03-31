from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from models import DEFAULT_API_SERVER, DeployResult, DestroyResult, get_auth_headers


def _write_result(result: DestroyResult, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "destroy.json").write_text(json.dumps(result.model_dump(), indent=2))


async def destroy_lab(
    deploy: DeployResult,
    api_server: str | None = None,
    output_dir: Path | None = None,
) -> DestroyResult:
    from clab_client import CLabClient, CLABAPIError

    server = api_server or deploy.api_server or DEFAULT_API_SERVER
    lab_name = deploy.lab_name
    test_run_id = deploy.test_run_id
    dest = output_dir or Path(".")

    # Extract Bearer token from auth headers
    auth_headers = get_auth_headers()
    auth_header_value = auth_headers.get("Authorization", "")
    token = auth_header_value.removeprefix("Bearer ").strip()

    try:
        client = await CLabClient.build(server, token)
    except Exception as exc:
        result = DestroyResult(
            test_run_id=test_run_id,
            lab_name=lab_name,
            containers_removed=[],
            residual_resources=[],
            timestamp=datetime.now(UTC).isoformat(),
            status="failed",
            error=f"Failed to build API client: {exc}",
        )
        _write_result(result, dest)
        return result

    try:
        await client.destroy(lab_name)
    except CLABAPIError as exc:
        result = DestroyResult(
            test_run_id=test_run_id,
            lab_name=lab_name,
            containers_removed=[],
            residual_resources=[],
            timestamp=datetime.now(UTC).isoformat(),
            status="failed",
            error=str(exc),
        )
        _write_result(result, dest)
        return result
    except Exception as exc:
        result = DestroyResult(
            test_run_id=test_run_id,
            lab_name=lab_name,
            containers_removed=[],
            residual_resources=[],
            timestamp=datetime.now(UTC).isoformat(),
            status="failed",
            error=str(exc),
        )
        _write_result(result, dest)
        return result

    # Verify removal — 404 means success
    destroyed = False
    try:
        await client.inspect(lab_name)
        # If no exception, lab still exists
        destroyed = False
    except CLABAPIError as exc:
        if exc.status_code == 404:
            destroyed = True
        else:
            destroyed = False

    containers_removed = list(deploy.nodes.keys())
    residual_resources: list[str] = []

    status = "success" if destroyed else "partial"

    result = DestroyResult(
        test_run_id=test_run_id,
        lab_name=lab_name,
        containers_removed=containers_removed,
        residual_resources=residual_resources,
        timestamp=datetime.now(UTC).isoformat(),
        status=status,
    )
    _write_result(result, dest)
    return result
