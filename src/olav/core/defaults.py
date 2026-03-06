"""OLAV Default Configuration (Blueprint Tier).

This module defines the Tier 1 default configuration values.
These are the baseline settings that can be overridden by:
- Tier 2: Project config (.olav/config/*)
- Tier 3: User/Env config (~/.olav/config.json or env vars)

Loading priority (high to low):
1. Environment variables (OLAV_*)
2. User config (~/.olav/config.json)
3. Project config (.olav/config/*)
4. This file (defaults)
"""

from typing import Any

# ============================================================================
# LLM Configuration Defaults
# ============================================================================

DEFAULT_LLM_CONFIG: dict[str, Any] = {
    "provider": "openai",
    "model": "gpt-4-turbo",
    "temperature": 0.1,
    "max_tokens": 16000,
    "base_url": "",  # For OpenAI-compatible APIs
    "custom_headers": {},
}


# ============================================================================
# Embedding Configuration Defaults
# ============================================================================

DEFAULT_EMBEDDING_CONFIG: dict[str, Any] = {
    "mode": "local",  # "local" or "api"
    "local": {
        "model": "BAAI/bge-small-zh-v1.5",
        "device": "cpu",
        "normalize_embeddings": True,
    },
    "api": {
        "model": "text-embedding-3-small",
        "base_url": "",
        "api_key": "",
    },
    "fallback": {
        "enabled": True,
    },
}


# ============================================================================
# Path Configuration Defaults
# ============================================================================

DEFAULT_PATHS_CONFIG: dict[str, Any] = {
    "agent_dir": ".olav",
    "databases_dir": ".olav/databases",
    "exports_dir": "exports",
    "agent_outputs_dir": "agent_outputs",
    "run_dir": "run",
    "logs_dir": ".olav/logs",
    "log_storage_dir": ".olav/databases/logs",
    "knowledge_dir": ".olav/knowledge",
    "workspace_dir": ".olav/workspace",
    "templates_dir": ".olav/templates",
    "config_dir": ".olav/config",
    "files": {
        "main_db": ".olav/databases/main.duckdb",
        "llm_cache": ".olav/databases/llm_cache.sqlite",
    },
}


# ============================================================================
# Runtime Configuration Defaults
# ============================================================================

DEFAULT_RUNTIME_CONFIG: dict[str, Any] = {
    "execution": {
        "use_textfsm": True,
        "timeout": 30,
        "retry_attempts": 3,
    },
    "logging": {
        "level": "INFO",
        "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    },
}


# ============================================================================
# Security Configuration Defaults
# ============================================================================

DEFAULT_SECURITY_CONFIG: dict[str, Any] = {
    "guardrails": {
        "enabled": True,
        "threshold": 0.85,
    },
    "denylist": {
        "enabled": True,
        "categories": ["destructive", "high_risk"],
    },
}


# ============================================================================
# Router Configuration Defaults
# ============================================================================

DEFAULT_ROUTER_CONFIG: dict[str, Any] = {
    "semantic": {
        "enabled": True,
        "threshold": 0.85,
        "fallback_to_llm": True,
    },
    "embedding": {
        "model": "BAAI/bge-small-zh-v1.5",
    },
}


# ============================================================================
# Database Configuration Defaults
# ============================================================================

DEFAULT_DATABASE_CONFIG: dict[str, Any] = {
    "duckdb": {
        "threads": 4,
        "memory_limit": "8GB",
    },
    "lancedb": {
        "vector_size": 384,
    },
}


# ============================================================================
# Network Operations Configuration Defaults
# ============================================================================

DEFAULT_NETWORK_CONFIG: dict[str, Any] = {
    "nornir": {
        "connection_timeout": 30,
        "execution_timeout": 60,
    },
    "commands": {
        "allowed_file": ".olav/templates/config/allowed_commands.yaml",
        "denied_file": ".olav/templates/config/blacklisted_commands.yaml",
    },
}


# ============================================================================
# Helper Functions
# ============================================================================


def get_default_config() -> dict[str, Any]:
    """Get all default configuration values.

    Returns:
        Dict containing all default configuration sections
    """
    return {
        "llm": DEFAULT_LLM_CONFIG,
        "embedding": DEFAULT_EMBEDDING_CONFIG,
        "paths": DEFAULT_PATHS_CONFIG,
        "runtime": DEFAULT_RUNTIME_CONFIG,
        "security": DEFAULT_SECURITY_CONFIG,
        "router": DEFAULT_ROUTER_CONFIG,
        "database": DEFAULT_DATABASE_CONFIG,
        "network": DEFAULT_NETWORK_CONFIG,
    }


def get_default_value(section: str, key: str, default: Any = None) -> Any:
    """Get a specific default configuration value.

    Args:
        section: Configuration section (e.g., "llm", "paths")
        key: Configuration key within the section
        default: Default value to return if not found

    Returns:
        The default value or the provided default
    """
    config = get_default_config()
    section_data = config.get(section, {})
    return section_data.get(key, default)


# ============================================================================
# Constants
# ============================================================================

# Default port for OLAV Web (FastAPI) server
DEFAULT_WEB_PORT: int = 2280

# Default port for OLAV Syslog collector (UDP/TCP)
DEFAULT_LOG_PORT: int = 5514

# Default threshold for semantic routing
DEFAULT_ROUTING_THRESHOLD: float = 0.85

# Default threshold for security guardrails
DEFAULT_GUARDRAIL_THRESHOLD: float = 0.85

# Maximum retry attempts for SQL reflection
SQL_REFLECTION_MAX_RETRIES: int = 3

# Context compression threshold (number of messages)
CONTEXT_COMPRESSION_THRESHOLD: int = 20
