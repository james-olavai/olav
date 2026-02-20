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

# Import Task Scheduler Configuration
from config.tasks import TaskSchedulerSettings

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
# Configuration Classes
# =============================================================================


class DatabaseSettings(BaseSettings):
    """数据库配置 (v0.10.2+ 支持配置分层)"""

    main_db: Path = Field(
        default=Path(".olav/databases/main.duckdb"),
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
        default=30, ge=30, le=600, description="CLI query timeout in seconds"
    )

    # Advanced Netmiko Configuration (for slow devices or long outputs)
    global_delay_factor: int = Field(
        default=4, ge=1, le=10, description="Netmiko global delay multiplier (higher = more patient with slow devices)"
    )
    max_loops: int = Field(
        default=1000, ge=100, le=10000, description="Maximum read loops for long command outputs"
    )

    # Scrapli timeout for exhaustive snapshots (in seconds)
    scrapli_timeout_ops: int = Field(
        default=300, ge=60, le=600, description="Scrapli operation timeout for exhaustive snapshots"
    )

    # Nornir concurrency (num_workers for parallel execution)
    concurrency: int = Field(
        default=10, ge=1, le=100, description="Number of parallel workers for network operations"
    )


class RuntimeSettings(BaseSettings):
    """Runtime Configuration - Paths, Timeouts, Connection Settings
    
    Centralizes all hardcoded configuration values for paths, timeouts, and connection parameters.
    Extracted from 23 hardcoded locations across the codebase.
    """

    model_config = SettingsConfigDict(env_prefix="RUNTIME_")

    # Directory and Path Configuration
    olav_config_dir: str = Field(
        default=".olav",
        description="OLAV configuration directory (can be .olav, .claude, .cursor, etc.)"
    )
    exports_dir: str = Field(
        default="exports",
        description="Directory for exporting query results and reports"
    )
    skills_dir: str = Field(
        default=".olav/skills",
        description="Directory containing skills definitions"
    )
    knowledge_dir: str = Field(
        default=".olav/knowledge",
        description="Directory for knowledge base files"
    )
    templates_dir: str = Field(
        default=".olav/templates",
        description="Directory for TextFSM templates"
    )
    config_dir: str = Field(
        default=".olav/config",
        description="Directory for configuration files"
    )

    # Connection Configuration
    default_host: str = Field(
        default="127.0.0.1",
        description="Default host for connections (localhost/API server)"
    )
    default_port: int = Field(
        default=8000,
        ge=1,
        le=65535,
        description="Default port for connections"
    )
    nornir_host: str = Field(
        default="localhost",
        description="Host for Nornir network executor"
    )

    # Timeout Configuration (in seconds)
    analyzer_timeout: int = Field(
        default=30,
        ge=5,
        le=300,
        description="Analyzer agent timeout"
    )
    cli_timeout: int = Field(
        default=300,
        ge=30,
        le=3600,
        description="CLI command timeout"
    )
    script_engine_timeout: int = Field(
        default=300,
        ge=30,
        le=3600,
        description="Script engine execution timeout"
    )
    session_timeout: int = Field(
        default=30,
        ge=5,
        le=300,
        description="Session read timeout"
    )
    default_timeout: int = Field(
        default=30,
        ge=5,
        le=300,
        description="Default operation timeout"
    )

    # Business Parameters
    max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Maximum retry attempts for operations"
    )
    batch_size: int = Field(
        default=10,
        ge=1,
        le=1000,
        description="Batch size for bulk operations"
    )
    max_devices: int = Field(
        default=1000,
        ge=1,
        le=10000,
        description="Maximum number of devices to process"
    )

    def get_full_path(self, relative_path: str) -> Path:
        """Get full path relative to project root
        
        Args:
            relative_path: Path relative to project root
            
        Returns:
            Absolute Path object
        """
        return PROJECT_ROOT / relative_path

    def get_exports_dir(self) -> Path:
        """Get exports directory path"""
        return self.get_full_path(self.exports_dir)

    def get_skills_dir(self) -> Path:
        """Get skills directory path"""
        return self.get_full_path(self.skills_dir)

    def get_knowledge_dir(self) -> Path:
        """Get knowledge directory path"""
        return self.get_full_path(self.knowledge_dir)

    def get_templates_dir(self) -> Path:
        """Get templates directory path"""
        return self.get_full_path(self.templates_dir)


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
        default=".olav/skills/olav-guard/config/command_mode.yaml",
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
    llm_provider: Literal["openai", "ollama", "azure", "xai", "anthropic", "groq", "mistral"] = "openai"
    llm_api_key: str = ""
    llm_model_name: str = "gpt-4-turbo"
    llm_base_url: str = ""
    llm_temperature: float = 0.1
    llm_max_tokens: int = 16000

    # =========================================================================
    # Embedding Configuration (Independent from LLM)
    # =========================================================================
    # Mode options:
    #   - "local": Use sentence-transformers (local, free, no API needed)
    #   - "openai": Use OpenAI API or OpenAI-compatible (text-embedding-3-small, etc.)
    # Default: "local" (recommended - no API costs)
    embedding_mode: str = Field(
        default="local",
        description="Embedding mode: 'local' (sentence-transformers) or 'openai' (API)"
    )
    
    # When embedding_mode="local": sentence-transformers model name
    # Recommended models:
    #   - all-MiniLM-L6-v2 (384 dim, fastest, ~22MB)
    #   - all-mpnet-base-v2 (768 dim, higher quality, ~440MB)
    #   - bge-small-zh-v1.5 (512 dim, Chinese-optimized, ~200MB) - 推荐用于中文
    embedding_local_model: str = Field(
        default="BAAI/bge-small-zh-v1.5",
        description="Sentence-transformers model for local embedding"
    )
    
    # When embedding_mode="openai": API configuration (backward compatible)
    embedding_provider: str = ""  # Empty = use llm_provider (for openai mode)
    embedding_model: str = ""  # Empty = use text-embedding-3-small
    embedding_base_url: str = ""  # Empty = use llm_base_url
    embedding_api_key: str = ""  # Empty = use llm_api_key
    
    # Fallback for embedding: If embedding_mode="openai" and API fails, fallback to local
    embedding_enable_fallback: bool = Field(
        default=True,
        description="Enable automatic fallback from openai to local embeddings if API call fails (improves reliability)"
    )

    # =========================================================================
    # Nested Configuration Objects
    # =========================================================================
    execution: ExecutionSettings = Field(
        default_factory=ExecutionSettings, description="Command execution configuration"
    )
    sync: SyncSettings = Field(
        default_factory=SyncSettings, description="Synchronization configuration"
    )
    database: DatabaseSettings = Field(
        default_factory=DatabaseSettings, description="Database configuration (v0.10.2+)"
    )
    tasks: TaskSchedulerSettings = Field(
        default_factory=TaskSchedulerSettings, description="Task scheduler configuration (v2.0+)"
    )
    runtime: RuntimeSettings = Field(
        default_factory=RuntimeSettings, description="Runtime paths and connection configuration"
    )

    # =========================================================================
    # Agent Configuration
    # =========================================================================
    agent_dir: str = ".olav"
    agent_name: str = "OLAV"

    # =========================================================================
    # Network Execution Configuration
    # =========================================================================
    nornir_ssh_port: int = 22

    # =========================================================================
    # Application Settings
    # =========================================================================
    environment: Literal["local", "development", "production"] = "local"

    # =========================================================================
    # Logging & Debug
    # =========================================================================
    display_thinking: bool = True
    log_level: str = "CRITICAL"
    log_format: Literal["json", "text"] = "text"
    debug: bool = False
    langsmith_api_key: str = ""  # Optional for LangSmith tracing
    langsmith_project: str = "olav-v2"

    # =========================================================================
    # Network Inspection Configuration
    # =========================================================================
    nornir_default_group: str = Field(
        default="test", description="Default Nornir group for network device operations"
    )
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

            # Map JSON keys → Settings field names
            simple_mapping = {
                "model": "llm_model_name",
                "temperature": "llm_temperature",
                "displayThinking": "display_thinking",
            }

            # Env vars that take priority over settings.json
            env_var_map = {
                "llm_model_name": "LLM_MODEL_NAME",
                "llm_temperature": "LLM_TEMPERATURE",
                "llm_max_tokens": "LLM_MAX_TOKENS",
                "log_level": "LOG_LEVEL",
            }

            for json_key, attr_name in simple_mapping.items():
                if json_key in olav_settings:
                    value = olav_settings[json_key]
                    env_var = env_var_map.get(attr_name)
                    if env_var and os.getenv(env_var):
                        continue  # Environment variable takes priority
                    setattr(self, attr_name, value)

            # Apply live nested configuration
            nested_mapping = {
                "execution": ("execution", ExecutionSettings),
                "sync": ("sync", SyncSettings),
            }

            for json_key, (attr_name, cls) in nested_mapping.items():
                if json_key in olav_settings:
                    nested_data = olav_settings[json_key]
                    if isinstance(nested_data, dict):
                        try:
                            converted_data = {
                                self._camel_to_snake(k): v
                                for k, v in nested_data.items()
                            }
                            setattr(self, attr_name, cls(**converted_data))
                        except Exception:  # noqa: S110
                            pass  # keep default on validation failure

        except (json.JSONDecodeError, OSError):
            pass  # silently ignore invalid/missing settings.json

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

        data = {
            "model": self.llm_model_name,
            "temperature": self.llm_temperature,
            "displayThinking": self.display_thinking,
            "sync": self.sync.model_dump(),
            "execution": self.execution.model_dump(),
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
