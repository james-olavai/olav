"""
OLAV v0.8 Configuration Settings

Three-layer configuration architecture (per DESIGN_V0.81.md §C.1-C.2):
- Layer 1: .env (sensitive + connection) - human-maintained, never commit to git
- Layer 2: .olav/settings.json (behavior + preferences) - user-editable, agent-readable
- Layer 3: This file (loader + defaults) - code implementation

Configuration Priority (high to low):
1. Environment variables (export LLM_MODEL_NAME=gpt-4o)
2. .env file (LLM_MODEL_NAME=gpt-4-turbo)
3. .olav/settings.json ({"model": "gpt-4o"})
4. Code defaults (llm_model_name: str = "gpt-4-turbo")

True Source of Truth:
- .env: Sensitive configuration (API Keys, passwords, tokens)
- .olav/settings.json: Agent behavior (model, temperature, routing, HITL)
- This file: Code defaults and validation only (NOT true source)
"""

import json
import os

# =============================================================================
# Project Paths
# =============================================================================
# Use absolute path to find project root
# Navigate up: config/ -> project_root/
import os as _os
import re
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_this_file = _os.path.abspath(__file__)
_config_dir = _os.path.dirname(_this_file)
_project_root = _os.path.dirname(_config_dir)

PROJECT_ROOT = Path(_project_root)
ENV_FILE = PROJECT_ROOT / ".env"
OLAV_DIR = PROJECT_ROOT / ".olav"

# Agent directory configuration (can be .olav, .claude, .cursor, etc.)
# Defaults to .olav for backward compatibility
# Can be overridden via AGENT_DIR environment variable
_agent_dir_name = os.getenv("AGENT_DIR", ".olav")
AGENT_DIR = PROJECT_ROOT / _agent_dir_name

# Load .env file first
load_dotenv(ENV_FILE)

# Ensure environment variables are properly set for pydantic-settings
# This fixes issues where old values might be cached
if not os.getenv("LLM_PROVIDER"):
    os.environ["LLM_PROVIDER"] = "openai"
if not os.getenv("OLAV_MODE"):
    os.environ["OLAV_MODE"] = "QuickTest"


# =============================================================================
# Nested Configuration Classes (Pydantic v2)
# =============================================================================


class AgentSettings(BaseSettings):
    """Agent and Middleware Configuration"""

    # Orchestrator LLM Configuration
    orchestrator_model: str = Field(
        default="",
        description="LLM model for orchestrator (empty = use global LLM_MODEL_NAME)",
    )
    orchestrator_base_url: str = Field(
        default="",
        description="Base URL for orchestrator LLM (empty = use global LLM_BASE_URL)",
    )
    orchestrator_api_key: str = Field(
        default="",
        description="API key for orchestrator LLM (empty = use global LLM_API_KEY)",
    )

    # Analyzer LLM Configuration
    analyzer_model: str = Field(
        default="",
        description="LLM model for analyzer agent (empty = use global LLM_MODEL_NAME)",
    )
    analyzer_base_url: str = Field(
        default="",
        description="Base URL for analyzer LLM (empty = use global LLM_BASE_URL)",
    )
    analyzer_api_key: str = Field(
        default="",
        description="API key for analyzer LLM (empty = use global LLM_API_KEY)",
    )

    # Guard LLM Configuration
    guard_model: str = Field(
        default="",
        description="LLM model for guard intent filtering (empty = use global LLM_MODEL_NAME)",
    )
    guard_base_url: str = Field(
        default="",
        description="Base URL for guard LLM (empty = use global LLM_BASE_URL)",
    )
    guard_api_key: str = Field(
        default="",
        description="API key for guard LLM (empty = use global LLM_API_KEY)",
    )

    # TextFSM Agent LLM Configuration
    textfsm_model: str = Field(
        default="",
        description="LLM model for TextFSM template generation (empty = use global LLM_MODEL_NAME)",
    )
    textfsm_base_url: str = Field(
        default="",
        description="Base URL for TextFSM LLM (empty = use global LLM_BASE_URL)",
    )
    textfsm_api_key: str = Field(
        default="",
        description="API key for TextFSM LLM (empty = use global LLM_API_KEY)",
    )

    # LLM Interface (Map-Reduce) Configuration
    llm_interface_model: str = Field(
        default="",
        description="LLM model for LLMInterface (empty = use global LLM_MODEL_NAME)",
    )
    llm_interface_base_url: str = Field(
        default="",
        description="Base URL for LLM Interface (empty = use global LLM_BASE_URL)",
    )
    llm_interface_api_key: str = Field(
        default="",
        description="API key for LLM Interface (empty = use global LLM_API_KEY)",
    )

    # Summarization Middleware Configuration
    enable_summarization: bool = Field(
        default=False,
        description="Enable conversation summarization middleware",
    )
    summarization_model: str = Field(
        default="",
        description="LLM model for summarization (empty = use global LLM_MODEL_NAME)",
    )
    summarization_base_url: str = Field(
        default="",
        description="Base URL for summarization LLM (empty = use global LLM_BASE_URL)",
    )
    summarization_api_key: str = Field(
        default="",
        description="API key for summarization LLM (empty = use global LLM_API_KEY)",
    )
    summarization_trigger_tokens: int = Field(
        default=50000,
        ge=1000,
        le=1000000,
        description="Token count to trigger summarization",
    )
    summarization_keep_messages: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Number of recent messages to keep after summarization",
    )

    # Guard Layer Configuration (v0.12.0+)
    enable_guard_routing: bool = Field(
        default=True,
        description="Enable Guard layer for query classification and fast routing (default: True for v0.12.0+)",
    )
    guard_cache_ttl: int = Field(
        default=3600,
        ge=60,
        le=86400,
        description="Cache TTL for Guard classifications in seconds (default: 1 hour)",
    )
    guard_confidence_threshold: float = Field(
        default=0.85,
        ge=0.5,
        le=0.99,
        description="Confidence threshold for direct routing (>=0.85 direct, <0.85 to Orchestrator)",
    )
    guard_enable_multi_agent_detection: bool = Field(
        default=True,
        description="Enable MULTI_AGENT route detection (for future NetBox, CMDB integration)",
    )
    guard_rules_overrides: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Override Guard classification patterns (e.g. {'simple_indicators': [...], 'cli_indicators': [...]}). "
                    "Leave empty to use SKILL.md rules. Example in .olav/settings.json shows how to customize.",
    )
    guard_rules_file: str = Field(
        default="",
        description="Path to custom Guard rules YAML file (empty = use SKILL.md). "
                    "Can also be set via OLAV_GUARD_RULES_FILE environment variable.",
    )

    def get_agent_config(
        self, agent_name: str, global_settings: "Settings"
    ) -> dict[str, str]:
        """Get agent-specific configuration with global fallback.

        Args:
            agent_name: Agent name (orchestrator, analyzer, guard, textfsm, llm_interface, summarization)
            global_settings: Global settings object for fallback

        Returns:
            Dict with model, base_url, api_key (falls back to global if agent-specific is empty)
        """
        agent_prefix = agent_name.lower()

        model = getattr(self, f"{agent_prefix}_model", "") or global_settings.llm_model_name
        base_url = getattr(self, f"{agent_prefix}_base_url", "") or global_settings.llm_base_url
        api_key = getattr(self, f"{agent_prefix}_api_key", "") or global_settings.llm_api_key

        return {
            "model": model,
            "base_url": base_url,
            "api_key": api_key,
        }


class DatabaseSettings(BaseSettings):
    """数据库配置 (v0.10.2+ 支持配置分层)"""

    main_db: Path = Field(
        default=Path(".olav/db/olav.duckdb"),
        description="主数据库路径 (设备、接口、拓扑等所有数据)",
    )

    test_db: Path | None = Field(
        default=None,
        description="测试数据库路径，未设置时使用 main_db",
    )

    read_only: bool = Field(
        default=True,
        description="数据库只读模式 (query 操作建议为 True)",
    )

    connection_timeout: int = Field(
        default=30,
        ge=1,
        le=300,
        description="数据库连接超时 (秒)",
    )

    query_timeout: int = Field(
        default=60,
        ge=1,
        le=600,
        description="SQL 查询超时 (秒)",
    )


class GuardSettings(BaseSettings):
    """Guard Intent Filter Configuration"""

    enabled: bool = Field(default=True, description="Enable Guard filtering (Tier 0/0.5/2)")
    strict_mode: bool = Field(
        default=False, description="Strict mode: only allow explicit network operations requests"
    )
    # Tier 0: Static blacklist
    check_blacklist: bool = Field(default=True, description="Enable static blacklist check")
    # Tier 0.5: Dynamic rejection cache (learning mechanism)
    enable_dynamic_learning: bool = Field(
        default=True, description="Enable dynamic learning for non-network queries"
    )
    # Tier 2: Network relevance check
    check_network_relevance: bool = Field(
        default=True, description="Enable LLM-based network relevance check"
    )
    # Performance tuning
    relevance_check_timeout: float = Field(
        default=1.0, ge=0.1, le=5.0, description="Network relevance check timeout (seconds)"
    )


class RoutingSettings(BaseSettings):
    """Skill Routing Configuration"""

    confidence_threshold: float = Field(
        default=0.6, ge=0.0, le=1.0, description="Skill matching confidence threshold"
    )
    fallback_skill: str = Field(default="quick-query", description="Fallback target Skill ID")

    # Cache confidence settings (场景化配置)
    # 主路由 / Orchestrator: fuzzy 模式（容错）
    cache_match_mode: Literal["exact", "fuzzy", "semantic"] = Field(
        default="fuzzy",
        description="Cache matching mode: exact (hash), fuzzy (threshold), semantic (embedding)",
    )
    cache_confidence_threshold: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Cache match confidence threshold (for fuzzy/semantic mode)",
    )

    # SubAgent 专用配置（精确匹配）
    query_agent_cache_mode: Literal["exact", "fuzzy"] = Field(
        default="exact", description="Query SubAgent cache mode (must be exact)"
    )
    cli_agent_cache_mode: Literal["exact", "fuzzy"] = Field(
        default="exact", description="CLI SubAgent cache mode (must be exact)"
    )

    cache_ttl_hours: int = Field(
        default=168, ge=1, le=8760, description="Cache time-to-live in hours (default: 7 days)"
    )


class HITLSettings(BaseSettings):
    """Human-in-the-Loop Configuration"""

    require_approval_for_write: bool = Field(
        default=True, description="Require approval for write operations"
    )
    require_approval_for_skill_update: bool = Field(
        default=True, description="Require approval for Skill/Knowledge updates"
    )
    approval_timeout_seconds: int = Field(
        default=300, ge=10, le=3600, description="Approval timeout in seconds"
    )


class ExecutionSettings(BaseSettings):
    """Command Execution Configuration"""

    use_textfsm: bool = Field(default=True, description="Use TextFSM to parse command output")
    textfsm_fallback_to_raw: bool = Field(
        default=True, description="Fallback to raw text if TextFSM parsing fails"
    )
    textfsm_template_dir: Path = Field(
        default=Path(".olav/templates"),
        description="TextFSM template directory path (relative to project root)"
    )
    enable_token_statistics: bool = Field(default=True, description="Enable token statistics")

    # Task 11.4: Centralize Timeouts and Concurrency
    # Default timeout for network device commands (in seconds)
    timeout: int = Field(default=30, ge=5, le=300, description="Network command timeout in seconds")

    # Query timeout for CLI interactive mode (in seconds)
    query_timeout: int = Field(
        default=180, ge=30, le=600, description="CLI query timeout in seconds (for complex queries)"
    )

    # Nornir concurrency (num_workers for parallel execution)
    concurrency: int = Field(
        default=10, ge=1, le=100, description="Number of parallel workers for network operations"
    )


class DiagnosisSettings(BaseSettings):
    """Diagnosis Module Configuration"""

    macro_max_confidence: float = Field(
        default=0.7, ge=0.0, le=1.0, description="Maximum confidence threshold for macro analysis"
    )
    micro_target_confidence: float = Field(
        default=0.9, ge=0.0, le=1.0, description="Target confidence for micro analysis"
    )
    max_diagnosis_iterations: int = Field(
        default=5, ge=1, le=20, description="Maximum diagnosis iterations per round"
    )
    require_approval_for_micro_analysis: bool = Field(
        default=True, description="Require approval for micro analysis"
    )
    auto_approve_if_confidence_below: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Auto-approve if confidence is below this threshold",
    )
    enable_web_search: bool = Field(
        default=True, description="Enable web search during diagnosis (fallback mode)"
    )
    web_search_fallback_only: bool = Field(
        default=True, description="Web search only enabled when local knowledge base has no results"
    )
    web_search_max_results: int = Field(
        default=3, ge=1, le=10, description="Maximum results per web search"
    )
    web_search_timeout: int = Field(
        default=10, ge=5, le=30, description="Web search timeout in seconds"
    )


class LoggingSettings(BaseSettings):
    """Logging Configuration"""

    level: str = Field(default="INFO", description="Logging level")
    audit_enabled: bool = Field(default=True, description="Enable audit logging")


class ThresholdSettings(BaseSettings):
    """Threshold Detection Configuration.

    Migrated from ThresholdAgent (v0.9.8) to align with OLAV design principles.

    Configuration structure:
    - defaults: Default threshold values for all metrics
    - metrics: Metric-specific threshold configurations
    - devices: Device-specific threshold overrides

    Threshold strategies:
    - fixed: Static thresholds (warning/critical values)
    - statistical: Mean + N*std deviation
    - percentile: Percentile-based thresholds
    """

    model_config = SettingsConfigDict(env_prefix="THRESHOLD_")

    # Default thresholds (fallback)
    default_warning: float = Field(
        default=80.0,
        ge=0.0,
        le=100.0,
        description="Default warning threshold (percentage)",
    )
    default_critical: float = Field(
        default=90.0,
        ge=0.0,
        le=100.0,
        description="Default critical threshold (percentage)",
    )

    # Strategy defaults
    default_strategy: Literal["fixed", "statistical", "percentile"] = Field(
        default="fixed",
        description="Default threshold strategy",
    )
    warning_sigma: float = Field(
        default=2.0,
        ge=0.1,
        le=10.0,
        description="Warning threshold sigma multiplier (statistical strategy)",
    )
    critical_sigma: float = Field(
        default=3.0,
        ge=0.1,
        le=10.0,
        description="Critical threshold sigma multiplier (statistical strategy)",
    )

    # Metric-specific thresholds (can be extended via .olav/settings.json)
    # Example format in settings.json:
    # {
    #   "threshold": {
    #     "metrics": {
    #       "cpu_5sec": {"strategy": "fixed", "warning": 75, "critical": 85}
    #     }
    #   }
    # }


class FeatureFlagSettings(BaseSettings):
    """Feature Flag Configuration (v0.12.0+)
    
    Supports gradual rollout and A/B testing:
    - enable/disable features at runtime
    - percentage-based rollout (0-100%)
    - user segment support (all, admin, internal, beta)
    - metrics collection for comparison
    
    Example .olav/settings.json:
    {
      "feature_flags": {
        "guard_routing": {
          "enabled": true,
          "rollout_percentage": 25,
          "rollout_user_segment": "internal",
          "metrics_enabled": true
        }
      }
    }
    """

    guard_routing: dict[str, Any] = Field(
        default_factory=lambda: {
            "enabled": True,
            "rollout_percentage": 100,
            "rollout_user_segment": "all",
            "metrics_enabled": True,
        },
        description="Guard routing feature flag (enable/disable, rollout %, user segment)",
    )
    
    metrics_collection: dict[str, Any] = Field(
        default_factory=lambda: {
            "enabled": True,
            "rollout_percentage": 100,
            "rollout_user_segment": "all",
            "metrics_enabled": True,
        },
        description="Metrics collection feature flag",
    )


class CacheSettings(BaseSettings):
    """Cache Management Configuration (v0.10.1)"""

    # LLM call cache TTL (olav_cache.db - SQLite)
    # 0 = infinite (no expiration), > 0 = hours
    llm_cache_ttl_hours: int = Field(
        default=0,
        ge=0,
        le=8760,
        description="LLM call cache lifetime in hours (0 = infinite, default: 0)",
    )

    # Query result cache TTL (DuckDB only - in-memory by default)
    query_cache_ttl_hours: int = Field(
        default=24,
        ge=0,
        le=8760,
        description="Query result cache lifetime in hours (0 = infinite, default: 24)",
    )

    # Auto-cleanup expired cache entries
    cache_cleanup_enabled: bool = Field(
        default=True,
        description="Enable automatic cache cleanup of expired entries",
    )
    cache_cleanup_interval_hours: int = Field(
        default=24,
        ge=1,
        le=168,
        description="Cache cleanup interval in hours (default: 24 = daily)",
    )


class SyncSettings(BaseSettings):
    """Snapshot Synchronization Configuration"""

    command_mode: Literal["whitelist", "blacklist", "hybrid"] = Field(
        default="hybrid",
        description="Execution mode: whitelist (strict), blacklist (permissive), or hybrid (recommended)",
    )
    whitelist_file: str = Field(
        default=".olav/config/command_whitelist.yaml",
        description="Path to command whitelist YAML",
    )
    command_mode_config: str = Field(
        default=".olav/skills/guard/config/command_mode.yaml",
        description="Path to command mode configuration YAML (v0.10.1: moved to guard skill)",
    )


# =============================================================================
# Settings Classes
# =============================================================================


class Settings(BaseSettings):
    """OLAV Configuration Settings - Three-Layer Architecture

    This is NOT the true source of truth, but a loader with defaults:
    - Layer 1 (.env): True source for sensitive config (API Keys, passwords)
    - Layer 2 (.olav/settings.json): True source for agent behavior config
    - Layer 3 (this file): Code defaults and validation only

    Configuration Priority (high to low):
    1. Environment variables (export MY_VAR=value)
    2. .env file (MY_VAR=value)
    3. .olav/settings.json ({"myField": value})
    4. Code defaults (field: type = default_value)

    Supports three-layer configuration:
    - Environment variables (highest priority)
    - .olav/settings.json (Layer 2)
    - Default values (lowest priority)
    """

    model_config = SettingsConfigDict(
        # Don't use env_file since load_dotenv is called at module level
        # env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # =========================================================================
    # LLM Configuration
    # =========================================================================
    llm_provider: Literal["openai", "ollama", "azure", "xai", "anthropic"] = "openai"
    llm_api_key: str = ""
    llm_model_name: str = "gpt-4-turbo"
    llm_model_provider: str = ""  # Optional: explicit provider for create_deep_agent
    llm_base_url: str = ""
    llm_temperature: float = 0.1
    llm_max_tokens: int = 16000

    # =========================================================================
    # Skill Configuration (Phase C-1)
    # =========================================================================
    enabled_skills: list[str] = Field(
        default_factory=list, description="List of enabled Skill IDs (empty means all enabled)"
    )
    disabled_skills: list[str] = Field(
        default_factory=list, description="List of disabled Skill IDs"
    )

    # =========================================================================
    # Nested Configuration Objects (Phase C-1)
    # =========================================================================
    agent: AgentSettings = Field(
        default_factory=AgentSettings, description="Agent and middleware configuration"
    )
    guard: GuardSettings = Field(
        default_factory=GuardSettings, description="Guard filter configuration"
    )
    routing: RoutingSettings = Field(
        default_factory=RoutingSettings, description="Skill routing configuration"
    )
    hitl: HITLSettings = Field(
        default_factory=HITLSettings, description="HITL approval configuration"
    )
    diagnosis: DiagnosisSettings = Field(
        default_factory=DiagnosisSettings, description="Diagnosis configuration"
    )
    execution: ExecutionSettings = Field(
        default_factory=ExecutionSettings, description="Command execution configuration"
    )
    threshold: ThresholdSettings = Field(
        default_factory=ThresholdSettings, description="Threshold detection configuration"
    )
    logging_settings: LoggingSettings = Field(
        default_factory=LoggingSettings, description="Logging configuration"
    )
    sync: SyncSettings = Field(
        default_factory=SyncSettings, description="Synchronization configuration"
    )
    cache: CacheSettings = Field(
        default_factory=CacheSettings, description="Cache management configuration"
    )
    database: DatabaseSettings = Field(
        default_factory=DatabaseSettings, description="Database configuration (v0.10.2+)"
    )
    feature_flags: FeatureFlagSettings = Field(
        default_factory=FeatureFlagSettings, description="Feature flag configuration (v0.12.0+)"
    )

    # =========================================================================
    # Database Configuration
    # =========================================================================
    # NOTE: Database paths are now centralized in config/paths.py
    # - NETWORK_SNAPSHOT_PATH: Network snapshot data warehouse
    # - NETWORK_COMMANDS_PATH: Command whitelist registry
    # - KNOWLEDGE_PATH: RAG knowledge base
    #
    # Legacy fields removed (no longer used):
    # - duckdb_path, knowledge_db_path, checkpoint_db_path

    # =========================================================================
    # Agent Configuration (Claude Code Compatibility)
    # =========================================================================
    # Agent directory name (e.g., .olav, .claude, .cursor)
    agent_dir: str = ".olav"
    agent_name: str = "OLAV"

    # Skills format: "auto" (detect), "legacy" (flat files), "claude-code" (SKILL.md)
    skill_format: Literal["auto", "legacy", "claude-code"] = "auto"

    # NOTE: Checkpoint database path removed - now managed by DeepAgents runtime
    # Agent session persistence is handled by LangGraph's built-in checkpoint system

    # =========================================================================
    # Network Device Configuration
    # =========================================================================
    netbox_url: str = ""
    netbox_token: str = ""
    netbox_verify_ssl: bool = True
    netbox_device_tag: str = "olav-managed"

    device_username: str = "admin"
    device_password: str = ""
    device_enable_password: str = ""
    device_timeout: int = 30

    # =========================================================================
    # Network Execution Configuration
    # =========================================================================
    nornir_ssh_port: int = 22

    # NETCONF support planned for Phase 2+
    # netconf_port: int = 830  # Uncomment when NETCONF is needed

    # =========================================================================
    # Application Settings
    # =========================================================================
    # Use 'environment' field for runtime context (local/development/production)
    # Removed 'olav_mode' - this was v0.5 legacy; environment provides clearer semantics
    environment: Literal["local", "development", "production"] = "local"

    server_host: str = "0.0.0.0"  # noqa: S104
    server_port: int = 8000

    # =========================================================================
    # CLI Display Settings
    # =========================================================================
    # Display LLM thinking process during streaming output
    # When enabled: Shows "🤔 Thinking..." spinner and verbose thinking in verbose mode
    # When disabled: Only shows tool calls and final results
    display_thinking: bool = True

    # Logging
    log_level: str = "CRITICAL"

    # Network relevance guard - filters out non-network queries
    guard_enabled: bool = True

    # =========================================================================
    # Skill Routing Configuration (from .olav/settings.json)
    # =========================================================================
    routing_confidence_threshold: float = 0.6
    routing_fallback_skill: str = "quick-query"

    # =========================================================================
    # Diagnosis Configuration (from .olav/settings.json)
    # =========================================================================
    diagnosis_macro_max_confidence: float = 0.7
    diagnosis_micro_target_confidence: float = 0.9
    diagnosis_max_iterations: int = 5

    # =========================================================================
    # Security & Authentication
    # =========================================================================
    auth_disabled: bool = True
    token_max_age_hours: int = 24
    session_token_max_age_hours: int = 168
    olav_api_token: str = ""
    log_format: Literal["json", "text"] = "text"

    # HITL Configuration
    # Master switch for Human-in-the-Loop - set ENABLE_HITL=false in .env for yolo mode
    enable_hitl: bool = True  # Reads from ENABLE_HITL env var
    hitl_require_approval_for_write: bool = True

    # =========================================================================
    # Network Inspection Configuration (Moved from hardcoded values)
    # =========================================================================
    # Default Nornir group for network operations (snapshot, inspect)
    nornir_default_group: str = Field(
        default="test", description="Default Nornir group for network device operations"
    )

    # Device platform configuration
    device_default_platform: str = Field(
        default="cisco_ios", description="Default device platform when not specified"
    )
    device_supported_platforms: list[str] = Field(
        default_factory=lambda: ["cisco_ios", "arista_eos", "juniper", "h3c"],
        description="List of supported device platforms",
    )

    # Health score configuration (previously hardcoded)
    # Used for device health assessment and reporting
    health_score_config: dict[str, Any] = Field(
        default_factory=lambda: {
            "max_score": 100,
            "critical_weight": 20,
            "warning_weight": 5,
            "thresholds": {
                "healthy": 90,  # >= 90: HEALTHY
                "warning": 70,  # >= 70: WARNING
                "critical": 0,  # < 70: CRITICAL
            },
        },
        description="Health score calculation parameters",
    )
    hitl_require_approval_for_skill_update: bool = True
    hitl_approval_timeout_seconds: int = 300

    # =========================================================================
    # Optional Services (Removed in v0.8)
    # =========================================================================
    # OpenSearch, Redis, and other external services are NOT used in v0.8
    # All caching is done via DuckDB locally
    # These fields are kept for reference only and will be removed in future

    # =========================================================================
    # Development Settings
    # =========================================================================
    use_dynamic_router: bool = True
    langsmith_api_key: str = ""  # Optional for debugging
    langsmith_project: str = "olav-v0.8"
    debug: bool = False

    # =========================================================================
    # Validators (Removed)
    # =========================================================================
    # postgres_uri validator removed - not needed in v0.8
    # All database operations use DuckDB via duckdb_path

    def __init__(self, **kwargs: Any) -> None:
        """Initialize settings and apply .olav/settings.json overrides (Layer 2)."""
        super().__init__(**kwargs)
        self._apply_olav_settings()

    def _apply_olav_settings(self) -> None:
        """Layer 2: Load and apply settings from .olav/settings.json.

        Priority: Environment variable > .env > .olav/settings.json > code defaults
        """
        settings_path = OLAV_DIR / "settings.json"
        if not settings_path.exists():
            return

        try:
            olav_settings = json.loads(settings_path.read_text(encoding="utf-8"))

            # Map JSON paths to Python attributes (simple fields)
            simple_mapping = {
                "model": "llm_model_name",
                "temperature": "llm_temperature",
                "enabledSkills": "enabled_skills",
                "disabledSkills": "disabled_skills",
                "displayThinking": "display_thinking",
            }

            # Get environment variable names for checking if explicitly set
            env_var_map = {
                "llm_model_name": "LLM_MODEL_NAME",
                "llm_temperature": "LLM_TEMPERATURE",
                "llm_max_tokens": "LLM_MAX_TOKENS",
                "guard_enabled": "GUARD_ENABLED",
                "log_level": "LOG_LEVEL",
            }

            # Apply simple field mappings
            for json_key, attr_name in simple_mapping.items():
                if json_key in olav_settings:
                    value = olav_settings[json_key]
                    # Only override if NOT already set by environment variable
                    env_var = env_var_map.get(attr_name)
                    if env_var and os.getenv(env_var):
                        continue  # Environment variable takes priority
                    setattr(self, attr_name, value)

            # Apply nested configuration mappings
            nested_mapping = {
                "guard": ("guard", GuardSettings),
                "routing": ("routing", RoutingSettings),
                "hitl": ("hitl", HITLSettings),
                "diagnosis": ("diagnosis", DiagnosisSettings),
                "execution": ("execution", ExecutionSettings),
                "logging": ("logging_settings", LoggingSettings),
                "sync": ("sync", SyncSettings),
                "cache": ("cache", CacheSettings),
                "featureFlags": ("feature_flags", FeatureFlagSettings),
            }

            for json_key, (attr_name, cls) in nested_mapping.items():
                if json_key in olav_settings:
                    nested_data = olav_settings[json_key]
                    if isinstance(nested_data, dict):
                        try:
                            # Convert camelCase keys to snake_case for Pydantic
                            converted_data = {}
                            for k, v in nested_data.items():
                                snake_key = self._camel_to_snake(k)
                                converted_data[snake_key] = v
                            # Create new nested object from converted JSON data
                            nested_obj = cls(**converted_data)
                            setattr(self, attr_name, nested_obj)
                        except Exception:  # noqa: S110
                            # If validation fails, keep default
                            pass

        except (json.JSONDecodeError, OSError):
            # Silently ignore invalid settings.json - use defaults
            pass

    @staticmethod
    def _camel_to_snake(name: str) -> str:
        """Convert camelCase to snake_case."""
        s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
        return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()

    def to_dict(self) -> dict[str, Any]:
        """Export configuration as dictionary (for serialization)."""
        return self.model_dump()

    def save_to_json(self, path: Path | None = None) -> None:
        """Save configuration to JSON file.

        Args:
            path: Target file path. Defaults to .olav/settings.json
        """
        if path is None:
            path = OLAV_DIR / "settings.json"

        # Convert nested objects to dictionaries with camelCase keys
        def snake_to_camel(name: str) -> str:
            components = name.split("_")
            return components[0] + "".join(x.title() for x in components[1:])

        routing_dict = self.routing.model_dump()
        routing_dict_camel = {snake_to_camel(k): v for k, v in routing_dict.items()}

        hitl_dict = self.hitl.model_dump()
        hitl_dict_camel = {snake_to_camel(k): v for k, v in hitl_dict.items()}

        diagnosis_dict = self.diagnosis.model_dump()
        diagnosis_dict_camel = {snake_to_camel(k): v for k, v in diagnosis_dict.items()}

        cache_dict = self.cache.model_dump()
        cache_dict_camel = {snake_to_camel(k): v for k, v in cache_dict.items()}

        feature_flags_dict = self.feature_flags.model_dump()
        feature_flags_dict_camel = {snake_to_camel(k): v for k, v in feature_flags_dict.items()}

        data = {
            "model": self.llm_model_name,
            "temperature": self.llm_temperature,
            "enabledSkills": self.enabled_skills,
            "disabledSkills": self.disabled_skills,
            "guard": self.guard.model_dump(),
            "routing": routing_dict_camel,
            "hitl": hitl_dict_camel,
            "diagnosis": diagnosis_dict_camel,
            "logging": self.logging_settings.model_dump(),
            "sync": self.sync.model_dump(),
            "cache": cache_dict_camel,
            "featureFlags": feature_flags_dict_camel,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    @field_validator("llm_model_name")
    @classmethod
    def validate_model_name(cls, v: str) -> str:
        """Validate LLM model name."""
        if not v or len(v.strip()) == 0:
            raise ValueError("llm_model_name cannot be empty")
        return v.strip()

    @field_validator("llm_temperature")
    @classmethod
    def validate_temperature(cls, v: float) -> float:
        """Validate LLM temperature parameter."""
        if not (0.0 <= v <= 2.0):
            raise ValueError("llm_temperature must be between 0.0 and 2.0")
        return v


# =============================================================================
# Singleton Instance
# =============================================================================

# Lazy initialization - will be initialized on first access
_settings = None


def get_settings() -> Settings:
    """Get or create the settings singleton"""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


# For backward compatibility - will trigger lazy initialization on import
try:
    settings = get_settings()
except Exception as e:
    # If loading fails, provide a helpful error message
    print(f"Error loading settings: {e}")
    print("Please ensure .env file exists in the project root with proper values")
    raise
