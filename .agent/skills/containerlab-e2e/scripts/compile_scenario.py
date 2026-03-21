from __future__ import annotations

import ipaddress
import json
import uuid
from datetime import UTC, datetime, timezone
from pathlib import Path

import yaml
from models import (
    MGMT_CLOUD_BASE,
    MGMT_CLOUD_MAX_NODES,
    MGMT_CLOUD_START_OFFSET,
    ExecutionPlan,
    PlannedLink,
    PlannedNode,
    Scenario,
)


def _allocate_mgmt_ips(node_names: list[str]) -> dict[str, str]:
    if len(node_names) > MGMT_CLOUD_MAX_NODES:
        msg = f"Too many nodes ({len(node_names)}), max {MGMT_CLOUD_MAX_NODES}"
        raise ValueError(msg)
    return {
        name: f"{MGMT_CLOUD_BASE}.{MGMT_CLOUD_START_OFFSET + i}"
        for i, name in enumerate(node_names)
    }


def _allocate_p2p(
    links: list[dict],
    pool: str,
    prefixlen: int,
) -> list[PlannedLink]:
    network = ipaddress.IPv4Network(pool)
    subnets = list(network.subnets(new_prefix=prefixlen))
    planned: list[PlannedLink] = []
    for i, link in enumerate(links):
        endpoints = link["endpoints"] if isinstance(link, dict) else link.endpoints
        p2p_net = str(subnets[i]) if i < len(subnets) else None
        planned.append(PlannedLink(endpoints=endpoints, p2p_network=p2p_net))
    return planned


def _allocate_loopbacks(node_names: list[str], pool: str) -> dict[str, str]:
    network = ipaddress.IPv4Network(pool)
    hosts = list(network.hosts())
    return {name: str(hosts[i]) for i, name in enumerate(node_names) if i < len(hosts)}


def compile_scenario_from_dict(data: dict) -> ExecutionPlan:
    scenario = Scenario.model_validate(data)
    return _compile(scenario)


def compile_scenario(scenario_path: Path, evidence_base: Path | None = None) -> ExecutionPlan:
    raw = yaml.safe_load(scenario_path.read_text())
    scenario = Scenario.model_validate(raw)
    plan = _compile(scenario)

    base = evidence_base or Path(".agent/skills/containerlab-e2e/evidence")
    out_dir = base / plan.test_run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "execution-plan.json").write_text(json.dumps(plan.model_dump(), indent=2))
    return plan


def _compile(scenario: Scenario) -> ExecutionPlan:
    test_run_id = f"{uuid.uuid4().hex[:8]}_{scenario.scenario}"
    node_names = list(scenario.nodes.keys())

    mgmt_ips = _allocate_mgmt_ips(node_names)

    loopback_pool = scenario.addressing.get("loopback_pool_v4")
    loopbacks = _allocate_loopbacks(node_names, loopback_pool) if loopback_pool else {}

    p2p_pool = scenario.addressing.get("p2p_pool_v4", "10.0.0.0/24")
    p2p_prefixlen = scenario.addressing.get("p2p_prefixlen_v4", 30)

    links_raw = [link.model_dump() for link in scenario.links]
    planned_links = _allocate_p2p(links_raw, p2p_pool, p2p_prefixlen)

    planned_nodes: dict[str, PlannedNode] = {}
    for name, node_def in scenario.nodes.items():
        planned_nodes[name] = PlannedNode(
            name=name,
            platform=node_def.platform,
            mgmt_cloud_ip=mgmt_ips[name],
            loopback_ip=loopbacks.get(name),
            configs=node_def.configs,
        )

    return ExecutionPlan(
        test_run_id=test_run_id,
        scenario_name=scenario.scenario,
        topology_file=scenario.topology,
        nodes=planned_nodes,
        links=planned_links,
        addressing=scenario.addressing,
        queries=scenario.queries,
        assertions=[a.model_dump() for a in scenario.assertions],
        query_assertions=scenario.query_assertions,
        defaults=scenario.defaults,
        timestamp=datetime.now(UTC).isoformat(),
        metadata=scenario.metadata,
    )
