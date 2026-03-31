from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import yaml
from models import (
    DEFAULT_API_SERVER,
    DeployResult,
    ExecutionPlan,
    NodeInfo,
    get_auth_headers,
)

_SKILL_ROOT = Path(__file__).parent.resolve()


def _resolve_topology_content(topology_ref: str) -> dict:
    """Return topology parsed as dict (YAML→JSON-serializable).

    Tries, in order:
    1. Absolute path  → read and parse YAML
    2. Relative to skill root  → read and parse YAML
    3. Relative to cwd  → read and parse YAML
    4. Treat as raw YAML string → parse
    """
    for base in (None, _SKILL_ROOT, Path.cwd()):
        p = Path(topology_ref) if base is None else base / topology_ref
        if p.exists():
            return yaml.safe_load(p.read_text())
    # Already content (raw YAML string)
    return yaml.safe_load(topology_ref)


async def deploy_lab(
    plan: ExecutionPlan,
    api_server: str = DEFAULT_API_SERVER,
    evidence_dir: Path | None = None,
) -> DeployResult:
    from clab_client import CLabClient, CLABAPIError

    out_dir = evidence_dir or Path(f".agent/skills/containerlab-e2e/evidence/{plan.test_run_id}")
    out_dir.mkdir(parents=True, exist_ok=True)

    topology_content = _resolve_topology_content(plan.topology_file)

    # Extract Bearer token from auth headers
    auth_headers = get_auth_headers()
    auth_header_value = auth_headers.get("Authorization", "")
    token = auth_header_value.removeprefix("Bearer ").strip()

    try:
        client = await CLabClient.build(api_server, token)
        body = await client.deploy(topology_content, reconfigure=False)

        # Extract lab name — body is {lab_name: [node_list]}
        if isinstance(body, dict) and body:
            lab_name = next(iter(body))
        else:
            lab_name = plan.scenario_name

        default_username = plan.defaults.get("username", "admin")
        default_password = plan.defaults.get("password", "admin")
        nodes: dict[str, NodeInfo] = {}
        for name, planned in plan.nodes.items():
            nodes[name] = NodeInfo(
                name=name,
                platform=planned.platform,
                mgmt_cloud_ip=planned.mgmt_cloud_ip,
                mgmt_cloud_port=planned.mgmt_cloud_port,
                username=default_username,
                password=default_password,
            )

        result = DeployResult(
            test_run_id=plan.test_run_id,
            lab_name=lab_name,
            api_server=api_server,
            nodes=nodes,
            timestamp=datetime.now(UTC).isoformat(),
            status="success",
        )

    except (CLABAPIError, KeyError, ValueError, Exception) as exc:
        result = DeployResult(
            test_run_id=plan.test_run_id,
            lab_name="",
            api_server=api_server,
            nodes={},
            timestamp=datetime.now(UTC).isoformat(),
            status="failed",
            error=str(exc),
        )

    (out_dir / "deploy.json").write_text(json.dumps(result.model_dump(), indent=2))
    return result
