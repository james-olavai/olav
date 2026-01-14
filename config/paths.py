"""Path Configuration for OLAV v0.8.2+

Centralized path configuration to eliminate hardcoded paths.
All tools should import from this module instead of hardcoding paths.

Usage:
    from config.paths import NETWORK_SNAPSHOT_PATH, VISUALIZATION_DIR
    db_path = NETWORK_SNAPSHOT_PATH
"""

from config.settings import AGENT_DIR, PROJECT_ROOT

# =============================================================================
# Database Paths (Internal - .olav/db/)
# =============================================================================

DB_DIR = AGENT_DIR / "db"
NETWORK_SNAPSHOT_PATH = DB_DIR / "network_snapshot.duckdb"
NETWORK_COMMANDS_PATH = DB_DIR / "network_commands.duckdb"
KNOWLEDGE_PATH = DB_DIR / "knowledge.duckdb"

# Backwards compatibility aliases (deprecated - use new names)
NETWORK_WAREHOUSE_PATH = NETWORK_SNAPSHOT_PATH  # Legacy alias
REGISTRY_PATH = NETWORK_COMMANDS_PATH  # Legacy alias

# =============================================================================
# Export Paths (User-Facing - exports/)
# =============================================================================

EXPORTS_DIR = PROJECT_ROOT / "exports"

# Snapshots: exports/snapshots/<YYYY-MM-DD>/
# Simplified structure (removed /sync/ layer)
SNAPSHOTS_DIR = EXPORTS_DIR / "snapshots"
# Note: SNAPSHOT_SYNC_DIR kept for backwards compatibility, maps to SNAPSHOTS_DIR
SNAPSHOT_SYNC_DIR = SNAPSHOTS_DIR  # Alias - sync is implied

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
