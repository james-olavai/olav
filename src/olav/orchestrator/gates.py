"""
Decision Gate Logic - Expert Orchestrator's Multi-Level Validation Gates

This module contains the pure decision logic for the Expert Orchestrator:
1. Apply multi-level decision gates (constraint, confidence, accuracy)
2. Determine routing target based on decisions
3. Generate detailed decision reasoning and improvement suggestions

The gates implement a sequential validation pipeline with clearly defined
thresholds and fallback paths. Each gate checks specific criteria and either
passes to the next gate or makes a final decision.

Gate Sequence:
  Constraint Gate
    ↓ (if REJECT) → Final REJECT
    ↓ (if pass) → Confidence Gate
         ↓ (if UNCERTAIN) → Final UNCERTAIN
         ↓ (if pass) → Accuracy Gate (if available)
              ↓ (if UNCERTAIN) → Final UNCERTAIN
              ↓ (if ACCEPT/REVIEW) → Accept Gate
                   → ACCEPT or REVIEW based on thresholds
"""

import logging
from typing import List, Optional

from olav.testing.diagnosis_verifier import VerificationReport
from olav.testing.expert_constraints import ValidationReport

from olav.orchestrator.state import (
    DecisionGateConfig,
    OrchestratorDecision,
    RouteDecision,
    RoutingTarget,
)

logger = logging.getLogger(__name__)


def apply_decision_gates(
    constraint_score: float,
    accuracy_score: Optional[float],
    hybrid_score: Optional[float],
    confidence_score: float,
    constraint_report: ValidationReport,
    verification_report: Optional[VerificationReport],
    gate_config: DecisionGateConfig,
) -> tuple[OrchestratorDecision, str, List[str], List[str], List[str]]:
    """
    Apply decision gates and determine pass/fail/review/uncertain.

    Multi-level gate sequence:
    1. **Constraint Gate**: Validates absence of hallucinations/incomplete diag
       - REJECT if constraint_score < warning_threshold
       - CONTINUE if constraint_score >= warning_threshold

    2. **Confidence Gate**: Validates Expert Agent's confidence
       - UNCERTAIN if confidence_score < pass_threshold
       - CONTINUE otherwise

    3. **Accuracy Gate** (optional): Validates vs ground truth
       - UNCERTAIN if accuracy_score < warning_threshold
       - CONTINUE otherwise

    4. **Accept Gate**: Final acceptance decision
       - ACCEPT if constraint_score >= pass_threshold
       - REVIEW if constraint_score in [warning, pass)

    Args:
        constraint_score: Validation score (0.0-1.0) from Task 4
        accuracy_score: Optional verification score (0.0-1.0) from Task 5
        hybrid_score: Optional combined score (constraint + accuracy)
        confidence_score: Expert Agent's confidence (0.0-1.0)
        constraint_report: Detailed constraint validation results
        verification_report: Optional detailed verification results
        gate_config: Decision gate configuration with thresholds

    Returns:
        Tuple: (decision, reason, critical_failures, warnings, improvements)
            - decision: OrchestratorDecision (ACCEPT/REVIEW/REJECT/UNCERTAIN)
            - reason: Human-readable explanation of decision
            - critical_failures: List of critical issues (blocks diagnosis)
            - warnings: List of warnings (flags for review)
            - improvements: Suggestions for improvement
    """
    critical_failures = list(constraint_report.critical_failures or [])
    warnings = []
    improvements = []

    # ========================================================================
    # Gate 1: Constraint Score - Primary Validation
    # ========================================================================
    # Constraint validation (Task 4) is REQUIRED and PRIMARY gate.
    # Low constraint score indicates hallucinations, incomplete diagnosis,
    # or other fundamental issues with the diagnosis quality.

    if constraint_score < gate_config.constraint_warning_threshold:
        decision = OrchestratorDecision.REJECT
        reason = (
            f"Constraint score {constraint_score:.2%} below warning "
            f"threshold {gate_config.constraint_warning_threshold:.2%}. "
            f"Diagnosis contains critical validation failures."
        )
        critical_failures.append(reason)

        logger.warning(
            f"Gate 1 (Constraint) REJECTED: constraint_score={constraint_score:.2%} "
            f"< warning_threshold={gate_config.constraint_warning_threshold:.2%}"
        )

        return decision, reason, critical_failures, warnings, improvements

    # ========================================================================
    # Gate 2: Confidence Score - Expert Agent Confidence
    # ========================================================================
    # Expert Agent's confidence indicates how sure it is about the diagnosis.
    # Low confidence suggests uncertainty that should be resolved before
    # sending diagnosis to user.

    if confidence_score < gate_config.confidence_pass_threshold:
        decision = OrchestratorDecision.UNCERTAIN
        reason = (
            f"Expert Agent confidence {confidence_score:.2%} below "
            f"threshold {gate_config.confidence_pass_threshold:.2%}. "
            f"Diagnosis needs higher confidence for acceptance."
        )
        warnings.append(reason)
        improvements.append(
            "Request Expert Agent to increase confidence through additional analysis"
        )

        logger.info(
            f"Gate 2 (Confidence) UNCERTAIN: confidence_score={confidence_score:.2%} "
            f"< pass_threshold={gate_config.confidence_pass_threshold:.2%}"
        )

        return decision, reason, critical_failures, warnings, improvements

    # ========================================================================
    # Gate 3: Accuracy Score (if available) - Ground Truth Comparison
    # ========================================================================
    # Accuracy verification (Task 5) is OPTIONAL when ground truth available.
    # It compares diagnosis against known ground truth to catch systematic errors.

    if accuracy_score is not None:
        if accuracy_score < gate_config.accuracy_warning_threshold:
            decision = OrchestratorDecision.UNCERTAIN
            reason = (
                f"Accuracy score {accuracy_score:.2%} below warning "
                f"threshold {gate_config.accuracy_warning_threshold:.2%}. "
                f"Verification against ground truth shows possible inaccuracy."
            )
            warnings.append(reason)

            if verification_report:
                improvements.extend(
                    verification_report.improvement_suggestions or []
                )

            logger.info(
                f"Gate 3 (Accuracy) UNCERTAIN: accuracy_score={accuracy_score:.2%} "
                f"< warning_threshold={gate_config.accuracy_warning_threshold:.2%}"
            )

            return decision, reason, critical_failures, warnings, improvements

    # ========================================================================
    # Gate 4: Final Accept Decision - Constraint Threshold
    # ========================================================================
    # If all previous gates passed, make final decision based on constraint score.
    # Constraint score determines if diagnosis is ready for user (ACCEPT) or
    # needs human review (REVIEW).

    if constraint_score >= gate_config.constraint_pass_threshold:
        # Constraint score is good enough for direct acceptance
        if accuracy_score:
            # If accuracy also available, check it too
            if accuracy_score >= gate_config.accuracy_pass_threshold:
                decision = OrchestratorDecision.ACCEPT
                reason = "Passed all gates (constraint + accuracy, both at pass threshold)"
            else:
                # Accuracy is in warning range but not critical
                decision = OrchestratorDecision.REVIEW
                reason = (
                    f"Constraint OK ({constraint_score:.2%}), "
                    f"but accuracy {accuracy_score:.2%} in warning range "
                    f"[{gate_config.accuracy_warning_threshold:.2%}, "
                    f"{gate_config.accuracy_pass_threshold:.2%}]"
                )
                warnings.append(reason)
        else:
            # No accuracy score, constraint alone is sufficient
            decision = OrchestratorDecision.ACCEPT
            reason = f"Constraint score {constraint_score:.2%} >= pass threshold {gate_config.constraint_pass_threshold:.2%}"
    else:
        # Constraint score is in warning range [warning_threshold, pass_threshold)
        # This triggers review despite passing all gates
        decision = OrchestratorDecision.REVIEW
        reason = (
            f"Constraint score {constraint_score:.2%} in warning range "
            f"[{gate_config.constraint_warning_threshold:.2%}, "
            f"{gate_config.constraint_pass_threshold:.2%}]. "
            f"Diagnosis requires human review before sending to user."
        )
        warnings.append(reason)

    logger.info(
        f"Gate 4 (Final) {decision.value.upper()}: "
        f"constraint_score={constraint_score:.2%}, "
        f"accuracy_score={accuracy_score:.2%}" if accuracy_score else ""
    )

    # Add improvement suggestions from constraint report
    if constraint_report.constraint_results:
        for result in constraint_report.constraint_results:
            if result.violations:
                for violation in result.violations:
                    improvements.append(
                        f"{result.constraint_name}: {violation.message}"
                    )

    # Add improvement suggestions from verification report
    if verification_report:
        improvements.extend(verification_report.improvement_suggestions or [])

    return decision, reason, critical_failures, warnings, improvements


def determine_routing(
    decision: OrchestratorDecision,
    critical_failures: List[str],
    warnings: List[str],
    verification_report: Optional[VerificationReport],
) -> RouteDecision:
    """
    Determine routing target based on orchestrator decision.

    Routing Logic:
        ACCEPT
          → DIRECT_USER: Return diagnosis immediately to user
             (diagnosis passed all validation gates)

        REVIEW
          → HUMAN_REVIEW_QUEUE: Queue for human expert review
             (warning-level issues, needs expert judgment)

        REJECT
          → ESCALATION_QUEUE: Critical issues, escalate immediately
             (diagnosis has critical failures, requires escalation)

        UNCERTAIN
          → REANALYSIS_QUEUE: Route back for Expert Agent re-analysis
             (low confidence or accuracy, needs fresh analysis)

    Args:
        decision: OrchestratorDecision from apply_decision_gates()
        critical_failures: List of critical failure messages
        warnings: List of warning messages
        verification_report: Optional verification results

    Returns:
        RouteDecision with target, reason, and escalation info
    """

    if decision == OrchestratorDecision.ACCEPT:
        result = RouteDecision(
            target=RoutingTarget.DIRECT_USER,
            reason="Diagnosis passed all validation gates, safe to return to user",
            requires_review=False,
            escalation_level="normal",
        )
        logger.info(
            f"Routing ACCEPT decision to DIRECT_USER"
        )

    elif decision == OrchestratorDecision.REVIEW:
        result = RouteDecision(
            target=RoutingTarget.HUMAN_REVIEW_QUEUE,
            reason="Diagnosis flagged for human expert review (warning-level issues)",
            requires_review=True,
            escalation_level="normal",
        )
        logger.info(
            f"Routing REVIEW decision to HUMAN_REVIEW_QUEUE (warnings: {len(warnings)})"
        )

    elif decision == OrchestratorDecision.REJECT:
        result = RouteDecision(
            target=RoutingTarget.ESCALATION_QUEUE,
            reason=f"Diagnosis rejected due to critical failures ({len(critical_failures)}): "
            + "; ".join(critical_failures[:3]),  # First 3 failures in reason
            requires_review=True,
            escalation_level="critical",
        )
        logger.warning(
            f"Routing REJECT decision to ESCALATION_QUEUE "
            f"(critical_failures: {len(critical_failures)})"
        )

    else:  # UNCERTAIN
        result = RouteDecision(
            target=RoutingTarget.REANALYSIS_QUEUE,
            reason="Diagnosis uncertain, routing back for Expert Agent re-analysis",
            requires_review=False,
            escalation_level="normal",
        )
        logger.info(
            f"Routing UNCERTAIN decision to REANALYSIS_QUEUE"
        )

    return result
