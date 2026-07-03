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

import os
from typing import Any


def _env_int(name: str, default: int) -> int:
    """Return int env var ``name``, or ``default`` when unset or not parseable."""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default

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
    "run_dir": "run",
    "logs_dir": ".olav/logs",
    "syslog_storage_dir": ".olav/databases/syslogs",
    "knowledge_dir": ".olav/knowledge",
    "workspace_dir": ".olav/workspace",
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
        "timeout": 30,
        "retry_attempts": 3,
    },
    "logging": {
        "level": "INFO",
        "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    },
}


# ============================================================================
# Constants
# ============================================================================

# Default port for OLAV Web (FastAPI) server — ``OLAV_WEB_PORT`` env overrides.
DEFAULT_WEB_PORT: int = _env_int("OLAV_WEB_PORT", 2280)

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
