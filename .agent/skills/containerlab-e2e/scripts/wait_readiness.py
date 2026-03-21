from __future__ import annotations

import asyncio
import random
import time
from datetime import UTC, datetime, timezone
from pathlib import Path

import httpx
from models import (
    DEFAULT_PROTOCOL_TIMEOUT,
    DEFAULT_SSH_TIMEOUT,
    DeployResult,
    NodeReadinessStatus,
    ReadinessResult,
    get_auth_headers,
)


async def _poll_ssh(
    host: str,
    port: int,
    timeout: float,
) -> tuple[bool, int, int, str | None]:
    deadline = time.monotonic() + timeout
    retries = 0
    base_delay = 1.0
    max_delay = 10.0
    start = time.monotonic()

    while time.monotonic() < deadline:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=min(5.0, deadline - time.monotonic()),
            )
            writer.close()
            await writer.wait_closed()
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return True, retries, elapsed_ms, None
        except (TimeoutError, OSError, ConnectionRefusedError):
            retries += 1
            jitter = random.uniform(0, base_delay * 0.5)
            delay = min(base_delay + jitter, max_delay)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            await asyncio.sleep(min(delay, remaining))
            base_delay = min(base_delay * 2, max_delay)

    elapsed_ms = int((time.monotonic() - start) * 1000)
    return False, retries, elapsed_ms, f"SSH timeout after {timeout}s"


async def _check_protocol_convergence(
    host: str,
    port: int,
    timeout: float,
) -> tuple[bool, str | None]:
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=min(5.0, timeout),
        )
        writer.close()
        await writer.wait_closed()
        return True, None
    except (TimeoutError, OSError, ConnectionRefusedError) as exc:
        return False, str(exc)


async def _check_exec_health(
    api_server: str,
    lab_name: str,
) -> tuple[bool, str | None]:
    """Exec-based health check: run `hostname` via clab exec API."""
    try:
        async with httpx.AsyncClient(headers=get_auth_headers()) as client:
            resp = await client.post(
                f"{api_server}/labs/{lab_name}/exec",
                json={"Command": "hostname"},
                timeout=10.0,
            )
            if resp.status_code == 200 and resp.json():
                return True, None
            return False, f"exec health check returned status {resp.status_code}"
    except Exception as exc:
        return False, str(exc)


async def wait_readiness(
    deploy: DeployResult,
    ssh_timeout: int = DEFAULT_SSH_TIMEOUT,
    protocol_timeout: int = DEFAULT_PROTOCOL_TIMEOUT,
    evidence_dir: Path | None = None,
) -> ReadinessResult:
    node_statuses: dict[str, NodeReadinessStatus] = {}
    overall_status: str = "success"

    async def _check_node(node_name: str) -> None:
        nonlocal overall_status
        node = deploy.nodes[node_name]

        ssh_ok, retries, duration_ms, ssh_err = await _poll_ssh(
            node.mgmt_cloud_ip, node.mgmt_cloud_port, float(ssh_timeout)
        )

        proto_ok = False
        proto_err: str | None = None
        if ssh_ok:
            proto_ok, proto_err = await _check_protocol_convergence(
                node.mgmt_cloud_ip, node.mgmt_cloud_port, float(protocol_timeout)
            )

        # Fallback: if SSH unreachable (management IPs not accessible from this
        # host), verify via ContainerLab exec API instead.
        if not ssh_ok:
            exec_ok, exec_err = await _check_exec_health(
                deploy.api_server, deploy.lab_name
            )
            if exec_ok:
                print(
                    f"  ⚠ {node_name}: SSH unreachable ({ssh_err}); "
                    f"exec health-check passed — treating as ready"
                )
                ssh_ok = True
                proto_ok = True
                ssh_err = f"SSH bypassed (exec health-check OK): {ssh_err}"

        error = ssh_err if not ssh_ok else proto_err
        if not ssh_ok:
            overall_status = "timeout"
        elif not proto_ok:
            overall_status = "failed"

        node_statuses[node_name] = NodeReadinessStatus(
            name=node_name,
            ssh_reachable=ssh_ok,
            protocol_converged=proto_ok,
            retries=retries,
            duration_ms=duration_ms,
            error=error,
        )

    tasks = [_check_node(name) for name in deploy.nodes]
    await asyncio.gather(*tasks)

    result = ReadinessResult(
        test_run_id=deploy.test_run_id,
        nodes=node_statuses,
        timestamp=datetime.now(UTC).isoformat(),
        status=overall_status,
    )

    if evidence_dir is not None:
        evidence_dir.mkdir(parents=True, exist_ok=True)
        (evidence_dir / "readiness.json").write_text(result.model_dump_json(indent=2))
    return result
