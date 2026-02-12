"""
Admin Agent Module

Provides system configuration management for OLAV.

Design References:
  See: dev_doc/ADMIN_AGENT_SIMPLIFIED_DESIGN.md (v3.0)
       dev_doc/ADMIN_AGENT_CODE_ORGANIZATION.md
       dev_doc/ADMIN_AGENT_DEVELOPMENT_PLAN.md

Security:
  - Three-layer safety checks implemented
  - No database/backup/code modifications allowed
  - All operations logged and auditable
"""

from .admin_agent import AdminAgent
from .admin_file_manager import AdminFileManager
# from .config_manager import ConfigManager  # DEPRECATED (v0.9.6) - use AdminFileManager instead
from .knowledge_manager import KnowledgeManager
from .exceptions import (
    AdminException,
    ValidationError,
    OperationError,
    PathError,
    PermissionError as AdminPermissionError,
    IntentError,
)
from .validators import (
    validate_device_name,
    validate_device_ip,
    validate_username,
    validate_cron_schedule,
    validate_knowledge_topic,
    validate_not_empty,
)

__all__ = [
    "AdminAgent",
    "AdminFileManager",
    "KnowledgeManager",
    "AdminException",
    "ValidationError",
    "OperationError",
    "PathError",
    "AdminPermissionError",
    "IntentError",
    "validate_device_name",
    "validate_device_ip",
    "validate_username",
    "validate_cron_schedule",
    "validate_knowledge_topic",
    "validate_not_empty",
]

__version__ = "1.0.0"
