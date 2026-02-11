"""
Example Usage of Fault Injection Framework

This module demonstrates how to use the fault injection framework to:
1. Define fault scenarios
2. Execute fault injection, verification, and recovery workflows
3. Integrate with Expert Agent diagnostics
4. Measure diagnostic accuracy and confidence scores
"""

import asyncio
import logging
from typing import Optional
from dataclasses import dataclass

from olav.testing.fault_injection import (
    FaultScenario,
    FaultScenarioRegistry,
    FaultInjector,
    FaultCommand,
    FaultStep,
    FaultCategory,
    FaultSeverity,
    FaultScenarioBuilder,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class DiagnosisResult:
    """Result of Expert Agent diagnosis."""
    root_cause: str
    confidence_score: float
    solution_steps: list[str]
    diagnostic_time_ms: int
    contains_vague_terms: bool = False
    accuracy_rating: Optional[str] = None  # correct, partial, incorrect


class FaultInjectionTestHarness:
    """
    Complete test harness for fault injection + Expert Agent diagnostics.
    
    Workflow:
    1. Select a fault scenario
    2. Inject the fault
    3. Verify fault is present
    4. Run Expert Agent diagnosis
    5. Evaluate diagnosis quality
    6. Recover from fault
    7. Verify recovery
    8. Generate report
    """
    
    def __init__(self, scenario: FaultScenario):
        """Initialize harness with a fault scenario."""
        self.scenario = scenario
        self.injector = FaultInjector(scenario)
        self.diagnosis_result: Optional[DiagnosisResult] = None
        self.test_report = {
            "scenario_id": scenario.scenario_id,
            "scenario_name": scenario.name,
            "status": "pending",
            "phases": {}
        }
        
    async def run_complete_test_cycle(self) -> dict:
        """
        Execute complete fault injection + diagnosis + recovery cycle.
        
        Returns:
            Test report with all results
        """
        logger.info(f"Starting complete test cycle for: {self.scenario.name}")
        
        # Phase 1: Injection
        logger.info("=== Phase 1: Fault Injection ===")
        if not await self.injector.inject():
            logger.error("Injection failed")
            self.test_report["status"] = "failed_injection"
            return self.test_report
        self.test_report["phases"]["injection"] = "success"
        
        # Phase 2: Verification
        logger.info("=== Phase 2: Fault Verification ===")
        if not await self.injector.verify_fault():
            logger.error("Verification failed")
            self.test_report["status"] = "failed_verification"
            return self.test_report
        self.test_report["phases"]["verification"] = "success"
        
        # Phase 3: Diagnostic (this would call Expert Agent)
        logger.info("=== Phase 3: Expert Agent Diagnosis ===")
        self.diagnosis_result = await self._run_expert_agent_diagnosis()
        self.test_report["phases"]["diagnosis"] = {
            "root_cause": self.diagnosis_result.root_cause,
            "confidence": self.diagnosis_result.confidence_score,
            "accuracy": self._evaluate_diagnosis_accuracy(),
        }
        
        # Phase 4: Recovery
        logger.info("=== Phase 4: Fault Recovery ===")
        if not await self.injector.recover():
            logger.error("Recovery failed")
            self.test_report["status"] = "failed_recovery"
            return self.test_report
        self.test_report["phases"]["recovery"] = "success"
        
        # Phase 5: Verification of Recovery
        logger.info("=== Phase 5: Recovery Verification ===")
        if not await self.injector.verify_recovery():
            logger.error("Recovery verification failed")
            self.test_report["status"] = "failed_recovery_verification"
            return self.test_report
        self.test_report["phases"]["recovery_verification"] = "success"
        
        self.test_report["status"] = "completed_successfully"
        return self.test_report
        
    async def _run_expert_agent_diagnosis(self) -> DiagnosisResult:
        """
        Run Expert Agent diagnostics on the injected fault.
        
        This is where the Expert Agent's SKILL_DIAGNOSTIC_WORKFLOW would be invoked.
        
        Returns:
            DiagnosisResult with diagnosis details
        """
        import time
        start_time = time.time()
        
        # TODO: Integrate with actual Expert Agent
        # For now, return a stub diagnosis
        
        diagnosis = DiagnosisResult(
            root_cause=self.scenario.expected_diagnosis or "Unknown",
            confidence_score=self.scenario.min_confidence_score,
            solution_steps=["Step 1", "Step 2", "Step 3"],
            diagnostic_time_ms=int((time.time() - start_time) * 1000),
            contains_vague_terms=False,
        )
        
        logger.info(f"Diagnosis: {diagnosis.root_cause}")
        logger.info(f"Confidence: {diagnosis.confidence_score:.2%}")
        
        return diagnosis
        
    def _evaluate_diagnosis_accuracy(self) -> str:
        """
        Evaluate accuracy of diagnosis by comparing with expected result.
        
        Returns:
            "correct", "partial", or "incorrect"
        """
        if not self.diagnosis_result:
            return "no_diagnosis"
            
        # Simple keyword matching for evaluation
        expected_keywords = self.scenario.root_cause.lower().split()
        actual_keywords = self.diagnosis_result.root_cause.lower().split()
        
        matches = sum(1 for kw in expected_keywords 
                     if any(kw in ak for ak in actual_keywords))
        
        match_ratio = matches / len(expected_keywords) if expected_keywords else 0
        
        if match_ratio >= 0.8:
            return "correct"
        elif match_ratio >= 0.5:
            return "partial"
        else:
            return "incorrect"
            
    def generate_report(self) -> str:
        """Generate human-readable test report."""
        report = f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║ FAULT INJECTION TEST REPORT                                                  ║
╚══════════════════════════════════════════════════════════════════════════════╝

Scenario: {self.scenario.name}
ID: {self.scenario.scenario_id}
Category: {self.scenario.category.value}
Severity: {self.scenario.severity.name}

────────────────────────────────────────────────────────────────────────────────
SCENARIO DETAILS
────────────────────────────────────────────────────────────────────────────────
Description: {self.scenario.description}
Root Cause: {self.scenario.root_cause}
Affected Devices: {', '.join(self.scenario.affected_devices)}

────────────────────────────────────────────────────────────────────────────────
EXECUTION RESULTS
────────────────────────────────────────────────────────────────────────────────
Overall Status: {self.test_report.get('status', 'Unknown').upper()}

Phase Results:
"""
        for phase, result in self.test_report.get("phases", {}).items():
            status = "✓ PASS" if result == "success" else "✗ FAIL"
            report += f"  • {phase.upper():.<40} {status}\n"
            
        if self.diagnosis_result:
            report += f"""
────────────────────────────────────────────────────────────────────────────────
DIAGNOSTIC EVALUATION
────────────────────────────────────────────────────────────────────────────────
Root Cause Identified: {self.diagnosis_result.root_cause}
Confidence Score: {self.diagnosis_result.confidence_score:.2%}
Minimum Threshold: {self.scenario.min_confidence_score:.2%}
Score Status: {'✓ PASS' if self.diagnosis_result.confidence_score >= self.scenario.min_confidence_score else '✗ FAIL'}

Accuracy: {self.test_report['phases']['diagnosis'].get('accuracy', 'Unknown').upper()}
Diagnostic Time: {self.diagnosis_result.diagnostic_time_ms}ms
Contains Vague Terms: {'✗ YES' if self.diagnosis_result.contains_vague_terms else '✓ NO'}

Suggested Solution Steps: {len(self.diagnosis_result.solution_steps)}
"""
            for i, step in enumerate(self.diagnosis_result.solution_steps, 1):
                report += f"  {i}. {step}\n"
                
        report += f"""
────────────────────────────────────────────────────────────────────────────────
EXECUTION LOG
────────────────────────────────────────────────────────────────────────────────
Events: {len(self.injector.execution_log)}
"""
        for event in self.injector.execution_log[:10]:  # Show first 10 events
            report += f"  • [{event.get('type', 'unknown')}] {event.get('message', '')}\n"
            
        if len(self.injector.execution_log) > 10:
            report += f"  ... and {len(self.injector.execution_log) - 10} more events\n"
            
        report += f"""
────────────────────────────────────────────────────────────────────────────────
ACCEPTANCE CRITERIA
────────────────────────────────────────────────────────────────────────────────
✓ Fault injected successfully: {'PASS' if self.test_report['phases'].get('injection') == 'success' else 'FAIL'}
✓ Fault verified: {'PASS' if self.test_report['phases'].get('verification') == 'success' else 'FAIL'}
✓ Diagnosis confidence ≥ {self.scenario.min_confidence_score:.0%}: {'PASS' if self.diagnosis_result and self.diagnosis_result.confidence_score >= self.scenario.min_confidence_score else 'FAIL'}
✓ No vague terms in diagnosis: {'PASS' if not self.diagnosis_result or not self.diagnosis_result.contains_vague_terms else 'FAIL'}
✓ Recovery successful: {'PASS' if self.test_report['phases'].get('recovery') == 'success' else 'FAIL'}
✓ Recovery verified: {'PASS' if self.test_report['phases'].get('recovery_verification') == 'success' else 'FAIL'}

════════════════════════════════════════════════════════════════════════════════
"""
        return report


# ============================================================================
# Quick Start Examples
# ============================================================================

async def example_1_simple_test():
    """Example 1: Run Scenario 1 (BGP Interface Down)."""
    print("\n" + "="*80)
    print("EXAMPLE 1: BGP Interface Down - Simple Scenario")
    print("="*80)
    
    scenario = FaultScenarioRegistry.get_scenario(1)
    if not scenario:
        print("❌ Scenario 1 not found")
        return
        
    harness = FaultInjectionTestHarness(scenario)
    await harness.run_complete_test_cycle()
    print(harness.generate_report())


async def example_2_batch_test():
    """Example 2: Run all registered scenarios."""
    print("\n" + "="*80)
    print("EXAMPLE 2: Run All Registered Scenarios")
    print("="*80)
    
    scenarios = FaultScenarioRegistry.get_all_scenarios()
    results = []
    
    for scenario in scenarios:
        print(f"\nRunning Scenario {scenario.scenario_id}: {scenario.name}")
        harness = FaultInjectionTestHarness(scenario)
        report = await harness.run_complete_test_cycle()
        results.append(report)
        
    # Summary
    print("\n" + "-"*80)
    print("BATCH TEST SUMMARY")
    print("-"*80)
    passed = sum(1 for r in results if r.get('status') == 'completed_successfully')
    print(f"Scenarios Completed: {passed}/{len(scenarios)}")
    for scenario in scenarios:
        status = next((r.get('status') for r in results 
                      if r.get('scenario_id') == scenario.scenario_id), 'unknown')
        icon = "✓" if status == 'completed_successfully' else "✗"
        print(f"  {icon} Scenario {scenario.scenario_id}: {scenario.name} [{status}]")


async def example_3_custom_scenario():
    """Example 3: Create and run a custom fault scenario."""
    print("\n" + "="*80)
    print("EXAMPLE 3: Custom Fault Scenario")
    print("="*80)
    
    custom_scenario = (FaultScenarioBuilder(99, "Custom BGP Test")
        .with_description("Custom test scenario")
        .with_category(FaultCategory.BGP)
        .with_severity(FaultSeverity.LOW)
        .with_devices("R1", "R2")
        .with_root_cause("Test root cause")
        .with_expected_diagnosis("Test diagnosis expected")
        .with_confidence_threshold(0.85)
        .add_injection_step(FaultStep(
            name="Test Injection",
            commands=[FaultCommand("test command", "R1", "Test command")]
        ))
        .build()
    )
    
    harness = FaultInjectionTestHarness(custom_scenario)
    await harness.run_complete_test_cycle()
    print(harness.generate_report())


async def example_4_filter_scenarios():
    """Example 4: Filter scenarios by category or severity."""
    print("\n" + "="*80)
    print("EXAMPLE 4: Filter Scenarios")
    print("="*80)
    
    # By category
    bgp_scenarios = FaultScenarioRegistry.get_scenarios_by_category(FaultCategory.BGP)
    print(f"\nBGP Scenarios ({len(bgp_scenarios)}):")
    for scenario in bgp_scenarios:
        print(f"  • Scenario {scenario.scenario_id}: {scenario.name}")
        
    # By severity
    simple_scenarios = FaultScenarioRegistry.get_scenarios_by_severity(FaultSeverity.LOW)
    print(f"\nSimple (Low Severity) Scenarios ({len(simple_scenarios)}):")
    for scenario in simple_scenarios:
        print(f"  • Scenario {scenario.scenario_id}: {scenario.name}")


# ============================================================================
# Main - Run Examples
# ============================================================================

async def main():
    """Run example demonstrations."""
    print("╔════════════════════════════════════════════════════════════════════════════╗")
    print("║ FAULT INJECTION FRAMEWORK - EXAMPLES                                       ║")
    print("╚════════════════════════════════════════════════════════════════════════════╝")
    
    # Run examples
    await example_1_simple_test()
    await example_2_batch_test()
    await example_3_custom_scenario()
    await example_4_filter_scenarios()
    
    print("\n" + "="*80)
    print("All examples completed!")
    print("="*80)


if __name__ == "__main__":
    asyncio.run(main())
