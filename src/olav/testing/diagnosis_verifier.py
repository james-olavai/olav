"""
Diagnosis Verifier - Expert Agent Accuracy Scoring

Implements DiagnosisVerifier to score Expert Agent diagnostic accuracy
against ground truth, measuring RCA correctness, solution effectiveness,
and verification plan completeness.

Version: v1.0.0 (2026-02-11)
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Optional, Tuple, Set
import re
from abc import ABC
import logging

logger = logging.getLogger(__name__)


class AccuracyLevel(str, Enum):
    """Accuracy assessment levels."""
    EXCEPTIONAL = "exceptional"  # 0.95-1.00
    EXCELLENT = "excellent"      # 0.90-0.94
    GOOD = "good"                # 0.80-0.89
    FAIR = "fair"                # 0.70-0.79
    POOR = "poor"                # < 0.70


@dataclass
class GroundTruth:
    """Represents the expected/correct diagnosis for a scenario."""
    scenario_id: str
    expected_root_cause: str      # What the RCA should be
    expected_solution: str        # What the solution should be
    expected_recovery_commands: List[str]  # Exact commands to fix
    expected_verification_steps: List[str] # Commands to verify fix
    difficulty_level: str = "medium"  # simple/medium/complex
    description: str = ""         # Scenario description
    
    def to_dict(self) -> Dict[str, any]:
        """Convert to dictionary."""
        return {
            "scenario_id": self.scenario_id,
            "expected_root_cause": self.expected_root_cause,
            "expected_solution": self.expected_solution,
            "expected_recovery_commands": self.expected_recovery_commands,
            "expected_verification_steps": self.expected_verification_steps,
            "difficulty_level": self.difficulty_level,
            "description": self.description,
        }


@dataclass
class AssessmentDetail:
    """Details of a single assessment (RCA, Solution, or Verification)."""
    aspect: str              # "RCA", "Solution", or "Verification"
    score: float             # 0.0-1.0
    level: AccuracyLevel     # exceptional/excellent/good/fair/poor
    matching_elements: List[str] = field(default_factory=list)  # What matched
    missing_elements: List[str] = field(default_factory=list)   # What's missing
    extra_elements: List[str] = field(default_factory=list)     # Extra info
    feedback: str = ""       # Detailed feedback for improvement
    
    def to_dict(self) -> Dict[str, any]:
        """Convert to dictionary."""
        return {
            "aspect": self.aspect,
            "score": self.score,
            "level": self.level.value,
            "matching_elements": self.matching_elements,
            "missing_elements": self.missing_elements,
            "extra_elements": self.extra_elements,
            "feedback": self.feedback,
        }


@dataclass
class VerificationReport:
    """Complete verification report for a diagnosis."""
    scenario_id: str
    constraint_score: float  # From Task 4 (0.0-1.0)
    rca_accuracy: AssessmentDetail
    solution_effectiveness: AssessmentDetail
    verification_plan: AssessmentDetail
    overall_accuracy_score: float  # Average of 3 assessments
    overall_accuracy_level: AccuracyLevel
    critical_issues: List[str] = field(default_factory=list)
    improvement_suggestions: List[str] = field(default_factory=list)
    
    def passed(self) -> bool:
        """Check if overall accuracy is acceptable (≥0.80)."""
        return self.overall_accuracy_score >= 0.80
    
    def to_dict(self) -> Dict[str, any]:
        """Convert to dictionary."""
        return {
            "scenario_id": self.scenario_id,
            "constraint_score": self.constraint_score,
            "overall_accuracy_score": self.overall_accuracy_score,
            "overall_accuracy_level": self.overall_accuracy_level.value,
            "rca_accuracy": self.rca_accuracy.to_dict(),
            "solution_effectiveness": self.solution_effectiveness.to_dict(),
            "verification_plan": self.verification_plan.to_dict(),
            "critical_issues": self.critical_issues,
            "improvement_suggestions": self.improvement_suggestions,
        }
    
    def summary(self) -> str:
        """Generate human-readable summary."""
        lines = [
            f"Diagnosis Verification Report - {self.scenario_id}",
            f"{'=' * 70}",
            f"Overall Accuracy: {self.overall_accuracy_score:.0%} ({self.overall_accuracy_level.value.upper()})",
            f"Constraint Score: {self.constraint_score:.0%}",
            "",
            "Assessment Breakdown:",
            f"  RCA Accuracy:          {self.rca_accuracy.score:.0%} ({self.rca_accuracy.level.value})",
            f"  Solution Effectiveness: {self.solution_effectiveness.score:.0%} ({self.solution_effectiveness.level.value})",
            f"  Verification Plan:     {self.verification_plan.score:.0%} ({self.verification_plan.level.value})",
        ]
        
        if self.critical_issues:
            lines.append("")
            lines.append("Critical Issues:")
            for issue in self.critical_issues:
                lines.append(f"  ❌ {issue}")
        
        if self.improvement_suggestions:
            lines.append("")
            lines.append("Improvement Suggestions:")
            for suggestion in self.improvement_suggestions:
                lines.append(f"  💡 {suggestion}")
        
        return "\n".join(lines)


class TextualMatcher(ABC):
    """Base class for textual comparison/matching."""
    
    @staticmethod
    def extract_keywords(text: str) -> Set[str]:
        """Extract meaningful keywords from text."""
        # Remove common words
        stop_words = {
            'the', 'a', 'an', 'and', 'or', 'but', 'is', 'are', 'was', 'were',
            'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did',
            'will', 'would', 'should', 'could', 'may', 'might', 'must', 'can',
            'it', 'its', 'to', 'for', 'of', 'in', 'on', 'at', 'by', 'with',
            'interface', 'show', 'execute', 'configure', 'terminal',
        }
        
        # Convert to lowercase and split
        words = re.findall(r'\b\w+\b', text.lower())
        
        # Filter stop words and short words
        keywords = {
            w for w in words
            if w not in stop_words and len(w) > 2
        }
        
        return keywords
    
    @staticmethod
    def calculate_overlap(set1: Set[str], set2: Set[str]) -> float:
        """Calculate Jaccard similarity between two sets."""
        if not set1 and not set2:
            return 1.0
        if not set1 or not set2:
            return 0.0
        
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        
        return intersection / union if union > 0 else 0.0


class RCAVerifier(TextualMatcher):
    """Verifies Root Cause Analysis accuracy."""
    
    def __init__(self):
        self.name = "RCA Verifier"
    
    async def verify(
        self,
        expert_rca: str,
        expected_rca: str,
    ) -> AssessmentDetail:
        """Verify expert RCA against expected RCA."""
        
        # Extract keywords from both
        expert_keywords = self.extract_keywords(expert_rca)
        expected_keywords = self.extract_keywords(expected_rca)
        
        # Calculate match score
        keyword_overlap = self.calculate_overlap(expert_keywords, expected_keywords)
        
        # Check for specific network terms
        network_terms = {'bgp', 'ospf', 'interface', 'neighbor', 'shutdown', 
                        'down', 'up', 'error', 'mismatch', 'hello', 'cost'}
        
        expert_network = expert_keywords & network_terms
        expected_network = expected_keywords & network_terms
        
        network_match = 0.0
        if expected_network:
            network_match = len(expert_network & expected_network) / len(expected_network)
        
        # Compute final score (weighted combination)
        score = 0.7 * keyword_overlap + 0.3 * network_match
        
        # Determine level
        level = self._score_to_level(score)
        
        # Identify matching and missing elements
        matching = list(expert_network & expected_network)
        missing = list(expected_network - expert_network)
        extra = list(expert_network - expected_network)
        
        # Generate feedback
        feedback = self._generate_feedback(
            expert_rca, expected_rca, score, missing, extra
        )
        
        return AssessmentDetail(
            aspect="RCA",
            score=score,
            level=level,
            matching_elements=matching,
            missing_elements=missing,
            extra_elements=extra,
            feedback=feedback,
        )
    
    @staticmethod
    def _score_to_level(score: float) -> AccuracyLevel:
        """Convert score to accuracy level."""
        if score >= 0.95:
            return AccuracyLevel.EXCEPTIONAL
        elif score >= 0.90:
            return AccuracyLevel.EXCELLENT
        elif score >= 0.80:
            return AccuracyLevel.GOOD
        elif score >= 0.70:
            return AccuracyLevel.FAIR
        else:
            return AccuracyLevel.POOR
    
    @staticmethod
    def _generate_feedback(
        expert_rca: str,
        expected_rca: str,
        score: float,
        missing: List[str],
        extra: List[str],
    ) -> str:
        """Generate improvement feedback."""
        feedback_parts = []
        
        if score >= 0.95:
            feedback_parts.append("RCA is very accurate and well-identified.")
        elif score >= 0.80:
            feedback_parts.append("RCA captures the main issue correctly.")
            if missing:
                feedback_parts.append(f"Could mention: {', '.join(missing[:2])}")
        elif score >= 0.70:
            feedback_parts.append("RCA identifies some correct elements but is incomplete.")
            if missing:
                feedback_parts.append(f"Missing key components: {', '.join(missing[:2])}")
        else:
            feedback_parts.append("RCA does not match the expected root cause.")
            feedback_parts.append(f"Expected to identify: {expected_rca[:50]}...")
        
        return " ".join(feedback_parts)


class SolutionVerifier(TextualMatcher):
    """Verifies solution effectiveness."""
    
    def __init__(self):
        self.name = "Solution Verifier"
    
    async def verify(
        self,
        expert_solution: str,
        expert_commands: List[str],
        expected_solution: str,
        expected_commands: List[str],
    ) -> AssessmentDetail:
        """Verify expert solution against expected solution."""
        
        # Extract command keywords
        expert_cmd_keywords = set()
        for cmd in expert_commands:
            keywords = self.extract_keywords(cmd)
            expert_cmd_keywords.update(keywords)
        
        expected_cmd_keywords = set()
        for cmd in expected_commands:
            keywords = self.extract_keywords(cmd)
            expected_cmd_keywords.update(keywords)
        
        # Calculate command match
        command_overlap = self.calculate_overlap(
            expert_cmd_keywords,
            expected_cmd_keywords
        )
        
        # Extract keywords from solution description
        expert_sol_keywords = self.extract_keywords(expert_solution)
        expected_sol_keywords = self.extract_keywords(expected_solution)
        
        # Calculate solution text match
        solution_overlap = self.calculate_overlap(
            expert_sol_keywords,
            expected_sol_keywords
        )
        
        # Check for harmful commands (penalize)
        harmful_keywords = {'delete', 'remove', 'clear', 'reboot', 'shutdown'}
        harmful_commands = len(expert_cmd_keywords & harmful_keywords)
        
        # Compute final score
        score = 0.6 * command_overlap + 0.4 * solution_overlap
        score = max(0.0, score - harmful_commands * 0.1)  # Penalize for harmful
        
        # Determine level
        level = RCAVerifier._score_to_level(score)
        
        # Identify elements
        matching = list(expert_cmd_keywords & expected_cmd_keywords)
        missing = list(expected_cmd_keywords - expert_cmd_keywords)
        extra = list(expert_cmd_keywords - expected_cmd_keywords)
        
        # Generate feedback
        feedback = self._generate_feedback(
            expert_commands, expected_commands, score, missing, harmful_commands
        )
        
        return AssessmentDetail(
            aspect="Solution",
            score=score,
            level=level,
            matching_elements=matching,
            missing_elements=missing,
            extra_elements=extra,
            feedback=feedback,
        )
    
    @staticmethod
    def _generate_feedback(
        expert_commands: List[str],
        expected_commands: List[str],
        score: float,
        missing: List[str],
        harmful_count: int,
    ) -> str:
        """Generate improvement feedback."""
        feedback_parts = []
        
        if harmful_count > 0:
            feedback_parts.append(f"⚠️ WARNING: {harmful_count} potentially harmful command(s) detected.")
        
        if score >= 0.95:
            feedback_parts.append("Solution is correct and complete.")
        elif score >= 0.80:
            feedback_parts.append("Solution addresses the issue effectively.")
            if missing:
                feedback_parts.append(f"Could also include: {', '.join(missing[:1])}")
        elif score >= 0.70:
            feedback_parts.append("Solution partially addresses the issue.")
            feedback_parts.append(f"Expected: {expected_commands[0] if expected_commands else 'specific command'}")
        else:
            feedback_parts.append("Solution does not address the root cause.")
            feedback_parts.append("Review the RCA and propose corrective commands.")
        
        return " ".join(feedback_parts)


class VerificationVerifier(TextualMatcher):
    """Verifies verification plan completeness."""
    
    def __init__(self):
        self.name = "Verification Verifier"
    
    async def verify(
        self,
        expert_verification_steps: List[str],
        expected_verification_steps: List[str],
    ) -> AssessmentDetail:
        """Verify expert verification plan against expected."""
        
        # Extract keywords from verification steps
        expert_verify_keywords = set()
        for step in expert_verification_steps:
            keywords = self.extract_keywords(step)
            expert_verify_keywords.update(keywords)
        
        expected_verify_keywords = set()
        for step in expected_verification_steps:
            keywords = self.extract_keywords(step)
            expected_verify_keywords.update(keywords)
        
        # Calculate verification match
        verification_overlap = self.calculate_overlap(
            expert_verify_keywords,
            expected_verify_keywords
        )
        
        # Check for comprehensive verification
        # Good verification includes multiple aspects
        verification_aspects = {'interface', 'bgp', 'ospf', 'status', 'neighbor',
                               'ping', 'traceroute', 'connectivity', 'show'}
        
        expert_aspects = len(expert_verify_keywords & verification_aspects)
        expected_aspects = len(expected_verify_keywords & verification_aspects)
        
        aspect_coverage = 0.0
        if expected_aspects > 0:
            aspect_coverage = min(1.0, expert_aspects / expected_aspects)
        
        # Compute final score
        score = 0.6 * verification_overlap + 0.4 * aspect_coverage
        
        # Determine level
        level = RCAVerifier._score_to_level(score)
        
        # Identify elements
        matching = list(expert_verify_keywords & expected_verify_keywords)
        missing = list(expected_verify_keywords - expert_verify_keywords)
        extra = list(expert_verify_keywords - expected_verify_keywords)
        
        # Generate feedback
        feedback = self._generate_feedback(
            expert_verification_steps, expected_verification_steps, score, missing
        )
        
        return AssessmentDetail(
            aspect="Verification",
            score=score,
            level=level,
            matching_elements=matching,
            missing_elements=missing,
            extra_elements=extra,
            feedback=feedback,
        )
    
    @staticmethod
    def _generate_feedback(
        expert_steps: List[str],
        expected_steps: List[str],
        score: float,
        missing: List[str],
    ) -> str:
        """Generate improvement feedback."""
        feedback_parts = []
        
        if score >= 0.95:
            feedback_parts.append("Verification plan is comprehensive and thorough.")
        elif score >= 0.80:
            feedback_parts.append("Verification plan adequately confirms the fix.")
        elif score >= 0.70:
            feedback_parts.append("Verification plan covers basic checks.")
            feedback_parts.append("Consider adding more validation steps.")
        else:
            feedback_parts.append("Verification plan is minimal or missing key checks.")
            if expected_steps:
                feedback_parts.append(f"Expected: {expected_steps[0]}")
        
        return " ".join(feedback_parts)


class DiagnosisVerifier:
    """Main orchestrator for diagnosis verification."""
    
    def __init__(self):
        """Initialize verifier with all sub-verifiers."""
        self.rca_verifier = RCAVerifier()
        self.solution_verifier = SolutionVerifier()
        self.verification_verifier = VerificationVerifier()
    
    async def verify(
        self,
        expert_diagnosis: 'ExpertDiagnosisOutput',  # From Task 4
        ground_truth: GroundTruth,
        constraint_score: float = 0.0,
    ) -> VerificationReport:
        """
        Verify expert diagnosis against ground truth.
        
        Args:
            expert_diagnosis: Diagnosis output from Expert Agent
            ground_truth: Expected/correct diagnosis
            constraint_score: Constraint validation score (from Task 4)
            
        Returns:
            Complete verification report
        """
        
        # Run all verifications in parallel concept
        rca_assessment = await self.rca_verifier.verify(
            expert_diagnosis.root_cause,
            ground_truth.expected_root_cause,
        )
        
        solution_assessment = await self.solution_verifier.verify(
            expert_diagnosis.solution,
            expert_diagnosis.recovery_commands,
            ground_truth.expected_solution,
            ground_truth.expected_recovery_commands,
        )
        
        verification_assessment = await self.verification_verifier.verify(
            expert_diagnosis.verification_steps,
            ground_truth.expected_verification_steps,
        )
        
        # Calculate overall accuracy
        overall_accuracy_score = (
            rca_assessment.score +
            solution_assessment.score +
            verification_assessment.score
        ) / 3.0
        
        # Determine overall level
        overall_level = RCAVerifier._score_to_level(overall_accuracy_score)
        
        # Identify critical issues
        critical_issues = []
        if rca_assessment.score < 0.5:
            critical_issues.append(
                f"Root Cause Analysis is significantly incorrect (score: {rca_assessment.score:.0%})"
            )
        if solution_assessment.score < 0.5:
            critical_issues.append(
                f"Proposed solution may not work (score: {solution_assessment.score:.0%})"
            )
        
        # Generate improvement suggestions
        improvement_suggestions = []
        if rca_assessment.missing_elements:
            improvement_suggestions.append(
                f"For RCA: Mention {', '.join(rca_assessment.missing_elements[:2])}"
            )
        if solution_assessment.missing_elements:
            improvement_suggestions.append(
                f"For Solution: Include {', '.join(solution_assessment.missing_elements[:1])}"
            )
        if verification_assessment.score < 0.8:
            improvement_suggestions.append(
                "Add more comprehensive verification steps to confirm the fix"
            )
        
        return VerificationReport(
            scenario_id=ground_truth.scenario_id,
            constraint_score=constraint_score,
            rca_accuracy=rca_assessment,
            solution_effectiveness=solution_assessment,
            verification_plan=verification_assessment,
            overall_accuracy_score=overall_accuracy_score,
            overall_accuracy_level = overall_level,
            critical_issues=critical_issues,
            improvement_suggestions=improvement_suggestions,
        )
    
    async def verify_batch(
        self,
        diagnoses: List[Tuple['ExpertDiagnosisOutput', GroundTruth]],
        constraint_scores: Optional[Dict[str, float]] = None,
    ) -> Dict[str, VerificationReport]:
        """
        Verify multiple diagnoses against their ground truth.
        
        Args:
            diagnoses: List of (diagnosis, ground_truth) tuples
            constraint_scores: Optional dict mapping scenario_id to constraint_score
            
        Returns:
            Dictionary mapping scenario_id to VerificationReport
        """
        reports = {}
        
        for diagnosis, ground_truth in diagnoses:
            constraint_score = (
                constraint_scores.get(ground_truth.scenario_id, 0.0)
                if constraint_scores
                else 0.0
            )
            
            report = await self.verify(
                diagnosis,
                ground_truth,
                constraint_score,
            )
            
            reports[ground_truth.scenario_id] = report
        
        return reports


# Convenience function for quick verification
async def verify_diagnosis(
    expert_diagnosis: 'ExpertDiagnosisOutput',
    ground_truth: GroundTruth,
    constraint_score: float = 0.0,
) -> VerificationReport:
    """
    Quickly verify a diagnosis using default verifier.
    
    Args:
        expert_diagnosis: The diagnosis to verify
        ground_truth: Expected correct diagnosis
        constraint_score: Constraint validation score
        
    Returns:
        Verification report
    """
    verifier = DiagnosisVerifier()
    return await verifier.verify(expert_diagnosis, ground_truth, constraint_score)
