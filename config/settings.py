# -*- coding: utf-8 -*-
"""
OLAV Unified Configuration - Single Source of Truth
====================================================

Usage:
1. Copy .env.example to .env and configure your credentials
2. All settings load from .env file
3. Use config classes for default values that rarely change

Priority:
1. Environment variables (highest priority)
2. .env file values
3. Default values in this file
"""

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# =============================================================================
# Project Root Detection
# =============================================================================

PROJECT_ROOT = Path(__file__).parent.parent
ENV_FILE_PATH = PROJECT_ROOT / ".env"
DATA_DIR = PROJECT_ROOT / "data"
CONFIG_DIR = PROJECT_ROOT / "config"


# =============================================================================
# Environment Settings (loads from .env)
# =============================================================================

class EnvSettings(BaseSettings):
    """Environment-based configuration loaded from .env file.
    
    All sensitive credentials and runtime configurations should be set here.
    """

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE_PATH),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # =========================================================================
    # LLM Configuration
    # =========================================================================
    llm_provider: Literal["openai", "ollama", "azure"] = "ollama"
    llm_api_key: str = ""
    llm_base_url: str = "http://127.0.0.1:11434"
    llm_model_name: str = "qwen3:30b"
    llm_fast_model: str = "qwen3:8b"
    llm_temperature: float = 0.1
    llm_max_tokens: int = 16384

    # =========================================================================
    # Embedding Configuration
    # =========================================================================
    embedding_provider: Literal["openai", "ollama"] = "ollama"
    embedding_api_key: str = ""
    embedding_base_url: str = "http://127.0.0.1:11434"
    embedding_model: str = "nomic-embed-text:latest"
    embedding_dimensions: int = 768

    # =========================================================================
    # PostgreSQL (LangGraph Checkpointer)
    # =========================================================================
    postgres_host: str = "localhost"
    postgres_port: int = 55432
    postgres_user: str = "olav"
    postgres_password: str = "OlavPG123!"
    postgres_db: str = "olav"

    @property
    def postgres_uri(self) -> str:
        """Build PostgreSQL connection URI."""
        return f"postgresql://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

    # =========================================================================
    # OpenSearch
    # =========================================================================
    opensearch_host: str = "localhost"
    opensearch_port: int = 19200
    opensearch_username: str = ""
    opensearch_password: str = ""
    opensearch_verify_certs: bool = False
    opensearch_index_prefix: str = "olav"

    @property
    def opensearch_url(self) -> str:
        """Build OpenSearch URL."""
        return f"http://{self.opensearch_host}:{self.opensearch_port}"

    # =========================================================================
    # Redis
    # =========================================================================
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = ""

    @property
    def redis_url(self) -> str:
        """Build Redis connection URL."""
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}"
        return f"redis://{self.redis_host}:{self.redis_port}"

    # =========================================================================
    # NetBox (Single Source of Truth for Inventory)
    # =========================================================================
    netbox_url: str = ""
    netbox_token: str = ""
    netbox_verify_ssl: bool = True

    # =========================================================================
    # Device Credentials
    # =========================================================================
    device_username: str = "cisco"
    device_password: str = "cisco"

    # =========================================================================
    # API Server
    # =========================================================================
    server_host: str = "0.0.0.0"
    server_port: int = 8000
    cors_origins: str = "*"
    cors_allow_credentials: bool = True
    api_rate_limit_rpm: int = 60
    api_rate_limit_enabled: bool = False

    # =========================================================================
    # Authentication
    # =========================================================================
    token_max_age_hours: int = 24
    session_token_max_age_hours: int = 168
    auth_disabled: bool = False

    # =========================================================================
    # WebSocket
    # =========================================================================
    websocket_heartbeat_interval: int = 30
    websocket_max_connections: int = 100

    # =========================================================================
    # Feature Flags
    # =========================================================================
    expert_mode: bool = False
    use_dynamic_router: bool = True  # Enable DynamicIntentRouter
    enable_agentic_rag: bool = True
    enable_deep_dive_memory: bool = True
    stream_stateless: bool = True  # Enable streaming
    enable_guard_mode: bool = True
    enable_hitl: bool = True
    yolo_mode: bool = False  # Skip approval (dangerous, test only)

    # =========================================================================
    # Agent Configuration
    # =========================================================================
    agent_max_tool_calls: int = 10
    agent_tool_timeout: int = 30
    agent_memory_window: int = 10
    agent_max_reflections: int = 3
    agent_language: Literal["auto", "zh", "en"] = "auto"

    # =========================================================================
    # Diagnosis Configuration
    # =========================================================================
    diagnosis_max_iterations: int = 5
    diagnosis_confidence_threshold: float = 0.8
    diagnosis_methodology: Literal["funnel", "parallel"] = "funnel"

    # =========================================================================
    # LangSmith Tracing (optional)
    # =========================================================================
    langsmith_enabled: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "olav-dev"
    langsmith_endpoint: str = "https://api.smith.langchain.com"

    # =========================================================================
    # Collector/Sandbox Configuration
    # =========================================================================
    collector_force_enable: bool = False
    collector_min_privilege: int = 15
    collector_blacklist_file: str = "command_blacklist.txt"
    collector_capture_diff: bool = True

    # =========================================================================
    # Paths (can be overridden via env vars)
    # =========================================================================
    suzieq_data_dir: str = "data/suzieq-parquet"
    documents_dir: str = "data/documents"
    reports_dir: str = "data/reports"
    inspection_reports_dir: str = "data/inspection-reports"
    cache_dir: str = "data/cache"
    logs_dir: str = "logs"
    prompts_dir: str = "config/prompts"
    inspections_dir: str = "config/inspections"

    # =========================================================================
    # Logging
    # =========================================================================
    log_level: str = "INFO"
    log_format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    log_file_enabled: bool = True
    log_file_path: str = "logs/olav.log"
    log_file_max_size_mb: int = 10
    log_file_backup_count: int = 5

    # =========================================================================
    # Inspection
    # =========================================================================
    inspection_enabled: bool = True
    inspection_parallel_devices: int = 5
    inspection_device_timeout: int = 120
    inspection_notify_on_critical: bool = True
    inspection_notify_on_complete: bool = True
    inspection_notify_on_failure: bool = True
    inspection_notify_webhook_url: str = ""

    # =========================================================================
    # Tool Configuration
    # =========================================================================
    nornir_num_workers: int = 10
    command_timeout: int = 30
    suzieq_timeout: int = 60

    # =========================================================================
    # LLM Retry Configuration
    # =========================================================================
    llm_max_retries: int = 3
    llm_retry_delay: float = 1.0
    llm_retry_backoff_multiplier: float = 2.0
    llm_retry_max_delay: float = 30.0


# =============================================================================
# Global Settings Instance
# =============================================================================

settings = EnvSettings()


# =============================================================================
# Path Helper Functions
# =============================================================================

def get_path(name: str) -> Path:
    """Get absolute path for a configured directory.
    
    Args:
        name: Path name (suzieq_data, documents, reports, cache, logs, prompts, inspections)
        
    Returns:
        Absolute path
    """
    paths_map = {
        "suzieq_data": settings.suzieq_data_dir,
        "documents": settings.documents_dir,
        "reports": settings.reports_dir,
        "inspection_reports": settings.inspection_reports_dir,
        "cache": settings.cache_dir,
        "logs": settings.logs_dir,
        "prompts": settings.prompts_dir,
        "inspections": settings.inspections_dir,
    }
    rel_path = paths_map.get(name)
    if rel_path is None:
        raise ValueError(f"Unknown path: {name}")
    return PROJECT_ROOT / rel_path


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Settings
    "EnvSettings",
    "settings",
    # Paths
    "PROJECT_ROOT",
    "ENV_FILE_PATH",
    "DATA_DIR",
    "CONFIG_DIR",
    "get_path",
]
