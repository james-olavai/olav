"""
Configuration for TextFSM Interactive Agent

Centralized configuration with three-tier priority:
1. Environment variables (highest)
2. SKILL.md settings
3. Code defaults (lowest)

Ensures all hardcoded values are configurable and traceable.
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TextFSMConfig:
    """TextFSM Interactive Agent configuration.
    
    Configuration priority:
    1. Environment variables
    2. SKILL.md config dict
    3. Code defaults
    """
    
    # ==== Workflow Parameters ====
    max_iterations: int = int(os.getenv("TEXTFSM_MAX_ITERATIONS", "3"))
    success_threshold: float = float(os.getenv("TEXTFSM_SUCCESS_THRESHOLD", "0.80"))
    auto_approve_fields: bool = os.getenv("TEXTFSM_AUTO_APPROVE", "false").lower() == "true"
    approval_timeout: int = int(os.getenv("TEXTFSM_APPROVAL_TIMEOUT", "300"))
    
    # ==== Caching Configuration (Phase 3+ Optimization) ====
    enable_template_cache: bool = os.getenv("TEXTFSM_CACHE_ENABLED", "true").lower() == "true"
    enable_field_analysis_cache: bool = os.getenv("TEXTFSM_FIELD_CACHE_ENABLED", "false").lower() == "true"
    memory_cache_size: int = int(os.getenv("TEXTFSM_MEMORY_CACHE_SIZE", "100"))
    similarity_threshold: float = float(os.getenv("TEXTFSM_SIMILARITY_THRESHOLD", "0.85"))
    cache_ttl_days: int = int(os.getenv("TEXTFSM_CACHE_TTL_DAYS", "30"))
    track_cache_stats: bool = os.getenv("TEXTFSM_TRACK_CACHE_STATS", "true").lower() == "true"
    
    # ==== Quality Metrics Weights (must sum to 1.0) ====
    quality_weights: dict[str, float] = field(default_factory=lambda: {
        "parse_success": 0.4,
        "value_coverage": 0.3,
        "regex_accuracy": 0.2,
        "state_completeness": 0.1,
    })
    
    # ==== Quality Tier Thresholds ====
    tier_excellent: float = 0.90
    tier_good: float = 0.80
    tier_partial: float = 0.60
    
    # ==== Mock Metrics (for development/testing - Phase 4+ will use real values) ====
    mock_success_rate: float = 0.82
    mock_value_coverage: float = 0.90
    mock_regex_accuracy: float = 0.85
    mock_state_completeness: float = 0.80
    
    # ==== Timeouts (seconds) ====
    command_timeout: int = int(os.getenv("TEXTFSM_CMD_TIMEOUT", "30"))
    analysis_timeout: int = int(os.getenv("TEXTFSM_ANALYSIS_TIMEOUT", "60"))
    ntc_search_timeout: int = int(os.getenv("TEXTFSM_NTC_TIMEOUT", "30"))
    generation_timeout: int = int(os.getenv("TEXTFSM_GEN_TIMEOUT", "120"))
    test_timeout: int = int(os.getenv("TEXTFSM_TEST_TIMEOUT", "30"))
    
    # ==== Directories ====
    template_dir: str = os.getenv("TEXTFSM_TEMPLATE_DIR", ".olav/templates/custom")
    cache_db: str = os.getenv("TEXTFSM_CACHE_DB", ".olav/cache/semantic_cache.db")
    
    # ==== Feature Flags ====
    use_ntc_references: bool = os.getenv("TEXTFSM_USE_NTC", "true").lower() == "true"
    use_deepagents: bool = os.getenv("TEXTFSM_USE_DEEPAGENTS", "false").lower() == "true"
    
    # ==== LLM Configuration ====
    llm_provider: str = os.getenv("TEXTFSM_LLM_PROVIDER", "openrouter")
    llm_temperature: float = float(os.getenv("TEXTFSM_LLM_TEMPERATURE", "0.3"))
    llm_max_tokens: int = int(os.getenv("TEXTFSM_LLM_MAX_TOKENS", "4096"))
    llm_timeout: int = int(os.getenv("TEXTFSM_LLM_TIMEOUT", "120"))
    
    def __post_init__(self) -> None:
        """Initialize derived values and validate configuration."""
        # Ensure quality_weights is initialized
        if self.quality_weights is None:
            self.quality_weights = {
                "parse_success": 0.4,
                "value_coverage": 0.3,
                "regex_accuracy": 0.2,
                "state_completeness": 0.1,
            }
        
        # Validate weights sum to 1.0
        weight_sum = sum(self.quality_weights.values())
        if not (0.99 < weight_sum < 1.01):
            logger.warning(
                f"Quality weights sum to {weight_sum:.2f}, should be 1.0. "
                f"Normalizing..."
            )
            factor = 1.0 / weight_sum
            self.quality_weights = {
                k: v * factor for k, v in self.quality_weights.items()
            }
    
    @classmethod
    def from_skill(
        cls,
        skill_config: dict[str, Any] | None = None,
    ) -> "TextFSMConfig":
        """Create config from SKILL.md settings + env overrides.
        
        Configuration priority:
        1. Environment variables (highest)
        2. SKILL.md config dict (skill_config parameter)
        3. Code defaults (lowest)
        
        This allows SKILL.md to be the source of truth for business
        configuration, while environment variables can override for
        deployment-specific needs.
        
        Args:
            skill_config: Configuration dict from SKILL.md frontmatter
            
        Returns:
            TextFSMConfig instance with merged settings
        """
        if skill_config is None:
            skill_config = {}
        
        # Priority 1: Get from environment or SKILL.md defaults
        config_dict = {
            # Workflow
            "max_iterations": int(
                os.getenv(
                    "TEXTFSM_MAX_ITERATIONS",
                    str(skill_config.get("max_iterations", 3)),
                )
            ),
            "success_threshold": float(
                os.getenv(
                    "TEXTFSM_SUCCESS_THRESHOLD",
                    str(skill_config.get("success_threshold", "0.80")),
                )
            ),
            "auto_approve_fields": (
                os.getenv("TEXTFSM_AUTO_APPROVE", "").lower() == "true"
                or skill_config.get("auto_approve_fields", False)
            ),
            "approval_timeout": int(
                os.getenv(
                    "TEXTFSM_APPROVAL_TIMEOUT",
                    str(skill_config.get("approval_timeout", 300)),
                )
            ),
            # Paths
            "template_dir": os.getenv(
                "TEXTFSM_TEMPLATE_DIR",
                skill_config.get("template_dir", ".olav/templates/custom"),
            ),
            "cache_db": os.getenv(
                "TEXTFSM_CACHE_DB",
                skill_config.get("cache_db", ".olav/cache/semantic_cache.db"),
            ),
            # Features
            "use_ntc_references": (
                os.getenv("TEXTFSM_USE_NTC", "").lower() != "false"
                and skill_config.get("use_ntc_references", True)
            ),
        }
        
        # Caching configuration (from SKILL.md caching section)
        caching_config = skill_config.get("caching", {})
        config_dict.update({
            "enable_template_cache": (
                os.getenv("TEXTFSM_CACHE_ENABLED", "").lower() != "false"
                and caching_config.get("enable_template_cache", True)
            ),
            "enable_field_analysis_cache": (
                os.getenv("TEXTFSM_FIELD_CACHE_ENABLED", "").lower() == "true"
                or caching_config.get("enable_field_analysis_cache", False)
            ),
            "memory_cache_size": int(
                os.getenv(
                    "TEXTFSM_MEMORY_CACHE_SIZE",
                    str(caching_config.get("memory_cache_size", 100)),
                )
            ),
            "similarity_threshold": float(
                os.getenv(
                    "TEXTFSM_SIMILARITY_THRESHOLD",
                    str(caching_config.get("similarity_threshold", "0.85")),
                )
            ),
            "cache_ttl_days": int(
                os.getenv(
                    "TEXTFSM_CACHE_TTL_DAYS",
                    str(caching_config.get("cache_ttl_days", 30)),
                )
            ),
            "track_cache_stats": (
                os.getenv("TEXTFSM_TRACK_CACHE_STATS", "").lower() != "false"
                and caching_config.get("track_cache_stats", True)
            ),
        })
        
        # Timeout configuration (from SKILL.md timeouts section)
        timeouts_config = skill_config.get("timeouts", {})
        config_dict.update({
            "command_timeout": int(
                os.getenv(
                    "TEXTFSM_CMD_TIMEOUT",
                    str(timeouts_config.get("command_execution", 30)),
                )
            ),
            "analysis_timeout": int(
                os.getenv(
                    "TEXTFSM_ANALYSIS_TIMEOUT",
                    str(timeouts_config.get("field_analysis", 60)),
                )
            ),
            "ntc_search_timeout": int(
                os.getenv(
                    "TEXTFSM_NTC_TIMEOUT",
                    str(timeouts_config.get("ntc_search", 30)),
                )
            ),
            "generation_timeout": int(
                os.getenv(
                    "TEXTFSM_GEN_TIMEOUT",
                    str(timeouts_config.get("template_generation", 120)),
                )
            ),
            "test_timeout": int(
                os.getenv(
                    "TEXTFSM_TEST_TIMEOUT",
                    str(timeouts_config.get("template_testing", 30)),
                )
            ),
        })
        
        # LLM configuration (from SKILL.md llm_config section)
        llm_config = skill_config.get("llm_config", {})
        config_dict.update({
            "llm_provider": os.getenv(
                "TEXTFSM_LLM_PROVIDER",
                llm_config.get("provider", "openrouter"),
            ),
            "llm_temperature": float(
                os.getenv(
                    "TEXTFSM_LLM_TEMPERATURE",
                    str(llm_config.get("temperature", "0.3")),
                )
            ),
            "llm_max_tokens": int(
                os.getenv(
                    "TEXTFSM_LLM_MAX_TOKENS",
                    str(llm_config.get("max_tokens", "4096")),
                )
            ),
            "llm_timeout": int(
                os.getenv(
                    "TEXTFSM_LLM_TIMEOUT",
                    str(llm_config.get("timeout", "120")),
                )
            ),
        })
        
        logger.debug(
            f"Created config from SKILL.md: "
            f"cache={'enabled' if config_dict['enable_template_cache'] else 'disabled'}, "
            f"max_iterations={config_dict['max_iterations']}, "
            f"threshold={config_dict['success_threshold']}"
        )
        
        return cls(**config_dict)


# Global singleton instance
_config: TextFSMConfig | None = None


def get_config() -> TextFSMConfig:
    """Get global configuration instance.
    
    Creates a new instance on first call using code defaults.
    Use set_config() to provide custom configuration.
    
    Returns:
        Global TextFSMConfig instance
    """
    global _config
    if _config is None:
        _config = TextFSMConfig()
    return _config


def set_config(config: TextFSMConfig) -> None:
    """Set global configuration instance (for testing).
    
    Args:
        config: TextFSMConfig instance to use globally
    """
    global _config
    _config = config


def load_config_from_skill(skill_config: dict[str, Any] | None = None) -> TextFSMConfig:
    """Create and set global config from SKILL.md settings.
    
    Configuration priority:
    1. Environment variables
    2. SKILL.md config dict
    3. Code defaults
    
    This is typically called during agent initialization to load
    configuration from the SKILL.md file.
    
    Args:
        skill_config: Configuration dict loaded from SKILL.md frontmatter
        
    Returns:
        Global TextFSMConfig instance (also sets as global)
    """
    global _config
    _config = TextFSMConfig.from_skill(skill_config)
    return _config
