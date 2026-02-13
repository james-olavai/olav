"""Path Configuration for OLAV v0.8.2+

Centralized path configuration to eliminate hardcoded paths.
All tools should import from this module instead of hardcoding paths.

Usage:
    from config.paths import NETWORK_SNAPSHOT_PATH, VISUALIZATION_DIR
    db_path = NETWORK_SNAPSHOT_PATH
"""

import os
from pathlib import Path

from config.settings import AGENT_DIR, PROJECT_ROOT

# =============================================================================
# v0.10.0: OLAV Base Directories
# =============================================================================

OLAV_BASE_DIR = AGENT_DIR  # Points to .olav/
LIB_DIR = OLAV_BASE_DIR / "lib"  # Platform-agnostic utilities (data_gateway.py)

# =============================================================================
# Database Paths (Internal - .olav/db/) - v0.10.1: Unified Single Database
# =============================================================================

DB_DIR = AGENT_DIR / "db"

def get_database_path(force_test: bool = False) -> Path:
    """获取当前环境的数据库路径 (v0.10.2+ 动态配置)
    
    优先级:
    1. OLAV_DB_PATH 环境变量 (最高)
    2. force_test=True → settings.database.test_db
    3. settings.database.main_db (默认)
    
    Args:
        force_test: 强制使用测试数据库 (用于测试脚本)
        
    Returns:
        数据库文件路径
        
    Examples:
        >>> get_database_path()  # 生产环境
        PosixPath('.olav/db/olav.duckdb')
        
        >>> get_database_path(force_test=True)  # 测试环境
        PosixPath('.olav/db/test_network.duckdb')
        
        >>> os.environ["OLAV_DB_PATH"] = "/tmp/custom.duckdb"
        >>> get_database_path()  # 环境变量覆盖
        PosixPath('/tmp/custom.duckdb')
    """
    # 1. 环境变量最高优先级
    if env_path := os.getenv("OLAV_DB_PATH"):
        return Path(env_path)
    
    # 2. 测试环境
    if force_test:
        from config.settings import settings
        if settings.database.test_db:
            return settings.database.test_db
    
    # 3. 默认生产数据库
    from config.settings import settings
    return settings.database.main_db

# v0.10.2: Unified Single Database Architecture
# All data (devices, raw_outputs, audit, knowledge) in one DuckDB file
# Note: UNIFIED_DB is now computed at runtime - see get_database_path()
try:
    UNIFIED_DB = get_database_path()  # Dynamic path resolution
except Exception:
    # Fallback if get_database_path() fails (shouldn't happen)
    UNIFIED_DB = DB_DIR / "olav.duckdb"

# Backward compatibility aliases (all point to unified database)
MAIN_DB_PATH = UNIFIED_DB  # Device metadata
SNAPSHOTS_DB = UNIFIED_DB  # Network snapshots & query cache
AUDIT_LOGS_DB = UNIFIED_DB  # Command audit logs
OLAV_DB_PATH = UNIFIED_DB  # Main database

# Deprecated paths (kept for backwards compat, not used)
NETWORK_DB_PATH = UNIFIED_DB
NETWORK_COMMANDS_PATH = UNIFIED_DB
KNOWLEDGE_PATH = UNIFIED_DB
NETWORK_SNAPSHOT_PATH = UNIFIED_DB
NETWORK_WAREHOUSE_PATH = UNIFIED_DB

# User-Local Cache (Phase 8 Multi-User Architecture)
# Resolves locking issues by giving each user their own writeable DB
try:
    # Prioritize environment variable for container/test support
    _username = os.environ.get("USER") or os.getlogin()
except Exception:
    # Windows fallback
    _username = os.environ.get("USERNAME", "default_user")

USER_CACHE_FILENAME = f"cache_{_username}.duckdb"
USER_CACHE_PATH = Path.home() / ".olav" / USER_CACHE_FILENAME

# Cache directory for LLM call cache (v0.10.1: SQLite with TTL)
CACHE_DIR = AGENT_DIR / "cache"
LLM_CACHE_DB = CACHE_DIR / "olav_cache.db"  # SQLite - LLM call cache

# User-Local Checkpoint & History (LangGraph Native - Phase 9)
USER_CHECKPOINT_DIR = Path.home() / ".olav" / "checkpoints"
USER_CHECKPOINT_PATH = USER_CHECKPOINT_DIR / f"{_username}.duckdb"
USER_HISTORY_DIR = Path.home() / ".olav" / "history"
USER_HISTORY_PATH = USER_HISTORY_DIR / f"{_username}.txt"
USER_SESSION_DIR = Path.home() / ".olav" / "sessions"

# =============================================================================
# Export Paths (User-Facing - exports/)
# =============================================================================

import os

# ✅ #Phase 3.1: Support OLAV_EXPORTS_DIR environment variable for testing
_exports_dir_env = os.environ.get("OLAV_EXPORTS_DIR")
if _exports_dir_env:
    EXPORTS_DIR = Path(_exports_dir_env)
else:
    EXPORTS_DIR = PROJECT_ROOT / "exports"

# Snapshots: exports/snapshots/<YYYY-MM-DD>/
# Simplified structure (removed /sync/ layer)
SNAPSHOTS_DIR = EXPORTS_DIR / "snapshots"
EXPORTS_SNAPSHOTS_DIR = SNAPSHOTS_DIR  # v0.10.0: Explicit export alias for tests
# Note: SNAPSHOT_SYNC_DIR kept for backwards compatibility, maps to SNAPSHOTS_DIR
SNAPSHOT_SYNC_DIR = SNAPSHOTS_DIR  # Alias - sync is implied

# Sync data directory (for sync_tools)
SYNC_DIR = SNAPSHOTS_DIR  # Unified with snapshots directory

# Reports (standalone analysis reports)
REPORTS_DIR = EXPORTS_DIR / "reports"
EXPORTS_REPORTS_DIR = REPORTS_DIR  # v0.10.0: Explicit export alias for tests
REPORTS_ANALYSIS_DIR = REPORTS_DIR / "analysis"

# Visualizations: exports/topology/ (simplified from exports/visualizations/topology)
VISUALIZATION_DIR = EXPORTS_DIR / "visualizations"
TOPOLOGY_VIZ_DIR = EXPORTS_DIR / "topology"  # Simplified path

# =============================================================================
# Logs Directory (Platform Logs)
# =============================================================================

LOGS_DIR = PROJECT_ROOT / "logs"

# =============================================================================
# Task Scheduler Paths (.olav/tasks/)
# =============================================================================

TASKS_DIR = AGENT_DIR / "tasks"
TASKS_SCHEDULED_DIR = TASKS_DIR / "scheduled"  # Active scheduled tasks
TASKS_RESULTS_DIR = TASKS_DIR / "results"     # Task execution results
TASKS_ARCHIVE_DIR = TASKS_DIR / "archived"    # Completed/expired tasks
TASKS_DLQ_DIR = TASKS_DIR / "dead_letter_queue"  # Failed tasks for manual retry
TASKS_AUDIT_DIR = TASKS_DIR / "audit"         # Approval and activity logs

# =============================================================================
# Agent Configuration Paths (.olav/config/)
# =============================================================================

CONFIG_DIR = AGENT_DIR / "config"
SETTINGS_JSON_PATH = AGENT_DIR / "settings.json"

# =============================================================================
# Skills Directory (.olav/skills/)
# =============================================================================

SKILL_BASE_PATH = AGENT_DIR / "skills"
SKILLS_DIR = SKILL_BASE_PATH  # Alias for backward compatibility

# v0.10.1: Skill-Specific Config Paths (migrated from .olav/config/)
SKILL_NETWORK_EXPERT_DIR = SKILLS_DIR / "network-expert"
SKILL_NETWORK_EXPERT_CONFIG = SKILL_NETWORK_EXPERT_DIR / "config"

SKILL_NETWORK_INSPECTION_DIR = SKILLS_DIR / "network-inspection"
SKILL_NETWORK_INSPECTION_CONFIG = SKILL_NETWORK_INSPECTION_DIR / "config"
THRESHOLDS_CONFIG_PATH = SKILL_NETWORK_INSPECTION_CONFIG / "thresholds.yaml"

SKILL_TEXTFSM_GENERATOR_DIR = SKILLS_DIR / "textfsm-generator"
SKILL_TEXTFSM_GENERATOR_CONFIG = SKILL_TEXTFSM_GENERATOR_DIR / "config"
# Priority: Use central .olav/templates/ directory (contains custom overrides)
# Fallback: Skill output directory if needed
TEXTFSM_TEMPLATES_DIR = OLAV_BASE_DIR / "templates"

SKILL_GUARD_DIR = SKILLS_DIR / "guard"
SKILL_GUARD_CONFIG = SKILL_GUARD_DIR / "config"
COMMAND_MODE_CONFIG_PATH = SKILL_GUARD_CONFIG / "command_mode.yaml"
GUARD_WHITELIST_PATH = SKILL_GUARD_DIR / "whitelist.yaml"  # For CLI whitelist loading
GUARD_RULES_PATH = SKILL_GUARD_DIR / "rules.yaml"  # For Guard agent filtering

# Legacy skill paths (deprecated, use config paths above)
SKILL_INSPECT_ANALYZER = SKILLS_DIR / "inspect-analyzer" / "SKILL.md"
SKILL_LOG_ANALYZER = SKILLS_DIR / "log-analyzer" / "SKILL.md"
SKILL_DAILY_REPORT = SKILLS_DIR / "daily-report" / "SKILL.md"

# =============================================================================
# Security Configuration (Guard Skill)
# =============================================================================

GUARD_SKILL_DIR = SKILL_BASE_PATH / "guard"
GUARD_RULES_PATH = GUARD_SKILL_DIR / "rules.yaml"
GUARD_WHITELIST_PATH = GUARD_SKILL_DIR / "whitelist.yaml"

# =============================================================================
# Skill-Level Cache/Checkpoint Paths (v0.10.0+)
# Each skill has its own isolated cache/checkpoint database
# =============================================================================

def get_skill_checkpoint_path(skill_name: str) -> Path:
    """Get checkpoint database path for a specific skill.
    
    Args:
        skill_name: Name of the skill (e.g., 'orchestrator', 'network-query')
    
    Returns:
        Path to skill's checkpoint database (.olav/skills/{skill_name}/skill.duckdb)
    
    Examples:
        >>> get_skill_checkpoint_path('orchestrator')
        Path('.olav/skills/olav-orchestrator/skill.duckdb')
        >>> get_skill_checkpoint_path('network-query')
        Path('.olav/skills/network-query/skill.duckdb')
    """
    skill_dir = SKILLS_DIR / skill_name
    skill_dir.mkdir(parents=True, exist_ok=True)
    return skill_dir / "skill.duckdb"

# Pre-defined skill checkpoint paths (most commonly used)
ORCHESTRATOR_CHECKPOINT_PATH = get_skill_checkpoint_path("orchestrator")
NETWORK_QUERY_CHECKPOINT_PATH = get_skill_checkpoint_path("network-query")

# =============================================================================
# Documentation Paths
# =============================================================================

OLAV_README = PROJECT_ROOT / "OLAV.md"

# =============================================================================
# Snapshot Latest Symlink
# =============================================================================

SNAPSHOTS_LATEST_DIR = SNAPSHOTS_DIR / "latest"

# =============================================================================
# Configuration & Retention
# =============================================================================

# Log analysis time window (hours)
LOG_ANALYSIS_WINDOW_HOURS = 24

# Data retention policy (days)
# Snapshots older than this will be archived/deleted
RETENTION_DAYS = 30

# =============================================================================
# Backwards Compatibility (Deprecated)
# =============================================================================

# Legacy paths for migration scripts
LEGACY_DATA_SYNC_DIR = PROJECT_ROOT / "data" / "sync"
LEGACY_DATA_VIZ_DIR = PROJECT_ROOT / "data" / "visualizations"
LEGACY_OLAV_DATA_DIR = AGENT_DIR / "data"
