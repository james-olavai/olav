"""
Expert Orchestrator Integration with Query Guard & Expert Agent

Complete integration of Orchestrator into Expert Agent workflow:
1. Expert Agent receives user query
2. Produces diagnosis with confidence score
3. Orchestrator validates & verifies diagnosis
4. Routes based on decision (ACCEPT/REVIEW/REJECT/UNCERTAIN)
5. Returns result or queues for review

Architecture:
┌─────────────┐
│ User Query  │
└──────┬──────┘
       │
   ┌───▼────┐
   │ Guard  │
   │ Routes │
   └───┬────┘
       │
   ┌───▼─────────────────────┐
   │ Expert Agent            │
   │ (Diagnostician)         │
   │ → ExpertDiagnosisOutput │
   └───┬─────────────────────┘
       │
   ┌───▼──────────────────────────────────┐
   │ ORCHESTRATOR (Task 6) ← THIS MODULE  │
   │ 1. Task 4: Validate constraints      │
   │ 2. Task 5: Verify accuracy (optional)│
   │ 3. Apply decision gates              │
   │ 4. Determine routing                 │
   └───┬──────────────────────────────────┘
       │
   ┌───┴─────────────────────────────────┐
   │                                      │
   ▼                                      ▼
ACCEPT                              REVIEW/REJECT
│                                      │
Return to User                    Queue for Review
(immediate)                       (human processing)
"""

import logging
from typing import Any, Dict, Optional

from olav.orchestrator import (
    DecisionGateConfig,
    ExpertOrchestrator,
    OrchestratorDecision,
    OrchestratorReport,
)
from olav.testing.diagnosis_verifier import DiagnosisVerifier, GroundTruth
from olav.testing.expert_constraints import (
    ExpertConstraintsValidator,
    ExpertDiagnosisOutput,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Integration: Expert Agent → Orchestrator → Routing
# ============================================================================


class QueryGuardIntegration:
    """
    Integration layer between Query Guard and Orchestrator.
    
    Responsibilities:
    1. Receive diagnosis from Expert Agent
    2. Pass to Orchestrator for validation
    3. Route result based on decision
    4. Manage human review queue
    5. Provide feedback to Expert Agent
    """

    def __init__(
        self,
        orchestrator: ExpertOrchestrator,
        enable_verification: bool = False,
        human_review_callback=None,
        escalation_callback=None,
    ):
        """
        Initialize Query Guard integration.

        Args:
            orchestrator: Pre-configured ExpertOrchestrator instance
            enable_verification: Whether to use Task 5 verification
            human_review_callback: Async function to handle REVIEW queue
            escalation_callback: Async function to handle REJECT cases
        """
        self.orchestrator = orchestrator
        self.enable_verification = enable_verification
        self.human_review_callback = human_review_callback
        self.escalation_callback = escalation_callback

        logger.info("QueryGuardIntegration initialized")

    async def process_expert_diagnosis(
        self,
        diagnosis: ExpertDiagnosisOutput,
        user_id: Optional[str] = None,
        scenario_id: Optional[str] = None,
        ground_truth: Optional[GroundTruth] = None,
    ) -> Dict[str, Any]:
        """
        Main integration point: Process Expert Agent diagnosis.

        Flow:
        1. Validate via Orchestrator
        2. Make routing decision
        3. Execute appropriate action
        4. Return result to user or queue

        Args:
            diagnosis: Output from Expert Agent
            user_id: User ID for tracking
            scenario_id: Scenario ID (for testing)
            ground_truth: Optional ground truth (for verification)

        Returns:
            Dict with:
            - decision: ACCEPT/REVIEW/REJECT/UNCERTAIN
            - routing: where to send result
            - message: user-facing message
            - report: OrchestratorReport with full details
            - action: what was executed
        """
        logger.info(
            f"Processing diagnosis from Expert Agent "
            f"(scenario: {scenario_id}, user: {user_id})"
        )

        # Step 1: Run Orchestrator
        report = await self.orchestrator.process(diagnosis, ground_truth=ground_truth)

        logger.info(
            f"Orchestrator decision: {report.overall_decision.value}, "
            f"constraint_score: {report.constraint_score:.2%}"
        )

        # Step 2: Route based on decision
        result = {
            "decision": report.overall_decision.value,
            "routing": report.routing_decision.target.value,
            "scenario_id": diagnosis.scenario_id,
            "user_id": user_id,
            "timestamp": report.timestamp,
            "report": report,
        }

        # Step 3: Execute routing action
        if report.overall_decision == OrchestratorDecision.ACCEPT:
            result["action"] = "return_to_user"
            result["message"] = (
                f"Expert diagnosis: {diagnosis.solution}\n"
                f"Recovery: {', '.join(diagnosis.recovery_commands)}\n"
                f"Verification: {', '.join(diagnosis.verification_steps)}"
            )
            logger.info(f"✓ ACCEPT: Returning diagnosis to user {user_id}")

        elif report.overall_decision == OrchestratorDecision.REVIEW:
            result["action"] = "route_to_review"
            result["message"] = (
                f"⚠️  Diagnosis flagged for human review\n"
                f"Issue: {report.reason}\n"
                f"Please wait while our experts review..."
            )
            logger.info(f"📋 REVIEW: Routing to human review queue")

            # Call human review callback if provided
            if self.human_review_callback:
                try:
                    await self.human_review_callback(report)
                except Exception as e:
                    logger.error(f"Error in human review callback: {e}")

        elif report.overall_decision == OrchestratorDecision.REJECT:
            result["action"] = "route_to_escalation"
            result["message"] = (
                f"❌ Diagnosis rejected - critical issues detected\n"
                f"Issue: {report.reason}\n"
                f"Escalating to senior technical team..."
            )
            logger.warning(f"🚨 REJECT: Routing to escalation queue")

            # Call escalation callback if provided
            if self.escalation_callback:
                try:
                    await self.escalation_callback(report)
                except Exception as e:
                    logger.error(f"Error in escalation callback: {e}")

        else:  # UNCERTAIN
            result["action"] = "route_to_reanalysis"
            result["message"] = (
                f"⚠️  More analysis needed\n"
                f"Reason: {report.reason}\n"
                f"Re-analyzing with more detailed inspection..."
            )
            logger.info(f"🔄 UNCERTAIN: Routing back for re-analysis")

        return result

    async def process_batch(
        self,
        diagnoses: list[ExpertDiagnosisOutput],
        scenario_ids: Optional[list[str]] = None,
        ground_truths: Optional[Dict[str, GroundTruth]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Process batch of diagnoses.

        Args:
            diagnoses: List of diagnoses
            scenario_ids: Optional list of scenario IDs
            ground_truths: Optional dict of ground truths

        Returns:
            Dict mapping scenario_id → result
        """
        logger.info(f"Processing batch of {len(diagnoses)} diagnoses...")

        scenario_ids = scenario_ids or [
            d.scenario_id for d in diagnoses
        ]
        ground_truths = ground_truths or {}

        results = {}
        for diagnosis, scenario_id in zip(diagnoses, scenario_ids):
            ground_truth = ground_truths.get(scenario_id)
            result = await self.process_expert_diagnosis(
                diagnosis,
                scenario_id=scenario_id,
                ground_truth=ground_truth,
            )
            results[scenario_id] = result

        return results

    def get_quality_metrics(
        self, results: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Calculate quality metrics from batch results.

        Args:
            results: Results from process_batch()

        Returns:
            Dict with metrics:
            - decision_distribution (ACCEPT/REVIEW/REJECT/UNCERTAIN counts)
            - pass_rate (% ACCEPT)
            - average_constraint_score
            - average_confidence_score
            - critical_issues (REJECT count)
        """
        decisions = {"accept": 0, "review": 0, "reject": 0, "uncertain": 0}
        constraint_scores = []
        confidence_scores = []

        for result in results.values():
            report = result["report"]
            decision_key = report.overall_decision.value
            decisions[decision_key] = decisions.get(decision_key, 0) + 1

            constraint_scores.append(report.constraint_score)
            confidence_scores.append(report.confidence_score)

        total = len(results)

        return {
            "total_processed": total,
            "accept_count": decisions["accept"],
            "review_count": decisions["review"],
            "reject_count": decisions["reject"],
            "uncertain_count": decisions["uncertain"],
            "pass_rate": decisions["accept"] / total if total > 0 else 0,
            "review_rate": decisions["review"] / total if total > 0 else 0,
            "reject_rate": decisions["reject"] / total if total > 0 else 0,
            "uncertain_rate": decisions["uncertain"] / total if total > 0 else 0,
            "avg_constraint_score": (
                sum(constraint_scores) / len(constraint_scores)
                if constraint_scores
                else 0
            ),
            "avg_confidence_score": (
                sum(confidence_scores) / len(confidence_scores)
                if confidence_scores
                else 0
            ),
            "critical_issues": decisions["reject"],
        }


# ============================================================================
# Expert Agent Integration
# ============================================================================


class ExpertAgentOrchestration:
    """
    Integration between Expert Agent and Orchestrator.
    
    Manages complete diagnostic workflow:
    1. User query → Expert Agent (diagnosis)
    2. Diagnosis → Orchestrator (validation)
    3. Orchestrator decision → action
    """

    def __init__(
        self,
        expert_agent_diagnose_func,
        orchestrator: ExpertOrchestrator,
        gate_config: Optional[DecisionGateConfig] = None,
    ):
        """
        Initialize Expert Agent orchestration.

        Args:
            expert_agent_diagnose_func: Async function that diagnoses
            orchestrator: Pre-configured ExpertOrchestrator
            gate_config: Optional configuration overrides
        """
        self.expert_agent_diagnose = expert_agent_diagnose_func
        self.orchestrator = orchestrator
        self.gate_config = gate_config or orchestrator.gate_config

        logger.info("ExpertAgentOrchestration initialized")

    async def diagnose_and_validate(
        self,
        user_query: str,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Complete workflow: Query → Diagnose → Validate → Decision.

        Args:
            user_query: User's question/issue description
            user_id: User ID for tracking

        Returns:
            Complete result with decision and routing
        """
        logger.info(f"Starting diagnosis workflow for query: {user_query[:50]}...")

        # Step 1: Expert Agent diagnoses
        try:
            diagnosis = await self.expert_agent_diagnose(user_query)
        except Exception as e:
            logger.error(f"Expert Agent diagnosis failed: {e}")
            return {
                "status": "error",
                "error": str(e),
                "decision": "uncertain",
                "message": "Diagnosis failed. Please try again.",
            }

        logger.info(
            f"Expert Agent diagnosis complete: "
            f"confidence={diagnosis.confidence_score:.2%}"
        )

        # Step 2: Orchestrator validates
        try:
            report = await self.orchestrator.process(diagnosis)
        except Exception as e:
            logger.error(f"Orchestrator validation failed: {e}")
            return {
                "status": "error",
                "error": str(e),
                "decision": "uncertain",
                "message": "Validation failed. Please try again.",
            }

        logger.info(
            f"Orchestrator validation complete: "
            f"decision={report.overall_decision.value}"
        )

        # Step 3: Prepare result
        result = {
            "status": "success",
            "decision": report.overall_decision.value,
            "routing": report.routing_decision.target.value,
            "diagnosis": diagnosis,
            "report": report,
            "user_id": user_id,
        }

        # Step 4: Format user message
        if report.overall_decision == OrchestratorDecision.ACCEPT:
            result["message"] = (
                f"✓ Diagnosis Complete\n\n"
                f"Issue: {diagnosis.root_cause}\n\n"
                f"Solution: {diagnosis.solution}\n\n"
                f"Recovery Steps:\n"
                + "\n".join(f"  • {cmd}" for cmd in diagnosis.recovery_commands)
                + f"\n\nVerification:\n"
                + "\n".join(f"  • {step}" for step in diagnosis.verification_steps)
            )
        else:
            result["message"] = (
                f"⚠️  {report.overall_decision.value.upper()}\n\n"
                f"Reason: {report.reason}\n\n"
                f"Status: {report.routing_decision.target.value}\n\n"
                f"Please wait while we process your request..."
            )

        return result


# ============================================================================
# Queue Management for REVIEW/REJECT Cases
# ============================================================================


class HumanReviewQueue:
    """
    Manages human review queue for REVIEW decisions.
    
    Stores flagged diagnoses until human expert review.
    """

    def __init__(self, max_queue_size: int = 1000):
        self.queue: list[OrchestratorReport] = []
        self.max_size = max_queue_size
        self.processed: list[OrchestratorReport] = []

    async def add_to_queue(self, report: OrchestratorReport) -> bool:
        """Add diagnosis to human review queue."""
        if len(self.queue) >= self.max_size:
            logger.warning(f"Review queue full ({self.max_size}), dropping oldest")
            self.queue.pop(0)

        self.queue.append(report)
        logger.info(
            f"Added to review queue: {report.scenario_id} "
            f"(queue size: {len(self.queue)})"
        )
        return True

    async def get_next_for_review(self) -> Optional[OrchestratorReport]:
        """Get next diagnosis for human review."""
        if not self.queue:
            return None
        return self.queue.pop(0)

    async def mark_reviewed(
        self, report: OrchestratorReport, approved: bool
    ) -> None:
        """Mark diagnosis as reviewed by human."""
        self.processed.append(report)
        logger.info(
            f"Human review complete: {report.scenario_id} "
            f"(approved={approved})"
        )

    def queue_size(self) -> int:
        """Get current queue size."""
        return len(self.queue)

    def stats(self) -> Dict[str, int]:
        """Get queue statistics."""
        return {
            "pending_review": len(self.queue),
            "processed": len(self.processed),
            "total": len(self.queue) + len(self.processed),
        }


class EscalationQueue:
    """
    Manages escalation queue for REJECT decisions.
    
    Critical issues requiring immediate attention.
    """

    def __init__(self, max_queue_size: int = 100):
        self.queue: list[OrchestratorReport] = []
        self.max_size = max_queue_size
        self.processed: list[OrchestratorReport] = []

    async def add_to_escalation(self, report: OrchestratorReport) -> bool:
        """Add diagnosis to escalation queue."""
        if len(self.queue) >= self.max_size:
            logger.error(f"Escalation queue full ({self.max_size}), dropping oldest")
            self.queue.pop(0)

        self.queue.append(report)
        logger.critical(
            f"ESCALATION: {report.scenario_id} "
            f"(critical_failures: {report.critical_failures})"
        )
        return True

    async def get_next_critical(self) -> Optional[OrchestratorReport]:
        """Get next critical issue."""
        if not self.queue:
            return None
        return self.queue.pop(0)

    def queue_size(self) -> int:
        """Get escalation queue size."""
        return len(self.queue)

    def stats(self) -> Dict[str, int]:
        """Get escalation statistics."""
        return {
            "pending_escalation": len(self.queue),
            "processed": len(self.processed),
            "total": len(self.queue) + len(self.processed),
        }


# ============================================================================
# Factory Functions
# ============================================================================


def create_production_integration() -> QueryGuardIntegration:
    """
    Creates production-ready integration with conservative gates.
    
    Configuration:
    - Constraint pass threshold: 0.90 (strict)
    - Confidence threshold: 0.85 (strict)
    - Accuracy threshold: 0.85 (strict)
    
    Suitable for: Production deployment
    """
    validator = ExpertConstraintsValidator()
    verifier = DiagnosisVerifier()

    config = DecisionGateConfig(
        constraint_pass_threshold=0.90,
        confidence_pass_threshold=0.85,
        accuracy_pass_threshold=0.85,
    )

    orchestrator = ExpertOrchestrator(
        constraint_validator=validator,
        verifier=verifier,
        gate_config=config,
    )

    return QueryGuardIntegration(orchestrator)


def create_staging_integration() -> QueryGuardIntegration:
    """
    Creates staging integration with moderate gates.
    
    Configuration:
    - Constraint pass threshold: 0.85 (default)
    - Confidence threshold: 0.80 (default)
    - Accuracy threshold: 0.80 (default)
    
    Suitable for: Staging/testing
    """
    validator = ExpertConstraintsValidator()
    verifier = DiagnosisVerifier()

    config = DecisionGateConfig()

    orchestrator = ExpertOrchestrator(
        constraint_validator=validator,
        verifier=verifier,
        gate_config=config,
    )

    return QueryGuardIntegration(orchestrator)


def create_development_integration() -> QueryGuardIntegration:
    """
    Creates development integration with lenient gates.
    
    Configuration:
    - Constraint pass threshold: 0.75 (lenient)
    - Confidence threshold: 0.70 (lenient)
    - Accuracy threshold: 0.70 (lenient)
    
    Suitable for: Development/testing
    """
    validator = ExpertConstraintsValidator()

    config = DecisionGateConfig(
        constraint_pass_threshold=0.75,
        confidence_pass_threshold=0.70,
        accuracy_pass_threshold=0.70,
    )

    orchestrator = ExpertOrchestrator(
        constraint_validator=validator,
        gate_config=config,
    )

    return QueryGuardIntegration(orchestrator, enable_verification=False)
