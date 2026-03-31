"""CLAB CAB Agent — Phase 6 (10. CLAB_CAB_AGENT_DESIGN.md).

CAB = Change Advisory Board validation path.

Architecture:
    OpsNetworkXSandbox (Phase 5)
        └── CandidatePlan
                ↓
        CLABCABAgent
            ├── build_reduced_topology()   — topology_links → reduced lab spec
            ├── evaluate_assertions()       — pre/post-change assertions
            ├── compare_predictions()       — sandbox prediction vs observation
            ├── determine_verdict()         — 4-class verdict
            └── emit_artifact()             — CABEvidenceArtifact

Contracts (from §8 of design doc):
    Query:     semantic views as default source of truth
    Graph:     topology_links for lab topology construction
    Render:    canonical projections + schema_catalog
    Isolation: each test_run_id uses separate DuckDB
    Boundary:  no production writes — output is recommendation only

Verdict classes:
    RECOMMEND_HUMAN_EXECUTION
    RECOMMEND_HUMAN_EXECUTION_WITH_CONDITIONS
    NEEDS_REVIEW
    REJECT_CHANGE

Usage:
    from clab_cab import CLABCABAgent, CandidatePlan, AssertionSpec, AssertionType

    agent = CLABCABAgent.from_db(".olav/databases/main.duckdb")
    plan = CandidatePlan(
        change_intent="Adjust BGP local-preference on R1",
        actions=["route-map R1_OUT permit 10: set local-preference 200"],
        affected_devices=["R1"],
        blast_radius_estimate=["R1", "R2", "R3"],
        predicted_risk="medium",
        assertions=[
            AssertionSpec(AssertionType.BGP_SESSION_ESTABLISHED, device="R1", target="10.0.0.2"),
            AssertionSpec(AssertionType.BLAST_RADIUS_BOUNDED, device="*", target="R4", expected_value=False),
        ],
    )
    artifact = agent.run_validation(plan, dry_run=True)
    print(artifact.verdict)
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_LAB_SCRIPTS = _Path(__file__).parent.resolve()
if str(_LAB_SCRIPTS) not in _sys.path:
    _sys.path.insert(0, str(_LAB_SCRIPTS))

import asyncio
import logging
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Skill script imports — module-level names allow unittest.mock.patch.
# Imported lazily (inside _ensure_skill_imports) so unit tests without the
# skill directory on sys.path can still import this module.
# ---------------------------------------------------------------------------

_SKILL_IMPORTS_DONE = False

CLabClient = None       # patched by tests or loaded by _ensure_skill_imports
collect_exec = None     # patched by tests or loaded by _ensure_skill_imports
wait_readiness = None   # patched by tests or loaded by _ensure_skill_imports
DeployResult = None     # patched by tests or loaded by _ensure_skill_imports

# BGP convergence wait after exec config push — patch to 0 in unit tests
_BGP_CONVERGENCE_WAIT_SECS: int = 30

# SRL management plane poll timeout — patch to 0 in unit tests
_SRL_MGMT_POLL_TIMEOUT_SECS: int = 180

# ControlPlaneIR is a real dependency; imported here for testability (mock.patch target)
from olav.core.control_plane_ir import ControlPlaneIR  # noqa: E402

from clab_topology_render import render_clab_topology, build_iface_map_from_spec  # noqa: E402
from oc_payload_builder import snapshot_to_srl_config  # noqa: E402


NodeInfo = None  # loaded by _ensure_skill_imports


def _ensure_skill_imports() -> None:
    """Load CLAB skill modules into module-level names (once)."""
    global _SKILL_IMPORTS_DONE, CLabClient, collect_exec, wait_readiness, DeployResult, NodeInfo
    if _SKILL_IMPORTS_DONE:
        return

    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / ".agent" / "skills" / "containerlab-e2e" / "scripts"
        if candidate.exists():
            skill_path = str(candidate)
            if skill_path not in sys.path:
                sys.path.insert(0, skill_path)
            break

    import importlib
    _cc = importlib.import_module("clab_client")
    _ce = importlib.import_module("collect_exec")
    _wr = importlib.import_module("wait_readiness")
    _m  = importlib.import_module("models")

    CLabClient    = _cc.CLabClient
    collect_exec  = _ce.collect_exec
    wait_readiness = _wr.wait_readiness
    DeployResult  = _m.DeployResult
    NodeInfo      = _m.NodeInfo

    _SKILL_IMPORTS_DONE = True


# ---------------------------------------------------------------------------
# Assertion types
# ---------------------------------------------------------------------------


class AssertionType(str, Enum):
    """Assertion types the CAB path can evaluate.

    Based on §9 of the design doc.
    """

    BGP_SESSION_ESTABLISHED = "bgp_session_established"
    PREFIX_REACHABLE = "prefix_reachable"
    NEXTHOP_UNCHANGED = "nexthop_unchanged"
    OSPF_ADJACENCY_UP = "ospf_adjacency_up"
    INTERFACE_PRESENT = "interface_present"
    BLAST_RADIUS_BOUNDED = "blast_radius_bounded"


@dataclass
class AssertionSpec:
    """Pre-defined assertion that must hold after (or before) a change.

    Attributes:
        type:           What to check.
        device:         Device to check on. Use "*" for network-wide checks.
        target:         Peer IP / prefix / neighbor-id / device name (type-dependent).
        expected_value: Optional expected value (e.g. next-hop string, or False for
                        BLAST_RADIUS_BOUNDED meaning the target must NOT be affected).
        description:    Human-readable label for the assertion.
    """

    type: AssertionType
    device: str
    target: str
    expected_value: Any = None
    description: str = ""

    def __post_init__(self) -> None:
        if not self.description:
            self.description = f"{self.type.value} on {self.device} → {self.target}"


@dataclass
class AssertionResult:
    """Outcome of evaluating a single AssertionSpec."""

    spec: AssertionSpec
    passed: bool
    observed_value: Any = None
    detail: str = ""


# ---------------------------------------------------------------------------
# Candidate plan (from Ops sandbox)
# ---------------------------------------------------------------------------


@dataclass
class CandidatePlan:
    """Structured change plan emitted by OpsNetworkXSandbox.

    This is the primary input to the CLAB CAB agent.
    """

    change_intent: str
    actions: list[str]
    affected_devices: list[str]
    blast_radius_estimate: list[str]
    predicted_risk: str  # "low" | "medium" | "high" | "critical"
    assertions: list[AssertionSpec] = field(default_factory=list)
    requires_clab: bool = True
    source: str = "ops_networkx_sandbox"
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Lab topology spec
# ---------------------------------------------------------------------------


@dataclass
class LabNode:
    """Single node in the reduced lab topology."""

    name: str
    platform: str | None = None
    mgmt_ip: str | None = None
    role: str = "router"


@dataclass
class LabLink:
    """Single link in the reduced lab topology."""

    source: str
    target: str
    source_iface: str | None = None
    target_iface: str | None = None
    link_type: str | None = None


@dataclass
class LabTopologySpec:
    """Reduced ContainerLab topology for the affected blast radius.

    Only includes nodes and links relevant to the change; not the full network.
    """

    nodes: list[LabNode] = field(default_factory=list)
    links: list[LabLink] = field(default_factory=list)
    blast_radius_devices: list[str] = field(default_factory=list)

    def node_names(self) -> set[str]:
        return {n.name for n in self.nodes}

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [
                {"name": n.name, "platform": n.platform, "mgmt_ip": n.mgmt_ip, "role": n.role}
                for n in self.nodes
            ],
            "links": [
                {
                    "source": lk.source,
                    "target": lk.target,
                    "source_iface": lk.source_iface,
                    "target_iface": lk.target_iface,
                    "link_type": lk.link_type,
                }
                for lk in self.links
            ],
            "blast_radius_devices": self.blast_radius_devices,
        }


# ---------------------------------------------------------------------------
# Prediction match + verdict
# ---------------------------------------------------------------------------


class PredictionMatch(str, Enum):
    """How well sandbox predictions matched observed lab results."""

    FULL = "full"
    PARTIAL = "partial"
    MISMATCH = "mismatch"
    UNKNOWN = "unknown"          # dry-run: lab not deployed, no observations


class CABVerdict(str, Enum):
    """Four-class CAB verdict (§11 of design doc)."""

    RECOMMEND_HUMAN_EXECUTION = "RECOMMEND_HUMAN_EXECUTION"
    RECOMMEND_HUMAN_EXECUTION_WITH_CONDITIONS = "RECOMMEND_HUMAN_EXECUTION_WITH_CONDITIONS"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    REJECT_CHANGE = "REJECT_CHANGE"


# ---------------------------------------------------------------------------
# Evidence artifact
# ---------------------------------------------------------------------------


@dataclass
class CABEvidenceArtifact:
    """Full CAB evidence artifact (§12 of design doc).

    Serialisable to JSON. Explicitly states whether results came from
    lab observation or sandbox reasoning only.
    """

    lab_id: str
    timestamp: str
    change_intent: str
    candidate_plan_source: str
    query_contract: str
    graph_contract: str
    render_contract: str
    predicted_risk: str
    observed_risk: str
    prediction_match: PredictionMatch
    assertions_passed: int
    assertions_failed: int
    assertion_details: list[dict[str, Any]]
    verdict: CABVerdict
    recommendation: str
    dry_run: bool
    lab_deployed: bool
    audit_run_id: str
    blast_radius_devices: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    lab_name: str | None = None
    evidence_db_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "lab_id": self.lab_id,
            "timestamp": self.timestamp,
            "change_intent": self.change_intent,
            "candidate_plan_source": self.candidate_plan_source,
            "query_contract": self.query_contract,
            "graph_contract": self.graph_contract,
            "render_contract": self.render_contract,
            "predicted_risk": self.predicted_risk,
            "observed_risk": self.observed_risk,
            "prediction_match": self.prediction_match.value,
            "assertions": {
                "passed": self.assertions_passed,
                "failed": self.assertions_failed,
                "details": self.assertion_details,
            },
            "verdict": self.verdict.value,
            "recommendation": self.recommendation,
            "dry_run": self.dry_run,
            "lab_deployed": self.lab_deployed,
            "blast_radius_devices": self.blast_radius_devices,
            "warnings": self.warnings,
            "audit_run_id": self.audit_run_id,
            "production_execution": "HUMAN RESPONSIBILITY — system output is advisory only",
        }


# ---------------------------------------------------------------------------
# CLAB CAB Agent
# ---------------------------------------------------------------------------


class CLABCABAgent:
    """Change Advisory Board validation agent.

    Receives a CandidatePlan from OpsNetworkXSandbox, builds a reduced
    ContainerLab topology for the blast radius, evaluates assertions, and
    emits a structured CABEvidenceArtifact with a 4-class verdict.

    Execution boundary:
        This agent MUST NOT write configuration to production devices.
        Even in non-dry-run mode, all writes go to the isolated lab only.
        The artifact is advisory; production execution is a human responsibility.
    """

    def __init__(self, snapshot: Any) -> None:
        """Initialise with a pre-loaded ControlPlaneSnapshot."""
        self.snapshot = snapshot

    @classmethod
    def from_db(cls, db_path: str | Path = ".olav/databases/main.duckdb") -> "CLABCABAgent":
        """Build agent by loading snapshot from DuckDB."""
        from olav.core.control_plane_ir import ControlPlaneIR

        ir = ControlPlaneIR(db_path)
        snapshot = ir.build()
        agent = cls(snapshot)
        agent._db_path = str(db_path)  # stored for CABConfigExtractor in run_validation_live
        return agent

    # ------------------------------------------------------------------
    # Topology reduction
    # ------------------------------------------------------------------

    def build_reduced_topology(
        self,
        devices: list[str],
        include_neighbors: bool = True,
    ) -> LabTopologySpec:
        """Build a reduced lab topology covering only the specified devices.

        If include_neighbors=True (default) also pulls in devices directly
        adjacent to any device in the list, ensuring the blast radius is
        properly bounded.

        Contract: uses topology_links (graph contract §8.2).
        """
        target_set: set[str] = set(devices)

        # Collect direct neighbors for each target device
        if include_neighbors:
            for link in self.snapshot.topology_links:
                if link.source in target_set:
                    target_set.add(link.target)
                elif link.target in target_set:
                    target_set.add(link.source)

        # Build device index from snapshot
        device_index = {d.name: d for d in self.snapshot.devices}

        nodes = []
        for name in sorted(target_set):
            dev = device_index.get(name)
            nodes.append(
                LabNode(
                    name=name,
                    platform=dev.platform if dev else None,
                    mgmt_ip=dev.mgmt_ip if dev else None,
                )
            )

        # Filter links to only those within the target set
        links = []
        for link in self.snapshot.topology_links:
            if link.source in target_set and link.target in target_set:
                links.append(
                    LabLink(
                        source=link.source,
                        target=link.target,
                        source_iface=link.source_iface,
                        target_iface=link.target_iface,
                        link_type=link.link_type,
                    )
                )

        spec = LabTopologySpec(
            nodes=nodes,
            links=links,
            blast_radius_devices=sorted(target_set),
        )
        logger.debug(
            "Reduced topology: %d nodes, %d links for devices %s",
            len(nodes),
            len(links),
            devices,
        )
        return spec

    # ------------------------------------------------------------------
    # Assertion evaluation
    # ------------------------------------------------------------------

    def evaluate_assertions(
        self,
        assertions: list[AssertionSpec],
        blast_radius: list[str] | None = None,
    ) -> list[AssertionResult]:
        """Evaluate assertions against the current snapshot.

        In dry-run mode this evaluates the pre-change (current) state.
        In a full run this would be called twice: pre and post change.
        """
        results = []
        for spec in assertions:
            result = self._eval_one(spec, blast_radius or [])
            results.append(result)
            logger.debug(
                "Assertion %s → %s (observed: %s)",
                spec.description,
                "PASS" if result.passed else "FAIL",
                result.observed_value,
            )
        return results

    def _eval_one(
        self,
        spec: AssertionSpec,
        blast_radius: list[str],
    ) -> AssertionResult:
        if spec.type == AssertionType.BGP_SESSION_ESTABLISHED:
            return self._assert_bgp_established(spec)
        if spec.type == AssertionType.PREFIX_REACHABLE:
            return self._assert_prefix_reachable(spec)
        if spec.type == AssertionType.NEXTHOP_UNCHANGED:
            return self._assert_nexthop(spec)
        if spec.type == AssertionType.OSPF_ADJACENCY_UP:
            return self._assert_ospf_up(spec)
        if spec.type == AssertionType.INTERFACE_PRESENT:
            return self._assert_interface_present(spec)
        if spec.type == AssertionType.BLAST_RADIUS_BOUNDED:
            return self._assert_blast_bounded(spec, blast_radius)
        return AssertionResult(spec=spec, passed=False, detail=f"Unknown assertion type: {spec.type}")

    def _assert_bgp_established(self, spec: AssertionSpec) -> AssertionResult:
        """BGP session to spec.target must be Established on spec.device."""
        for n in self.snapshot.bgp_neighbors:
            if n.device == spec.device and n.peer_ip == spec.target:
                passed = n.state.lower() in ("established", "up")
                return AssertionResult(
                    spec=spec,
                    passed=passed,
                    observed_value=n.state,
                    detail=f"BGP {spec.device} → {spec.target}: state={n.state}",
                )
        return AssertionResult(
            spec=spec,
            passed=False,
            observed_value=None,
            detail=f"BGP session {spec.device} → {spec.target} not found in snapshot",
        )

    def _assert_prefix_reachable(self, spec: AssertionSpec) -> AssertionResult:
        """spec.target prefix must have a route on spec.device."""
        for r in self.snapshot.routes:
            if r.device == spec.device and spec.target in r.network:
                return AssertionResult(
                    spec=spec,
                    passed=True,
                    observed_value=r.next_hop,
                    detail=f"Route {spec.target} found on {spec.device} via {r.next_hop}",
                )
        # Partial match: prefix is a subnet of a known route
        prefix_net = spec.target.split("/")[0]
        for r in self.snapshot.routes:
            if r.device == spec.device and prefix_net in r.network:
                return AssertionResult(
                    spec=spec,
                    passed=True,
                    observed_value=r.next_hop,
                    detail=f"Route covering {spec.target} found on {spec.device}",
                )
        return AssertionResult(
            spec=spec,
            passed=False,
            observed_value=None,
            detail=f"No route to {spec.target} on {spec.device}",
        )

    def _assert_nexthop(self, spec: AssertionSpec) -> AssertionResult:
        """Next-hop for spec.target network on spec.device must equal expected_value."""
        for r in self.snapshot.routes:
            if r.device == spec.device and spec.target in r.network:
                observed = r.next_hop
                passed = observed == spec.expected_value
                return AssertionResult(
                    spec=spec,
                    passed=passed,
                    observed_value=observed,
                    detail=f"Next-hop for {spec.target} on {spec.device}: {observed} (expected {spec.expected_value})",
                )
        return AssertionResult(
            spec=spec,
            passed=False,
            observed_value=None,
            detail=f"Route {spec.target} not found on {spec.device}",
        )

    def _assert_ospf_up(self, spec: AssertionSpec) -> AssertionResult:
        """OSPF adjacency to spec.target (neighbor_id) must be Full/FULL on spec.device."""
        for n in self.snapshot.ospf_neighbors:
            if n.device == spec.device and (n.neighbor_id == spec.target or n.neighbor_ip == spec.target):
                passed = n.state.lower() in ("full", "2way", "up")
                return AssertionResult(
                    spec=spec,
                    passed=passed,
                    observed_value=n.state,
                    detail=f"OSPF {spec.device} → {spec.target}: state={n.state}",
                )
        return AssertionResult(
            spec=spec,
            passed=False,
            observed_value=None,
            detail=f"OSPF neighbor {spec.device} → {spec.target} not found in snapshot",
        )

    def _assert_interface_present(self, spec: AssertionSpec) -> AssertionResult:
        """Interface spec.target must appear in topology links for spec.device."""
        for link in self.snapshot.topology_links:
            if link.source == spec.device and link.source_iface == spec.target:
                return AssertionResult(
                    spec=spec, passed=True, observed_value=spec.target,
                    detail=f"Interface {spec.target} present on {spec.device}",
                )
            if link.target == spec.device and link.target_iface == spec.target:
                return AssertionResult(
                    spec=spec, passed=True, observed_value=spec.target,
                    detail=f"Interface {spec.target} present on {spec.device}",
                )
        return AssertionResult(
            spec=spec, passed=False, observed_value=None,
            detail=f"Interface {spec.target} not found in topology for {spec.device}",
        )

    def _assert_blast_bounded(
        self,
        spec: AssertionSpec,
        blast_radius: list[str],
    ) -> AssertionResult:
        """spec.target device must NOT appear in blast_radius (expected_value=False)
        or MUST appear (expected_value=True).

        Default: expected_value=False means target must not be in blast radius.
        """
        in_blast = spec.target in blast_radius
        expected_in = spec.expected_value if spec.expected_value is not None else False
        passed = in_blast == expected_in
        return AssertionResult(
            spec=spec,
            passed=passed,
            observed_value=in_blast,
            detail=(
                f"{spec.target} {'IS' if in_blast else 'IS NOT'} in blast radius "
                f"(expected: {'in' if expected_in else 'not in'})"
            ),
        )

    # ------------------------------------------------------------------
    # Prediction comparison
    # ------------------------------------------------------------------

    def compare_predictions(
        self,
        plan: CandidatePlan,
        assertion_results: list[AssertionResult],
        lab_deployed: bool = False,
    ) -> PredictionMatch:
        """Compare sandbox predictions with assertion results.

        In dry-run mode (lab_deployed=False), returns UNKNOWN because we
        have no post-change observations to compare against.

        In a full run, FULL means all critical assertions passed and risk
        matched; PARTIAL means most passed; MISMATCH means significant
        divergence from predictions.
        """
        if not lab_deployed:
            return PredictionMatch.UNKNOWN

        if not assertion_results:
            return PredictionMatch.UNKNOWN

        total = len(assertion_results)
        passed = sum(1 for r in assertion_results if r.passed)
        pass_rate = passed / total

        if pass_rate == 1.0:
            return PredictionMatch.FULL
        if pass_rate >= 0.7:
            return PredictionMatch.PARTIAL
        return PredictionMatch.MISMATCH

    # ------------------------------------------------------------------
    # Verdict determination
    # ------------------------------------------------------------------

    def determine_verdict(
        self,
        plan: CandidatePlan,
        assertion_results: list[AssertionResult],
        prediction_match: PredictionMatch,
        dry_run: bool = True,
    ) -> tuple[CABVerdict, str]:
        """Determine CAB verdict and generate human-readable recommendation.

        Verdict logic:
            RECOMMEND_HUMAN_EXECUTION:            all assertions passed, risk ≤ medium
            RECOMMEND_HUMAN_EXECUTION_WITH_CONDITIONS: pass_rate ≥ 0.8, risk ≤ high, PARTIAL match
            NEEDS_REVIEW:                         pass_rate ≥ 0.5, or risk=high, or MISMATCH
            REJECT_CHANGE:                        critical assertion failure or pass_rate < 0.5
        """
        total = len(assertion_results)
        passed = sum(1 for r in assertion_results if r.passed)
        pass_rate = passed / total if total > 0 else 1.0

        risk = plan.predicted_risk.lower()
        critical_failure = any(
            not r.passed
            and r.spec.type in (AssertionType.BGP_SESSION_ESTABLISHED, AssertionType.OSPF_ADJACENCY_UP)
            for r in assertion_results
        )

        # Reject on critical protocol assertion failure
        if critical_failure or pass_rate < 0.5:
            verdict = CABVerdict.REJECT_CHANGE
            rec = (
                f"REJECT: Critical assertion failure detected ({passed}/{total} passed). "
                "Do not proceed without root-cause investigation."
            )

        # Needs review on high risk or significant failures or mismatch
        elif risk == "critical" or (
            prediction_match == PredictionMatch.MISMATCH and not dry_run
        ) or pass_rate < 0.8:
            verdict = CABVerdict.NEEDS_REVIEW
            rec = (
                f"NEEDS REVIEW: {passed}/{total} assertions passed, risk={risk}, "
                f"prediction_match={prediction_match.value}. "
                "Human review required before execution."
            )

        # Conditional approval on high risk or partial match with good pass rate
        elif risk == "high" or prediction_match == PredictionMatch.PARTIAL:
            verdict = CABVerdict.RECOMMEND_HUMAN_EXECUTION_WITH_CONDITIONS
            rec = (
                f"CONDITIONAL: {passed}/{total} assertions passed. "
                f"Risk={risk}. Proceed with caution and monitoring."
            )

        # Full recommendation on clean state
        else:
            verdict = CABVerdict.RECOMMEND_HUMAN_EXECUTION
            rec = (
                f"RECOMMEND: All {total} assertions passed, risk={risk}. "
                "Recommend human engineer proceed with execution."
            )

        if dry_run:
            rec += " [DRY RUN — lab not deployed, pre-change state only]"

        return verdict, rec

    # ------------------------------------------------------------------
    # Observed risk inference
    # ------------------------------------------------------------------

    def _infer_observed_risk(
        self,
        assertion_results: list[AssertionResult],
        plan: CandidatePlan,
    ) -> str:
        """Infer observed risk from assertion results.

        When lab is not deployed, returns the predicted risk (no new data).
        """
        if not assertion_results:
            return plan.predicted_risk

        total = len(assertion_results)
        failed = sum(1 for r in assertion_results if not r.passed)
        fail_rate = failed / total

        if fail_rate == 0:
            return "low"
        if fail_rate <= 0.2:
            return "medium"
        if fail_rate <= 0.5:
            return "high"
        return "critical"

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run_validation(
        self,
        plan: CandidatePlan,
        dry_run: bool = True,
        test_run_id: str | None = None,
    ) -> CABEvidenceArtifact:
        """Run the full CAB validation pipeline.

        dry_run=True (default):
            - Builds reduced topology
            - Evaluates assertions against current (pre-change) snapshot
            - Does NOT deploy CLAB lab
            - Returns advisory artifact with DRY RUN note

        dry_run=False:
            - Reserved for future CLAB integration
            - Would deploy → push config → collect → assert → compare → destroy
            - Currently raises NotImplementedError

        Returns:
            CABEvidenceArtifact with verdict, evidence, and recommendation.
            Execution of the change remains the human engineer's responsibility.
        """
        if not dry_run:
            return asyncio.run(
                self.run_validation_live(
                    plan,
                    api_server=getattr(self, "_api_server", "http://192.168.100.12:8080/api/v1"),
                    token=getattr(self, "_token", ""),
                    test_run_id=test_run_id,
                )
            )

        run_id = test_run_id or str(uuid.uuid4())
        lab_id = f"cab-dry-{plan.affected_devices[0] if plan.affected_devices else 'unknown'}-{run_id[:8]}"
        timestamp = datetime.now(timezone.utc).isoformat()

        logger.info("CAB validation: lab_id=%s dry_run=%s", lab_id, dry_run)

        # Step 1: Build reduced topology
        topology = self.build_reduced_topology(
            devices=plan.blast_radius_estimate or plan.affected_devices,
        )
        logger.info(
            "Reduced topology: %d nodes, %d links",
            len(topology.nodes),
            len(topology.links),
        )

        # Step 2: Evaluate assertions against current snapshot (pre-change)
        assertion_results = self.evaluate_assertions(
            assertions=plan.assertions,
            blast_radius=topology.blast_radius_devices,
        )

        # Step 3: Compare predictions (UNKNOWN in dry-run)
        prediction_match = self.compare_predictions(
            plan=plan,
            assertion_results=assertion_results,
            lab_deployed=False,
        )

        # Step 4: Infer observed risk
        observed_risk = self._infer_observed_risk(assertion_results, plan)

        # Step 5: Determine verdict
        verdict, recommendation = self.determine_verdict(
            plan=plan,
            assertion_results=assertion_results,
            prediction_match=prediction_match,
            dry_run=dry_run,
        )

        passed = sum(1 for r in assertion_results if r.passed)
        failed = len(assertion_results) - passed

        warnings: list[str] = []
        if dry_run:
            warnings.append(
                "Dry-run mode: assertions evaluated against pre-change snapshot only. "
                "Lab was not deployed. Prediction match is UNKNOWN."
            )
        if plan.predicted_risk in ("high", "critical"):
            warnings.append(f"High-risk change ({plan.predicted_risk}) — requires senior engineer review.")

        artifact = CABEvidenceArtifact(
            lab_id=lab_id,
            timestamp=timestamp,
            change_intent=plan.change_intent,
            candidate_plan_source=plan.source,
            query_contract="semantic_views",
            graph_contract="topology_links",
            render_contract="schema_catalog+canonical_projection",
            predicted_risk=plan.predicted_risk,
            observed_risk=observed_risk,
            prediction_match=prediction_match,
            assertions_passed=passed,
            assertions_failed=failed,
            assertion_details=[
                {
                    "type": r.spec.type.value,
                    "device": r.spec.device,
                    "target": r.spec.target,
                    "passed": r.passed,
                    "observed_value": r.observed_value,
                    "detail": r.detail,
                }
                for r in assertion_results
            ],
            verdict=verdict,
            recommendation=recommendation,
            dry_run=dry_run,
            lab_deployed=False,
            blast_radius_devices=topology.blast_radius_devices,
            warnings=warnings,
            audit_run_id=run_id,
        )

        logger.info(
            "CAB verdict: %s | assertions %d/%d | risk %s→%s | match=%s",
            verdict.value,
            passed,
            len(assertion_results),
            plan.predicted_risk,
            observed_risk,
            prediction_match.value,
        )
        return artifact

    # ------------------------------------------------------------------
    # Live pipeline (dry_run=False)
    # ------------------------------------------------------------------

    async def run_validation_live(
        self,
        plan: CandidatePlan,
        api_server: str,
        token: str,
        srl_image: str = "ghcr.io/nokia/srlinux",
        evidence_dir: Path | None = None,
        test_run_id: str | None = None,
    ) -> CABEvidenceArtifact:
        """Full live pipeline: render → deploy → collect → assert → destroy.

        Steps (§16):
            1. Build reduced topology for blast radius
            2. Write SRL startup config files per node
            3. Render .clab.yaml with startup-config paths
            4. Deploy lab via CLAB API
            5. Wait for nodes ready (exec hostname poll)
            6. Collect post-deploy state into isolated DuckDB
            7. Load post-deploy snapshot via ControlPlaneIR
            8. Evaluate assertions against observed state
            9. Compare sandbox predictions vs observed
            10. Destroy lab (always, in finally block)
            11. Return CABEvidenceArtifact with lab_deployed=True

        Args:
            plan:         CandidatePlan from OpsNetworkXSandbox.
            api_server:   CLAB REST API base URL.
            token:        Bearer token for CLAB API auth.
            srl_image:    SR Linux image (default: ghcr.io/nokia/srlinux).
            evidence_dir: Directory for configs + isolated DB. Defaults to
                          /tmp/cab_{run_id}.
            test_run_id:  Optional run ID; UUID generated if not provided.
        """
        # Allow tests to patch these module-level names
        import clab_cab as _self_mod
        _CLabClient    = _self_mod.CLabClient
        _collect_exec  = _self_mod.collect_exec
        _wait_readiness = _self_mod.wait_readiness
        _DeployResult  = _self_mod.DeployResult
        _NodeInfo      = _self_mod.NodeInfo

        # If module-level names are None (not yet loaded), pull from skill
        if _CLabClient is None:
            _ensure_skill_imports()
            _CLabClient    = _self_mod.CLabClient
            _collect_exec  = _self_mod.collect_exec
            _wait_readiness = _self_mod.wait_readiness
            _DeployResult  = _self_mod.DeployResult
            _NodeInfo      = _self_mod.NodeInfo

        run_id = test_run_id or str(uuid.uuid4())
        evidence_dir = Path(evidence_dir or f"/tmp/cab_{run_id}")
        evidence_dir.mkdir(parents=True, exist_ok=True)

        config_dir = evidence_dir / "configs"
        config_dir.mkdir(exist_ok=True)

        isolated_db = str(evidence_dir / f"cab_{run_id}.duckdb")
        timestamp = datetime.now(timezone.utc).isoformat()

        logger.info("CAB live: run_id=%s evidence_dir=%s", run_id, evidence_dir)

        # Step 1: Build reduced topology
        spec = self.build_reduced_topology(
            devices=plan.blast_radius_estimate or plan.affected_devices,
        )
        lab_name = run_id[:12]

        # Step 2: OC extraction → SRL JSON config (primary: no LLM, just iface substitution)
        # iface_map is derived from the same topology spec used to build the CLAB YAML,
        # ensuring real interface names (GigabitEthernet1) are translated to SRL
        # ethernet-1/N names consistently between the topology and the config.
        iface_map = build_iface_map_from_spec(spec)
        db_path = getattr(self, "_db_path", None)

        # LLM function — used only for: JSON repair on import failure, vendor extension translation
        _llm_fn = None
        try:
            from olav.core.llm import LLMFactory
            _llm = LLMFactory.get_chat_model(agent_id="srl_renderer", temperature=0)
            _llm_fn = lambda prompt: _llm.invoke([("human", prompt)]).content
            logger.debug("CAB live: LLM available (for JSON repair + vendor extensions)")
        except Exception as _exc:
            logger.debug("CAB live: LLM not available (%s) — JSON repair disabled", _exc)

        node_json_configs: dict[str, dict] = {}   # {device: srl_json} for JSON import path
        node_vendor_fields: dict[str, list] = {}  # {device: [_unmapped vendor dicts]}
        node_configs: dict[str, str] = {}         # fallback: {device: set/ commands string}

        if db_path:
            from cab_config_extractor import CABConfigExtractor
            from oc_config_builder import build_srl_config_json

            extractor = CABConfigExtractor(db_path=db_path)
            # Primary path: nested OC records → SRL JSON (no LLM, just structural transform)
            oc_records_by_device = extractor.extract_oc_records_from_snapshot(
                list(spec.node_names())
            )
            for device, oc_records in oc_records_by_device.items():
                srl_json, vendor_fields = build_srl_config_json(device, oc_records, iface_map)
                node_json_configs[device] = srl_json
                node_vendor_fields[device] = vendor_fields

            # Vendor extension fields: LLM translates to OC paths → merge into JSON
            if _llm_fn:
                for device, vf in node_vendor_fields.items():
                    if vf:
                        extra = _llm_translate_vendor_fields(device, vf, _llm_fn)
                        if extra and isinstance(extra, dict):
                            _merge_into_srl_json(node_json_configs.setdefault(device, {}), extra)
                            logger.debug("CAB live: merged vendor extensions for %s", device)

            logger.info(
                "CAB live: SRL JSON configs built for %d nodes (OC direct import path)",
                len(node_json_configs),
            )
        else:
            # Fallback: snapshot-based set/ commands (no db_path available)
            node_configs = {
                node: snapshot_to_srl_config(node, self.snapshot)
                for node in spec.node_names()
            }
            logger.info("CAB live: SRL configs built for %d nodes (snapshot fallback)", len(node_configs))

        # Step 3: Render .clab.yaml without startup-config paths
        # (config pushed via exec after nodes boot — avoids remote-path constraint)
        topology_content = render_clab_topology(
            spec, lab_name=lab_name, srl_image=srl_image,
        )

        # Step 4: Deploy lab
        client = await _CLabClient.build(api_server, token)
        deploy_response = await client.deploy(topology_content, reconfigure=True)
        deployed_lab_name = next(iter(deploy_response)) if isinstance(deploy_response, dict) else lab_name

        # Construct minimal DeployResult using the real NodeInfo model (or mock in tests)
        def _make_node_info(node):
            if _NodeInfo is not None:
                return _NodeInfo(
                    name=node.name,
                    platform=node.platform or "srl",
                    mgmt_cloud_ip=node.mgmt_ip or "127.0.0.1",
                    mgmt_cloud_port=22,
                    username="admin",
                    password="NokiaSrl1!",
                )
            # Fallback for tests where NodeInfo is mocked/None
            return {"name": node.name, "platform": node.platform or "srl",
                    "mgmt_cloud_ip": node.mgmt_ip or "127.0.0.1", "mgmt_cloud_port": 22,
                    "username": "admin", "password": "NokiaSrl1!"}

        deploy_result = _DeployResult(
            test_run_id=run_id,
            lab_name=deployed_lab_name,
            api_server=api_server,
            nodes={node.name: _make_node_info(node) for node in spec.nodes},
            timestamp=timestamp,
            status="success",
        )

        lab_deployed = False
        assertion_results: list = []
        prediction_match = PredictionMatch.UNKNOWN

        import asyncio as _asyncio

        try:
            # Step 5: Boot readiness + EARLY SRL topology.yml fix.
            # The CLAB REST API bind-mount bug (0.74.1) creates /tmp/topology.yml as
            # an empty directory; sr_device_mgr crashes on boot. The fix MUST arrive
            # within ~1-2s of container first response — before sr_app_mgr gives up
            # restarting sr_device_mgr. We poll hostname every 1s and apply the fix
            # on the very first successful response, then wait for all nodes ready.
            await _boot_and_fix_srl(
                client, deployed_lab_name, timeout=_SRL_MGMT_POLL_TIMEOUT_SECS
            )
            lab_deployed = True
            logger.info("CAB live: lab %s ready + SRL management plane up", deployed_lab_name)

            # Step 5.5: Push per-node SRL config via exec
            # Primary path: JSON import (load json) — atomic, no per-leaf translation
            # Fallback path: set/ commands (snapshot fallback or if no OC records)
            if node_json_configs:
                write_cmd, apply_cmd = _build_json_import_script(node_json_configs)
                path_label = "JSON import"
            else:
                write_cmd, apply_cmd = _build_exec_script_from_configs(node_configs)
                path_label = "set/ commands"

            if write_cmd:
                logger.info("CAB live: writing SRL config files to containers (%s)", path_label)
                await client.exec_command(deployed_lab_name, write_cmd, timeout=30.0)
                logger.info("CAB live: applying SRL config via sr_cli (%s)", path_label)
                apply_resp = await client.exec_command(deployed_lab_name, apply_cmd, timeout=60.0)

                # Log per-node apply outcome; collect failures for LLM repair
                failed_nodes: list[str] = []
                if isinstance(apply_resp, dict):
                    for node_name, node_results in apply_resp.items():
                        out = node_results[0].get("stdout", "") if node_results else ""
                        if "CFG_RC=0" in out:
                            logger.info("CAB live: config applied on %s (CFG_RC=0)", node_name)
                        elif "CFG_SKIP" in out:
                            logger.info("CAB live: no config file for %s (skipped)", node_name)
                        else:
                            logger.warning("CAB live: config apply failed on %s: %s", node_name, out[:200])
                            failed_nodes.append(node_name)

                # LLM JSON repair: on import failure, LLM fixes the JSON → retry once
                if failed_nodes and _llm_fn and node_json_configs:
                    repaired: dict[str, dict] = {}
                    for node_name in failed_nodes:
                        node_results = apply_resp.get(node_name, [{}]) if isinstance(apply_resp, dict) else [{}]
                        err_out = node_results[0].get("stdout", "") if node_results else ""
                        original_json = node_json_configs.get(node_name, {})
                        fixed = _llm_repair_srl_json(node_name, original_json, err_out, _llm_fn)
                        if fixed:
                            repaired[node_name] = fixed

                    if repaired:
                        logger.info("CAB live: retrying %d nodes with LLM-repaired JSON", len(repaired))
                        rw_cmd, ra_cmd = _build_json_import_script(repaired)
                        if rw_cmd:
                            await client.exec_command(deployed_lab_name, rw_cmd, timeout=30.0)
                            retry_resp = await client.exec_command(deployed_lab_name, ra_cmd, timeout=60.0)
                            if isinstance(retry_resp, dict):
                                for node_name, nr in retry_resp.items():
                                    out = nr[0].get("stdout", "") if nr else ""
                                    level = logger.info if "CFG_RC=0" in out else logger.warning
                                    level("CAB live: repair retry on %s: %s", node_name, out[:100])

                # Allow BGP to converge before collection
                await _asyncio.sleep(_BGP_CONVERGENCE_WAIT_SECS)
                logger.info("CAB live: config pushed, BGP convergence wait done")

            # Step 6: Collect post-deploy state
            # Build a minimal ExecutionPlan-like object for collect_exec
            plan_obj = _build_execution_plan_proxy(run_id, spec, plan)
            await _collect_exec(
                deploy_result,
                plan_obj,
                db_path=isolated_db,
                evidence_dir=evidence_dir,
            )
            logger.info("CAB live: collection done → %s", isolated_db)

            # Step 7: Load post-deploy snapshot (use module-level name for testability)
            # collect_exec may produce no data (e.g. mgmt plane not ready) → empty snapshot
            try:
                post_ir = _self_mod.ControlPlaneIR(isolated_db)
                post_snapshot = post_ir.build()
            except Exception as exc:
                logger.warning("CAB live: could not load post-deploy snapshot (%s) — using empty", exc)
                from olav.core.control_plane_ir import ControlPlaneSnapshot
                post_snapshot = ControlPlaneSnapshot()

            # Step 8: Evaluate assertions against observed state
            post_agent = CLABCABAgent(post_snapshot)
            assertion_results = post_agent.evaluate_assertions(
                plan.assertions,
                blast_radius=spec.blast_radius_devices,
            )

            # Step 9: Compare predictions
            prediction_match = self.compare_predictions(
                plan, assertion_results, lab_deployed=True,
            )

        finally:
            # Step 10: Always destroy lab
            try:
                await client.destroy(deployed_lab_name)
                logger.info("CAB live: lab %s destroyed", deployed_lab_name)
            except Exception as exc:
                logger.warning("CAB live: destroy failed (non-fatal): %s", exc)

        # Step 11: Build artifact
        observed_risk = self._infer_observed_risk(assertion_results, plan)
        verdict, recommendation = self.determine_verdict(
            plan, assertion_results, prediction_match, dry_run=False,
        )

        passed = sum(1 for r in assertion_results if r.passed)
        failed = len(assertion_results) - passed

        return CABEvidenceArtifact(
            lab_id=f"cab-live-{plan.affected_devices[0] if plan.affected_devices else 'unknown'}-{run_id[:8]}",
            timestamp=timestamp,
            change_intent=plan.change_intent,
            candidate_plan_source=plan.source,
            query_contract="semantic_views",
            graph_contract="topology_links",
            render_contract="srl_startup_cfg+cab_config_extractor",
            predicted_risk=plan.predicted_risk,
            observed_risk=observed_risk,
            prediction_match=prediction_match,
            assertions_passed=passed,
            assertions_failed=failed,
            assertion_details=[
                {
                    "type": r.spec.type.value,
                    "device": r.spec.device,
                    "target": r.spec.target,
                    "passed": r.passed,
                    "observed_value": r.observed_value,
                    "detail": r.detail,
                }
                for r in assertion_results
            ],
            verdict=verdict,
            recommendation=recommendation,
            dry_run=False,
            lab_deployed=lab_deployed,
            blast_radius_devices=spec.blast_radius_devices,
            warnings=[],
            audit_run_id=run_id,
            lab_name=deployed_lab_name,
            evidence_db_path=isolated_db,
        )


_SRL_VSRL_TOPOLOGY_YML = """\
chassis_configuration:
    "chassis_type": 74
    "base_mac" : 00:01:01:00:00:00
    "cpm_card_type" : 47
    "product_name": "vsrl"
    "mac_cout": 10

slot_configuration:
    1:
        "card_type": 47
        "mda_type": 10
"""


async def _fix_srl_topology_yml(client: "CLabClient", lab_name: str) -> None:
    """Fix the CLAB REST API bug that bind-mounts /tmp/topology.yml as a directory.

    CLAB REST API 0.2.2 creates /tmp/topology.yml as an empty directory inside
    SRL containers (Docker bind-mount with no pre-existing host file). SRL's
    sr_device_mgr reads this file to build virtual chassis information; if it's
    a directory the process crashes and loops, keeping the management plane down.

    Fix: umount the bind mount, rmdir the empty dir, write the correct vsrl
    chassis YAML, then kill the crashing sr_device_mgr so sr_app_mgr restarts
    it cleanly.

    Safe to call on non-SRL topologies — if umount fails the command exits 0.
    """
    import base64 as _b64

    b64 = _b64.b64encode(_SRL_VSRL_TOPOLOGY_YML.encode()).decode()
    # umount/rmdir are best-effort (use ';' not '&&') — if topology.yml is already
    # a regular file (CLAB fixed the bug in a later version), umount fails silently
    # and we still overwrite the file. Only the base64 write step uses '&&' to stop
    # on actual I/O error; the kill step is always best-effort.
    fix_cmd = (
        f"bash -c '"
        f"umount /tmp/topology.yml 2>/dev/null; "
        f"rmdir /tmp/topology.yml 2>/dev/null; "
        f"echo {b64} | base64 -d > /tmp/topology.yml && "
        f"kill $(pgrep -f sr_device_mgr) 2>/dev/null; "
        f"exit 0"
        f"'"
    )
    try:
        await client.exec_command(lab_name, fix_cmd, timeout=20.0)
        logger.debug("_fix_srl_topology_yml: applied to lab %s", lab_name)
    except Exception as exc:
        logger.debug("_fix_srl_topology_yml: skipped (%s)", exc)


async def _boot_and_fix_srl(
    client: "CLabClient",
    lab_name: str,
    timeout: int = 180,
) -> None:
    """Apply topology.yml fix and restart sr_app_mgr so sr_device_mgr starts.

    CLAB REST API 0.74.1 bind-mount bug:
        /tmp/topology.yml is mounted as an empty directory.
        sr_app_mgr tries to start sr_device_mgr at t≈0; sr_device_mgr reads
        topology.yml, finds a directory, crashes. sr_app_mgr stops retrying.
        Result: sr_device_mgr never appears in the process list; sr_cli RC=1
        forever (no management plane, no interfaces).

    Fix strategy:
        Phase 1 — Poll hostname every 1s. On FIRST response:
          a) Write correct topology.yml (the CLAB REST API content)
          b) Kill sr_app_mgr — tini auto-restarts it within ~1s
          The restarted sr_app_mgr reads the now-correct topology.yml and
          successfully starts sr_device_mgr and all NDK applications.

        Phase 2 — Poll sr_cli until RC=0. With sr_device_mgr running, the
          management plane becomes available within ~20-30s.

    timeout=0 in unit tests → while loops skip, function returns immediately.
    """
    import asyncio as _asyncio
    import time as _time

    if timeout == 0:
        return

    # Phase 1: Poll hostname every 1s; apply fix + restart sr_app_mgr on FIRST response
    fix_applied = False
    deadline = _time.monotonic() + timeout
    while _time.monotonic() < deadline:
        await _asyncio.sleep(1)
        try:
            r = await client.exec_command(lab_name, "hostname", timeout=3.0)
            if r and any(res for res in r.values()):
                # Step a: write correct topology.yml
                await _fix_srl_topology_yml(client, lab_name)
                # Step b: kill sr_app_mgr — tini restarts it with correct topology.yml
                # sr_device_mgr never appeared because sr_app_mgr saw bad topology.yml
                # at t=0 and gave up. Restarting sr_app_mgr triggers a fresh startup.
                try:
                    await client.exec_command(
                        lab_name,
                        "bash -c 'kill $(pgrep -x sr_app_mgr) 2>/dev/null; exit 0'",
                        timeout=5.0,
                    )
                except Exception:
                    pass
                fix_applied = True
                elapsed = timeout - (deadline - _time.monotonic())
                logger.info(
                    "_boot_and_fix_srl: topology.yml fixed + sr_app_mgr restarted at t≈%.1fs",
                    elapsed,
                )
                break
        except Exception as exc:
            logger.debug("_boot_and_fix_srl: hostname poll failed: %s", exc)

    if not fix_applied:
        logger.warning("_boot_and_fix_srl: could not apply topology.yml fix (timeout)")
        return

    # Brief pause for tini to restart sr_app_mgr and for sr_app_mgr to start applications
    await _asyncio.sleep(3)

    # Phase 2: Poll sr_cli until management plane ready (sr_device_mgr up, yang fully loaded).
    # "enter candidate; quit" returns RC=0 even during yang reload, but the output contains
    # "yang reload" / "unable to modify" warnings. Exclude those to detect real readiness.
    check_cmd = (
        "bash -c 'printf \"enter candidate\\nquit\\n\" | sr_cli 2>&1; echo RC=$?'"
    )
    _NOT_READY = ("server is not running", "yang", "unable to modify", "parsing error")
    while _time.monotonic() < deadline:
        await _asyncio.sleep(3)
        try:
            resp = await client.exec_command(lab_name, check_cmd, timeout=10.0)
            for node_results in resp.values():
                out = (node_results[0].get("stdout", "") if node_results else "")
                out_lower = out.lower()
                if any(s in out_lower for s in _NOT_READY):
                    continue
                if "RC=0" in out:
                    logger.info("_boot_and_fix_srl: SRL management plane ready (yang loaded)")
                    return
        except Exception as exc:
            logger.debug("_boot_and_fix_srl: sr_cli poll failed: %s", exc)

    logger.warning(
        "_boot_and_fix_srl: management plane not ready after %ds — proceeding anyway", timeout
    )


async def _poll_srl_mgmt_ready(
    client: "CLabClient",
    lab_name: str,
    timeout: int = 120,
    poll_interval: float = 3.0,
) -> None:
    """Poll until SRL sr_cli management plane accepts 'enter candidate'.

    After topology.yml fix and sr_device_mgr restart, the management plane
    needs ~10-20s to initialize. Returns as soon as any node reports ready
    (all nodes share the same chassis init timeline).

    Silently returns on timeout — config push will still be attempted.
    """
    import asyncio as _asyncio
    import time as _time

    deadline = _time.monotonic() + timeout
    check_cmd = "bash -c 'printf \"enter candidate\\nquit\\n\" | sr_cli 2>&1; echo RC=$?'"

    while _time.monotonic() < deadline:
        await _asyncio.sleep(poll_interval)
        try:
            resp = await client.exec_command(lab_name, check_cmd, timeout=10.0)
            # Check any node — if one is ready, all are (same image, same init)
            for node_results in resp.values():
                out = (node_results[0].get("stdout", "") if node_results else "")
                if "RC=0" in out and "Server is not running" not in out:
                    return
        except Exception as exc:
            logger.debug("_poll_srl_mgmt_ready: poll error: %s", exc)

    logger.warning("_poll_srl_mgmt_ready: timed out after %ds", timeout)


def _merge_into_srl_json(base: dict, overlay: dict) -> None:
    """Deep-merge overlay into base SRL JSON in-place. Lists are extended."""
    for key, val in overlay.items():
        if key in base and isinstance(base[key], dict) and isinstance(val, dict):
            _merge_into_srl_json(base[key], val)
        elif key in base and isinstance(base[key], list) and isinstance(val, list):
            base[key].extend(val)
        else:
            base[key] = val


def _llm_translate_vendor_fields(
    device: str,
    vendor_fields: list[dict],
    llm_fn,
) -> dict | None:
    """Ask LLM to translate vendor-specific (_unmapped) fields to SRL JSON.

    Returns a partial SRL JSON dict to merge into the main config, or None if
    the LLM produces no usable output.
    """
    import json as _json
    if not vendor_fields:
        return None

    prompt = f"""You are translating vendor-specific network configuration fields to SR Linux (SRL) JSON.

Device: {device}

The following fields were collected from the production device snapshot but could not be
automatically mapped to standard OpenConfig paths. They may contain useful configuration
(e.g. vendor-specific BGP attributes, interface settings, MPLS, QoS, etc.).

Vendor fields:
{_json.dumps(vendor_fields, indent=2)}

Translate these fields to SRL native JSON format wherever possible.
Output ONLY a valid JSON object with SRL configuration (same format as sr_cli load json).
If a field cannot be translated to SRL, omit it.
If nothing can be translated, output an empty JSON object: {{}}
No explanation, no markdown fences, just the JSON object."""

    try:
        response = llm_fn(prompt).strip()
        # Strip markdown fences if present
        if response.startswith("```"):
            lines = response.splitlines()
            response = "\n".join(
                l for l in lines
                if not l.startswith("```")
            ).strip()
        return _json.loads(response) if response else None
    except Exception as exc:
        logger.debug("_llm_translate_vendor_fields [%s]: %s", device, exc)
        return None


def _llm_repair_srl_json(
    device: str,
    original_json: dict,
    error_output: str,
    llm_fn,
) -> dict | None:
    """Ask LLM to repair an SRL JSON that failed to import.

    Returns a corrected JSON dict, or None if repair failed.
    """
    import json as _json
    if not original_json:
        return None

    prompt = f"""SR Linux rejected a JSON configuration import for device '{device}'.

The JSON that was rejected:
{_json.dumps(original_json, indent=2)}

SR Linux error output:
{error_output[:1000]}

Fix the JSON so that sr_cli load json can import it successfully.
Common issues:
- Wrong leaf names (SRL uses 'admin-state enable/disable', not 'admin-status UP/DOWN')
- Missing required list keys (interfaces need 'name', neighbors need 'peer-address')
- Incorrect value types (AS numbers should be integers, not strings)
- Wrong container structure (SRL doesn't have config/ containers)

Output ONLY the corrected JSON object. No explanation, no markdown fences."""

    try:
        response = llm_fn(prompt).strip()
        if response.startswith("```"):
            lines = response.splitlines()
            response = "\n".join(
                l for l in lines
                if not l.startswith("```")
            ).strip()
        result = _json.loads(response) if response else None
        if result:
            logger.debug("_llm_repair_srl_json [%s]: LLM produced repaired JSON", device)
        return result
    except Exception as exc:
        logger.debug("_llm_repair_srl_json [%s]: %s", device, exc)
        return None


def _build_json_import_script(
    node_json_configs: dict[str, dict],
) -> tuple[str, str]:
    """Build two hostname-conditional bash commands to push SRL config via JSON import.

    Primary config push path: write per-node JSON files → ``sr_cli load json <file>``

    The JSON format is SRL-native YANG JSON produced by oc_config_builder.
    Using ``load json`` is atomic (one import per node) and does not require
    per-leaf translation — the structural conversion is done by oc_config_builder.

    Returns:
        (write_cmd, apply_cmd) — both empty strings if all nodes have empty configs.
    """
    import base64
    import json as _json

    tmp_prefix = "/tmp/olav"
    write_parts: list[str] = []

    for node_name, srl_json in node_json_configs.items():
        if not srl_json:
            continue
        json_text = _json.dumps(srl_json, indent=2)
        b64 = base64.b64encode(json_text.encode()).decode()
        tmp_path = f"{tmp_prefix}_{node_name}.json"
        write_parts.append(f"echo {b64} | base64 -d > {tmp_path}")

    if not write_parts:
        return "", ""

    write_cmd = "bash -c '" + " && ".join(write_parts) + "'"
    # Each node loads only its own JSON file.
    # sr_cli load json: loads config into candidate, then commit now.
    # Echoes CFG_RC=0 on success, CFG_RC=<n> on failure, CFG_SKIP_$H if no file.
    apply_cmd = (
        f"bash -c 'H=$(hostname); jf={tmp_prefix}_${{H}}.json; "
        f'[ -f "$jf" ] && (sr_cli -e "load json $jf" "commit now" 2>&1; echo CFG_RC=$?) '
        f"|| echo CFG_SKIP_$H'"
    )
    return write_cmd, apply_cmd


def _build_exec_script_from_configs(node_configs: dict[str, str]) -> tuple[str, str]:
    """Build two hostname-conditional bash commands to push SRL config via exec.

    The CLAB exec endpoint runs the same command on ALL nodes.
    Strategy (matching configure_device.py):
      1. write_cmd — writes each node's config to a unique temp file on ALL containers
      2. apply_cmd — each container applies only its own file via `sr_cli < file`

    Config file content: `set /` lines + `commit now` (no `enter candidate` — not
    needed for `sr_cli < file` in non-interactive mode).

    Relies on ``prefix: ""`` in the topology so container hostnames match node names.

    Args:
        node_configs: {node_name: srl_cli_config_string} from snapshot_to_srl_config.

    Returns:
        (write_cmd, apply_cmd) — both empty strings if all nodes have no config.
    """
    import base64

    tmp_prefix = "/tmp/olav"
    write_parts: list[str] = []

    for node_name, cfg in node_configs.items():
        set_lines = [l for l in cfg.splitlines() if l.strip().startswith("set /")]
        if not set_lines:
            continue
        cli_input = "enter candidate\n" + "\n".join(set_lines) + "\ncommit now\n"
        b64 = base64.b64encode(cli_input.encode()).decode()
        tmp_path = f"{tmp_prefix}_{node_name}.cfg"
        write_parts.append(f"echo {b64} | base64 -d > {tmp_path}")

    if not write_parts:
        return "", ""

    write_cmd = "bash -c '" + " && ".join(write_parts) + "'"
    # apply_cmd runs on ALL containers; each node applies only its own config file.
    # Outputs CFG_RC=0 on success, CFG_RC=<n> on sr_cli failure, CFG_SKIP_$H if no file.
    # bash always exits 0 so CLAB exec returns HTTP 200 regardless of sr_cli outcome.
    apply_cmd = (
        f"bash -c 'H=$(hostname); cfg={tmp_prefix}_${{H}}.cfg; "
        f'[ -f "$cfg" ] && (sr_cli < "$cfg" 2>&1; echo CFG_RC=$?) || echo CFG_SKIP_$H\''
    )
    return write_cmd, apply_cmd


def _build_execution_plan_proxy(run_id: str, spec: "LabTopologySpec", plan: "CandidatePlan"):
    """Build a minimal duck-typed ExecutionPlan for collect_exec()."""

    class _PlannedNode:
        def __init__(self, name, platform):
            self.name = name
            self.platform = platform or "srl"
            self.mgmt_cloud_ip = "127.0.0.1"
            self.mgmt_cloud_port = 22
            self.loopback_ip = None
            self.configs = []

    class _PlannedLink:
        def __init__(self, src, dst, src_iface, dst_iface):
            self.endpoints = [
                f"{src}:{src_iface or 'ethernet-1/1'}",
                f"{dst}:{dst_iface or 'ethernet-1/1'}",
            ]

    class _ExecutionPlan:
        def __init__(self):
            self.test_run_id = run_id
            self.scenario_name = "cab-live"
            self.topology_file = ""
            self.nodes = {
                n.name: _PlannedNode(n.name, n.platform) for n in spec.nodes
            }
            self.links = [
                _PlannedLink(lk.source, lk.target, lk.source_iface, lk.target_iface)
                for lk in spec.links
            ]
            self.addressing = {}
            self.assertions = []
            self.defaults = {}
            self.timestamp = datetime.now(timezone.utc).isoformat()

    return _ExecutionPlan()
