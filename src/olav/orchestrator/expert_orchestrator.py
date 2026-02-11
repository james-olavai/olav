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

import json
import logging
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# Import from Task 4: Constraint Validation
from olav.testing.expert_constraints import (
    ExpertConstraintsValidator,
    ExpertDiagnosisOutput,
    ValidationReport,
)

# Import from Task 5: Verification
from olav.testing.diagnosis_verifier import (
    DiagnosisVerifier,
    GroundTruth,
    VerificationReport,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Enums & Constants
# ============================================================================


class OrchestratorDecision(str, Enum):
    """Final decision made by orchestrator"""

    ACCEPT = "accept"  # Passes all gates, safe to return to user
    REVIEW = "review"  # Flagged for human review (constraint warning)
    REJECT = "reject"  # Critical failure, blocked diagnosis
    UNCERTAIN = "uncertain"  # Low confidence, needs re-analysis


class RoutingTarget(str, Enum):
    """Where to route the result"""

    DIRECT_USER = "direct_user"  # Return directly to user
    HUMAN_REVIEW_QUEUE = "human_review_queue"  # Queue for human expert
    REANALYSIS_QUEUE = "reanalysis_queue"  # Route back to Expert Agent
    ESCALATION_QUEUE = "escalation_queue"  # Critical issues, escalate


# ============================================================================
# Decision Gate Configuration
# ============================================================================


class DecisionGateConfig(BaseModel):
    """Configuration for acceptance criteria"""

    # Constraint gates (Task 4 validation)
    constraint_pass_threshold: float = Field(
        default=0.85,
        description="Min constraint score to ACCEPT (0.0-1.0)",
        ge=0.0,
        le=1.0,
    )
    constraint_warning_threshold: float = Field(
        default=0.70,
        description="Min constraint score to avoid REJECT (0.0-1.0)",
        ge=0.0,
        le=1.0,
    )

    # Accuracy gates (Task 5 verification, optional)
    accuracy_pass_threshold: float = Field(
        default=0.80,
        description="Min accuracy to ACCEPT with verification (0.0-1.0)",
        ge=0.0,
        le=1.0,
    )
    accuracy_warning_threshold: float = Field(
        default=0.65,
        description="Min accuracy to avoid REJECT with verification (0.0-1.0)",
        ge=0.0,
        le=1.0,
    )

    # Confidence gates (Expert Agent output)
    confidence_pass_threshold: float = Field(
        default=0.80,
        description="Min confidence score from Expert Agent (0.0-1.0)",
        ge=0.0,
        le=1.0,
    )

    # Hybrid gate (constraint + accuracy)
    hybrid_gate_enabled: bool = Field(
        default=True, description="Enable hybrid scoring (constraint + accuracy)"
    )
    hybrid_weight_constraint: float = Field(
        default=0.60, description="Weight for constraint score in hybrid"
    )
    hybrid_weight_accuracy: float = Field(
        default=0.40, description="Weight for accuracy score in hybrid"
    )

    def validate_weights(self) -> None:
        """Ensure weights sum to 1.0"""
        total = self.hybrid_weight_constraint + self.hybrid_weight_accuracy
        if abs(total - 1.0) > 0.001:
            raise ValueError(
                f"Hybrid weights must sum to 1.0, got {total}. "
                f"constraint={self.hybrid_weight_constraint}, "
                f"accuracy={self.hybrid_weight_accuracy}"
            )


# ============================================================================
# Result Models
# ============================================================================


class RouteDecision(BaseModel):
    """Routing decision with explanation"""

    target: RoutingTarget
    reason: str
    requires_review: bool = False
    escalation_level: str = Field(
        default="normal", description="escalation, critical, normal"
    )

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


class OrchestratorReport(BaseModel):
    """Complete orchestrator output with all decisions"""

    # Identification
    scenario_id: str
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    batch_id: Optional[str] = None

    # Input diagnosis
    expert_diagnosis: ExpertDiagnosisOutput

    # Task 4: Constraint validation
    constraint_report: ValidationReport

    # Task 5: Accuracy verification (optional)
    verification_report: Optional[VerificationReport] = None

    # Decision gates
    overall_decision: OrchestratorDecision
    routing_decision: RouteDecision
    reason: str

    # Scores
    constraint_score: float = Field(ge=0.0, le=1.0)
    accuracy_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    hybrid_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    confidence_score: float = Field(ge=0.0, le=1.0)

    # Critical issues
    critical_failures: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)

    # Improvement suggestions
    improvement_suggestions: List[str] = Field(default_factory=list)

    # Metadata
    total_execution_time_ms: float
    gate_config: DecisionGateConfig

    def to_dict(self) -> Dict[str, Any]:
        """Export to dictionary"""
        return {
            "scenario_id": self.scenario_id,
            "timestamp": self.timestamp,
            "batch_id": self.batch_id,
            "overall_decision": self.overall_decision.value,
            "routing_decision": self.routing_decision.to_dict(),
            "reason": self.reason,
            "constraint_score": self.constraint_score,
            "accuracy_score": self.accuracy_score,
            "hybrid_score": self.hybrid_score,
            "confidence_score": self.confidence_score,
            "critical_failures": self.critical_failures,
            "warnings": self.warnings,
            "improvement_suggestions": self.improvement_suggestions,
            "execution_time_ms": self.total_execution_time_ms,
        }

    def to_json(self, indent: Optional[int] = 2) -> str:
        """Export to JSON string"""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def to_markdown(self) -> str:
        """Export to Markdown format (default for users)"""
        lines = [
            f"# Expert 诊断报告",
            f"",
            f"**场景ID**: {self.scenario_id}  ",
            f"**生成时间**: {self.timestamp}  ",
            f"",
            f"## 诊断决策",
            f"",
            f"| 项目 | 值 |",
            f"|------|-----|",
            f"| **决策** | {self.overall_decision.value.upper()} |",
            f"| **路由** | {self.routing_decision.target.value} |",
            f"| **理由** | {self.reason} |",
            f"",
            f"## 诊断分数",
            f"",
            f"| 指标 | 分数 | 说明 |",
            f"|------|------|------|",
            f"| 约束验证 (Task 4) | {self.constraint_score:.1%} | 幻觉检测、完整性检查 |",
        ]

        if self.accuracy_score is not None:
            lines.append(f"| 准确性验证 (Task 5) | {self.accuracy_score:.1%} | 与Ground Truth对比 |")
        else:
            lines.append(f"| 准确性验证 (Task 5) | N/A | 未提供Ground Truth |")

        if self.hybrid_score is not None:
            lines.append(f"| 混合分数 | {self.hybrid_score:.1%} | 约束 + 准确性加权 |")

        lines.extend([
            f"| Expert置信度 | {self.confidence_score:.1%} | Expert Agent的置信度 |",
            f"",
            f"## Expert诊断信息",
            f"",
            f"### 根本原因 (Root Cause)",
            f"```",
            f"{self.expert_diagnosis.root_cause}",
            f"```",
            f"",
            f"### 解决方案 (Solution)",
            f"```",
            f"{self.expert_diagnosis.solution}",
            f"```",
            f"",
            f"### 恢复命令 (Recovery Commands)",
            f"",
        ])

        for cmd in self.expert_diagnosis.recovery_commands:
            lines.append(f"- `{cmd}`")

        lines.extend([
            f"",
            f"### 验证步骤 (Verification Steps)",
            f"",
        ])

        for step in self.expert_diagnosis.verification_steps:
            lines.append(f"- {step}")

        lines.extend([
            f"",
            f"### 证据 (Evidence)",
            f"```",
            f"{self.expert_diagnosis.evidence}",
            f"```",
            f"",
        ])

        if self.critical_failures:
            lines.extend([
                f"## ⚠️  关键问题 ({len(self.critical_failures)})",
                f"",
            ])
            for issue in self.critical_failures:
                lines.append(f"- {issue}")
            lines.append("")

        if self.warnings:
            lines.extend([
                f"## ⚠️  警告 ({len(self.warnings)})",
                f"",
            ])
            for w in self.warnings:
                lines.append(f"- {w}")
            lines.append("")

        if self.improvement_suggestions:
            lines.extend([
                f"## 💡 改进建议 ({len(self.improvement_suggestions)})",
                f"",
            ])
            for s in self.improvement_suggestions:
                lines.append(f"- {s}")
            lines.append("")

        lines.extend([
            f"## 执行信息",
            f"",
            f"- **执行时间**: {self.total_execution_time_ms:.1f}ms",
            f"- **生成时间**: {datetime.utcnow().isoformat()}",
            f"",
            f"---",
            f"*此报告由Expert Orchestrator自动生成*",
        ])

        return "\n".join(lines)

    def summary(self) -> str:
        """Human-readable summary"""
        lines = [
            f"═══════════════════════════════════════════════════════",
            f"ORCHESTRATOR REPORT: {self.scenario_id}",
            f"═══════════════════════════════════════════════════════",
            f"",
            f"Decision:     {self.overall_decision.value.upper()}",
            f"Routing:      {self.routing_decision.target.value}",
            f"Reason:       {self.reason}",
            f"",
            f"Constraint Score: {self.constraint_score:.2%}",
            f"Accuracy Score:   {self.accuracy_score:.2%}" if self.accuracy_score else "",
            f"Hybrid Score:     {self.hybrid_score:.2%}" if self.hybrid_score else "",
            f"Confidence Score: {self.confidence_score:.2%}",
            f"",
        ]

        if self.critical_failures:
            lines.append(f"⚠️  CRITICAL ISSUES ({len(self.critical_failures)}):")
            for issue in self.critical_failures:
                lines.append(f"   - {issue}")
            lines.append("")

        if self.warnings:
            lines.append(f"⚠️  WARNINGS ({len(self.warnings)}):")
            for w in self.warnings:
                lines.append(f"   - {w}")
            lines.append("")

        if self.improvement_suggestions:
            lines.append(f"💡 SUGGESTIONS ({len(self.improvement_suggestions)}):")
            for s in self.improvement_suggestions:
                lines.append(f"   - {s}")
            lines.append("")

        lines.append(
            f"Execution Time: {self.total_execution_time_ms:.1f}ms"
        )
        lines.append(f"═══════════════════════════════════════════════════════")

        return "\n".join(filter(None, lines))


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
            self._apply_decision_gates(
                constraint_score=constraint_score,
                accuracy_score=accuracy_score,
                hybrid_score=hybrid_score,
                confidence_score=diagnosis.confidence_score,
                constraint_report=constraint_report,
                verification_report=verification_report,
            )
        )

        logger.info(f"      Decision: {decision.value}")

        # ====================================================================
        # Step 4: Route to Appropriate Target
        # ====================================================================

        logger.info(f"[4/4] Determining routing decision...")

        routing_decision = self._determine_routing(
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

    def _apply_decision_gates(
        self,
        constraint_score: float,
        accuracy_score: Optional[float],
        hybrid_score: Optional[float],
        confidence_score: float,
        constraint_report: ValidationReport,
        verification_report: Optional[VerificationReport],
    ) -> tuple[OrchestratorDecision, str, List[str], List[str], List[str]]:
        """
        Apply decision gates and determine pass/fail/review.

        Logic:
        - REJECT: Constraint < warning_threshold OR critical failures
        - ACCEPT: Constraint >= pass_threshold AND confidence >= pass_threshold
        - REVIEW: Constraint >= warning_threshold (but < pass)
        - UNCERTAIN: Low confidence OR accuracy < warning_threshold

        Returns:
            (decision, reason, critical_failures, warnings, improvements)
        """
        critical_failures = list(constraint_report.critical_failures or [])
        warnings = []
        improvements = []

        # ====================================================================
        # Gate 1: Constraint Score
        # ====================================================================

        if constraint_score < self.gate_config.constraint_warning_threshold:
            decision = OrchestratorDecision.REJECT
            reason = (
                f"Constraint score {constraint_score:.2%} below warning "
                f"threshold {self.gate_config.constraint_warning_threshold:.2%}"
            )
            critical_failures.append(reason)
            return decision, reason, critical_failures, warnings, improvements

        # ====================================================================
        # Gate 2: Confidence Score
        # ====================================================================

        if confidence_score < self.gate_config.confidence_pass_threshold:
            decision = OrchestratorDecision.UNCERTAIN
            reason = (
                f"Expert Agent confidence {confidence_score:.2%} below "
                f"threshold {self.gate_config.confidence_pass_threshold:.2%}"
            )
            warnings.append(reason)

            improvements.append(
                "Request Expert Agent to increase confidence through additional analysis"
            )

            return decision, reason, critical_failures, warnings, improvements

        # ====================================================================
        # Gate 3: Accuracy Score (if available)
        # ====================================================================

        if accuracy_score is not None:
            if accuracy_score < self.gate_config.accuracy_warning_threshold:
                decision = OrchestratorDecision.UNCERTAIN
                reason = (
                    f"Accuracy score {accuracy_score:.2%} below warning "
                    f"threshold {self.gate_config.accuracy_warning_threshold:.2%}"
                )
                warnings.append(reason)

                if verification_report:
                    improvements.extend(
                        verification_report.improvement_suggestions or []
                    )

                return decision, reason, critical_failures, warnings, improvements

        # ====================================================================
        # Gate 4: Accept Decision
        # ====================================================================

        # Check constraint pass threshold
        if constraint_score >= self.gate_config.constraint_pass_threshold:
            # Optional accuracy check
            if accuracy_score:
                if accuracy_score >= self.gate_config.accuracy_pass_threshold:
                    decision = OrchestratorDecision.ACCEPT
                    reason = "Passed all gates (constraint + accuracy)"
                else:
                    decision = OrchestratorDecision.REVIEW
                    reason = (
                        f"Constraint OK ({constraint_score:.2%}), "
                        f"but accuracy {accuracy_score:.2%} <= "
                        f"{self.gate_config.accuracy_pass_threshold:.2%}"
                    )
                    warnings.append(reason)
            else:
                decision = OrchestratorDecision.ACCEPT
                reason = f"Constraint score {constraint_score:.2%} >= {self.gate_config.constraint_pass_threshold:.2%}"
        else:
            decision = OrchestratorDecision.REVIEW
            reason = (
                f"Constraint score {constraint_score:.2%} in warning range "
                f"[{self.gate_config.constraint_warning_threshold:.2%}, "
                f"{self.gate_config.constraint_pass_threshold:.2%})"
            )
            warnings.append(reason)

        # Add improvement suggestions from constraint report
        if constraint_report.constraint_results:
            for result in constraint_report.constraint_results:
                if result.violations:
                    for violation in result.violations:
                        improvements.append(f"{result.constraint_name}: {violation.message}")

        # Add improvement suggestions from verification report
        if verification_report:
            improvements.extend(verification_report.improvement_suggestions or [])

        return decision, reason, critical_failures, warnings, improvements

    def _determine_routing(
        self,
        decision: OrchestratorDecision,
        critical_failures: List[str],
        warnings: List[str],
        verification_report: Optional[VerificationReport],
    ) -> RouteDecision:
        """
        Determine where to route the result based on decision.

        Routing Logic:
        - ACCEPT → DIRECT_USER (return immediately)
        - REVIEW → HUMAN_REVIEW_QUEUE (expert review)
        - REJECT → ESCALATION_QUEUE (critical issues)
        - UNCERTAIN → REANALYSIS_QUEUE (re-run Expert Agent)

        Returns:
            RouteDecision with target and reason
        """

        if decision == OrchestratorDecision.ACCEPT:
            return RouteDecision(
                target=RoutingTarget.DIRECT_USER,
                reason="Diagnosis passed all validation gates, safe to return to user",
                requires_review=False,
                escalation_level="normal",
            )

        elif decision == OrchestratorDecision.REVIEW:
            return RouteDecision(
                target=RoutingTarget.HUMAN_REVIEW_QUEUE,
                reason="Diagnosis flagged for human expert review (warning-level issues)",
                requires_review=True,
                escalation_level="normal",
            )

        elif decision == OrchestratorDecision.REJECT:
            return RouteDecision(
                target=RoutingTarget.ESCALATION_QUEUE,
                reason=f"Diagnosis rejected due to critical failures: {critical_failures}",
                requires_review=True,
                escalation_level="critical",
            )

        else:  # UNCERTAIN
            return RouteDecision(
                target=RoutingTarget.REANALYSIS_QUEUE,
                reason="Diagnosis uncertain, routing back for Expert Agent re-analysis",
                requires_review=False,
                escalation_level="normal",
            )

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
