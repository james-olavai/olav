"""
Expert Constraints Usage Examples

Demonstrates how to validate Expert Agent diagnostic outputs
against constraints to prevent hallucinations and ensure quality.

Version: v1.0.0 (2026-02-11)
"""

import asyncio
from expert_constraints import (
    ExpertConstraintsValidator,
    ExpertDiagnosisOutput,
    ConstraintStatus,
)


class ConstraintValidationExamples:
    """Example usage patterns for constraint validation."""
    
    @staticmethod
    async def example_1_simple_validation():
        """
        Example 1: Validate a single diagnosis output.
        
        This shows the basic flow:
        1. Create diagnosis output from Expert Agent
        2. Run validation
        3. Check if constraints passed
        """
        print("\n" + "="*70)
        print("EXAMPLE 1: Simple Validation")
        print("="*70)
        
        # Simulated diagnosis from Expert Agent for Scenario 1
        diagnosis = ExpertDiagnosisOutput(
            scenario_id="scenario_1_bgp_interface_down",
            root_cause="BGP neighbor 3.3.3.3 on R1 is down because interface Gi1 is administratively shutdown using the 'shutdown' command.",
            confidence_score=0.95,
            solution="Remove the shutdown command from interface Gi1, then restart BGP process to re-establish neighbor adjacency.",
            verification_steps=[
                "show interface Gi1",
                "show ip bgp neighbors 3.3.3.3",
                "show ip bgp summary",
            ],
            evidence=[
                "show interface Gi1 shows 'administratively down'",
                "show ip bgp neighbors 3.3.3.3 shows 'Neighbor is DOWN'",
                "show ip bgp summary shows 0 established neighbors",
            ],
            diagnostic_reasoning="Interface status directly impacts BGP neighbor state. Shutdown command on Gi1 prevents BGP neighbor formation. Removing shutdown and clearing counters will restore adjacency.",
            recovery_commands=[
                "configure terminal",
                "interface Gi1",
                "no shutdown",
                "exit",
            ],
        )
        
        # Create validator and validate
        validator = ExpertConstraintsValidator()
        report = await validator.validate(diagnosis)
        
        # Print results
        print(report.summary())
        print(f"\n✅ Validation {'PASSED' if report.passed() else 'FAILED'}")
        return report
    
    @staticmethod
    async def example_2_detect_hallucination():
        """
        Example 2: Detect hallucination in diagnosis.
        
        This shows how the constraint system identifies suspicious patterns:
        - Vague terms (也许, 可能, maybe, probably)
        - Circular reasoning
        - Generic solutions
        """
        print("\n" + "="*70)
        print("EXAMPLE 2: Detect Hallucination")
        print("="*70)
        
        # Problematic diagnosis with hallucination characteristics
        bad_diagnosis = ExpertDiagnosisOutput(
            scenario_id="scenario_1_bad_hallucination",
            root_cause="可能 BGP 接口可能会 shutdown，也许导致邻居可能 down，可能需要 fix",
            confidence_score=0.45,  # Low confidence is a red flag
            solution="可能需要 check 接口，然后 configure some things",
            verification_steps=[],  # Empty verification steps
            evidence=[],  # No supporting evidence
            diagnostic_reasoning="",
            recovery_commands=[],
        )
        
        validator = ExpertConstraintsValidator()
        report = await validator.validate(bad_diagnosis)
        
        print(report.summary())
        print(f"\n❌ Validation {'PASSED' if report.passed() else 'FAILED'}")
        print("\nHallucination Indicators:")
        for result in report.constraint_results:
            if result.violations:
                for violation in result.violations:
                    print(f"  • {violation.message}")
                    print(f"    → {violation.suggestion}")
        
        return report
    
    @staticmethod
    async def example_3_incomplete_diagnosis():
        """
        Example 3: Handle incomplete diagnosis.
        
        Shows what happens when Expert Agent provides incomplete output:
        - Missing RCA
        - Missing solution
        - Missing recovery commands
        """
        print("\n" + "="*70)
        print("EXAMPLE 3: Incomplete Diagnosis Detection")
        print("="*70)
        
        incomplete_diagnosis = ExpertDiagnosisOutput(
            scenario_id="scenario_2_incomplete",
            root_cause="",  # Missing RCA!
            confidence_score=0.88,
            solution="Execute no shutdown",
            verification_steps=["show interface"],
            evidence=["Interface down"],
            recovery_commands=["no shutdown"],
        )
        
        validator = ExpertConstraintsValidator()
        report = await validator.validate(incomplete_diagnosis)
        
        print(report.summary())
        print(f"\n❌ Critical Issues Found: {len(report.critical_failures)}")
        
        return report
    
    @staticmethod
    async def example_4_batch_validation():
        """
        Example 4: Validate multiple diagnoses from different scenarios.
        
        Useful for:
        - Testing Expert Agent across multiple fault scenarios
        - Generating quality metrics and reports
        - Identifying pattern of issues
        """
        print("\n" + "="*70)
        print("EXAMPLE 4: Batch Validation (Multiple Scenarios)")
        print("="*70)
        
        # Create sample diagnoses for different scenarios
        diagnoses = [
            # Scenario 1: Good diagnosis
            ExpertDiagnosisOutput(
                scenario_id="scenario_1_bgp_interface_down",
                root_cause="BGP neighbor down due to interface shutdown on Gi1",
                confidence_score=0.95,
                solution="Execute 'no shutdown' on interface Gi1",
                verification_steps=["show interface Gi1", "show ip bgp summary"],
                evidence=["Interface administratively down", "BGP neighbor state IDLE"],
                recovery_commands=["config terminal", "interface Gi1", "no shutdown"],
            ),
            # Scenario 2: Medium confidence diagnosis
            ExpertDiagnosisOutput(
                scenario_id="scenario_2_bgp_config_mismatch",
                root_cause="BGP AS number mismatch between R1 (AS 65000) and R2 (AS 65001): internal peer misconfiguration",
                confidence_score=0.88,
                solution="Correct AS number on R2 to match AS 65000",
                verification_steps=["show run | include router bgp", "show ip bgp summary"],
                evidence=["R1 config shows 'router bgp 65000'", "R2 shows 'router bgp 65002'"],
                recovery_commands=["config terminal", "router bgp 65000", "exit"],
            ),
            # Scenario 3: Risky diagnosis (low confidence + vague terms)
            ExpertDiagnosisOutput(
                scenario_id="scenario_3_risky",
                root_cause="可能 OSPF 接口配置有问题，也许是 hello interval 不匹配",
                confidence_score=0.72,
                solution="检查并修复 OSPF 配置",
                verification_steps=[],
                evidence=[],
                recovery_commands=[],
            ),
        ]
        
        # Validate all diagnoses
        validator = ExpertConstraintsValidator()
        reports = await validator.validate_batch(diagnoses)
        
        # Print summary
        print("\nBatch Validation Results:")
        print("-" * 70)
        
        total_passed = 0
        total_failed = 0
        scores = []
        
        for scenario_id, report in reports.items():
            status = "✅ PASS" if report.passed() else "❌ FAIL"
            print(f"{scenario_id:40} | {status:10} | Score: {report.overall_score:.1%}")
            
            if report.passed():
                total_passed += 1
            else:
                total_failed += 1
            
            scores.append(report.overall_score)
        
        print("-" * 70)
        print(f"Summary: {total_passed} passed, {total_failed} failed")
        avg_score = sum(scores) / len(scores) if scores else 0
        print(f"Average Score: {avg_score:.1%}")
        
        return reports
    
    @staticmethod
    async def example_5_custom_constraints():
        """
        Example 5: Add custom constraints for domain-specific requirements.
        
        Demonstrates extending the constraint system with custom checks
        specific to your network environment.
        """
        print("\n" + "="*70)
        print("EXAMPLE 5: Custom Constraints")
        print("="*70)
        
        from expert_constraints import ConstraintChecker, ConstraintCheckResult, ConstraintStatus, ConstraintLevel
        
        class MustMentionDeviceNames(ConstraintChecker):
            """Custom constraint: diagnosis must mention specific device names."""
            
            def __init__(self):
                super().__init__("Device Name Reference", ConstraintLevel.HIGH)
                self.required_devices = ["R1", "R2", "R3", "R4", "SW1", "SW2"]
            
            async def check(self, diagnosis: ExpertDiagnosisOutput) -> ConstraintCheckResult:
                """Check diagnosis mentions at least one device name."""
                mentioned_devices = [
                    device for device in self.required_devices
                    if device in diagnosis.root_cause or device in diagnosis.solution
                ]
                
                if mentioned_devices:
                    return ConstraintCheckResult(
                        constraint_name=self.name,
                        status=ConstraintStatus.PASSED,
                        level=self.level,
                        message=f"Mentions {len(mentioned_devices)} device(s): {', '.join(mentioned_devices)}",
                        score=1.0,
                    )
                else:
                    return ConstraintCheckResult(
                        constraint_name=self.name,
                        status=ConstraintStatus.FAILED,
                        level=self.level,
                        message="No device names mentioned in diagnosis",
                        score=0.0,
                    )
        
        # Create validator with custom constraint
        custom_checker = MustMentionDeviceNames()
        validator = ExpertConstraintsValidator(custom_checkers=[custom_checker])
        
        # Test diagnosis
        diagnosis = ExpertDiagnosisOutput(
            scenario_id="scenario_with_custom_check",
            root_cause="On R1, BGP neighbor to R3 is down because interface Gi1 is shutdown",
            confidence_score=0.92,
            solution="On R1, remove shutdown from Gi1 to restore BGP to R3",
            verification_steps=["show ip bgp neighbors 3.3.3.3"],
            evidence=["R1 Gi1 is down"],
            recovery_commands=["config terminal", "interface Gi1", "no shutdown"],
        )
        
        report = await validator.validate(diagnosis)
        print(report.summary())
        
        return report
    
    @staticmethod
    async def example_6_constraint_metrics():
        """
        Example 6: Calculate quality metrics from constraint results.
        
        Useful for:
        - Tracking Expert Agent quality over time
        - Identifying which constraints are most problematic
        - Setting acceptance gates for production deployments
        """
        print("\n" + "="*70)
        print("EXAMPLE 6: Quality Metrics & Acceptance Gates")
        print("="*70)
        
        # Create test diagnoses
        diagnoses = []
        for i in range(1, 8):
            confidence = 0.95 - (i * 0.02)  # Decreasing confidence
            diagnoses.append(ExpertDiagnosisOutput(
                scenario_id=f"scenario_{i}",
                root_cause=f"BGP interface shutdown on Gi{i}" if i % 3 != 0 else f"也许 interface 可能 down",
                confidence_score=max(0.7, confidence),
                solution=f"Execute no shutdown on Gi{i}",
                verification_steps=["show interface"],
                evidence=[f"Gi{i} down"],
                recovery_commands=["no shutdown"],
            ))
        
        # Validate all
        validator = ExpertConstraintsValidator()
        reports = await validator.validate_batch(diagnoses)
        
        # Calculate metrics
        passed_count = sum(1 for r in reports.values() if r.passed())
        failed_count = sum(1 for r in reports.values() if r.overall_status == ConstraintStatus.FAILED)
        warning_count = len(reports) - passed_count - failed_count
        avg_score = sum(r.overall_score for r in reports.values()) / len(reports)
        
        # Print metrics
        print("\nQuality Metrics:")
        print(f"  Total Diagnoses: {len(reports)}")
        print(f"  Passed:          {passed_count}/{len(reports)} ({100*passed_count/len(reports):.0f}%)")
        print(f"  Warnings:        {warning_count}/{len(reports)} ({100*warning_count/len(reports):.0f}%)")
        print(f"  Failed:          {failed_count}/{len(reports)} ({100*failed_count/len(reports):.0f}%)")
        print(f"  Average Score:   {avg_score:.1%}")
        
        # Acceptance gate
        print("\nAcceptance Gate Analysis:")
        min_acceptance_rate = 0.85
        min_avg_score = 0.80
        
        acceptance_rate = passed_count / len(reports) if reports else 0
        
        if acceptance_rate >= min_acceptance_rate and avg_score >= min_avg_score:
            print(f"  ✅ ACCEPTED: {acceptance_rate:.0%} pass rate, {avg_score:.1%} avg score")
        else:
            print(f"  ❌ REJECTED: Below thresholds")
            if acceptance_rate < min_acceptance_rate:
                print(f"     • Pass rate: {acceptance_rate:.0%} (need ≥ {min_acceptance_rate:.0%})")
            if avg_score < min_avg_score:
                print(f"     • Avg score: {avg_score:.1%} (need ≥ {min_avg_score:.0%})")
        
        return reports


async def main():
    """Run all examples."""
    examples = ConstraintValidationExamples()
    
    print("\n")
    print("#" * 70)
    print("# Expert Constraints Validation System - Usage Examples")
    print("#" * 70)
    
    # Run examples
    await examples.example_1_simple_validation()
    await examples.example_2_detect_hallucination()
    await examples.example_3_incomplete_diagnosis()
    await examples.example_4_batch_validation()
    await examples.example_5_custom_constraints()
    await examples.example_6_constraint_metrics()
    
    print("\n" + "="*70)
    print("All Examples Completed Successfully!")
    print("="*70)


if __name__ == "__main__":
    asyncio.run(main())
