"""DuckDB database schema initialization for OLAV v0.9.8.

This module initializes all 5 DuckDB databases with their tables:
- orchestrator.duckdb: Execution plans, quality metrics
- snapshots.duckdb: Device snapshots, topology
- topology.duckdb: Network topology (legacy)
- knowledge.duckdb: Knowledge base documents and embeddings
- skill.duckdb: Expert agent history cases (per skill)

Reference: docs/00_development_guide.md §3.2 Database Design
"""

import logging
from pathlib import Path

import duckdb

logger = logging.getLogger(__name__)


class DatabaseSchemaManager:
    """Manages DuckDB database schema creation and validation."""

    # Orchestrator database schema
    ORCHESTRATOR_SCHEMA = """
    -- Execution plan cache (exact matching + learning)
    CREATE TABLE IF NOT EXISTS execution_plan_cache (
        id VARCHAR PRIMARY KEY DEFAULT uuid(),
        
        -- Query information
        query_text TEXT NOT NULL UNIQUE,
        query_category TEXT,
        
        -- Execution plan
        execution_plan JSON NOT NULL,
        
        -- Routing learning
        agents_involved JSON,
        is_multi_agent BOOLEAN,
        initial_route TEXT,
        final_route TEXT,
        was_upgraded BOOLEAN,
        
        -- Performance metrics
        success_rate FLOAT DEFAULT 1.0,
        avg_execution_time FLOAT,
        hit_count INTEGER DEFAULT 1,
        last_used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- Quality metrics
    CREATE TABLE IF NOT EXISTS quality_metrics (
        id VARCHAR PRIMARY KEY DEFAULT uuid(),
        query_id VARCHAR,
        quality_score FLOAT,
        user_feedback INTEGER,
        upgrade_triggered BOOLEAN,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (query_id) REFERENCES execution_plan_cache(id)
    );

    -- Indexes
    CREATE INDEX IF NOT EXISTS idx_plan_query ON execution_plan_cache(query_text);
    CREATE INDEX IF NOT EXISTS idx_plan_used ON execution_plan_cache(last_used_at);
    CREATE INDEX IF NOT EXISTS idx_quality_query ON quality_metrics(query_id);
    """

    # Network snapshots database schema
    SNAPSHOTS_SCHEMA = """
    -- Device snapshots
    CREATE TABLE IF NOT EXISTS device_snapshots (
        id VARCHAR PRIMARY KEY DEFAULT uuid(),
        hostname TEXT NOT NULL,
        snapshot_time TIMESTAMP NOT NULL,
        config_text TEXT,
        routing_table JSON,
        interfaces JSON,
        system_info JSON
    );

    -- Topology data
    CREATE TABLE IF NOT EXISTS topology (
        id VARCHAR PRIMARY KEY DEFAULT uuid(),
        source_device TEXT,
        source_interface TEXT,
        target_device TEXT,
        target_interface TEXT,
        link_type TEXT,
        discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- Indexes
    CREATE INDEX IF NOT EXISTS idx_snapshot_hostname ON device_snapshots(hostname);
    CREATE INDEX IF NOT EXISTS idx_snapshot_time ON device_snapshots(snapshot_time);
    CREATE INDEX IF NOT EXISTS idx_topology_source ON topology(source_device);
    CREATE INDEX IF NOT EXISTS idx_topology_target ON topology(target_device);
    """

    # Knowledge base database schema
    KNOWLEDGE_SCHEMA = """
    -- Sequence for knowledge sources
    CREATE SEQUENCE IF NOT EXISTS knowledge_sources_id_seq START 1;
    
    -- Document sources
    CREATE TABLE IF NOT EXISTS knowledge_sources (
        id INTEGER PRIMARY KEY DEFAULT nextval('knowledge_sources_id_seq'),
        name TEXT NOT NULL UNIQUE,
        base_path TEXT,
        doc_type TEXT,
        indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- Sequence for knowledge chunks
    CREATE SEQUENCE IF NOT EXISTS knowledge_chunks_id_seq START 1;
    
    -- Document chunks (vectorized)
    CREATE TABLE IF NOT EXISTS knowledge_chunks (
        id INTEGER PRIMARY KEY DEFAULT nextval('knowledge_chunks_id_seq'),
        source_id INTEGER,
        file_path TEXT NOT NULL,
        chunk_index INTEGER,
        content TEXT NOT NULL,
        embedding FLOAT[768],
        file_hash TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (source_id) REFERENCES knowledge_sources(id)
    );

    -- Indexes
    CREATE INDEX IF NOT EXISTS idx_chunk_source ON knowledge_chunks(source_id);
    CREATE INDEX IF NOT EXISTS idx_chunk_file ON knowledge_chunks(file_path);
    CREATE INDEX IF NOT EXISTS idx_chunk_hash ON knowledge_chunks(file_hash);
    """

    # Expert skill database schema
    SKILL_SCHEMA = """
    -- Historical diagnosis cases (semantic retrieval)
    CREATE TABLE IF NOT EXISTS history_cases (
        id VARCHAR PRIMARY KEY DEFAULT uuid(),
        
        -- Symptom (semantic retrieval)
        symptom TEXT NOT NULL,
        symptom_embedding FLOAT[768],
        
        -- Diagnosis process
        devices_checked JSON,
        commands_used JSON,
        diagnosis_steps TEXT,
        
        -- Conclusion
        root_cause TEXT,
        solution TEXT,
        
        -- Time information
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        age_days INTEGER
    );

    -- Indexes
    CREATE INDEX IF NOT EXISTS idx_case_symptom ON history_cases(symptom);
    CREATE INDEX IF NOT EXISTS idx_case_created ON history_cases(created_at);
    """

    def __init__(self, db_dir: Path | None = None):
        """Initialize schema manager.

        Args:
            db_dir: Base directory for database files (default: .olav/db/)
        """
        if db_dir is None:
            from config.settings import settings

            db_dir = Path(settings.project_paths.project_root) / ".olav" / "db"

        self.db_dir = Path(db_dir)
        self.db_dir.mkdir(parents=True, exist_ok=True)

        # Database file paths
        self.orchestrator_db = self.db_dir / "orchestrator.duckdb"
        self.snapshots_db = self.db_dir / "snapshots.duckdb"
        self.topology_db = self.db_dir / "topology.duckdb"
        self.knowledge_db = self.db_dir / "knowledge.duckdb"

    def initialize_all(self) -> bool:
        """Initialize all database schemas.

        Returns:
            True if all databases initialized successfully
        """
        try:
            self.initialize_orchestrator()
            self.initialize_snapshots()
            self.initialize_topology()
            self.initialize_knowledge()
            logger.info("All database schemas initialized successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize database schemas: {e}")
            return False

    def initialize_orchestrator(self) -> None:
        """Initialize orchestrator database."""
        logger.info(f"Initializing orchestrator database: {self.orchestrator_db}")
        conn = duckdb.connect(str(self.orchestrator_db))
        try:
            conn.execute(self.ORCHESTRATOR_SCHEMA)
            logger.info("Orchestrator database schema created")
        finally:
            conn.close()

    def initialize_snapshots(self) -> None:
        """Initialize snapshots database."""
        logger.info(f"Initializing snapshots database: {self.snapshots_db}")
        conn = duckdb.connect(str(self.snapshots_db))
        try:
            conn.execute(self.SNAPSHOTS_SCHEMA)
            logger.info("Snapshots database schema created")
        finally:
            conn.close()

    def initialize_topology(self) -> None:
        """Initialize topology database (legacy)."""
        logger.info(f"Initializing topology database: {self.topology_db}")
        conn = duckdb.connect(str(self.topology_db))
        try:
            # Simple topology table for backward compatibility
            conn.execute("""
                CREATE TABLE IF NOT EXISTS topology (
                    id VARCHAR PRIMARY KEY DEFAULT uuid(),
                    source_device TEXT,
                    source_interface TEXT,
                    target_device TEXT,
                    target_interface TEXT,
                    link_type TEXT,
                    discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                
                CREATE INDEX IF NOT EXISTS idx_topo_source ON topology(source_device);
                CREATE INDEX IF NOT EXISTS idx_topo_target ON topology(target_device);
            """)
            logger.info("Topology database schema created")
        finally:
            conn.close()

    def initialize_knowledge(self) -> None:
        """Initialize knowledge base database."""
        logger.info(f"Initializing knowledge database: {self.knowledge_db}")
        conn = duckdb.connect(str(self.knowledge_db))
        try:
            conn.execute(self.KNOWLEDGE_SCHEMA)
            logger.info("Knowledge database schema created")
        finally:
            conn.close()

    def initialize_skill_db(self, skill_dir: Path) -> None:
        """Initialize skill database for a specific skill.

        Args:
            skill_dir: Skill directory path (e.g., .olav/skills/network-expert/)
        """
        skill_db = skill_dir / "skill.duckdb"
        logger.info(f"Initializing skill database: {skill_db}")

        # Ensure skill directory exists
        skill_dir.mkdir(parents=True, exist_ok=True)

        conn = duckdb.connect(str(skill_db))
        try:
            conn.execute(self.SKILL_SCHEMA)
            logger.info(f"Skill database schema created: {skill_db}")
        finally:
            conn.close()

    def validate_all(self) -> dict[str, bool]:
        """Validate all database schemas exist.

        Returns:
            Dictionary mapping database names to validation status
        """
        results = {}

        # Check orchestrator
        results["orchestrator"] = self._validate_db(
            self.orchestrator_db, ["execution_plan_cache", "quality_metrics"]
        )

        # Check snapshots
        results["snapshots"] = self._validate_db(
            self.snapshots_db, ["device_snapshots", "topology"]
        )

        # Check topology
        results["topology"] = self._validate_db(self.topology_db, ["topology"])

        # Check knowledge
        results["knowledge"] = self._validate_db(
            self.knowledge_db, ["knowledge_sources", "knowledge_chunks"]
        )

        return results

    def _validate_db(self, db_path: Path, expected_tables: list[str]) -> bool:
        """Validate database has expected tables.

        Args:
            db_path: Path to database file
            expected_tables: List of expected table names

        Returns:
            True if all tables exist
        """
        if not db_path.exists():
            logger.warning(f"Database file not found: {db_path}")
            return False

        try:
            conn = duckdb.connect(str(db_path), read_only=True)
            try:
                # Get all table names
                result = conn.execute(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
                ).fetchall()
                tables = {row[0] for row in result}

                # Check all expected tables exist
                missing = set(expected_tables) - tables
                if missing:
                    logger.warning(f"Missing tables in {db_path.name}: {missing}")
                    return False

                return True
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"Error validating {db_path.name}: {e}")
            return False


def init_databases(db_dir: Path | None = None) -> bool:
    """Initialize all OLAV databases.

    Args:
        db_dir: Base directory for database files (default: .olav/db/)

    Returns:
        True if initialization successful
    """
    manager = DatabaseSchemaManager(db_dir)
    return manager.initialize_all()


def validate_databases(db_dir: Path | None = None) -> dict[str, bool]:
    """Validate all OLAV database schemas.

    Args:
        db_dir: Base directory for database files (default: .olav/db/)

    Returns:
        Dictionary mapping database names to validation status
    """
    manager = DatabaseSchemaManager(db_dir)
    return manager.validate_all()
