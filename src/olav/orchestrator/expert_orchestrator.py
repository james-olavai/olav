"""
Expert Orchestrator - Central Coordination for Diagnosis Validation & Verification

This module orchestrates the complete Expert Agent validation pipeline:
1. Constraint validation (detect hallucinations, incomplete diagnoses)
2. Accuracy verification (compare against ground truth)
3. Decision gating (accept/review/reject)
4. Human-in-the-loop routing
5. Feedback collection for Expert Agent improvement

Architecture:
┌─────────────────────────────────────────────────────────────┐
│ Expert Agent Diagnosis Output                               │
│ (root_cause, solution, recovery_cmds, verification_steps)   │
└────────────────────┬────────────────────────────────────────┘
                     │
              ┌──────▼────────┐
              │ Orchestrator  │
              └──────┬────────┘
                     │
        ┌────────────┼────────────┐
        │            │            │
        ▼            ▼            ▼
    Constraint  Verification  Decision
    Validation  (optional)     Gate
    (REQUIRED)
        │            │            │
        └────────────┼────────────┘
                     │
        ┌────────────▼────────────┐
        │  Orchestration Report   │
        │  - constraint_score     │
        │  - accuracy_score       │
        │  - decision (accept...) │
        │  - routing (user/queue) │
        └──────────┬─────────────┘
                   │
         ┌─────────┴─────────┐
         ▼                   ▼
    Return to User    Queue for Review
    (if accepted)     (if flag/reject)
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from olav.testing.expert_constraints import (
    ExpertConstraintsValidator,
    ExpertDiagnosisOutput,
    ValidationReport,
)
from olav.testing.diagnosis_verifier import (
    DiagnosisVerifier,
    GroundTruth,
    VerificationReport,
)

# Import state definitions from refactored module
from olav.orchestrator.state import (
    DecisionGateConfig,
    OrchestratorDecision,
    OrchestratorReport,
    RouteDecision,
    RoutingTarget,
)

# Import gate logic from refactored module
from olav.orchestrator.gates import (
    apply_decision_gates,
    determine_routing,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Expert Orchestrator
# ============================================================================


class ExpertOrchestrator:
    """
    Central coordinator for Expert Agent diagnosis validation & verification.

    Orchestrates the complete pipeline:
    1. Constraint validation (Task 4) - REQUIRED
    2. Accuracy verification (Task 5) - OPTIONAL
    3. Decision gating - REQUIRED
    4. Human-in-the-loop routing - REQUIRED
    5. Feedback collection - OPTIONAL

    Example:
        orchestrator = ExpertOrchestrator(
            constraint_validator=validator,
            verifier=verifier,
            gate_config=config
        )

        diagnosis = ExpertDiagnosisOutput(
            scenario_id="scenario_1",
            root_cause="BGP session down",
            confidence_score=0.92,
            solution="Restart BGP daemon",
            recovery_commands=["service bgp restart"],
            verification_steps=["Check BGP status"],
            evidence="BGP neighbor down, interface up"
        )

        report = await orchestrator.process(diagnosis)
        print(report.summary())
    """

    def __init__(
        self,
        constraint_validator: ExpertConstraintsValidator,
        verifier: Optional[DiagnosisVerifier] = None,
        gate_config: Optional[DecisionGateConfig] = None,
    ):
        """
        Initialize orchestrator.

        Args:
            constraint_validator: Task 4 constraint validation system (required)
            verifier: Task 5 verification system (optional)
            gate_config: Decision gate configuration (defaults to DecisionGateConfig())
        """
        self.constraint_validator = constraint_validator
        self.verifier = verifier
        self.gate_config = gate_config or DecisionGateConfig()

        # Validate configuration
        self.gate_config.validate_weights()

        logger.info(
            "ExpertOrchestrator initialized with "
            f"constraint_validator={constraint_validator.__class__.__name__}, "
            f"verifier={verifier.__class__.__name__ if verifier else 'None'}"
        )

    async def process(
        self,
        diagnosis: ExpertDiagnosisOutput,
        ground_truth: Optional[GroundTruth] = None,
    ) -> OrchestratorReport:
        """
        Process a diagnosis through complete validation pipeline.

        Pipeline:
        1. Validate constraints (Task 4) → constraint_score
        2. Verify accuracy (Task 5, optional) → accuracy_score
        3. Apply decision gates → decision
        4. Route to appropriate target → routing_decision
        5. Return complete report

        Args:
            diagnosis: Expert Agent diagnosis output
            ground_truth: Optional ground truth for verification (Task 5)

        Returns:
            OrchestratorReport with complete analysis & decision

        Raises:
            ValueError: Invalid diagnosis format
        """
        start_time = datetime.utcnow()

        logger.info(f"Processing diagnosis: {diagnosis.scenario_id}")

        # ====================================================================
        # Step 1: Constraint Validation (REQUIRED)
        # ====================================================================

        logger.info(f"[1/4] Running constraint validation...")
        constraint_report = await self.constraint_validator.validate(diagnosis)
        constraint_score = constraint_report.overall_score

        logger.info(
            f"      Constraint score: {constraint_score:.2%}, "
            f"status: {constraint_report.overall_status}"
        )

        # ====================================================================
        # Step 2: Accuracy Verification (OPTIONAL)
        # ====================================================================

        verification_report = None
        accuracy_score = None
        hybrid_score = None

        if ground_truth and self.verifier:
            logger.info(f"[2/4] Running accuracy verification (ground truth available)...")
            verification_report = await self.verifier.verify(
                diagnosis, ground_truth, constraint_score=constraint_score
            )
            accuracy_score = verification_report.overall_accuracy_score

            logger.info(
                f"      Accuracy score: {accuracy_score:.2%}, "
                f"level: {verification_report.overall_accuracy_level}"
            )

            # Calculate hybrid score
            if self.gate_config.hybrid_gate_enabled:
                hybrid_score = (
                    constraint_score * self.gate_config.hybrid_weight_constraint
                    + accuracy_score * self.gate_config.hybrid_weight_accuracy
                )
                logger.info(f"      Hybrid score: {hybrid_score:.2%}")
        else:
            if not ground_truth:
                logger.info(
                    f"[2/4] Skipping verification (no ground truth provided)"
                )
            else:
                logger.info(f"[2/4] Skipping verification (no verifier configured)")

        # ====================================================================
        # Step 3: Decision Gates
        # ====================================================================

        logger.info(f"[3/4] Applying decision gates...")

        decision, reason, critical_failures, warnings, improvements = (
            apply_decision_gates(
                constraint_score=constraint_score,
                accuracy_score=accuracy_score,
                hybrid_score=hybrid_score,
                confidence_score=diagnosis.confidence_score,
                constraint_report=constraint_report,
                verification_report=verification_report,
                gate_config=self.gate_config,
            )
        )

        logger.info(f"      Decision: {decision.value}")

        # ====================================================================
        # Step 4: Route to Appropriate Target
        # ====================================================================

        logger.info(f"[4/4] Determining routing decision...")

        routing_decision = determine_routing(
            decision=decision,
            critical_failures=critical_failures,
            warnings=warnings,
            verification_report=verification_report,
        )

        logger.info(f"      Route: {routing_decision.target.value}")

        # ====================================================================
        # Generate Report
        # ====================================================================

        total_time_ms = (datetime.utcnow() - start_time).total_seconds() * 1000

        report = OrchestratorReport(
            scenario_id=diagnosis.scenario_id,
            expert_diagnosis=diagnosis,
            constraint_report=constraint_report,
            verification_report=verification_report,
            overall_decision=decision,
            routing_decision=routing_decision,
            reason=reason,
            constraint_score=constraint_score,
            accuracy_score=accuracy_score,
            hybrid_score=hybrid_score,
            confidence_score=diagnosis.confidence_score,
            critical_failures=critical_failures,
            warnings=warnings,
            improvement_suggestions=improvements,
            total_execution_time_ms=total_time_ms,
            gate_config=self.gate_config,
        )

        logger.info(f"✓ Processing complete: {decision.value}")

        return report

    async def process_batch(
        self,
        diagnoses: List[ExpertDiagnosisOutput],
        ground_truths: Optional[Dict[str, GroundTruth]] = None,
    ) -> Dict[str, OrchestratorReport]:
        """
        Process multiple diagnoses (batch mode).

        Args:
            diagnoses: List of diagnosis outputs
            ground_truths: Optional dict mapping scenario_id → ground truth

        Returns:
            Dict[scenario_id] → OrchestratorReport
        """
        ground_truths = ground_truths or {}
        results = {}

        logger.info(
            f"Processing batch of {len(diagnoses)} diagnoses..."
        )

        for diagnosis in diagnoses:
            ground_truth = ground_truths.get(diagnosis.scenario_id)
            report = await self.process(diagnosis, ground_truth=ground_truth)
            results[diagnosis.scenario_id] = report

        return results

    def save_report(
        self,
        report: OrchestratorReport,
        output_dir: Optional[Path] = None,
        report_format: str = "markdown",
    ) -> Path:
        """
        Save expert report to file in specified format.

        Args:
            report: OrchestratorReport to save
            output_dir: Directory path (defaults to exports/, uses absolute path)
            report_format: Format type - 'markdown' (default) or 'json'

        Returns:
            Path to saved report file

        Examples:
            # Default: Markdown format
            path = orchestrator.save_report(report)
            # → exports/expert_report_scenario_id_20260211_103536.md

            # JSON format
            path = orchestrator.save_report(report, report_format="json")
            # → exports/expert_report_scenario_id_20260211_103536.json
        """
        # Use absolute path, default to exports/ in current working directory
        if output_dir is None:
            output_dir = Path.cwd() / "exports"
        else:
            output_dir = Path(output_dir).resolve()

        output_dir.mkdir(parents=True, exist_ok=True)

        # New naming convention: expert_report_{scenario_id}_{timestamp}
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename_base = f"expert_report_{report.scenario_id}_{timestamp}"

        # Determine content and extension based on format
        if report_format.lower() == "json":
            content = report.to_json()
            extension = "json"
        elif report_format.lower() == "markdown" or report_format.lower() == "md":
            content = report.to_markdown()
            extension = "md"
        else:
            logger.warning(
                f"Unknown format '{report_format}', defaulting to markdown"
            )
            content = report.to_markdown()
            extension = "md"

        filename = f"{filename_base}.{extension}"
        filepath = output_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info(
            f"Expert report saved to: {filepath} (format: {extension.upper()})"
        )
        return filepath


# ============================================================================
# Factory & Defaults
# ============================================================================


def create_default_orchestrator() -> ExpertOrchestrator:
    """
    Create orchestrator instance with default configuration.

    Uses:
    - ExpertConstraintsValidator() from Task 4
    - DiagnosisVerifier() from Task 5 (optional)
    - Default DecisionGateConfig()

    Returns:
        ExpertOrchestrator ready to process diagnoses
    """
    validator = ExpertConstraintsValidator()
    verifier = DiagnosisVerifier()
    config = DecisionGateConfig()

    return ExpertOrchestrator(
        constraint_validator=validator, verifier=verifier, gate_config=config
    )
