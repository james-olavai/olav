from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from pathlib import Path

from models import (
    DEFAULT_SSH_TIMEOUT,
    DeployResult,
    NodeReadinessStatus,
    ReadinessResult,
    get_auth_headers,
)


async def wait_readiness(
    deploy: DeployResult,
    ssh_timeout: int = DEFAULT_SSH_TIMEOUT,
    protocol_timeout: int = 240,
    poll_interval: float = 5.0,
    evidence_dir: Path | None = None,
) -> ReadinessResult:
    """Wait for all nodes to become reachable via the exec API.

    Uses client.exec_command(lab_name, "hostname") for each node.
    Polls every poll_interval seconds up to ssh_timeout total.
    No SSH polling, no protocol convergence check — exec health is sufficient.
    """
    from clab_client import CLabClient, CLABAPIError

    # Extract Bearer token
    auth_headers = get_auth_headers()
    auth_header_value = auth_headers.get("Authorization", "")
    token = auth_header_value.removeprefix("Bearer ").strip()

    try:
        client = await CLabClient.build(deploy.api_server, token)
    except Exception as exc:
        # If we can't even build the client, mark all nodes as failed
        ts = datetime.now(UTC).isoformat()
        node_statuses = {
            name: NodeReadinessStatus(
                name=name,
                ssh_reachable=False,
                protocol_converged=False,
                retries=0,
                duration_ms=0,
                error=f"Failed to build API client: {exc}",
            )
            for name in deploy.nodes
        }
        result = ReadinessResult(
            test_run_id=deploy.test_run_id,
            nodes=node_statuses,
            timestamp=ts,
            status="failed",
        )
        if evidence_dir is not None:
            evidence_dir.mkdir(parents=True, exist_ok=True)
            (evidence_dir / "readiness.json").write_text(result.model_dump_json(indent=2))
        return result

    node_statuses: dict[str, NodeReadinessStatus] = {}
    overall_status: str = "success"

    async def _check_node(node_name: str) -> None:
        nonlocal overall_status
        deadline = time.monotonic() + float(ssh_timeout)
        retries = 0
        start = time.monotonic()
        last_error: str | None = None
        ready = False

        while time.monotonic() < deadline:
            try:
                response = await client.exec_command(deploy.lab_name, "hostname", timeout=10.0)
                node_results = (
                    response.get(node_name)
                    or response.get(f"clab-{deploy.lab_name}-{node_name}")
                )
                if node_results:
                    result_item = node_results[0]
                    rc = result_item.get("return-code", 0)
                    if rc == 0:
                        ready = True
                        last_error = None
                        break
                    else:
                        last_error = f"hostname rc={rc}"
                else:
                    last_error = f"node '{node_name}' not in exec response"
            except CLABAPIError as exc:
                last_error = str(exc)
            except Exception as exc:
                last_error = str(exc)

            retries += 1
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            await asyncio.sleep(min(poll_interval, remaining))

        elapsed_ms = int((time.monotonic() - start) * 1000)

        if not ready:
            overall_status = "timeout"

        node_statuses[node_name] = NodeReadinessStatus(
            name=node_name,
            ssh_reachable=ready,
            protocol_converged=ready,
            retries=retries,
            duration_ms=elapsed_ms,
            error=last_error,
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
