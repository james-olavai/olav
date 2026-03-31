import json
import re
import sys
from pathlib import Path

import yaml

_SKILL_DIR = (
    Path(__file__).resolve().parents[2] / ".olav" / "workspace" / "ops" / "lab"
)
if str(_SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(_SKILL_DIR / "scripts"))

from compile_scenario import compile_scenario, compile_scenario_from_dict
from models import ExecutionPlan, PlannedLink, PlannedNode

MINIMAL_SCENARIO = {
    "scenario": "bgp_full_mesh",
    "topology": "bgp-dual-vendor.clab.yml",
    "addressing": {
        "p2p_pool_v4": "10.0.0.0/24",
        "p2p_prefixlen_v4": 30,
        "loopback_pool_v4": "10.255.0.0/24",
    },
    "defaults": {"ssh_timeout_sec": 180, "protocol_timeout_sec": 240, "keep_on_failure": False},
    "nodes": {
        "R1": {"platform": "cisco_ios", "configs": ["base", "bgp_peer"]},
        "R2": {"platform": "juniper_junos", "configs": ["base", "bgp_peer"]},
    },
    "links": [{"endpoints": ["R1:to_R2", "R2:to_R1"]}],
    "readiness": {"protocol": {"type": "bgp"}},
    "assertions": [
        {
            "type": "sql_count",
            "query": "SELECT COUNT(*) FROM bgp_neighbors WHERE state != 'Established'",
            "operator": "eq",
            "expected": 0,
        }
    ],
}


def test_compile_from_dict_returns_execution_plan():
    plan = compile_scenario_from_dict(MINIMAL_SCENARIO)
    assert isinstance(plan, ExecutionPlan)
    assert plan.scenario_name == "bgp_full_mesh"
    assert plan.topology_file == "bgp-dual-vendor.clab.yml"


def test_test_run_id_format():
    plan = compile_scenario_from_dict(MINIMAL_SCENARIO)
    assert re.match(r"^[0-9a-f]{8}_bgp_full_mesh$", plan.test_run_id)


def test_mgmt_ips_allocated_correctly():
    plan = compile_scenario_from_dict(MINIMAL_SCENARIO)
    assert plan.nodes["R1"].mgmt_cloud_ip == "192.168.100.110"
    assert plan.nodes["R2"].mgmt_cloud_ip == "192.168.100.111"


def test_loopback_ips_allocated():
    plan = compile_scenario_from_dict(MINIMAL_SCENARIO)
    assert plan.nodes["R1"].loopback_ip == "10.255.0.1"
    assert plan.nodes["R2"].loopback_ip == "10.255.0.2"


def test_p2p_links_allocated():
    plan = compile_scenario_from_dict(MINIMAL_SCENARIO)
    assert len(plan.links) == 1
    assert isinstance(plan.links[0], PlannedLink)
    assert plan.links[0].p2p_network == "10.0.0.0/30"
    assert plan.links[0].endpoints == ["R1:to_R2", "R2:to_R1"]


def test_too_many_nodes_raises():
    scenario = {**MINIMAL_SCENARIO}
    scenario["nodes"] = {f"R{i}": {"platform": "cisco_ios", "configs": []} for i in range(52)}
    try:
        compile_scenario_from_dict(scenario)
        assert False, "Should have raised ValueError"
    except ValueError as exc:
        assert "Too many nodes" in str(exc)


def test_compile_from_file_writes_execution_plan_json(tmp_path):
    scenario_file = tmp_path / "scenario.yaml"
    scenario_file.write_text(yaml.dump(MINIMAL_SCENARIO))
    evidence_base = tmp_path / "evidence"

    plan = compile_scenario(scenario_file, evidence_base=evidence_base)

    plan_file = evidence_base / plan.test_run_id / "execution-plan.json"
    assert plan_file.exists()
    data = json.loads(plan_file.read_text())
    assert data["scenario_name"] == "bgp_full_mesh"


def test_compile_from_file_reads_yaml(tmp_path):
    scenario_file = tmp_path / "scenario.yaml"
    scenario_file.write_text(yaml.dump(MINIMAL_SCENARIO))
    plan = compile_scenario(scenario_file, evidence_base=tmp_path / "ev")
    assert plan.scenario_name == "bgp_full_mesh"
    assert len(plan.nodes) == 2


def test_planned_node_fields():
    plan = compile_scenario_from_dict(MINIMAL_SCENARIO)
    r1 = plan.nodes["R1"]
    assert isinstance(r1, PlannedNode)
    assert r1.name == "R1"
    assert r1.platform == "cisco_ios"
    assert r1.configs == ["base", "bgp_peer"]
    assert r1.mgmt_cloud_ip.startswith("192.168.100.")
    assert r1.loopback_ip is not None


def test_planned_link_fields():
    plan = compile_scenario_from_dict(MINIMAL_SCENARIO)
    link = plan.links[0]
    assert isinstance(link, PlannedLink)
    assert len(link.endpoints) == 2
    assert link.p2p_network is not None


def test_assertions_preserved():
    plan = compile_scenario_from_dict(MINIMAL_SCENARIO)
    assert len(plan.assertions) == 1
    assert plan.assertions[0]["type"] == "sql_count"
    assert plan.assertions[0]["operator"] == "eq"
    assert plan.assertions[0]["expected"] == 0


def test_no_loopback_pool_gives_none():
    scenario = {**MINIMAL_SCENARIO}
    scenario["addressing"] = {
        "p2p_pool_v4": "10.0.0.0/24",
        "p2p_prefixlen_v4": 30,
    }
    plan = compile_scenario_from_dict(scenario)
    assert plan.nodes["R1"].loopback_ip is None
    assert plan.nodes["R2"].loopback_ip is None


def test_defaults_preserved():
    plan = compile_scenario_from_dict(MINIMAL_SCENARIO)
    assert plan.defaults["ssh_timeout_sec"] == 180
    assert plan.defaults["protocol_timeout_sec"] == 240
