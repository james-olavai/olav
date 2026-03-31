"""Shared Pydantic models for ContainerLab E2E test pipeline."""

from __future__ import annotations

import os
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Optional

import yaml
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Skill-local config loader
# ---------------------------------------------------------------------------

_SKILL_ROOT = Path(__file__).parent.parent.resolve()
_CONFIG_FILE = _SKILL_ROOT / "config" / "clab.yaml"


@lru_cache(maxsize=1)
def _load_config() -> dict[str, Any]:
    """Load skill-local config from config/clab.yaml.

    Returns an empty dict if the file is missing (all callers fall back
    to hard-coded defaults so the skill remains usable without the file).
    """
    if _CONFIG_FILE.exists():
        return yaml.safe_load(_CONFIG_FILE.read_text()) or {}
    return {}


def get_config() -> dict[str, Any]:
    """Return the loaded skill config dict."""
    return _load_config()


# ---------------------------------------------------------------------------
# Runtime constants — read from config/clab.yaml, fall back to defaults
# ---------------------------------------------------------------------------

def _cfg(*keys: str, default: Any = None) -> Any:
    """Navigate nested config dict by dot-path keys."""
    node: Any = _load_config()
    for k in keys:
        if not isinstance(node, dict):
            return default
        node = node.get(k, default)
    return node


MGMT_CLOUD_BASE: str = _cfg("mgmt_cloud", "base", default="192.168.100")
MGMT_CLOUD_START_OFFSET: int = _cfg("mgmt_cloud", "start_offset", default=110)
MGMT_CLOUD_MAX_NODES: int = _cfg("mgmt_cloud", "max_nodes", default=51)
DEFAULT_API_SERVER: str = _cfg("api", "server", default="http://192.168.100.12:8080/api/v1")
DEFAULT_SSH_TIMEOUT: int = _cfg("timeouts", "ssh", default=180)


def get_auth_headers() -> dict[str, str]:
    """Return Bearer auth headers from CLAB_API_TOKEN env var.

    Set the token before running:
        export CLAB_API_TOKEN="<jwt_token>"

    To obtain a fresh token (login endpoint is /login, NOT /api/v1/auth):
        curl -s -X POST http://<host>:8080/login \\
             -H 'Content-Type: application/json' \\
             -d '{"username":"<user>","password":"<pass>"}' \\
             | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])"
    """
    token = os.environ.get("CLAB_API_TOKEN", "")
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


class NodeInfo(BaseModel):
    name: str
    platform: str
    mgmt_cloud_ip: str
    mgmt_cloud_port: int = 22
    username: str = "admin"
    password: str = "admin"


class DeployResult(BaseModel):
    test_run_id: str
    lab_name: str
    api_server: str
    nodes: dict[str, NodeInfo]
    timestamp: str
    status: Literal["success", "failed"]
    error: str | None = None


class ScenarioNode(BaseModel):
    platform: str
    configs: list[str]


class ScenarioLink(BaseModel):
    endpoints: list[str]


class ScenarioAssertion(BaseModel):
    type: Literal["sql_count", "file_exists"]
    query: str | None = None
    path: str | None = None
    operator: Literal["eq", "ne", "gt", "gte", "lt", "lte"]
    expected: int


class ScenarioMetadata(BaseModel):
    """Optional rich metadata for the test capability matrix."""
    description: str = ""
    layers: list[str] = []          # e.g. ["L3_routing", "L2_LLDP"]
    features: list[str] = []        # e.g. ["bgp_neighbor_discovery"]
    commands_expected: list[str] = []  # commands that MUST appear in parsed_outputs


class ScenarioQuery(BaseModel):
    """A single natural-language query to issue to OLAV during collection."""
    agent: str = "ops"              # OLAV agent to route to (ops, sync, query)
    prompt: str                     # NL prompt sent to OLAV CLI
    description: str = ""           # human-readable intent (documents why)


class ScenarioQueryAssertion(BaseModel):
    """Ask OLAV an NL question and verify the response contains expected content.

    This tests the full agent chain:
        NL → Agent → Tool(SQL/CLI) → DuckDB → LLM answer → content check
    """
    agent: str = "quick"            # which OLAV agent to query ("quick", "olav", "audit")
    prompt: str                     # NL question to ask
    description: str = ""           # human label (used in output/JSON)
    expect_contains: list[str] = [] # ALL of these must appear in the response (case-insensitive)
    expect_not_contains: list[str] = []  # NONE of these may appear in the response


class QueryAssertionResult(BaseModel):
    description: str
    agent: str
    prompt: str
    passed: bool
    response_snippet: str           # first 300 chars of agent response
    matched: list[str]              # which expect_contains were found
    missing: list[str]              # which expect_contains were NOT found
    banned_found: list[str]         # which expect_not_contains were found
    error: str | None = None


class QueryAssertionsResult(BaseModel):
    test_run_id: str
    assertions: list[QueryAssertionResult]
    passed_count: int
    failed_count: int
    timestamp: str
    status: Literal["passed", "failed"]


class Scenario(BaseModel):
    scenario: str
    topology: str
    addressing: dict
    defaults: dict
    nodes: dict[str, ScenarioNode]
    links: list[ScenarioLink]
    readiness: dict
    queries: list[ScenarioQuery] = []               # NL collection prompts (write)
    assertions: list[ScenarioAssertion] = []         # SQL count assertions (structural)
    query_assertions: list[ScenarioQueryAssertion] = []  # NL query assertions (agent chain)
    metadata: ScenarioMetadata = ScenarioMetadata()
    # OC agent config source (Phase 6.7)
    config_source: str = "template"   # "template" | "oc_agent"
    change_intent: str = ""           # passed to CABConfigExtractor when config_source=oc_agent


class PlannedNode(BaseModel):
    name: str
    platform: str
    mgmt_cloud_ip: str
    mgmt_cloud_port: int = 22
    loopback_ip: str | None = None
    configs: list[str] = []


class PlannedLink(BaseModel):
    endpoints: list[str]
    p2p_network: str | None = None


class ExecutionPlan(BaseModel):
    test_run_id: str
    scenario_name: str
    topology_file: str
    nodes: dict[str, PlannedNode]
    links: list[PlannedLink]
    addressing: dict
    queries: list[ScenarioQuery] = []
    assertions: list
    query_assertions: list[ScenarioQueryAssertion] = []
    defaults: dict
    timestamp: str
    metadata: ScenarioMetadata = ScenarioMetadata()
    config_source: str = "template"
    change_intent: str = ""


class NodeConfigStatus(BaseModel):
    name: str
    status: Literal["success", "failed", "skipped"]
    commands_sent: int = 0
    error: str | None = None


class ConfigureResult(BaseModel):
    test_run_id: str
    nodes: dict[str, NodeConfigStatus]
    dry_run: bool
    timestamp: str
    status: Literal["success", "failed"]


class NodeReadinessStatus(BaseModel):
    name: str
    ssh_reachable: bool
    protocol_converged: bool
    retries: int
    duration_ms: int
    error: str | None = None


class ReadinessResult(BaseModel):
    test_run_id: str
    nodes: dict[str, NodeReadinessStatus]
    timestamp: str
    status: Literal["success", "failed", "timeout"]


class AssertionResult(BaseModel):
    name: str
    type: str
    passed: bool
    expected: int
    actual: int
    query_or_path: str
    operator: str
    error: str | None = None


class AssertionsResult(BaseModel):
    test_run_id: str
    assertions: list[AssertionResult]
    passed_count: int
    failed_count: int
    timestamp: str
    status: Literal["passed", "failed"]


class ArtifactEntry(BaseModel):
    name: str
    path: str
    type: Literal["file", "directory", "database"]
    size_bytes: int | None = None


class ArtifactsResult(BaseModel):
    test_run_id: str
    artifacts: list[ArtifactEntry]
    evidence_dir: str
    timestamp: str


class DestroyResult(BaseModel):
    test_run_id: str
    lab_name: str
    containers_removed: list[str]
    residual_resources: list[str]
    timestamp: str
    status: Literal["success", "failed", "partial"]
    error: str | None = None


class CoverageEntry(BaseModel):
    scenario: str
    topology_file: str              # which .clab.yaml was used
    platforms: list[str]           # all platforms present in the topology
    layers_tested: list[str]       # from scenario metadata.layers
    features_tested: list[str]     # from scenario metadata.features
    commands_expected: list[str]   # from scenario metadata.commands_expected
    node_count: int = 0
    link_count: int = 0
    status: Literal["not_tested", "passed", "failed", "blocked"]
    test_run_id: str
    last_run: str
    evidence_path: str
    collect_method: str = "exec_api"  # "nornir_ssh" or "exec_api" or "fallback"


class CoverageMatrix(BaseModel):
    entries: list[CoverageEntry]
    updated_at: str

    def get_matrix_summary(self) -> dict:
        """Return platform × feature pass/fail counts for quick reporting."""
        summary: dict[str, dict[str, int]] = {}
        for e in self.entries:
            for platform in e.platforms:
                summary.setdefault(platform, {"passed": 0, "failed": 0, "not_tested": 0})
                summary[platform][e.status] = summary[platform].get(e.status, 0) + 1
        return summary


# ─────────────────────────────────────────────────────────────────────────────
#  Session / Test Suite models  (lab_sessions/ + test_suites/)
#
#  The Session paradigm separates lab lifecycle from test lifecycle:
#    LabSession  — long-lived topology, deployed ONCE (idempotent)
#    TestSuite   — ordered test cases for one network layer (L2, L3, fault)
#    TestCase    — single test: queries + assertions + query_assertions
#                  (no deployment — assumes lab is already running)
# ─────────────────────────────────────────────────────────────────────────────


class SessionNode(BaseModel):
    """A node declared in SESSION.yaml with platform metadata for OLAV."""

    platform: str                   # arista_eos | juniper_junos | cisco_ios | paloalto_panos | fortinet
    site: str                       # A | B
    role: str                       # interconnect_switch | core_router | firewall | distribution_switch | access_switch
    mgmt_ip: str | None = None
    username: str = "admin"
    password: str = "admin"


class LabSession(BaseModel):
    """Parsed SESSION.yaml — long-lived topology declaration."""

    session: str
    description: str = ""
    topology_file: str              # relative path to topology.clab.yaml
    nodes: dict[str, SessionNode]
    collect_queries: list[ScenarioQuery] = []
    test_suites: list[str] = []     # relative paths to SUITE.yaml files
    readiness: dict = {}            # optional readiness checks (same schema as Scenario.readiness)


class TestCase(BaseModel):
    """
    A single test case within a suite. No lab deployment fields — the lab
    is already running. Has the same query/assertion fields as Scenario,
    minus topology/node/link/readiness.
    """

    name: str
    description: str = ""
    queries: list[ScenarioQuery] = []
    assertions: list[ScenarioAssertion] = []
    query_assertions: list[ScenarioQueryAssertion] = []

    # Fault injection (only used in fault_injection suite)
    pre_fault_queries: list[ScenarioQuery] = []
    pre_fault_assertions: list[ScenarioQueryAssertion] = []
    post_fault_queries: list[ScenarioQuery] = []
    post_fault_assertions: list[ScenarioQueryAssertion] = []
    fault: dict | None = None    # raw dict — parsed by inject_fault.py
    recover: dict | None = None  # raw dict — parsed by inject_fault.py


class TestSuite(BaseModel):
    """Parsed SUITE.yaml — ordered set of TestCase files for one network layer."""

    suite: str
    description: str = ""
    depends_on_session: str
    layer: str = ""                             # L2 | L3 | fault
    depends_on_suites: list[str] = []           # must pass before this runs
    precondition_queries: list[ScenarioQueryAssertion] = []
    test_cases: list[str]                       # relative paths to test case YAMLs


class TestCaseResult(BaseModel):
    name: str
    sql_result: AssertionsResult | None = None
    nl_result: QueryAssertionsResult | None = None
    status: Literal["passed", "failed", "skipped", "error"]
    error: str | None = None


class SuiteResult(BaseModel):
    suite: str
    test_cases: list[TestCaseResult]
    passed_count: int
    failed_count: int
    skipped_count: int = 0
    status: Literal["passed", "failed", "skipped"]
    timestamp: str


class SessionResult(BaseModel):
    session: str
    run_id: str
    suites: list[SuiteResult]
    passed_count: int
    failed_count: int
    status: Literal["passed", "failed"]
    timestamp: str
