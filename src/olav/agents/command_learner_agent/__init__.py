"""
Command Learner Agent - Complete Redesign

A user-interactive DeepAgents-based agent for automatic TextFSM template generation.

Features:
  - Step 1: Execute command on target host
  - Step 2: Auto-analyze required data fields
  - Step 3: User approval/modification workflow
  - Step 4: Fetch NTC-template references
  - Step 5: ReAct generation loop (test & iterate)
  - Step 6: Save template to custom directory

Architecture:
  ├─ deepagent.py: DeepAgents Plan Agent
  ├─ orchestrator.py: User interaction orchestration
  ├─ tools.py: Tool functions (execute, analyze, test, generate)
  ├─ models.py: Data models (AnalysisResult, ApprovalResult, etc.)
  └─ cleanup_checklist.py: Migration & cleanup verification

Version: v1.0.0 (2026-02-08 - Renamed from TextFSM Interactive)
"""

__version__ = "1.0.0"
__author__ = "Network AI Team"

from .config import TextFSMConfig, get_config, set_config, load_config_from_skill
from .deepagent import CommandLearnerAgent
from .orchestrator import CommandLearnerOrchestrator
from .template_cache import TextFSMTemplateCache, CachedTemplate, get_template_cache, set_template_cache
from .field_analysis_cache import FieldAnalysisCache, FieldAnalysisResult, get_field_analysis_cache, set_field_analysis_cache
from .models import (
    AnalysisResult,
    ApprovalResult,
    GenerationResult,
    GenerationMetrics,
    TemplateMetadata,
    FieldDefinition,
)
from .cleanup_checklist import CommandLearnerCleanupChecklist

__all__ = [
    "TextFSMConfig",
    "get_config",
    "set_config",
    "load_config_from_skill",
    "TextFSMTemplateCache",
    "CachedTemplate",
    "get_template_cache",
    "set_template_cache",
    "FieldAnalysisCache",
    "FieldAnalysisResult",
    "get_field_analysis_cache",
    "set_field_analysis_cache",
    "CommandLearnerAgent",
    "CommandLearnerOrchestrator",
    "AnalysisResult",
    "ApprovalResult",
    "GenerationResult",
    "GenerationMetrics",
    "TemplateMetadata",
    "FieldDefinition",
    "CommandLearnerCleanupChecklist",
]

# Backward compatibility aliases for legacy code
TextFSMInteractiveAgent = CommandLearnerAgent
TextFSMWorkflowOrchestrator = CommandLearnerOrchestrator
