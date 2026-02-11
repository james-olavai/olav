"""
Data Models for TextFSM Interactive Agent

Structured data types for each workflow step.
"""

from dataclasses import dataclass, field
from typing import Any, Literal
from datetime import datetime


@dataclass
class FieldDefinition:
    """Represents a single data field to extract."""
    
    name: str
    type: Literal["string", "integer", "list", "nested"]
    mandatory: bool = True
    description: str = ""
    regex_hint: str = ""
    examples: list[str] = field(default_factory=list)


@dataclass
class AnalysisResult:
    """Result of LLM analyzing command output structure."""
    
    command_name: str
    platform: str
    raw_output: str
    
    # Analysis results
    detected_fields: list[FieldDefinition]
    field_relationships: dict[str, str]  # e.g., {"Neighbors": "1-N with State"}
    extraction_strategy: str  # e.g., "column-based", "regex-based"
    confidence: float  # 0-1
    
    analysis_timestamp: datetime = field(default_factory=datetime.now)
    
    def to_display(self) -> str:
        """Format for user display."""
        fields_str = "\n".join(f"  ✓ {f.name} ({f.type})" for f in self.detected_fields)
        return f"""
Analysis Result:
  Command: {self.command_name}
  Platform: {self.platform}
  Confidence: {self.confidence:.1%}
  
Detected Fields:
{fields_str}

Strategy: {self.extraction_strategy}
"""


@dataclass
class ApprovalResult:
    """User's decision on analyzed fields."""
    
    analysis_result: AnalysisResult
    
    # User decisions
    approved_fields: list[FieldDefinition]  # Can be added, removed, or modified
    rejected_fields: list[str]              # Field names to skip
    additional_requirements: str = ""       # User notes
    
    approval_timestamp: datetime = field(default_factory=datetime.now)
    approved_by: str = "user"
    
    def validation_status(self) -> dict[str, Any]:
        """Check if approval is valid."""
        return {
            "num_fields": len(self.approved_fields),
            "valid_range": 3 <= len(self.approved_fields) <= 20,
            "has_mandatory": any(f.mandatory for f in self.approved_fields),
        }


@dataclass
class GenerationMetrics:
    """Metrics for template generation quality."""
    
    parse_success_rate: float  # 0-1
    value_coverage: float      # 0-1 (% of output matched)
    regex_accuracy: float      # 0-1 (% of patterns correct)
    state_completeness: float  # 0-1 (state machine completeness)
    
    overall_score: float = field(default=0.0)
    quality_tier: Literal["invalid", "minimal", "partial", "good", "excellent"] = "minimal"
    
    def __post_init__(self):
        """Calculate overall score."""
        weights = {
            "parse_success": 0.4,
            "value_coverage": 0.3,
            "regex_accuracy": 0.2,
            "state_completeness": 0.1,
        }
        self.overall_score = (
            self.parse_success_rate * weights["parse_success"] +
            self.value_coverage * weights["value_coverage"] +
            self.regex_accuracy * weights["regex_accuracy"] +
            self.state_completeness * weights["state_completeness"]
        )
        
        if self.overall_score >= 0.9:
            self.quality_tier = "excellent"
        elif self.overall_score >= 0.8:
            self.quality_tier = "good"
        elif self.overall_score >= 0.6:
            self.quality_tier = "partial"
        elif self.overall_score >= 0.3:
            self.quality_tier = "minimal"
        else:
            self.quality_tier = "invalid"


@dataclass
class GenerationResult:
    """Result of a single template generation attempt."""
    
    template_content: str
    iteration: int
    
    metrics: GenerationMetrics
    errors: list[str] = field(default_factory=list)
    regex_patterns: dict[str, str] = field(default_factory=dict)
    test_sample_results: dict[str, Any] = field(default_factory=dict)
    
    timestamp: datetime = field(default_factory=datetime.now)
    
    def is_success(self) -> bool:
        """Check if this result meets success threshold."""
        return self.metrics.parse_success_rate >= 0.8


@dataclass
class TemplateMetadata:
    """Metadata for saved template."""
    
    command_name: str
    platform: str
    filename: str
    file_path: str
    
    # Generation info
    generated_by: str = "deepagents_interactive"
    generation_method: Literal["auto", "guided", "manual"] = "guided"
    success_rate: float = 0.0
    
    # User info
    user_approved_fields: list[str] = field(default_factory=list)
    user_notes: str = ""
    
    # Validation
    ntc_references_used: list[str] = field(default_factory=list)
    iterations_count: int = 0
    generation_time_seconds: float = 0.0
    
    created_timestamp: datetime = field(default_factory=datetime.now)
    last_tested: datetime = field(default_factory=datetime.now)
    
    version: str = "1.0"
    
    def to_json_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "command": self.command_name,
            "platform": self.platform,
            "filename": self.filename,
            "path": self.file_path,
            "generated_by": self.generated_by,
            "method": self.generation_method,
            "success_rate": self.success_rate,
            "user_approved_fields": self.user_approved_fields,
            "user_notes": self.user_notes,
            "ntc_references": self.ntc_references_used,
            "iterations": self.iterations_count,
            "generation_time": self.generation_time_seconds,
            "created": self.created_timestamp.isoformat(),
            "last_tested": self.last_tested.isoformat(),
            "version": self.version,
        }
    
    def to_dict(self) -> dict[str, Any]:
        """Alias for to_json_dict for compatibility."""
        return self.to_json_dict()
