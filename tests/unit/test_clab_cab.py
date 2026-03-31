"""Unit tests for Phase 6 CLAB CAB Agent.

All tests use in-memory ControlPlaneSnapshot — no real DuckDB or CLAB required.

Coverage:
    - CandidatePlan construction
    - LabTopologySpec: build_reduced_topology (subset, include_neighbors, empty)
    - AssertionSpec + AssertionResult
    - evaluate_assertions:
        BGP_SESSION_ESTABLISHED (pass / fail / not-found)
        PREFIX_REACHABLE (exact / covering / not-found)
        NEXTHOP_UNCHANGED (match / mismatch / not-found)
        OSPF_ADJACENCY_UP (pass / fail / not-found)
        INTERFACE_PRESENT (pass / not-found)
        BLAST_RADIUS_BOUNDED (bounded / not-bounded)
    - compare_predictions: dry-run UNKNOWN, full FULL/PARTIAL/MISMATCH
    - determine_verdict: all 4 verdict classes
    - _infer_observed_risk: all risk levels
    - run_validation (dry_run=True): full pipeline, evidence artifact structure
    - run_validation (dry_run=False): raises NotImplementedError
    - CABEvidenceArtifact.to_dict: required keys present
    - LabTopologySpec.to_dict
"""

import sys
from pathlib import Path
_LAB_SCRIPTS = Path(__file__).resolve().parents[2] / ".olav" / "workspace" / "ops" / "lab" / "scripts"
if str(_LAB_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_LAB_SCRIPTS))

import pytest

from clab_cab import (
    AssertionSpec,
    AssertionType,
    CABVerdict,
    CLABCABAgent,
    CandidatePlan,
    LabTopologySpec,
    PredictionMatch,
)
from olav.core.control_plane_ir import (
    BGPNeighbor,
    ControlPlaneSnapshot,
    Device,
    OSPFNeighbor,
    Route,
    TopologyLink,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_snapshot() -> ControlPlaneSnapshot:
    """
    Topology:
        R1 -- R2 -- R3 -- R4
        R1 has BGP to R3 (Established), R2 has BGP to R3 (Idle)
        OSPF: R1↔R2 (Full), R2↔R3 (Full)
        Routes on R1: 10.0.0.0/8 via 192.168.1.2, 192.168.1.0/30 attached
        Routes on R4: 10.0.0.0/8 via 192.168.3.1
    """
    devices = [
        Device(name="R1", mgmt_ip="192.168.1.1", platform="IOS-XE"),
        Device(name="R2", mgmt_ip="192.168.1.2", platform="IOS-XE"),
        Device(name="R3", mgmt_ip="192.168.1.3", platform="IOS-XR"),
        Device(name="R4", mgmt_ip="192.168.1.4", platform="EOS"),
    ]
    topology_links = [
        TopologyLink(source="R1", target="R2", source_iface="Gi0/0", target_iface="Gi0/0", protocol="LLDP", link_type="L3"),
        TopologyLink(source="R2", target="R1", source_iface="Gi0/0", target_iface="Gi0/0", protocol="LLDP", link_type="L3"),
        TopologyLink(source="R2", target="R3", source_iface="Gi0/1", target_iface="Gi0/0", protocol="LLDP", link_type="L3"),
        TopologyLink(source="R3", target="R2", source_iface="Gi0/0", target_iface="Gi0/1", protocol="LLDP", link_type="L3"),
        TopologyLink(source="R3", target="R4", source_iface="Gi0/1", target_iface="Gi0/0", protocol="LLDP", link_type="L3"),
        TopologyLink(source="R4", target="R3", source_iface="Gi0/0", target_iface="Gi0/1", protocol="LLDP", link_type="L3"),
    ]
    bgp_neighbors = [
        BGPNeighbor(device="R1", peer_ip="10.0.0.3", peer_as="65003", state="Established"),
        BGPNeighbor(device="R3", peer_ip="10.0.0.1", peer_as="65001", state="Established"),
        BGPNeighbor(device="R2", peer_ip="10.0.0.3", peer_as="65003", state="Idle"),
    ]
    ospf_neighbors = [
        OSPFNeighbor(device="R1", neighbor_id="2.2.2.2", neighbor_ip="192.168.1.2", interface="Gi0/0", state="Full", cost=10),
        OSPFNeighbor(device="R2", neighbor_id="1.1.1.1", neighbor_ip="192.168.1.1", interface="Gi0/0", state="Full", cost=10),
        OSPFNeighbor(device="R2", neighbor_id="3.3.3.3", neighbor_ip="192.168.1.6", interface="Gi0/1", state="Full", cost=20),
    ]
    routes = [
        Route(device="R1", network="10.0.0.0/8", next_hop="192.168.1.2", protocol="BGP"),
        Route(device="R1", network="192.168.1.0/30", next_hop="attached", protocol="connected"),
        Route(device="R4", network="10.0.0.0/8", next_hop="192.168.3.1", protocol="BGP"),
    ]
    return ControlPlaneSnapshot(
        devices=devices,
        topology_links=topology_links,
        bgp_neighbors=bgp_neighbors,
        ospf_neighbors=ospf_neighbors,
        routes=routes,
    )


def _make_agent() -> CLABCABAgent:
    return CLABCABAgent(_make_snapshot())


def _make_plan(
    affected=None,
    blast=None,
    risk="medium",
    assertions=None,
) -> CandidatePlan:
    return CandidatePlan(
        change_intent="Test change intent",
        actions=["some action"],
        affected_devices=affected or ["R1"],
        blast_radius_estimate=blast or ["R1", "R2"],
        predicted_risk=risk,
        assertions=assertions or [],
    )


# ---------------------------------------------------------------------------
# CandidatePlan
# ---------------------------------------------------------------------------


class TestCandidatePlan:
    def test_defaults(self):
        plan = CandidatePlan(
            change_intent="adjust BGP policy",
            actions=["set local-pref 200"],
            affected_devices=["R1"],
            blast_radius_estimate=["R1", "R2"],
            predicted_risk="medium",
        )
        assert plan.requires_clab is True
        assert plan.source == "ops_networkx_sandbox"
        assert plan.assertions == []
        assert plan.metadata == {}

    def test_custom_assertions(self):
        spec = AssertionSpec(AssertionType.BGP_SESSION_ESTABLISHED, device="R1", target="10.0.0.3")
        plan = _make_plan(assertions=[spec])
        assert len(plan.assertions) == 1
        assert plan.assertions[0].type == AssertionType.BGP_SESSION_ESTABLISHED


# ---------------------------------------------------------------------------
# AssertionSpec
# ---------------------------------------------------------------------------


class TestAssertionSpec:
    def test_auto_description(self):
        spec = AssertionSpec(AssertionType.BGP_SESSION_ESTABLISHED, device="R1", target="10.0.0.3")
        assert "R1" in spec.description
        assert "10.0.0.3" in spec.description

    def test_custom_description(self):
        spec = AssertionSpec(
            AssertionType.BGP_SESSION_ESTABLISHED,
            device="R1",
            target="10.0.0.3",
            description="my custom desc",
        )
        assert spec.description == "my custom desc"


# ---------------------------------------------------------------------------
# Build reduced topology
# ---------------------------------------------------------------------------


class TestBuildReducedTopology:
    def test_single_device_includes_neighbors(self):
        agent = _make_agent()
        spec = agent.build_reduced_topology(["R1"])
        # R1 neighbors are R2 (via LLDP)
        assert "R1" in spec.node_names()
        assert "R2" in spec.node_names()

    def test_blast_radius_devices_set(self):
        agent = _make_agent()
        spec = agent.build_reduced_topology(["R2", "R3"])
        assert "R2" in spec.blast_radius_devices
        assert "R3" in spec.blast_radius_devices

    def test_links_filtered_to_subset(self):
        agent = _make_agent()
        spec = agent.build_reduced_topology(["R1"], include_neighbors=False)
        # Only R1 — no links because no link has both endpoints = R1
        assert all(lk.source == "R1" or lk.target == "R1" for lk in spec.links)

    def test_no_neighbors_flag(self):
        agent = _make_agent()
        spec = agent.build_reduced_topology(["R1"], include_neighbors=False)
        assert "R1" in spec.node_names()
        # Without neighbor expansion, R2 should NOT be included
        assert "R2" not in spec.node_names()

    def test_full_path_includes_all_hops(self):
        agent = _make_agent()
        spec = agent.build_reduced_topology(["R1", "R2", "R3"])
        assert {"R1", "R2", "R3"}.issubset(spec.node_names())

    def test_node_platform_filled(self):
        agent = _make_agent()
        spec = agent.build_reduced_topology(["R1"], include_neighbors=False)
        r1_node = next(n for n in spec.nodes if n.name == "R1")
        assert r1_node.platform == "IOS-XE"
        assert r1_node.mgmt_ip == "192.168.1.1"

    def test_topology_spec_to_dict(self):
        agent = _make_agent()
        spec = agent.build_reduced_topology(["R1"], include_neighbors=False)
        d = spec.to_dict()
        assert "nodes" in d
        assert "links" in d
        assert "blast_radius_devices" in d


# ---------------------------------------------------------------------------
# evaluate_assertions — BGP_SESSION_ESTABLISHED
# ---------------------------------------------------------------------------


class TestAssertBGPEstablished:
    def test_established_passes(self):
        agent = _make_agent()
        spec = AssertionSpec(AssertionType.BGP_SESSION_ESTABLISHED, device="R1", target="10.0.0.3")
        results = agent.evaluate_assertions([spec])
        assert results[0].passed is True
        assert results[0].observed_value == "Established"

    def test_idle_fails(self):
        agent = _make_agent()
        spec = AssertionSpec(AssertionType.BGP_SESSION_ESTABLISHED, device="R2", target="10.0.0.3")
        results = agent.evaluate_assertions([spec])
        assert results[0].passed is False
        assert results[0].observed_value == "Idle"

    def test_unknown_peer_fails(self):
        agent = _make_agent()
        spec = AssertionSpec(AssertionType.BGP_SESSION_ESTABLISHED, device="R1", target="9.9.9.9")
        results = agent.evaluate_assertions([spec])
        assert results[0].passed is False
        assert results[0].observed_value is None


# ---------------------------------------------------------------------------
# evaluate_assertions — PREFIX_REACHABLE
# ---------------------------------------------------------------------------


class TestAssertPrefixReachable:
    def test_exact_match_passes(self):
        agent = _make_agent()
        spec = AssertionSpec(AssertionType.PREFIX_REACHABLE, device="R1", target="10.0.0.0/8")
        results = agent.evaluate_assertions([spec])
        assert results[0].passed is True

    def test_no_route_fails(self):
        agent = _make_agent()
        spec = AssertionSpec(AssertionType.PREFIX_REACHABLE, device="R1", target="172.16.0.0/12")
        results = agent.evaluate_assertions([spec])
        assert results[0].passed is False

    def test_route_on_correct_device(self):
        agent = _make_agent()
        spec = AssertionSpec(AssertionType.PREFIX_REACHABLE, device="R4", target="10.0.0.0/8")
        results = agent.evaluate_assertions([spec])
        assert results[0].passed is True


# ---------------------------------------------------------------------------
# evaluate_assertions — NEXTHOP_UNCHANGED
# ---------------------------------------------------------------------------


class TestAssertNexthop:
    def test_nexthop_matches(self):
        agent = _make_agent()
        spec = AssertionSpec(
            AssertionType.NEXTHOP_UNCHANGED, device="R1", target="10.0.0.0/8",
            expected_value="192.168.1.2",
        )
        results = agent.evaluate_assertions([spec])
        assert results[0].passed is True
        assert results[0].observed_value == "192.168.1.2"

    def test_nexthop_changed_fails(self):
        agent = _make_agent()
        spec = AssertionSpec(
            AssertionType.NEXTHOP_UNCHANGED, device="R1", target="10.0.0.0/8",
            expected_value="192.168.1.99",
        )
        results = agent.evaluate_assertions([spec])
        assert results[0].passed is False

    def test_prefix_not_found(self):
        agent = _make_agent()
        spec = AssertionSpec(
            AssertionType.NEXTHOP_UNCHANGED, device="R1", target="99.0.0.0/8",
            expected_value="192.168.1.2",
        )
        results = agent.evaluate_assertions([spec])
        assert results[0].passed is False
        assert results[0].observed_value is None


# ---------------------------------------------------------------------------
# evaluate_assertions — OSPF_ADJACENCY_UP
# ---------------------------------------------------------------------------


class TestAssertOSPFUp:
    def test_full_adj_passes(self):
        agent = _make_agent()
        spec = AssertionSpec(AssertionType.OSPF_ADJACENCY_UP, device="R1", target="2.2.2.2")
        results = agent.evaluate_assertions([spec])
        assert results[0].passed is True
        assert results[0].observed_value == "Full"

    def test_unknown_neighbor_fails(self):
        agent = _make_agent()
        spec = AssertionSpec(AssertionType.OSPF_ADJACENCY_UP, device="R1", target="9.9.9.9")
        results = agent.evaluate_assertions([spec])
        assert results[0].passed is False

    def test_neighbor_ip_lookup(self):
        agent = _make_agent()
        spec = AssertionSpec(AssertionType.OSPF_ADJACENCY_UP, device="R1", target="192.168.1.2")
        results = agent.evaluate_assertions([spec])
        assert results[0].passed is True


# ---------------------------------------------------------------------------
# evaluate_assertions — INTERFACE_PRESENT
# ---------------------------------------------------------------------------


class TestAssertInterfacePresent:
    def test_present_passes(self):
        agent = _make_agent()
        spec = AssertionSpec(AssertionType.INTERFACE_PRESENT, device="R1", target="Gi0/0")
        results = agent.evaluate_assertions([spec])
        assert results[0].passed is True

    def test_absent_fails(self):
        agent = _make_agent()
        spec = AssertionSpec(AssertionType.INTERFACE_PRESENT, device="R1", target="Gi9/9")
        results = agent.evaluate_assertions([spec])
        assert results[0].passed is False


# ---------------------------------------------------------------------------
# evaluate_assertions — BLAST_RADIUS_BOUNDED
# ---------------------------------------------------------------------------


class TestAssertBlastBounded:
    def test_target_not_in_blast_passes_by_default(self):
        agent = _make_agent()
        spec = AssertionSpec(AssertionType.BLAST_RADIUS_BOUNDED, device="*", target="R4")
        blast = ["R1", "R2", "R3"]
        results = agent.evaluate_assertions([spec], blast_radius=blast)
        # R4 is NOT in blast → passes (expected_value defaults to False = not in blast)
        assert results[0].passed is True
        assert results[0].observed_value is False

    def test_target_in_blast_fails_by_default(self):
        agent = _make_agent()
        spec = AssertionSpec(AssertionType.BLAST_RADIUS_BOUNDED, device="*", target="R2")
        blast = ["R1", "R2", "R3"]
        results = agent.evaluate_assertions([spec], blast_radius=blast)
        assert results[0].passed is False
        assert results[0].observed_value is True

    def test_expected_in_blast(self):
        agent = _make_agent()
        spec = AssertionSpec(
            AssertionType.BLAST_RADIUS_BOUNDED, device="*", target="R2",
            expected_value=True,  # must be in blast
        )
        blast = ["R1", "R2", "R3"]
        results = agent.evaluate_assertions([spec], blast_radius=blast)
        assert results[0].passed is True


# ---------------------------------------------------------------------------
# compare_predictions
# ---------------------------------------------------------------------------


class TestComparePredictions:
    def test_dry_run_always_unknown(self):
        agent = _make_agent()
        plan = _make_plan()
        match = agent.compare_predictions(plan, [], lab_deployed=False)
        assert match == PredictionMatch.UNKNOWN

    def test_all_passed_full_match(self):
        agent = _make_agent()
        plan = _make_plan()
        spec = AssertionSpec(AssertionType.BGP_SESSION_ESTABLISHED, "R1", "10.0.0.3")
        from clab_cab import AssertionResult
        results = [AssertionResult(spec=spec, passed=True)]
        match = agent.compare_predictions(plan, results, lab_deployed=True)
        assert match == PredictionMatch.FULL

    def test_partial_pass_partial_match(self):
        agent = _make_agent()
        plan = _make_plan()
        from clab_cab import AssertionResult
        spec = AssertionSpec(AssertionType.BGP_SESSION_ESTABLISHED, "R1", "10.0.0.3")
        results = [
            AssertionResult(spec=spec, passed=True),
            AssertionResult(spec=spec, passed=True),
            AssertionResult(spec=spec, passed=True),
            AssertionResult(spec=spec, passed=False),  # 3/4 = 75% → PARTIAL (≥70%)
        ]
        match = agent.compare_predictions(plan, results, lab_deployed=True)
        assert match == PredictionMatch.PARTIAL

    def test_low_pass_mismatch(self):
        agent = _make_agent()
        plan = _make_plan()
        from clab_cab import AssertionResult
        spec = AssertionSpec(AssertionType.BGP_SESSION_ESTABLISHED, "R1", "10.0.0.3")
        results = [
            AssertionResult(spec=spec, passed=False),
            AssertionResult(spec=spec, passed=False),
            AssertionResult(spec=spec, passed=False),
        ]
        match = agent.compare_predictions(plan, results, lab_deployed=True)
        assert match == PredictionMatch.MISMATCH

    def test_no_assertions_unknown(self):
        agent = _make_agent()
        plan = _make_plan()
        match = agent.compare_predictions(plan, [], lab_deployed=True)
        assert match == PredictionMatch.UNKNOWN


# ---------------------------------------------------------------------------
# determine_verdict
# ---------------------------------------------------------------------------


class TestDetermineVerdict:
    def _results(self, passed_list: list[bool], types=None):
        from clab_cab import AssertionResult
        if types is None:
            types = [AssertionType.PREFIX_REACHABLE] * len(passed_list)
        specs = [AssertionSpec(t, "R1", "target") for t in types]
        return [AssertionResult(spec=s, passed=p) for s, p in zip(specs, passed_list)]

    def test_all_passed_low_risk_recommend(self):
        agent = _make_agent()
        plan = _make_plan(risk="low")
        results = self._results([True, True, True])
        verdict, rec = agent.determine_verdict(plan, results, PredictionMatch.FULL)
        assert verdict == CABVerdict.RECOMMEND_HUMAN_EXECUTION
        assert "DRY RUN" in rec  # dry_run=True default

    def test_all_passed_high_risk_conditional(self):
        agent = _make_agent()
        plan = _make_plan(risk="high")
        results = self._results([True, True, True])
        verdict, rec = agent.determine_verdict(plan, results, PredictionMatch.FULL)
        assert verdict == CABVerdict.RECOMMEND_HUMAN_EXECUTION_WITH_CONDITIONS

    def test_partial_pass_rate_needs_review(self):
        agent = _make_agent()
        plan = _make_plan(risk="medium")
        results = self._results([True, True, False, False])  # 50% → NEEDS_REVIEW
        verdict, rec = agent.determine_verdict(plan, results, PredictionMatch.PARTIAL)
        assert verdict == CABVerdict.NEEDS_REVIEW

    def test_critical_bgp_failure_reject(self):
        agent = _make_agent()
        plan = _make_plan(risk="medium")
        results = self._results(
            [False],
            types=[AssertionType.BGP_SESSION_ESTABLISHED],
        )
        verdict, rec = agent.determine_verdict(plan, results, PredictionMatch.UNKNOWN)
        assert verdict == CABVerdict.REJECT_CHANGE

    def test_critical_ospf_failure_reject(self):
        agent = _make_agent()
        plan = _make_plan(risk="low")
        results = self._results(
            [False],
            types=[AssertionType.OSPF_ADJACENCY_UP],
        )
        verdict, rec = agent.determine_verdict(plan, results, PredictionMatch.UNKNOWN)
        assert verdict == CABVerdict.REJECT_CHANGE

    def test_all_failed_reject(self):
        agent = _make_agent()
        plan = _make_plan(risk="low")
        results = self._results([False, False, False])
        verdict, rec = agent.determine_verdict(plan, results, PredictionMatch.UNKNOWN)
        assert verdict == CABVerdict.REJECT_CHANGE

    def test_partial_match_conditional(self):
        agent = _make_agent()
        plan = _make_plan(risk="medium")
        results = self._results([True, True, True, True, True])  # 100%, but PARTIAL match
        verdict, rec = agent.determine_verdict(plan, results, PredictionMatch.PARTIAL)
        assert verdict == CABVerdict.RECOMMEND_HUMAN_EXECUTION_WITH_CONDITIONS

    def test_critical_risk_needs_review(self):
        agent = _make_agent()
        plan = _make_plan(risk="critical")
        results = self._results([True, True, True])
        verdict, rec = agent.determine_verdict(plan, results, PredictionMatch.FULL)
        assert verdict == CABVerdict.NEEDS_REVIEW


# ---------------------------------------------------------------------------
# _infer_observed_risk
# ---------------------------------------------------------------------------


class TestInferObservedRisk:
    def _results(self, passed_list: list[bool]):
        from clab_cab import AssertionResult
        specs = [AssertionSpec(AssertionType.PREFIX_REACHABLE, "R1", "t") for _ in passed_list]
        return [AssertionResult(spec=s, passed=p) for s, p in zip(specs, passed_list)]

    def test_all_pass_low(self):
        agent = _make_agent()
        plan = _make_plan(risk="high")
        r = agent._infer_observed_risk(self._results([True, True, True]), plan)
        assert r == "low"

    def test_20pct_fail_medium(self):
        agent = _make_agent()
        plan = _make_plan(risk="low")
        r = agent._infer_observed_risk(self._results([True, True, True, True, False]), plan)
        assert r == "medium"

    def test_40pct_fail_high(self):
        agent = _make_agent()
        plan = _make_plan(risk="low")
        # 1/3 fail = 33% → high (>20% and ≤50%)
        r = agent._infer_observed_risk(self._results([True, True, False]), plan)
        assert r == "high"

    def test_majority_fail_critical(self):
        agent = _make_agent()
        plan = _make_plan(risk="low")
        r = agent._infer_observed_risk(self._results([False, False, False]), plan)
        assert r == "critical"

    def test_no_assertions_returns_predicted(self):
        agent = _make_agent()
        plan = _make_plan(risk="medium")
        r = agent._infer_observed_risk([], plan)
        assert r == "medium"


# ---------------------------------------------------------------------------
# run_validation — full pipeline
# ---------------------------------------------------------------------------


class TestRunValidation:
    def test_dry_run_returns_artifact(self):
        agent = _make_agent()
        plan = _make_plan(
            affected=["R1"],
            blast=["R1", "R2"],
            risk="medium",
            assertions=[
                AssertionSpec(AssertionType.BGP_SESSION_ESTABLISHED, "R1", "10.0.0.3"),
                AssertionSpec(AssertionType.PREFIX_REACHABLE, "R1", "10.0.0.0/8"),
            ],
        )
        artifact = agent.run_validation(plan, dry_run=True)
        assert artifact.dry_run is True
        assert artifact.lab_deployed is False
        assert artifact.verdict in list(CABVerdict)
        assert artifact.assertions_passed + artifact.assertions_failed == 2
        assert artifact.prediction_match == PredictionMatch.UNKNOWN

    def test_dry_run_warning_present(self):
        agent = _make_agent()
        plan = _make_plan()
        artifact = agent.run_validation(plan, dry_run=True)
        assert any("Dry-run" in w or "dry-run" in w.lower() for w in artifact.warnings)

    def test_artifact_has_required_keys(self):
        agent = _make_agent()
        plan = _make_plan()
        artifact = agent.run_validation(plan)
        d = artifact.to_dict()
        required_keys = [
            "lab_id", "timestamp", "change_intent", "candidate_plan_source",
            "query_contract", "graph_contract", "render_contract",
            "predicted_risk", "observed_risk", "prediction_match",
            "assertions", "verdict", "recommendation",
            "dry_run", "lab_deployed", "blast_radius_devices",
            "warnings", "audit_run_id", "production_execution",
        ]
        for key in required_keys:
            assert key in d, f"Missing key: {key}"

    def test_production_execution_advisory(self):
        agent = _make_agent()
        artifact = agent.run_validation(_make_plan())
        d = artifact.to_dict()
        assert "HUMAN RESPONSIBILITY" in d["production_execution"]

    def test_all_assertions_pass_good_verdict(self):
        agent = _make_agent()
        plan = _make_plan(
            risk="low",
            assertions=[
                AssertionSpec(AssertionType.BGP_SESSION_ESTABLISHED, "R1", "10.0.0.3"),
                AssertionSpec(AssertionType.PREFIX_REACHABLE, "R1", "10.0.0.0/8"),
                AssertionSpec(AssertionType.OSPF_ADJACENCY_UP, "R1", "2.2.2.2"),
            ],
        )
        artifact = agent.run_validation(plan)
        assert artifact.assertions_passed == 3
        assert artifact.assertions_failed == 0
        assert artifact.verdict == CABVerdict.RECOMMEND_HUMAN_EXECUTION

    def test_bgp_fail_triggers_reject(self):
        agent = _make_agent()
        plan = _make_plan(
            risk="medium",
            assertions=[
                # This peer doesn't exist → fails
                AssertionSpec(AssertionType.BGP_SESSION_ESTABLISHED, "R1", "9.9.9.9"),
            ],
        )
        artifact = agent.run_validation(plan)
        assert artifact.verdict == CABVerdict.REJECT_CHANGE

    def test_custom_test_run_id(self):
        agent = _make_agent()
        plan = _make_plan()
        artifact = agent.run_validation(plan, test_run_id="test-run-123")
        assert artifact.audit_run_id == "test-run-123"
        assert "test-run" in artifact.lab_id

    def test_high_risk_warning(self):
        agent = _make_agent()
        plan = _make_plan(risk="high")
        artifact = agent.run_validation(plan)
        assert any("high" in w.lower() or "High" in w for w in artifact.warnings)

    def test_blast_radius_in_artifact(self):
        agent = _make_agent()
        plan = _make_plan(blast=["R1", "R2", "R3"])
        artifact = agent.run_validation(plan)
        # Blast radius in artifact includes neighbors from topology expansion
        assert len(artifact.blast_radius_devices) >= 3

    def test_no_assertions_empty_plan(self):
        agent = _make_agent()
        plan = _make_plan(assertions=[])
        artifact = agent.run_validation(plan)
        assert artifact.assertions_passed == 0
        assert artifact.assertions_failed == 0
        assert artifact.verdict == CABVerdict.RECOMMEND_HUMAN_EXECUTION  # all 0/0 pass at 100%


# ---------------------------------------------------------------------------
# LabTopologySpec
# ---------------------------------------------------------------------------


class TestLabTopologySpec:
    def test_node_names(self):
        from clab_cab import LabNode, LabTopologySpec
        spec = LabTopologySpec(nodes=[LabNode("R1"), LabNode("R2")])
        assert spec.node_names() == {"R1", "R2"}

    def test_to_dict_structure(self):
        from clab_cab import LabLink, LabNode, LabTopologySpec
        spec = LabTopologySpec(
            nodes=[LabNode("R1", platform="IOS-XE", mgmt_ip="192.168.1.1")],
            links=[LabLink(source="R1", target="R2", link_type="L3")],
            blast_radius_devices=["R1", "R2"],
        )
        d = spec.to_dict()
        assert d["nodes"][0]["name"] == "R1"
        assert d["nodes"][0]["platform"] == "IOS-XE"
        assert d["links"][0]["source"] == "R1"
        assert d["blast_radius_devices"] == ["R1", "R2"]


# ---------------------------------------------------------------------------
# TestRunValidationLive — dry_run=False pipeline (mocked CLAB)
# ---------------------------------------------------------------------------


class TestRunValidationLive:
    """Tests for run_validation_live().

    CLabClient and collect_exec are mocked so no real CLAB infra is needed.
    ControlPlaneIR is replaced with a factory that returns a known post-snapshot.
    """

    def _make_plan_with_bgp_assertion(self) -> CandidatePlan:
        return CandidatePlan(
            change_intent="test live pipeline",
            actions=[],
            affected_devices=["R1"],
            blast_radius_estimate=["R1", "R2"],
            predicted_risk="low",
            assertions=[
                AssertionSpec(
                    AssertionType.BGP_SESSION_ESTABLISHED,
                    device="R1",
                    target="10.0.0.3",
                ),
            ],
        )

    def _make_post_snapshot_passing(self) -> ControlPlaneSnapshot:
        """Post-change snapshot where BGP R1→10.0.0.3 is Established."""
        return ControlPlaneSnapshot(
            devices=[
                Device(name="R1", mgmt_ip="192.168.1.1", platform="IOS-XE"),
                Device(name="R2", mgmt_ip="192.168.1.2", platform="IOS-XE"),
            ],
            bgp_neighbors=[
                BGPNeighbor(device="R1", peer_ip="10.0.0.3", peer_as="65002", state="Established"),
            ],
            topology_links=[
                TopologyLink(source="R1", target="R2", source_iface="eth1", target_iface="eth1",
                             protocol="lldp", link_type="L3"),
            ],
        )

    def _make_post_snapshot_failing(self) -> ControlPlaneSnapshot:
        """Post-change snapshot where BGP R1→10.0.0.3 is Idle (fails assertion)."""
        return ControlPlaneSnapshot(
            devices=[Device(name="R1", mgmt_ip="192.168.1.1", platform="IOS-XE")],
            bgp_neighbors=[
                BGPNeighbor(device="R1", peer_ip="10.0.0.3", peer_as="65002", state="Idle"),
            ],
        )

    def _run_live(self, post_snapshot, tmp_path, *, destroy_raises=False):
        """Helper: run run_validation_live with mocked dependencies."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        agent = CLABCABAgent(_make_snapshot())
        plan = self._make_plan_with_bgp_assertion()

        mock_deploy_result = MagicMock()
        mock_deploy_result.test_run_id = "test-run-001"
        mock_deploy_result.lab_name = "cab-testlab"
        mock_deploy_result.api_server = "http://mock:8080/api/v1"
        mock_deploy_result.nodes = {}

        mock_client = AsyncMock()
        mock_client.deploy.return_value = {"cab-testlab": []}
        if destroy_raises:
            mock_client.destroy.side_effect = Exception("destroy failed")
        else:
            mock_client.destroy.return_value = {"message": "ok"}

        mock_readiness = MagicMock()
        mock_readiness.status = "success"

        async def mock_collect(*args, **kwargs):
            return True

        async def mock_wait(*args, **kwargs):
            return mock_readiness

        with (
            patch("clab_cab.CLabClient") as mock_clab_cls,
            patch("clab_cab.collect_exec", side_effect=mock_collect),
            patch("clab_cab.wait_readiness", side_effect=mock_wait),
            patch("clab_cab.ControlPlaneIR") as mock_ir_cls,
            patch("clab_cab.DeployResult") as mock_deploy_cls,
            patch("clab_cab._BGP_CONVERGENCE_WAIT_SECS", 0),
            patch("clab_cab._SRL_MGMT_POLL_TIMEOUT_SECS", 0),
        ):
            mock_clab_cls.build = AsyncMock(return_value=mock_client)
            mock_ir_cls.return_value.build.return_value = post_snapshot
            mock_deploy_cls.return_value = mock_deploy_result

            artifact = asyncio.run(
                agent.run_validation_live(
                    plan,
                    api_server="http://mock:8080/api/v1",
                    token="test-token",
                    evidence_dir=tmp_path,
                    test_run_id="test-run-001",
                )
            )

        return artifact, mock_client

    def test_artifact_lab_deployed_true(self, tmp_path):
        artifact, _ = self._run_live(self._make_post_snapshot_passing(), tmp_path)
        assert artifact.lab_deployed is True

    def test_dry_run_false_in_artifact(self, tmp_path):
        artifact, _ = self._run_live(self._make_post_snapshot_passing(), tmp_path)
        assert artifact.dry_run is False

    def test_passing_assertion_recommend_verdict(self, tmp_path):
        artifact, _ = self._run_live(self._make_post_snapshot_passing(), tmp_path)
        assert artifact.assertions_passed == 1
        assert artifact.assertions_failed == 0
        assert artifact.verdict != CABVerdict.REJECT_CHANGE

    def test_failing_bgp_assertion_reject_verdict(self, tmp_path):
        artifact, _ = self._run_live(self._make_post_snapshot_failing(), tmp_path)
        assert artifact.assertions_failed == 1
        assert artifact.verdict == CABVerdict.REJECT_CHANGE

    def test_prediction_match_not_unknown_when_lab_deployed(self, tmp_path):
        artifact, _ = self._run_live(self._make_post_snapshot_passing(), tmp_path)
        assert artifact.prediction_match != PredictionMatch.UNKNOWN

    def test_destroy_called_after_assertions(self, tmp_path):
        _, mock_client = self._run_live(self._make_post_snapshot_passing(), tmp_path)
        mock_client.destroy.assert_called_once()

    def test_destroy_called_even_when_assertion_fails(self, tmp_path):
        _, mock_client = self._run_live(self._make_post_snapshot_failing(), tmp_path)
        mock_client.destroy.assert_called_once()

    def test_isolated_db_not_main_duckdb(self, tmp_path):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        captured_db_paths = []

        agent = CLABCABAgent(_make_snapshot())
        plan = self._make_plan_with_bgp_assertion()

        mock_deploy_result = MagicMock()
        mock_deploy_result.test_run_id = "test-run-001"
        mock_deploy_result.lab_name = "cab-testlab"
        mock_deploy_result.api_server = "http://mock:8080/api/v1"
        mock_deploy_result.nodes = {}
        mock_client = AsyncMock()
        mock_client.deploy.return_value = {"cab-testlab": []}
        mock_client.destroy.return_value = {}

        async def capture_collect(deploy, plan, db_path, **kwargs):
            captured_db_paths.append(str(db_path))
            return True

        with (
            patch("clab_cab.CLabClient") as mock_clab_cls,
            patch("clab_cab.collect_exec", side_effect=capture_collect),
            patch("clab_cab.wait_readiness", new_callable=AsyncMock),
            patch("clab_cab.ControlPlaneIR") as mock_ir_cls,
            patch("clab_cab.DeployResult") as mock_deploy_cls,
            patch("clab_cab._BGP_CONVERGENCE_WAIT_SECS", 0),
            patch("clab_cab._SRL_MGMT_POLL_TIMEOUT_SECS", 0),
        ):
            mock_clab_cls.build = AsyncMock(return_value=mock_client)
            mock_ir_cls.return_value.build.return_value = self._make_post_snapshot_passing()
            mock_deploy_cls.return_value = mock_deploy_result

            asyncio.run(
                agent.run_validation_live(
                    plan,
                    api_server="http://mock:8080/api/v1",
                    token="test-token",
                    evidence_dir=tmp_path,
                    test_run_id="test-run-001",
                )
            )

        assert len(captured_db_paths) == 1
        db_path = captured_db_paths[0]
        assert "main.duckdb" not in db_path
        assert "cab_" in db_path

    def test_artifact_has_all_required_keys(self, tmp_path):
        artifact, _ = self._run_live(self._make_post_snapshot_passing(), tmp_path)
        d = artifact.to_dict()
        for key in ["lab_id", "timestamp", "verdict", "lab_deployed", "dry_run",
                    "assertions", "prediction_match", "production_execution"]:
            assert key in d, f"Missing key: {key}"
