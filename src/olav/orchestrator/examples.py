"""
Expert Orchestrator - Complete Working Examples

Demonstrates orchestrator usage patterns:
1. Simple acceptance (diagnosis passes all gates)
2. Warning & review (constraint warning, needs human review)
3. Critical rejection (hallucinations detected)
4. Uncertain diagnosis (low confidence)
5. Verified acceptance (with ground truth)
6. Batch processing (multiple scenarios)

Each example includes:
- Setup code
- Diagnosis input
- Orchestrator processing
- Report interpretation
"""

import asyncio
from pathlib import Path

from olav.testing.diagnosis_verifier import DiagnosisVerifier, GroundTruth
from olav.testing.expert_constraints import (
    ExpertConstraintsValidator,
    ExpertDiagnosisOutput,
)

from .expert_orchestrator import (
    DecisionGateConfig,
    ExpertOrchestrator,
    OrchestratorDecision,
)


class OrchestratorExamples:
    """Complete working examples for ExpertOrchestrator"""

    @staticmethod
    async def example_1_simple_acceptance():
        """
        Example 1: Diagnosis passes all gates
        
        Scenario: BGP session down - Expert Agent provides high-quality diagnosis
        
        Expected Result: ACCEPT → DIRECT_USER
        Time: ~5 minutes
        
        Key Learning:
        - Constraint score high (>= 0.85)
        - Confidence score high (>= 0.80)
        - No critical failures
        - Routes directly to user
        """
        print("\n" + "=" * 70)
        print("EXAMPLE 1: Simple Acceptance (High-Quality Diagnosis)")
        print("=" * 70)

        # Setup
        validator = ExpertConstraintsValidator()
        config = DecisionGateConfig()
        orchestrator = ExpertOrchestrator(
            constraint_validator=validator, gate_config=config
        )

        # Create diagnosis
        diagnosis = ExpertDiagnosisOutput(
            scenario_id="example_1_acceptance",
            root_cause="BGP session terminated due to hold timer expiration (keepalive not received for 180s)",
            confidence_score=0.95,
            solution="Verify BGP neighbor configuration and restart BGP daemon on device",
            recovery_commands=[
                "interface eth0",
                "ip bgp neighbor 10.0.0.1 timers 60 180",
                "service bgp restart",
            ],
            verification_steps=[
                "show ip bgp neighbor | grep 10.0.0.1",
                "show ip bgp summary",
                "ping 10.0.0.1",
            ],
            evidence="BGP neighbor state: ESTABLISHED → IDLE, hold timer 0s, uptime counter reset",
            diagnostic_reasoning="BGP keepalive not received indicates either link issue or daemon crash. "
            "BGP state change from ESTABLISHED to IDLE indicates graceful shutdown.",
        )

        # Process
        report = await orchestrator.process(diagnosis)

        # Display
        print(report.summary())
        print(f"\n✓ Decision: {report.overall_decision.value.upper()}")
        print(f"✓ Routing: {report.routing_decision.target.value}")

        return report

    @staticmethod
    async def example_2_warning_review():
        """
        Example 2: Diagnosis with warnings, requires human review
        
        Scenario: Network interface down - Expert Agent has minor issues
        
        Expected Result: REVIEW → HUMAN_REVIEW_QUEUE
        Time: ~5 minutes
        
        Key Learning:
        - Constraint score OK but not excellent (0.70-0.85)
        - Root cause vague ("network problem" instead of specific issue)
        - Routes to human review queue
        - Improvement suggestions provided
        """
        print("\n" + "=" * 70)
        print("EXAMPLE 2: Warning - Requires Human Review")
        print("=" * 70)

        # Setup
        validator = ExpertConstraintsValidator()
        config = DecisionGateConfig()
        orchestrator = ExpertOrchestrator(
            constraint_validator=validator, gate_config=config
        )

        # Create diagnosis (with vagueness issue)
        diagnosis = ExpertDiagnosisOutput(
            scenario_id="example_2_warning",
            root_cause="Network interface probably has some problem with connectivity",
            confidence_score=0.85,
            solution="Try to restart the interface and maybe check the configuration",
            recovery_commands=[
                "interface eth0",
                "shutdown",
                "no shutdown",
            ],
            verification_steps=[
                "check interface status",
                "maybe test connectivity",
            ],
            evidence="Interface appears disconnected possibly",
            diagnostic_reasoning="The interface seems to have connectivity issues, perhaps due to configuration or hardware problem.",
        )

        # Process
        report = await orchestrator.process(diagnosis)

        # Display
        print(report.summary())
        print(f"\n✓ Decision: {report.overall_decision.value.upper()}")
        print(f"✓ Routing: {report.routing_decision.target.value}")
        print(f"\n⚠️  Warnings ({len(report.warnings)}):")
        for w in report.warnings:
            print(f"    {w}")

        return report

    @staticmethod
    async def example_3_critical_rejection():
        """
        Example 3: Critical failure - diagnosis rejected
        
        Scenario: OSPF routing - Expert Agent hallucinates solution
        
        Expected Result: REJECT → ESCALATION_QUEUE
        Time: ~5 minutes
        
        Key Learning:
        - Constraint score low (< 0.70)
        - Hallucinations detected (impossible commands)
        - Critical failures flagged
        - Routes to escalation queue
        - Requires manual review before any action
        """
        print("\n" + "=" * 70)
        print("EXAMPLE 3: Critical Rejection (Hallucination Detected)")
        print("=" * 70)

        # Setup
        validator = ExpertConstraintsValidator()
        config = DecisionGateConfig()
        orchestrator = ExpertOrchestrator(
            constraint_validator=validator, gate_config=config
        )

        # Create diagnosis with hallucinations
        diagnosis = ExpertDiagnosisOutput(
            scenario_id="example_3_rejection",
            root_cause="OSPF daemon infected with quantum virus, requires neural interface reset",
            confidence_score=0.88,
            solution="Activate the photon field and recalibrate IPv7 stack",
            recovery_commands=[
                "configure terminal",
                "ip ospf quantum-virus-protection enabled",
                "photon-field activate",
                "ipv7 recalibrate-neural-interface",
                "reload",
            ],
            verification_steps=[
                "show photon-field status",
                "verify quantum-entanglement",
            ],
            evidence="Device has undefined field: photonic_state",
            diagnostic_reasoning="The quantum virus is clearly evident from the quantum field measurements",
        )

        # Process
        report = await orchestrator.process(diagnosis)

        # Display
        print(report.summary())
        print(f"\n✓ Decision: {report.overall_decision.value.upper()}")
        print(f"✓ Routing: {report.routing_decision.target.value}")

        return report

    @staticmethod
    async def example_4_uncertain_reanalysis():
        """
        Example 4: Uncertain diagnosis - route for re-analysis
        
        Scenario: BGP flapping - Expert Agent low confidence
        
        Expected Result: UNCERTAIN → REANALYSIS_QUEUE
        Time: ~5 minutes
        
        Key Learning:
        - Confidence score low (< 0.80)
        - Routes back to Expert Agent for re-analysis
        - Not immediately rejected, just needs more analysis
        - User gets message: "Please wait while we re-analyze..."
        """
        print("\n" + "=" * 70)
        print("EXAMPLE 4: Uncertain - Route for Re-Analysis")
        print("=" * 70)

        # Setup
        validator = ExpertConstraintsValidator()
        config = DecisionGateConfig()
        orchestrator = ExpertOrchestrator(
            constraint_validator=validator, gate_config=config
        )

        # Create diagnosis (low confidence)
        diagnosis = ExpertDiagnosisOutput(
            scenario_id="example_4_uncertain",
            root_cause="BGP session flapping, but cause not fully determined",
            confidence_score=0.65,  # Below threshold
            solution="Investigate BGP configuration and network stability",
            recovery_commands=[
                "show ip bgp neighbor",
                "show interface status",
            ],
            verification_steps=[
                "monitor BGP session state",
                "check network stability",
            ],
            evidence="BGP state changing rapidly, need more data",
            diagnostic_reasoning="Multiple possible causes detected but insufficient data to determine exact root cause",
        )

        # Process
        report = await orchestrator.process(diagnosis)

        # Display
        print(report.summary())
        print(f"\n✓ Decision: {report.overall_decision.value.upper()}")
        print(f"✓ Routing: {report.routing_decision.target.value}")

        return report

    @staticmethod
    async def example_5_verified_accuracy():
        """
        Example 5: Process with ground truth verification
        
        Scenario: Interface down - Compare against expected diagnosis
        
        Expected Result: ACCEPT (if accurate) or REVIEW (if inaccurate)
        Time: ~10 minutes
        
        Key Learning:
        - Uses Task 5 VerificationReport
        - Compares agent diagnosis against ground truth
        - Calculates accuracy score
        - Uses hybrid gate (constraint + accuracy)
        - Better confidence in decision
        """
        print("\n" + "=" * 70)
        print("EXAMPLE 5: Verified Acceptance (With Ground Truth)")
        print("=" * 70)

        # Setup
        validator = ExpertConstraintsValidator()
        verifier = DiagnosisVerifier()
        config = DecisionGateConfig(hybrid_gate_enabled=True)
        orchestrator = ExpertOrchestrator(
            constraint_validator=validator, verifier=verifier, gate_config=config
        )

        # Create diagnosis
        diagnosis = ExpertDiagnosisOutput(
            scenario_id="example_5_verified",
            root_cause="Interface Gigabit0/0/0 shutdown due to administrative action",
            confidence_score=0.92,
            solution="Enable the interface",
            recovery_commands=["interface Gigabit0/0/0", "no shutdown"],
            verification_steps=[
                "show interfaces Gigabit0/0/0",
                "show interfaces Gigabit0/0/0 status",
            ],
            evidence="Interface status: administratively down, line protocol down",
            diagnostic_reasoning="Interface Gigabit0/0/0 shows administrative shutdown in 'show interfaces' output",
        )

        # Create ground truth
        ground_truth = GroundTruth(
            scenario_id="example_5_verified",
            expected_root_cause="Interface shutdown (administrative)",
            expected_solution="Enable interface via no shutdown command",
            expected_recovery_commands=["interface Gigabit0/0/0", "no shutdown"],
            expected_verification_steps=[
                "show interfaces status",
                "verify interface is up",
            ],
            difficulty_level="simple",
            description="Interface administratively shut down",
        )

        # Process (with ground truth)
        report = await orchestrator.process(diagnosis, ground_truth=ground_truth)

        # Display
        print(report.summary())
        print(f"\n✓ Decision: {report.overall_decision.value.upper()}")
        print(f"✓ Routing: {report.routing_decision.target.value}")
        if report.accuracy_score:
            print(f"✓ Accuracy: {report.accuracy_score:.2%}")
        if report.hybrid_score:
            print(f"✓ Hybrid Score: {report.hybrid_score:.2%}")

        return report

    @staticmethod
    async def example_6_batch_processing():
        """
        Example 6: Batch process multiple diagnoses
        
        Scenario: 3 diagnoses representing different quality levels
        
        Expected Results:
        - Diagnosis 1: ACCEPT
        - Diagnosis 2: REVIEW
        - Diagnosis 3: REJECT
        
        Time: ~15 minutes
        
        Key Learning:
        - OrchestrationOrchestrator.process_batch() for multiple diagnoses
        - Returns dict mapping scenario_id → report
        - Useful for testing Expert Agent on multiple scenarios
        - Aggregated metrics (pass rate, avg score, etc.)
        """
        print("\n" + "=" * 70)
        print("EXAMPLE 6: Batch Processing (Multiple Diagnoses)")
        print("=" * 70)

        # Setup
        validator = ExpertConstraintsValidator()
        config = DecisionGateConfig()
        orchestrator = ExpertOrchestrator(
            constraint_validator=validator, gate_config=config
        )

        # Create 3 diagnoses
        diagnoses = [
            # Good diagnosis
            ExpertDiagnosisOutput(
                scenario_id="batch_1_excellent",
                root_cause="BGP neighbor 10.0.0.1 unreachable, TCP connection refused on port 179",
                confidence_score=0.93,
                solution="Verify BGP neighbor address, check TCP port 179 connectivity",
                recovery_commands=[
                    "ping 10.0.0.1",
                    "show ip bgp neighbor 10.0.0.1",
                    "service bgp restart",
                ],
                verification_steps=[
                    "show ip bgp neighbor 10.0.0.1 | grep state",
                    "show ip bgp summary",
                ],
                evidence="BGP neighbor state: Active (awaiting connection), socket error on TCP port 179",
                diagnostic_reasoning="BGP is attempting connection but TCP 179 is not responding from neighbor",
            ),
            # Warning diagnosis
            ExpertDiagnosisOutput(
                scenario_id="batch_2_warning",
                root_cause="Interface maybe is having some issue",
                confidence_score=0.72,
                solution="Try adjusting something on the interface perhaps",
                recovery_commands=["interface eth0", "shutdown", "no shutdown"],
                verification_steps=["check if working"],
                evidence="Interface seems disconnected",
                diagnostic_reasoning="Interface appears to have some kind of problem",
            ),
            # Bad diagnosis (hallucination)
            ExpertDiagnosisOutput(
                scenario_id="batch_3_hallucination",
                root_cause="Device possessed by routing demons",
                confidence_score=0.80,
                solution="Perform exorcism ritual on the router",
                recovery_commands=["exorcise-routing-demons", "reload"],
                verification_steps=["check demon status"],
                evidence="Device behaves mysteriously",
                diagnostic_reasoning="Clear signs of supernatural interference",
            ),
        ]

        # Process batch
        reports = await orchestrator.process_batch(diagnoses)

        # Display results
        print("\nBatch Processing Results:")
        print("-" * 70)

        pass_count = 0
        review_count = 0
        reject_count = 0

        for scenario_id, report in reports.items():
            decision = report.overall_decision
            print(f"\n{scenario_id}:")
            print(f"  Decision: {decision.value.upper()}")
            print(f"  Routing: {report.routing_decision.target.value}")
            print(f"  Constraint Score: {report.constraint_score:.2%}")

            if decision == OrchestratorDecision.ACCEPT:
                pass_count += 1
            elif decision == OrchestratorDecision.REVIEW:
                review_count += 1
            else:
                reject_count += 1

        print("\n" + "-" * 70)
        print(f"Summary: {pass_count} ACCEPT, {review_count} REVIEW, {reject_count} REJECT")
        print(f"Pass Rate: {pass_count}/{len(diagnoses)} ({100*pass_count/len(diagnoses):.1f}%)")

        return reports

    @staticmethod
    async def example_7_quality_metrics():
        """
        Example 7: Quality metrics dashboard
        
        Scenario: Evaluate Expert Agent quality across multiple criteria
        
        Expected Output: Comprehensive quality report with metrics
        Time: ~10 minutes
        
        Key Learning:
        - Aggregated score distribution
        - Decision distribution (accept/review/reject rates)
        - Confidence histogram
        - Improvement areas
        - Acceptance gates summary
        """
        print("\n" + "=" * 70)
        print("EXAMPLE 7: Quality Metrics Dashboard")
        print("=" * 70)

        # Setup
        validator = ExpertConstraintsValidator()
        orchestrator = ExpertOrchestrator(constraint_validator=validator)

        # Create test diagnoses representing quality distribution
        diagnoses = []
        quality_levels = [
            ("excellent", 0.95, 0.93),  # Excellent: high confidence, high constraint
            ("good", 0.90, 0.88),
            ("good", 0.88, 0.87),
            ("acceptable", 0.82, 0.80),
            ("acceptable", 0.80, 0.75),
            ("warning", 0.75, 0.72),
            ("warning", 0.72, 0.68),
        ]

        for level, confidence, constraint_expectation in quality_levels:
            diagnosis = ExpertDiagnosisOutput(
                scenario_id=f"quality_{level}_{len(diagnoses)+1}",
                root_cause=f"Sample {level.upper()} diagnosis",
                confidence_score=confidence,
                solution="Standard recovery procedure",
                recovery_commands=["command1", "command2"],
                verification_steps=["verify step"],
                evidence="Sample evidence",
                diagnostic_reasoning="Standard reasoning for testing",
            )
            diagnoses.append(diagnosis)

        # Process batch
        reports = await orchestrator.process_batch(diagnoses)

        # Calculate metrics
        decisions = {
            "accept": 0,
            "review": 0,
            "reject": 0,
            "uncertain": 0,
        }

        constraint_scores = []
        confidence_scores = []
        routing_targets = {}

        for report in reports.values():
            decision_key = report.overall_decision.value
            decisions[decision_key] = decisions.get(decision_key, 0) + 1

            constraint_scores.append(report.constraint_score)
            confidence_scores.append(report.confidence_score)

            target = report.routing_decision.target.value
            routing_targets[target] = routing_targets.get(target, 0) + 1

        # Display dashboard
        print("\n📊 QUALITY METRICS DASHBOARD")
        print("=" * 70)

        print(f"\nDecision Distribution (Total: {len(reports)})")
        for decision, count in decisions.items():
            pct = 100 * count / len(reports)
            bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
            print(f"  {decision:12} {count:2}  {bar} {pct:5.1f}%")

        print(f"\nScore Statistics")
        avg_constraint = sum(constraint_scores) / len(constraint_scores)
        avg_confidence = sum(confidence_scores) / len(confidence_scores)
        print(f"  Constraint Avg:  {avg_constraint:.2%}")
        print(f"  Confidence Avg:  {avg_confidence:.2%}")
        print(f"  Constraint Min:  {min(constraint_scores):.2%}")
        print(f"  Constraint Max:  {max(constraint_scores):.2%}")

        print(f"\nRouting Targets")
        for target, count in routing_targets.items():
            pct = 100 * count / len(reports)
            print(f"  {target:25} {count:2}  ({pct:5.1f}%)")

        print(f"\nAcceptance Gates")
        print(f"  Pass Rate:       {100 * decisions['accept'] / len(reports):5.1f}%")
        print(f"  Review Rate:     {100 * decisions['review'] / len(reports):5.1f}%")
        print(f"  Reject Rate:     {100 * decisions['reject'] / len(reports):5.1f}%")

        print("\n" + "=" * 70)

        return reports

    @staticmethod
    async def run_all_examples():
        """Run all 7 examples sequentially"""
        print("\n" + "=" * 70)
        print("EXPERT ORCHESTRATOR - COMPLETE WORKING EXAMPLES")
        print("=" * 70)

        results = {}

        # Example 1
        results["example_1"] = await OrchestratorExamples.example_1_simple_acceptance()

        # Example 2
        results["example_2"] = await OrchestratorExamples.example_2_warning_review()

        # Example 3
        results["example_3"] = (
            await OrchestratorExamples.example_3_critical_rejection()
        )

        # Example 4
        results["example_4"] = await OrchestratorExamples.example_4_uncertain_reanalysis()

        # Example 5
        results["example_5"] = await OrchestratorExamples.example_5_verified_accuracy()

        # Example 6
        results["example_6"] = await OrchestratorExamples.example_6_batch_processing()

        # Example 7
        results["example_7"] = await OrchestratorExamples.example_7_quality_metrics()

        print("\n" + "=" * 70)
        print("ALL EXAMPLES COMPLETED SUCCESSFULLY ✓")
        print("=" * 70)

        return results


# ============================================================================
# Main Execution
# ============================================================================


if __name__ == "__main__":
    asyncio.run(OrchestratorExamples.run_all_examples())
