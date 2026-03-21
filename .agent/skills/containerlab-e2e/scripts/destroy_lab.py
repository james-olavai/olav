from __future__ import annotations

import json
from datetime import UTC, datetime, timezone
from pathlib import Path

import httpx
from models import DEFAULT_API_SERVER, DeployResult, DestroyResult, get_auth_headers


async def _delete_lab(client: httpx.AsyncClient, api_server: str, lab_name: str) -> bool:
    resp = await client.delete(f"{api_server}/labs/{lab_name}", timeout=30.0)
    return resp.status_code in (200, 204)


async def _verify_removed(client: httpx.AsyncClient, api_server: str, lab_name: str) -> bool:
    resp = await client.get(f"{api_server}/labs/{lab_name}", timeout=15.0)
    return resp.status_code == 404 or (
        resp.status_code == 200 and not resp.json().get("containers")
    )


async def _check_residual_containers(
    client: httpx.AsyncClient, api_server: str, lab_name: str
) -> list[str]:
    residuals: list[str] = []
    try:
        resp = await client.get(f"{api_server}/docker/containers", timeout=15.0)
        if resp.status_code == 200:
            containers = resp.json() if isinstance(resp.json(), list) else []
            for c in containers:
                name = c.get("name", "") if isinstance(c, dict) else str(c)
                if lab_name in name:
                    residuals.append(f"container:{name}")
    except httpx.HTTPError:
        pass
    return residuals


async def _check_residual_networks(
    client: httpx.AsyncClient, api_server: str, lab_name: str
) -> list[str]:
    residuals: list[str] = []
    try:
        resp = await client.get(f"{api_server}/docker/networks", timeout=15.0)
        if resp.status_code == 200:
            networks = resp.json() if isinstance(resp.json(), list) else []
            for n in networks:
                name = n.get("name", "") if isinstance(n, dict) else str(n)
                if lab_name in name:
                    residuals.append(f"network:{name}")
    except httpx.HTTPError:
        pass
    return residuals


async def _check_residual_volumes(
    client: httpx.AsyncClient, api_server: str, lab_name: str
) -> list[str]:
    residuals: list[str] = []
    try:
        resp = await client.get(f"{api_server}/docker/volumes", timeout=15.0)
        if resp.status_code == 200:
            volumes = resp.json() if isinstance(resp.json(), list) else []
            for v in volumes:
                name = v.get("name", "") if isinstance(v, dict) else str(v)
                if lab_name in name:
                    residuals.append(f"volume:{name}")
    except httpx.HTTPError:
        pass
    return residuals


def _write_result(result: DestroyResult, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "destroy.json").write_text(json.dumps(result.model_dump(), indent=2))


async def destroy_lab(
    deploy: DeployResult,
    api_server: str | None = None,
    output_dir: Path | None = None,
) -> DestroyResult:
    server = api_server or deploy.api_server or DEFAULT_API_SERVER
    lab_name = deploy.lab_name
    test_run_id = deploy.test_run_id
    dest = output_dir or Path(".")

    async with httpx.AsyncClient(headers=get_auth_headers()) as client:
        try:
            deleted = await _delete_lab(client, server, lab_name)
        except httpx.HTTPError as exc:
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

        if not deleted:
            result = DestroyResult(
                test_run_id=test_run_id,
                lab_name=lab_name,
                containers_removed=[],
                residual_resources=[],
                timestamp=datetime.now(UTC).isoformat(),
                status="failed",
                error="DELETE request returned non-success status",
            )
            _write_result(result, dest)
            return result

        containers_removed = list(deploy.nodes.keys())

        residuals: list[str] = []
        residuals.extend(await _check_residual_containers(client, server, lab_name))
        residuals.extend(await _check_residual_networks(client, server, lab_name))
        residuals.extend(await _check_residual_volumes(client, server, lab_name))

        if residuals:
            status = "partial"
        else:
            status = "success"

        result = DestroyResult(
            test_run_id=test_run_id,
            lab_name=lab_name,
            containers_removed=containers_removed,
            residual_resources=residuals,
            timestamp=datetime.now(UTC).isoformat(),
            status=status,
        )
        _write_result(result, dest)
        return result
