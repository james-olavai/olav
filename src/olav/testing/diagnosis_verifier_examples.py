"""
Diagnosis Verifier - Usage Examples

Demonstrates how to verify Expert Agent diagnostic accuracy
against ground truth data.

Version: v1.0.0 (2026-02-11)
"""

import asyncio
from typing import List
from diagnosis_verifier import (
    DiagnosisVerifier,
    GroundTruth,
    AccuracyLevel,
)

# Import from Task 4 constraints system
try:
    from expert_constraints import ExpertDiagnosisOutput
except ImportError:
    # Fallback definition if not available
    from dataclasses import dataclass, field
    
    @dataclass
    class ExpertDiagnosisOutput:
        scenario_id: str
        root_cause: str
        confidence_score: float
        solution: str
        verification_steps: List[str] = field(default_factory=list)
        evidence: List[str] = field(default_factory=list)
        diagnostic_reasoning: str = ""
        recovery_commands: List[str] = field(default_factory=list)


class DiagnosisVerifierExamples:
    """Complete examples of diagnosis verification."""
    
    @staticmethod
    async def example_1_perfect_diagnosis():
        """
        Example 1: Perfect diagnosis matching ground truth.
        
        Shows what happens when Expert Agent is 100% correct.
        """
        print("\n" + "="*70)
        print("EXAMPLE 1: Perfect Diagnosis (100% Accurate)")
        print("="*70)
        
        # Define ground truth for Scenario 1
        ground_truth = GroundTruth(
            scenario_id="scenario_1_bgp_interface_down",
            expected_root_cause="BGP neighbor down because interface Gi1 shutdown",
            expected_solution="Execute 'no shutdown' on interface Gi1",
            expected_recovery_commands=[
                "configure terminal",
                "interface Gi1",
                "no shutdown",
                "exit",
            ],
            expected_verification_steps=[
                "show interface Gi1",
                "show ip bgp neighbors",
                "show ip bgp summary",
            ],
            difficulty_level="simple",
            description="BGP neighbor down due to interface shutdown",
        )
        
        # Create perfect diagnosis (matches ground truth exactly)
        expert_diagnosis = ExpertDiagnosisOutput(
            scenario_id="scenario_1_bgp_interface_down",
            root_cause="BGP neighbor 3.3.3.3 is down because interface Gi1 is shutdown",
            confidence_score=0.98,
            solution="Execute the 'no shutdown' command on interface Gi1 to restore BGP adjacency",
            recovery_commands=[
                "configure terminal",
                "interface Gi1",
                "no shutdown",
                "exit",
            ],
            verification_steps=[
                "show interface Gi1",
                "show ip bgp neighbors",
                "show ip bgp summary",
            ],
            evidence=[
                "Interface Gi1 shows 'administratively down'",
                "BGP neighbor 3.3.3.3 shows IDLE state",
            ],
        )
        
        # Verify
        verifier = DiagnosisVerifier()
        report = await verifier.verify(expert_diagnosis, ground_truth, constraint_score=0.95)
        
        # Print results
        print(report.summary())
        print(f"\n✅ PERFECT DIAGNOSIS: {report.overall_accuracy_score:.0%} accuracy")
        
        return report
    
    @staticmethod
    async def example_2_excellent_diagnosis():
        """
        Example 2: Excellent diagnosis with minor variations.
        
        Shows diagnosis that's 90%+ correct but has some wording differences.
        """
        print("\n" + "="*70)
        print("EXAMPLE 2: Excellent Diagnosis (90%+ Accurate)")
        print("="*70)
        
        ground_truth = GroundTruth(
            scenario_id="scenario_2_ospf_mismatch",
            expected_root_cause="OSPF neighbor down because hello interval mismatch",
            expected_solution="Change hello interval to 10 seconds on R2",
            expected_recovery_commands=[
                "configure terminal",
                "interface Gi2",
                "ip ospf hello-interval 10",
                "exit",
            ],
            expected_verification_steps=[
                "show ip ospf interface Gi2",
                "show ip ospf neighbors",
            ],
            difficulty_level="medium",
        )
        
        # Very good diagnosis (captures key concepts)
        excellent_diagnosis = ExpertDiagnosisOutput(
            scenario_id="scenario_2_ospf_mismatch",
            root_cause="OSPF neighbor shows down due to hello interval mismatch between routers",
            confidence_score=0.92,
            solution="Synchronize hello intervals by configuring R2 interface to 10 second intervals",
            recovery_commands=[
                "config terminal",
                "interface Gi2",
                "ip ospf hello-interval 10",
                "exit",
            ],
            verification_steps=[
                "show ip ospf interface Gi2",
                "show ip ospf neighbors",
            ],
            evidence=[
                "R1 hello interval: 10 seconds",
                "R2 hello interval: 15 seconds (mismatch)",
            ],
        )
        
        # Verify
        verifier = DiagnosisVerifier()
        report = await verifier.verify(excellent_diagnosis, ground_truth, constraint_score=0.90)
        
        print(report.summary())
        print(f"\n✅ EXCELLENT DIAGNOSIS: {report.overall_accuracy_score:.0%} accuracy")
        
        return report
    
    @staticmethod
    async def example_3_partial_diagnosis():
        """
        Example 3: Diagnosis with some correct elements but gaps.
        
        Shows what happens when Expert Agent partially understands the issue.
        """
        print("\n" + "="*70)
        print("EXAMPLE 3: Partial Diagnosis (70% Accurate)")
        print("="*70)
        
        ground_truth = GroundTruth(
            scenario_id="scenario_1_bgp_interface_down",
            expected_root_cause="BGP neighbor down because interface shutdown",
            expected_solution="Execute 'no shutdown' on interface",
            expected_recovery_commands=["no shutdown on interface Gi1"],
            expected_verification_steps=["show interface", "show ip bgp"],
            difficulty_level="simple",
        )
        
        # Partial diagnosis (correct general concept, vague on details)
        partial_diagnosis = ExpertDiagnosisOutput(
            scenario_id="scenario_1_bgp_interface_down",
            root_cause="There is a networking connectivity issue affecting BGP",
            confidence_score=0.78,
            solution="Fix the interface configuration problem",
            recovery_commands=["fix the interface"],
            verification_steps=["check interface status"],
            evidence=["Network problem detected"],
        )
        
        # Verify
        verifier = DiagnosisVerifier()
        report = await verifier.verify(partial_diagnosis, ground_truth, constraint_score=0.70)
        
        print(report.summary())
        print(f"\n⚠️  PARTIAL DIAGNOSIS: {report.overall_accuracy_score:.0%} accuracy")
        
        return report
    
    @staticmethod
    async def example_4_wrong_diagnosis():
        """
        Example 4: Completely wrong diagnosis.
        
        Shows what happens when Expert Agent is fundamentally incorrect.
        """
        print("\n" + "="*70)
        print("EXAMPLE 4: Wrong Diagnosis (0% Accurate)")
        print("="*70)
        
        ground_truth = GroundTruth(
            scenario_id="scenario_1_bgp_interface_down",
            expected_root_cause="Interface Gi1 is shut down",
            expected_solution="Execute 'no shutdown' on Gi1",
            expected_recovery_commands=["no shutdown"],
            expected_verification_steps=["show interface Gi1"],
            difficulty_level="simple",
        )
        
        # Completely wrong diagnosis
        wrong_diagnosis = ExpertDiagnosisOutput(
            scenario_id="scenario_1_bgp_interface_down",
            root_cause="CPU usage is too high due to routing table explosion",
            confidence_score=0.85,
            solution="Clear BGP cache and restart the BGP process",
            recovery_commands=[
                "clear ip bgp *",
                "clear ip route *",
            ],
            verification_steps=[
                "show processes cpu",
                "show ip route summary",
            ],
            evidence=["High CPU detected"],
        )
        
        # Verify
        verifier = DiagnosisVerifier()
        report = await verifier.verify(wrong_diagnosis, ground_truth, constraint_score=0.50)
        
        print(report.summary())
        print(f"\n❌ WRONG DIAGNOSIS: {report.overall_accuracy_score:.0%} accuracy")
        
        return report
    
    @staticmethod
    async def example_5_batch_verification():
        """
        Example 5: Verify multiple diagnoses across scenarios.
        
        Useful for testing Expert Agent on a suite of scenarios
        and generating overall quality metrics.
        """
        print("\n" + "="*70)
        print("EXAMPLE 5: Batch Verification (Multiple Scenarios)")
        print("="*70)
        
        # Define ground truths for 3 scenarios
        ground_truth_1 = GroundTruth(
            scenario_id="scenario_1",
            expected_root_cause="Interface shutdown",
            expected_solution="no shutdown",
            expected_recovery_commands=["no shutdown"],
            expected_verification_steps=["show interface"],
            difficulty_level="simple",
        )
        
        ground_truth_2 = GroundTruth(
            scenario_id="scenario_2",
            expected_root_cause="Hello interval mismatch",
            expected_solution="Synchronize hello intervals",
            expected_recovery_commands=["ip ospf hello-interval 10"],
            expected_verification_steps=["show ip ospf interface"],
            difficulty_level="medium",
        )
        
        ground_truth_3 = GroundTruth(
            scenario_id="scenario_3",
            expected_root_cause="BGP AS number mismatch",
            expected_solution="Correct AS number configuration",
            expected_recovery_commands=["router bgp 65000"],
            expected_verification_steps=["show run | include router bgp"],
            difficulty_level="medium",
        )
        
        # Create expert diagnoses (mix of good and bad)
        diagnosis_1 = ExpertDiagnosisOutput(
            scenario_id="scenario_1",
            root_cause="Interface is shutdown",
            confidence_score=0.95,
            solution="Execute no shutdown",
            recovery_commands=["no shutdown"],
            verification_steps=["show interface"],
        )
        
        diagnosis_2 = ExpertDiagnosisOutput(
            scenario_id="scenario_2",
            root_cause="OSPF hello interval mismatch between neighbors",
            confidence_score=0.88,
            solution="Synchronize hello intervals to 10 seconds",
            recovery_commands=["ip ospf hello-interval 10"],
            verification_steps=["show ip ospf interface"],
        )
        
        diagnosis_3 = ExpertDiagnosisOutput(
            scenario_id="scenario_3",
            root_cause="BGP is not configured properly",
            confidence_score=0.65,
            solution="Configure BGP correctly",
            recovery_commands=["configure bgp"],
            verification_steps=["check bgp"],
        )
        
        # Prepare batch data
        batch_diagnoses = [
            (diagnosis_1, ground_truth_1),
            (diagnosis_2, ground_truth_2),
            (diagnosis_3, ground_truth_3),
        ]
        
        constraint_scores = {
            "scenario_1": 0.95,
            "scenario_2": 0.88,
            "scenario_3": 0.65,
        }
        
        # Verify batch
        verifier = DiagnosisVerifier()
        reports = await verifier.verify_batch(batch_diagnoses, constraint_scores)
        
        # Print results
        print("\nBatch Verification Results:")
        print("-" * 70)
        
        passed = 0
        scores = []
        
        for scenario_id, report in reports.items():
            status = "✅" if report.passed() else "❌"
            accuracy = report.overall_accuracy_score
            scores.append(accuracy)
            
            print(f"{scenario_id:20} | {status} | Accuracy: {accuracy:.0%}")
            
            if report.passed():
                passed += 1
        
        print("-" * 70)
        avg_accuracy = sum(scores) / len(scores) if scores else 0
        print(f"\nSummary: {passed}/{len(reports)} passed")
        print(f"Average Accuracy: {avg_accuracy:.0%}")
        print(f"Pass Rate: {100*passed/len(reports):.0f}%")
        
        return reports
    
    @staticmethod
    async def example_6_metrics_dashboard():
        """
        Example 6: Generate quality metrics from verification results.
        
        Useful for tracking Expert Agent quality over time
        and making deployment decisions.
        """
        print("\n" + "="*70)
        print("EXAMPLE 6: Quality Metrics & Acceptance Gates")
        print("="*70)
        
        # Generate sample ground truths
        ground_truths = [
            GroundTruth(
                scenario_id=f"scenario_{i}",
                expected_root_cause=f"Issue {i}",
                expected_solution=f"Fix {i}",
                expected_recovery_commands=[f"command {i}"],
                expected_verification_steps=[f"verify {i}"],
                difficulty_level="simple" if i < 3 else "medium",
            )
            for i in range(1, 8)
        ]
        
        # Generate sample diagnoses with varying accuracy
        diagnoses_with_truth = []
        for i, truth in enumerate(ground_truths, 1):
            # Decreasing accuracy (good first half, worse second half)
            accuracy = 0.98 - (i * 0.08)
            
            diagnosis = ExpertDiagnosisOutput(
                scenario_id=f"scenario_{i}",
                root_cause=f"Issue {i}" if accuracy > 0.80 else f"Wrong issue {i}",
                confidence_score=max(0.65, accuracy),
                solution=f"Fix {i}" if accuracy > 0.75 else "generic fix",
                recovery_commands=[f"command {i}"],
                verification_steps=[f"verify {i}"],
            )
            
            diagnoses_with_truth.append((diagnosis, truth))
        
        # Verify all
        verifier = DiagnosisVerifier()
        reports = await verifier.verify_batch(diagnoses_with_truth)
        
        # Calculate metrics
        passed = sum(1 for r in reports.values() if r.passed())
        excellent = sum(1 for r in reports.values() if r.overall_accuracy_level == AccuracyLevel.EXCELLENT)
        good = sum(1 for r in reports.values() if r.overall_accuracy_level == AccuracyLevel.GOOD)
        fair = sum(1 for r in reports.values() if r.overall_accuracy_level == AccuracyLevel.FAIR)
        poor = sum(1 for r in reports.values() if r.overall_accuracy_level == AccuracyLevel.POOR)
        
        avg_accuracy = sum(r.overall_accuracy_score for r in reports.values()) / len(reports)
        
        # Print dashboard
        print("\nQuality Metrics Dashboard:")
        print(f"  Total Scenarios:          {len(reports)}")
        print(f"  Passed (≥80%):            {passed}/{len(reports)} ({100*passed/len(reports):.0f}%)")
        print(f"  Excellent (90-94%):       {excellent}")
        print(f"  Good (80-89%):            {good}")
        print(f"  Fair (70-79%):            {fair}")
        print(f"  Poor (<70%):              {poor}")
        print(f"  Average Accuracy:         {avg_accuracy:.0%}")
        
        # Acceptance gate analysis
        print("\nAcceptance Gate Analysis:")
        
        pass_rate = passed / len(reports) if reports else 0
        min_pass_rate = 0.90 if all(
            ground_truths[i].difficulty_level == "simple"
            for i in range(len(ground_truths))
        ) else 0.75
        
        if pass_rate >= 0.90 and avg_accuracy >= 0.85:
            print("  ✅ ACCEPTED: Meets production criteria")
            print(f"     • Pass rate: {pass_rate:.0%} (need ≥90%)")
            print(f"     • Avg accuracy: {avg_accuracy:.0%} (need ≥85%)")
        elif pass_rate >= 0.75 and avg_accuracy >= 0.75:
            print("  ⚠️  CONDITIONAL: Meets staging criteria")
            print(f"     • Pass rate: {pass_rate:.0%} (need ≥75%)")
            print(f"     • Avg accuracy: {avg_accuracy:.0%} (need ≥75%)")
        else:
            print("  ❌ REJECTED: Below acceptance threshold")
            print(f"     • Pass rate: {pass_rate:.0%} (need ≥75%)")
            print(f"     • Avg accuracy: {avg_accuracy:.0%} (need ≥75%)")
        
        return reports


async def main():
    """Run all examples."""
    examples = DiagnosisVerifierExamples()
    
    print("\n")
    print("#" * 70)
    print("# Diagnosis Verifier - Usage Examples")
    print("#" * 70)
    
    # Run examples
    await examples.example_1_perfect_diagnosis()
    await examples.example_2_excellent_diagnosis()
    await examples.example_3_partial_diagnosis()
    await examples.example_4_wrong_diagnosis()
    await examples.example_5_batch_verification()
    await examples.example_6_metrics_dashboard()
    
    print("\n" + "="*70)
    print("All Examples Completed Successfully!")
    print("="*70)


if __name__ == "__main__":
    asyncio.run(main())
