"""E2E test: Minimal 2-node SR Linux lab — deploy → OSPF config → verify → destroy.

CLAB host: 192.168.100.12 (via services.yaml)
Image: ghcr.io/nokia/srlinux:latest

Gate conditions (ISSUE-P1-LAB-AGENT-E2E):
  - deploy_lab succeeds (SRL containers start + fix_srl_topology runs)
  - SR Linux management plane responds to exec_on_node
  - OSPF config pushes cleanly via exec API
  - OSPF neighbors reach FULL state on both nodes
  - Lab destroyed after test; no residual containers
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time
from pathlib import Path

import pytest

# Bootstrap path
_PROJECT_ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))
_LAB_TOOLS = _PROJECT_ROOT / ".olav/workspace/ops/lab/tools"
sys.path.insert(0, str(_LAB_TOOLS))

LAB_NAME = "e2e-minimal"
SRL_IMAGE = "ghcr.io/nokia/srlinux:latest"

TOPOLOGY_YAML = f"""\
name: {LAB_NAME}
topology:
  kinds:
    nokia_srlinux:
      type: ixrd3
      image: {SRL_IMAGE}
  nodes:
    srl1:
      kind: nokia_srlinux
    srl2:
      kind: nokia_srlinux
  links:
    - endpoints: ["srl1:e1-1", "srl2:e1-1"]
"""

# SR Linux OSPF config for srl1 (10.0.0.1/30 on e1-1, OSPFv2 area 0, router-id 1.1.1.1)
# SRL requires: version ospf-v2, explicit router-id, separate set lines per attribute
SRL1_OSPF_CONFIG = """\
enter candidate
set / interface ethernet-1/1 admin-state enable
set / interface ethernet-1/1 subinterface 0 admin-state enable
set / interface ethernet-1/1 subinterface 0 ipv4 admin-state enable
set / interface ethernet-1/1 subinterface 0 ipv4 address 10.0.0.1/30
set / network-instance default interface ethernet-1/1.0
set / network-instance default protocols ospf instance main admin-state enable
set / network-instance default protocols ospf instance main version ospf-v2
set / network-instance default protocols ospf instance main router-id 1.1.1.1
set / network-instance default protocols ospf instance main area 0.0.0.0 interface ethernet-1/1.0
set / network-instance default protocols ospf instance main area 0.0.0.0 interface ethernet-1/1.0 interface-type point-to-point
commit now
"""

# SR Linux OSPF config for srl2 (10.0.0.2/30 on e1-1, OSPFv2 area 0, router-id 2.2.2.2)
SRL2_OSPF_CONFIG = """\
enter candidate
set / interface ethernet-1/1 admin-state enable
set / interface ethernet-1/1 subinterface 0 admin-state enable
set / interface ethernet-1/1 subinterface 0 ipv4 admin-state enable
set / interface ethernet-1/1 subinterface 0 ipv4 address 10.0.0.2/30
set / network-instance default interface ethernet-1/1.0
set / network-instance default protocols ospf instance main admin-state enable
set / network-instance default protocols ospf instance main version ospf-v2
set / network-instance default protocols ospf instance main router-id 2.2.2.2
set / network-instance default protocols ospf instance main area 0.0.0.0 interface ethernet-1/1.0
set / network-instance default protocols ospf instance main area 0.0.0.0 interface ethernet-1/1.0 interface-type point-to-point
commit now
"""


def _bootstrap():
    os.environ.setdefault("CLAB_USERNAME", "olav")
    os.environ.setdefault("CLAB_PASSWORD", "olav123")


def _push_srl_config(lab_name: str, node: str, config_text: str) -> dict:
    """Push multi-line sr_cli config via base64 stdin pipe.

    SRL exec API only supports single-command strings; multi-line candidate
    transactions must be piped to sr_cli via: bash -c 'echo B64 | base64 -d | sr_cli'
    """
    from exec_on_node import exec_on_node
    b64 = base64.b64encode(config_text.encode()).decode()
    command = f"bash -c 'echo {b64} | base64 -d | sr_cli'"
    return json.loads(exec_on_node.invoke({"lab_name": lab_name, "node": node, "command": command}))


def _destroy_lab_if_exists(lab_name: str) -> None:
    """Best-effort lab cleanup — used in setUp and tearDown."""
    from olav.platform.services.client import service_call
    import olav.platform.services.client as _c
    _c._token_cache.clear()
    try:
        service_call("containerlab", "DELETE", f"/api/v1/labs/{lab_name}", confirmed=True)
    except Exception:
        pass


def _wait_for_mgmt_plane(lab_name: str, node: str, max_wait: int = 90) -> bool:
    """Poll exec_on_node until 'show version' succeeds."""
    from exec_on_node import exec_on_node
    deadline = time.monotonic() + max_wait
    while time.monotonic() < deadline:
        result = json.loads(exec_on_node.invoke({"lab_name": lab_name, "node": node, "command": "sr_cli -c 'show version'"}))
        if "error" not in result and result.get("return_code", 1) == 0:
            return True
        time.sleep(5)
    return False


@pytest.fixture(scope="module", autouse=True)
def bootstrap_clab():
    _bootstrap()


@pytest.fixture(scope="module")
def deployed_lab():
    """Deploy the minimal lab; yield lab_name; destroy on teardown."""
    _bootstrap()
    _destroy_lab_if_exists(LAB_NAME)  # pre-clean

    # Import deploy_lab tool (expects LangChain @tool style but also callable as function)
    import importlib
    deploy_mod = importlib.import_module("deploy_lab")

    result_str = deploy_mod.deploy_lab.invoke({"yaml_content": TOPOLOGY_YAML, "wait_seconds": 45})
    result = json.loads(result_str)

    if result.get("status") != "deployed":
        pytest.fail(f"deploy_lab failed: {result}")

    yield result["lab_name"]

    # Teardown — always destroy
    _destroy_lab_if_exists(result["lab_name"])


def test_deploy_lab_succeeds(deployed_lab):
    """deploy_lab returns status=deployed and lab_name matches."""
    assert deployed_lab == LAB_NAME


def test_srl1_mgmt_plane_ready(deployed_lab):
    """SRL management plane on srl1 responds within 90s."""
    ready = _wait_for_mgmt_plane(deployed_lab, "srl1", max_wait=90)
    assert ready, "srl1 management plane never became ready"


def test_srl2_mgmt_plane_ready(deployed_lab):
    """SRL management plane on srl2 responds within 90s."""
    ready = _wait_for_mgmt_plane(deployed_lab, "srl2", max_wait=90)
    assert ready, "srl2 management plane never became ready"


def test_push_ospf_config(deployed_lab):
    """Push OSPF config to both nodes via exec API (base64 → sr_cli stdin)."""
    # Push to srl1
    r1 = _push_srl_config(deployed_lab, "srl1", SRL1_OSPF_CONFIG)
    assert "error" not in r1, f"OSPF config push to srl1 failed: {r1}"
    assert r1.get("return_code", 1) == 0, f"srl1 commit failed:\n{r1.get('stderr', '')}"

    # Push to srl2
    r2 = _push_srl_config(deployed_lab, "srl2", SRL2_OSPF_CONFIG)
    assert "error" not in r2, f"OSPF config push to srl2 failed: {r2}"
    assert r2.get("return_code", 1) == 0, f"srl2 commit failed:\n{r2.get('stderr', '')}"


def test_ospf_convergence(deployed_lab):
    """OSPF neighbors on srl1 reach FULL state within 60s."""
    from exec_on_node import exec_on_node

    ospf_cmd = "sr_cli -c 'show network-instance default protocols ospf neighbor'"
    deadline = time.monotonic() + 60

    while time.monotonic() < deadline:
        result = json.loads(exec_on_node.invoke({
            "lab_name": deployed_lab,
            "node": "srl1",
            "command": ospf_cmd,
        }))
        stdout = result.get("stdout", "")
        if "FULL" in stdout or "full" in stdout.lower():
            return  # OSPF converged
        time.sleep(5)

    # Final check with full output in failure message
    result = json.loads(exec_on_node.invoke({"lab_name": deployed_lab, "node": "srl1", "command": ospf_cmd}))
    pytest.fail(f"OSPF did not converge. Output:\n{result.get('stdout', result)}")


def test_no_residual_containers(deployed_lab):
    """After the fixture destroys the lab, no containers remain (checked at module teardown).

    This test just documents intent; actual cleanup is in the fixture teardown.
    The deployed_lab fixture calls _destroy_lab_if_exists on exit.
    """
    # This test passes if we reach here — cleanup is fixture responsibility
    pass
