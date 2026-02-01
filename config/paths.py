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

# v0.9.9: Unified Database Core (deprecated - use SNAPSHOTS_DB instead)
OLAV_DB_PATH = DB_DIR / "olav.duckdb"

# User-Local Cache (Phase 8 Multi-User Architecture)
# Resolves locking issues by giving each user their own writeable DB
try:
    # Prioritize environment variable for container/test support
    _username = os.environ.get("USER") or os.getlogin()
except Exception:
    _username = "default_user"

USER_CACHE_FILENAME = f"cache_{_username}.duckdb"
USER_CACHE_PATH = Path.home() / ".olav" / USER_CACHE_FILENAME

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
# Note: SNAPSHOT_SYNC_DIR kept for backwards compatibility, maps to SNAPSHOTS_DIR
SNAPSHOT_SYNC_DIR = SNAPSHOTS_DIR  # Alias - sync is implied

# Sync data directory (for sync_tools)
SYNC_DIR = SNAPSHOTS_DIR  # Unified with snapshots directory

# Reports (standalone analysis reports)
REPORTS_DIR = EXPORTS_DIR / "reports"
REPORTS_ANALYSIS_DIR = REPORTS_DIR / "analysis"
REPORTS_SNAPSHOTS_DIR = REPORTS_DIR / "snapshots"

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
GUARD_RULES_PATH = CONFIG_DIR / "guard_rules.yaml"
ROUTING_RULES_PATH = CONFIG_DIR / "routing_rules.yaml"
SETTINGS_JSON_PATH = AGENT_DIR / "settings.json"

# =============================================================================
# Skills Directory (.olav/skills/)
# =============================================================================

SKILLS_DIR = AGENT_DIR / "skills"
SKILL_INSPECT_ANALYZER = SKILLS_DIR / "inspect-analyzer" / "SKILL.md"
SKILL_LOG_ANALYZER = SKILLS_DIR / "log-analyzer" / "SKILL.md"
SKILL_DAILY_REPORT = SKILLS_DIR / "daily-report" / "SKILL.md"

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
