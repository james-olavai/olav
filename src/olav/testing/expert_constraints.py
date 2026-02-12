"""
Expert Constraints Validation System

Validates diagnostic outputs from Expert Agent against predefined constraints.
Prevents hallucinations, ensures completeness, and enforces quality standards.

Version: v1.0.0 (2026-02-11)
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List, Dict, Optional
import re
from abc import ABC, abstractmethod
import logging

logger = logging.getLogger(__name__)


class ConstraintLevel(str, Enum):
    """Constraint severity levels."""
    CRITICAL = "critical"      # Must pass to accept diagnosis
    HIGH = "high"              # Should pass, blocks diagnosis if failed
    MEDIUM = "medium"          # Recommended, warnings only
    LOW = "low"                # Information only


class ConstraintStatus(str, Enum):
    """Result status for constraint checks."""
    PASSED = "passed"
    WARNING = "warning"
    FAILED = "failed"


@dataclass
class ConstraintViolation:
    """Represents a single constraint violation."""
    constraint_name: str
    level: ConstraintLevel
    message: str
    evidence: str = ""
    suggestion: str = ""
    
    def to_dict(self) -> Dict[str, str]:
        """Convert to dictionary."""
        return {
            "constraint": self.constraint_name,
            "level": self.level.value,
            "message": self.message,
            "evidence": self.evidence,
            "suggestion": self.suggestion,
        }


@dataclass
class ConstraintCheckResult:
    """Result of a single constraint check."""
    constraint_name: str
    status: ConstraintStatus
    level: ConstraintLevel
    message: str
    violations: List[ConstraintViolation] = field(default_factory=list)
    score: float = 1.0  # 0.0 to 1.0
    
    def passed(self) -> bool:
        """Check if constraint passed."""
        return self.status == ConstraintStatus.PASSED
    
    def critical_failure(self) -> bool:
        """Check if this is a critical failure."""
        return self.level == ConstraintLevel.CRITICAL and not self.passed()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "constraint": self.constraint_name,
            "status": self.status.value,
            "level": self.level.value,
            "message": self.message,
            "score": self.score,
            "violations": [v.to_dict() for v in self.violations],
        }


@dataclass
class ExpertDiagnosisOutput:
    """Represents Expert Agent diagnostic output."""
    scenario_id: str
    root_cause: str
    confidence_score: float  # 0.0 to 1.0
    solution: str
    verification_steps: List[str] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)
    diagnostic_reasoning: str = ""
    recovery_commands: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "scenario_id": self.scenario_id,
            "root_cause": self.root_cause,
            "confidence_score": self.confidence_score,
            "solution": self.solution,
            "verification_steps": self.verification_steps,
            "evidence": self.evidence,
            "diagnostic_reasoning": self.diagnostic_reasoning,
            "recovery_commands": self.recovery_commands,
        }


class ConstraintChecker(ABC):
    """Base class for constraint checkers."""
    
    def __init__(self, name: str, level: ConstraintLevel):
        self.name = name
        self.level = level
    
    @abstractmethod
    async def check(self, diagnosis: ExpertDiagnosisOutput) -> ConstraintCheckResult:
        """Execute constraint check."""
        pass


class OutputCompleteness(ConstraintChecker):
    """Validates that diagnosis output contains all required fields."""
    
    def __init__(self):
        super().__init__("Output Completeness", ConstraintLevel.CRITICAL)
    
    async def check(self, diagnosis: ExpertDiagnosisOutput) -> ConstraintCheckResult:
        """Check that all required fields are present and non-empty."""
        violations = []
        missing_fields = []
        
        # Check required string fields
        if not diagnosis.root_cause or not diagnosis.root_cause.strip():
            missing_fields.append("root_cause")
            violations.append(ConstraintViolation(
                constraint_name=self.name,
                level=ConstraintLevel.CRITICAL,
                message="Root cause is empty",
                evidence="diagnosis.root_cause = ''",
                suggestion="RCA must identify the specific network issue"
            ))
        
        if not diagnosis.solution or not diagnosis.solution.strip():
            missing_fields.append("solution")
            violations.append(ConstraintViolation(
                constraint_name=self.name,
                level=ConstraintLevel.CRITICAL,
                message="Solution is empty",
                evidence="diagnosis.solution = ''",
                suggestion="Solution must describe remediation steps"
            ))
        
        # Check lists have content
        if not diagnosis.verification_steps:
            missing_fields.append("verification_steps")
            violations.append(ConstraintViolation(
                constraint_name=self.name,
                level=ConstraintLevel.HIGH,
                message="No verification steps provided",
                evidence="verification_steps is empty list",
                suggestion="Include commands to verify problem resolution"
            ))
        
        if not diagnosis.evidence:
            missing_fields.append("evidence")
            violations.append(ConstraintViolation(
                constraint_name=self.name,
                level=ConstraintLevel.MEDIUM,
                message="No evidence provided",
                evidence="evidence is empty list",
                suggestion="Document which CLI outputs support the diagnosis"
            ))
        
        # Determine status
        if any(v.level == ConstraintLevel.CRITICAL for v in violations):
            status = ConstraintStatus.FAILED
            score = 0.5
        elif violations:
            status = ConstraintStatus.WARNING
            score = 0.7
        else:
            status = ConstraintStatus.PASSED
            score = 1.0
        
        message = f"Completeness check: {len(missing_fields)} fields missing" if missing_fields else "All required fields present"
        
        return ConstraintCheckResult(
            constraint_name=self.name,
            status=status,
            level=self.level,
            message=message,
            violations=violations,
            score=score
        )


class ConfidenceScoreValidator(ConstraintChecker):
    """Validates confidence score is within acceptable range."""
    
    def __init__(self, min_score: float = 0.80, max_score: float = 1.0):
        super().__init__("Confidence Score", ConstraintLevel.CRITICAL)
        self.min_score = min_score
        self.max_score = max_score
    
    async def check(self, diagnosis: ExpertDiagnosisOutput) -> ConstraintCheckResult:
        """Check confidence score is valid and within range."""
        violations = []
        
        # Check score is numeric and in range
        if not (0.0 <= diagnosis.confidence_score <= 1.0):
            violations.append(ConstraintViolation(
                constraint_name=self.name,
                level=ConstraintLevel.CRITICAL,
                message=f"Confidence score out of range: {diagnosis.confidence_score}",
                evidence=f"confidence_score = {diagnosis.confidence_score}",
                suggestion="Score must be between 0.0 and 1.0"
            ))
            return ConstraintCheckResult(
                constraint_name=self.name,
                status=ConstraintStatus.FAILED,
                level=self.level,
                message=f"Invalid confidence score: {diagnosis.confidence_score}",
                violations=violations,
                score=0.0
            )
        
        # Check score is above minimum threshold
        if diagnosis.confidence_score < self.min_score:
            violations.append(ConstraintViolation(
                constraint_name=self.name,
                level=ConstraintLevel.CRITICAL,
                message=f"Confidence score {diagnosis.confidence_score:.2f} below minimum {self.min_score:.2f}",
                evidence=f"confidence_score = {diagnosis.confidence_score:.2f}",
                suggestion=f"Diagnosis confidence must be ≥ {self.min_score}"
            ))
            status = ConstraintStatus.FAILED
            score = diagnosis.confidence_score
        else:
            status = ConstraintStatus.PASSED
            score = diagnosis.confidence_score
        
        message = f"Confidence score: {diagnosis.confidence_score:.2f} ({status.value})"
        
        return ConstraintCheckResult(
            constraint_name=self.name,
            status=status,
            level=self.level,
            message=message,
            violations=violations,
            score=score
        )


class HallucinationDetector(ConstraintChecker):
    """Detects signs of hallucination in diagnosis."""
    
    # Vague/uncertain terms indicating hallucination risk
    VAGUE_TERMS = [
        r'\b(也许|可能|似乎|应该|通常|一般|大概|或许|可能性|疑似)\b',
        r'\b(maybe|perhaps|probably|likely|appears|seems|might|could be|suggests|may)\b',
        r'\b(可能是|很可能|有可能|似乎是|好像|估计|想象|猜测)\b',
    ]
    
    # Nonsensical/impossible patterns
    NONSENSE_PATTERNS = [
        r'(完全|彻底|永远|绝对|从不|根本)\s*(无法|不能|不会|没有)',  # Absolute negatives
        r'([\w\s]+)\s+(配置|设置|修改)\s*(了|成功|完成)\s*([0-9]{3,})',  # Impossible numbers
        r'([\w\s]+)\s*(消失|消失了|不存在了|被删除了)',  # Impossible disappearances
    ]
    
    # Generic/placeholder content
    GENERIC_PATTERNS = [
        r'\b(等等|等等|以及|另外|此外|而且)\b',  # Filler words
        r'([\w]{1,3})\s*(问题|故障|错误)',  # Vague placeholders
        r'\b(unknown|undefined|null|none)\b',  # Null references
    ]
    
    def __init__(self, vague_term_threshold: float = 0.05):
        """
        Initialize hallucination detector.
        
        Args:
            vague_term_threshold: Max allowed ratio of vague terms (0.0-1.0)
        """
        super().__init__("Hallucination Detection", ConstraintLevel.CRITICAL)
        self.vague_term_threshold = vague_term_threshold
    
    async def check(self, diagnosis: ExpertDiagnosisOutput) -> ConstraintCheckResult:
        """Detect signs of hallucination."""
        violations = []
        hallucination_score = 0.0  # 0.0 = no hallucination, 1.0 = definite hallucination
        
        # Check for vague terms in RCA
        vague_count = self._count_pattern_matches(diagnosis.root_cause, self.VAGUE_TERMS)
        total_words = len(diagnosis.root_cause.split())
        vague_ratio = vague_count / max(total_words, 1)
        
        if vague_ratio > self.vague_term_threshold:
            hallucination_score += 0.3
            violations.append(ConstraintViolation(
                constraint_name=self.name,
                level=ConstraintLevel.HIGH,
                message=f"High vague term ratio in RCA: {vague_ratio:.1%}",
                evidence=f"Found {vague_count} vague terms in {total_words} words",
                suggestion="Use specific terms like 'BGP session down' instead of 'probably connectivity issue'"
            ))
        
        # Check for nonsense patterns
        nonsense_count = self._count_pattern_matches(diagnosis.root_cause, self.NONSENSE_PATTERNS)
        if nonsense_count > 0:
            hallucination_score += 0.4
            violations.append(ConstraintViolation(
                constraint_name=self.name,
                level=ConstraintLevel.CRITICAL,
                message=f"Impossible/nonsensical patterns detected: {nonsense_count}",
                evidence=f"RCA contains {nonsense_count} nonsensical pattern(s)",
                suggestion="Diagnosis seems fabricated; verify evidence supports output"
            ))
        
        # Check solution for generic content
        generic_count = self._count_pattern_matches(diagnosis.solution, self.GENERIC_PATTERNS)
        if generic_count > 2:
            hallucination_score += 0.2
            violations.append(ConstraintViolation(
                constraint_name=self.name,
                level=ConstraintLevel.MEDIUM,
                message=f"Generic content in solution: {generic_count} generic patterns",
                evidence=f"Solution contains {generic_count} generic term(s)",
                suggestion="Provide specific commands and configuration changes"
            ))
        
        # Check for circular reasoning
        if diagnosis.root_cause.lower() in diagnosis.solution.lower():
            hallucination_score += 0.25
            violations.append(ConstraintViolation(
                constraint_name=self.name,
                level=ConstraintLevel.MEDIUM,
                message="Circular reasoning detected",
                evidence="Solution simply restates the same problem",
                suggestion="Solution should describe how to FIX the identified problem"
            ))
        
        # Determine overall status
        if hallucination_score > 0.5:
            status = ConstraintStatus.FAILED
        elif hallucination_score > 0.2:
            status = ConstraintStatus.WARNING
        else:
            status = ConstraintStatus.PASSED
        
        score = 1.0 - hallucination_score
        
        return ConstraintCheckResult(
            constraint_name=self.name,
            status=status,
            level=self.level,
            message=f"Hallucination risk: {hallucination_score:.1%}",
            violations=violations,
            score=score
        )
    
    def _count_pattern_matches(self, text: str, patterns: List[str]) -> int:
        """Count total matches across all patterns."""
        count = 0
        for pattern in patterns:
            count += len(re.findall(pattern, text, re.IGNORECASE))
        return count


class RCACompleteness(ConstraintChecker):
    """Validates Root Cause Analysis (RCA) is complete and sound."""
    
    # Expected RCA components
    EXPECTED_RCA_COMPONENTS = [
        r'(接口|interface|BGP|OSPF|链路|link|邻居|neighbor)',  # Network element
        r'(关闭|shutdown|disabled|down|错误|error|失败|failure)',  # Problem state
        r'(导致|causes?|resulted?|leads? to)',  # Causality
    ]
    
    def __init__(self):
        super().__init__("RCA Completeness", ConstraintLevel.HIGH)
    
    async def check(self, diagnosis: ExpertDiagnosisOutput) -> ConstraintCheckResult:
        """Check RCA is complete and well-reasoned."""
        violations = []
        rca_completeness = 0.0
        
        # Check RCA has sufficient detail
        rca_words = len(diagnosis.root_cause.split())
        if rca_words < 10:
            violations.append(ConstraintViolation(
                constraint_name=self.name,
                level=ConstraintLevel.MEDIUM,
                message=f"RCA too brief: {rca_words} words",
                evidence=f"RCA length = {rca_words} words",
                suggestion="Provide detailed explanation (≥10 words)"
            ))
            rca_completeness = 0.5
        else:
            rca_completeness += 0.3
        
        # Check RCA mentions network element
        has_network_element = any(
            re.search(pattern, diagnosis.root_cause, re.IGNORECASE)
            for pattern in self.EXPECTED_RCA_COMPONENTS[:1]
        )
        if has_network_element:
            rca_completeness += 0.3
        else:
            violations.append(ConstraintViolation(
                constraint_name=self.name,
                level=ConstraintLevel.MEDIUM,
                message="RCA doesn't mention specific network element",
                evidence="RCA missing interface, protocol, or device reference",
                suggestion="Specify which interface/protocol/device is affected"
            ))
        
        # Check RCA mentions problem state
        has_problem_state = any(
            re.search(pattern, diagnosis.root_cause, re.IGNORECASE)
            for pattern in self.EXPECTED_RCA_COMPONENTS[1:2]
        )
        if has_problem_state:
            rca_completeness += 0.2
        
        # Check RCA includes causality
        has_causality = any(
            re.search(pattern, diagnosis.root_cause, re.IGNORECASE)
            for pattern in self.EXPECTED_RCA_COMPONENTS[2:3]
        )
        if has_causality:
            rca_completeness += 0.2
        
        # Map completeness to status
        if rca_completeness >= 0.8:
            status = ConstraintStatus.PASSED
            score = rca_completeness
        elif rca_completeness >= 0.5:
            status = ConstraintStatus.WARNING
            score = rca_completeness
        else:
            status = ConstraintStatus.FAILED
            score = rca_completeness
        
        message = f"RCA completeness: {rca_completeness:.0%}"
        
        return ConstraintCheckResult(
            constraint_name=self.name,
            status=status,
            level=self.level,
            message=message,
            violations=violations,
            score=score
        )


class SolutionFeasibility(ConstraintChecker):
    """Validates proposed solution is feasible and actionable."""
    
    def __init__(self):
        super().__init__("Solution Feasibility", ConstraintLevel.HIGH)
    
    async def check(self, diagnosis: ExpertDiagnosisOutput) -> ConstraintCheckResult:
        """Check solution is actionable and feasible."""
        violations = []
        feasibility_score = 0.0
        
        # Check solution has specific commands
        has_commands = bool(diagnosis.recovery_commands)
        if has_commands and len(diagnosis.recovery_commands) > 0:
            feasibility_score += 0.4
        else:
            violations.append(ConstraintViolation(
                constraint_name=self.name,
                level=ConstraintLevel.HIGH,
                message="No recovery commands in solution",
                evidence="recovery_commands is empty",
                suggestion="Include specific CLI commands to execute (e.g., 'no shutdown')"
            ))
        
        # Check solution mentions verification
        if diagnosis.verification_steps and len(diagnosis.verification_steps) > 0:
            feasibility_score += 0.3
        else:
            violations.append(ConstraintViolation(
                constraint_name=self.name,
                level=ConstraintLevel.MEDIUM,
                message="No verification steps provided",
                evidence="verification_steps is empty",
                suggestion="Include commands to verify the fix worked"
            ))
        
        # Check for generic solutions
        generic_words = ['fix', 'problem', 'issue', 'configure', 'check']
        solution_lower = diagnosis.solution.lower()
        generic_count = sum(1 for word in generic_words if word in solution_lower)
        
        if generic_count > 2:
            violations.append(ConstraintViolation(
                constraint_name=self.name,
                level=ConstraintLevel.MEDIUM,
                message=f"Solution too generic: uses {generic_count} generic terms",
                evidence=f"Found: {', '.join(w for w in generic_words if w in solution_lower)}",
                suggestion="Use specific protocol/interface names instead of generic terms"
            ))
        else:
            feasibility_score += 0.3
        
        # Map to status
        if feasibility_score >= 0.7:
            status = ConstraintStatus.PASSED
            score = feasibility_score
        elif feasibility_score >= 0.4:
            status = ConstraintStatus.WARNING
            score = feasibility_score
        else:
            status = ConstraintStatus.FAILED
            score = feasibility_score
        
        message = f"Solution feasibility: {feasibility_score:.0%}"
        
        return ConstraintCheckResult(
            constraint_name=self.name,
            status=status,
            level=self.level,
            message=message,
            violations=violations,
            score=score
        )


@dataclass
class ValidationReport:
    """Complete validation report for a diagnosis."""
    scenario_id: str
    diagnosis: ExpertDiagnosisOutput
    constraint_results: List[ConstraintCheckResult]
    overall_status: ConstraintStatus
    overall_score: float
    critical_failures: List[str] = field(default_factory=list)
    
    def passed(self) -> bool:
        """Check if all critical constraints passed."""
        return self.overall_status != ConstraintStatus.FAILED
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "scenario_id": self.scenario_id,
            "overall_status": self.overall_status.value,
            "overall_score": self.overall_score,
            "critical_failures": self.critical_failures,
            "constraint_results": [cr.to_dict() for cr in self.constraint_results],
            "diagnosis": self.diagnosis.to_dict(),
        }
    
    def summary(self) -> str:
        """Get human-readable summary."""
        lines = [
            f"Validation Report for {self.scenario_id}",
            f"{'=' * 60}",
            f"Overall Status: {self.overall_status.value.upper()}",
            f"Overall Score: {self.overall_score:.1%}",
            f"",
            "Constraint Results:",
        ]
        
        for result in self.constraint_results:
            status_icon = "✅" if result.passed() else "❌" if result.critical_failure() else "⚠️"
            lines.append(f"  {status_icon} {result.constraint_name}: {result.message}")
            if result.violations:
                for violation in result.violations:
                    lines.append(f"      • {violation.message}")
        
        if self.critical_failures:
            lines.append(f"")
            lines.append("Critical Failures:")
            for failure in self.critical_failures:
                lines.append(f"  ❌ {failure}")
        
        return "\n".join(lines)


class ExpertConstraintsValidator:
    """Main validator orchestrating all constraint checks."""
    
    def __init__(self, custom_checkers: Optional[List[ConstraintChecker]] = None):
        """
        Initialize validator with constraint checkers.
        
        Args:
            custom_checkers: Optional list of custom ConstraintChecker instances
        """
        self.checkers: Dict[str, ConstraintChecker] = {}
        
        # Add default checkers
        default_checkers = [
            OutputCompleteness(),
            ConfidenceScoreValidator(min_score=0.80),
            HallucinationDetector(vague_term_threshold=0.05),
            RCACompleteness(),
            SolutionFeasibility(),
        ]
        
        for checker in default_checkers:
            self.add_checker(checker)
        
        # Add custom checkers
        if custom_checkers:
            for checker in custom_checkers:
                self.add_checker(checker)
    
    def add_checker(self, checker: ConstraintChecker) -> None:
        """Register a constraint checker."""
        self.checkers[checker.name] = checker
    
    async def validate(self, diagnosis: ExpertDiagnosisOutput) -> ValidationReport:
        """
        Run all constraint checks against a diagnosis.
        
        Args:
            diagnosis: The diagnosis output to validate
            
        Returns:
            Complete validation report
        """
        results = []
        critical_failures = []
        
        # Run all constraint checks
        for checker in self.checkers.values():
            result = await checker.check(diagnosis)
            results.append(result)
            
            if result.critical_failure():
                critical_failures.append(f"{result.constraint_name}: {result.message}")
        
        # Calculate overall score
        if results:
            overall_score = sum(r.score for r in results) / len(results)
        else:
            overall_score = 0.0
        
        # Determine overall status
        critical_failures_exist = any(
            r.critical_failure() for r in results
        )
        if critical_failures_exist:
            overall_status = ConstraintStatus.FAILED
        elif any(r.status == ConstraintStatus.WARNING for r in results):
            overall_status = ConstraintStatus.WARNING
        else:
            overall_status = ConstraintStatus.PASSED
        
        return ValidationReport(
            scenario_id=diagnosis.scenario_id,
            diagnosis=diagnosis,
            constraint_results=results,
            overall_status=overall_status,
            overall_score=overall_score,
            critical_failures=critical_failures,
        )
    
    async def validate_batch(
        self, diagnoses: List[ExpertDiagnosisOutput]
    ) -> Dict[str, ValidationReport]:
        """
        Validate multiple diagnoses.
        
        Args:
            diagnoses: List of diagnosis outputs
            
        Returns:
            Dictionary mapping scenario_id to ValidationReport
        """
        reports = {}
        for diagnosis in diagnoses:
            report = await self.validate(diagnosis)
            reports[diagnosis.scenario_id] = report
        
        return reports


# Convenience function for quick validation
async def validate_diagnosis(diagnosis: ExpertDiagnosisOutput) -> ValidationReport:
    """
    Quickly validate a diagnosis using default constraints.
    
    Args:
        diagnosis: The diagnosis to validate
        
    Returns:
        Validation report
    """
    validator = ExpertConstraintsValidator()
    return await validator.validate(diagnosis)
