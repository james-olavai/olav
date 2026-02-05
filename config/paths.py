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
# Database Paths (Internal - .olav/db/)
# =============================================================================

DB_DIR = AGENT_DIR / "db"

# v0.10.0: Separated Shared Databases
SNAPSHOTS_DB = DB_DIR / "snapshots.duckdb"  # Network snapshot data (read-only)
TOPOLOGY_DB = DB_DIR / "topology.duckdb"  # Topology data (read-only)
AUDIT_LOGS_DB = DB_DIR / "audit_logs.duckdb"  # Command audit logs (write-only)
MAIN_DB_PATH = DB_DIR / "main.duckdb"  # Main database for devices table and structured data

# v0.9.9: Unified Database Core (deprecated - use SNAPSHOTS_DB instead)
OLAV_DB_PATH = DB_DIR / "olav.duckdb"

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

# Cache directory for unified cache system (v0.10.0+)
CACHE_DIR = AGENT_DIR / "cache"

# User-Local Checkpoint & History (LangGraph Native - Phase 9)
USER_CHECKPOINT_DIR = Path.home() / ".olav" / "checkpoints"
USER_CHECKPOINT_PATH = USER_CHECKPOINT_DIR / f"{_username}.duckdb"
USER_HISTORY_DIR = Path.home() / ".olav" / "history"
USER_HISTORY_PATH = USER_HISTORY_DIR / f"{_username}.txt"
USER_SESSION_DIR = Path.home() / ".olav" / "sessions"

# Map all legacy/specific paths to the unified core
NETWORK_DB_PATH = OLAV_DB_PATH
NETWORK_COMMANDS_PATH = OLAV_DB_PATH  # Default shared commands (read-only fallback)
KNOWLEDGE_PATH = OLAV_DB_PATH

# Backwards compatibility aliases (deprecated - use new names)
NETWORK_SNAPSHOT_PATH = SNAPSHOTS_DB  # v0.10.0: Points to separated snapshots DB
NETWORK_WAREHOUSE_PATH = NETWORK_DB_PATH  # Legacy alias

# =============================================================================
# Export Paths (User-Facing - exports/)
# =============================================================================

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
# Agent Configuration Paths (.olav/config/)
# =============================================================================

CONFIG_DIR = AGENT_DIR / "config"
ROUTING_RULES_PATH = CONFIG_DIR / "routing_rules.yaml"
SETTINGS_JSON_PATH = AGENT_DIR / "settings.json"

# =============================================================================
# Skills Directory (.olav/skills/)
# =============================================================================

SKILL_BASE_PATH = AGENT_DIR / "skills"
SKILLS_DIR = SKILL_BASE_PATH  # Alias for backward compatibility
SKILL_INSPECT_ANALYZER = SKILLS_DIR / "inspect-analyzer" / "SKILL.md"
SKILL_LOG_ANALYZER = SKILLS_DIR / "log-analyzer" / "SKILL.md"
SKILL_DAILY_REPORT = SKILLS_DIR / "daily-report" / "SKILL.md"

# =============================================================================
# Security Configuration (Guard Skill)
# =============================================================================

GUARD_SKILL_DIR = SKILL_BASE_PATH / "guard"
GUARD_RULES_PATH = GUARD_SKILL_DIR / "rules.yaml"
GUARD_WHITELIST_PATH = GUARD_SKILL_DIR / "whitelist.yaml"
SKILL_LOG_ANALYZER = SKILLS_DIR / "log-analyzer" / "SKILL.md"
SKILL_DAILY_REPORT = SKILLS_DIR / "daily-report" / "SKILL.md"

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
        Path('.olav/skills/orchestrator/skill.duckdb')
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
