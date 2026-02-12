"""
Expert Orchestrator - State & Configuration Models

Data models and enumerations for diagnosis orchestration:
- Decision enums (ACCEPT, REVIEW, REJECT, UNCERTAIN)
- Routing targets
- Configuration for decision gates
- Report models for results
"""

import json
import logging
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from olav.testing.expert_constraints import ExpertDiagnosisOutput, ValidationReport
from olav.testing.diagnosis_verifier import VerificationReport

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
