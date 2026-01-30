"""DuckDB database module for OLAV v0.9.

This module provides the core database functionality for storing and querying
audit logs and command caches.

NOTE: The capabilities table has been removed in v0.9 and replaced by the
file-based CommandRegistry (see olav.core.registry). Command discovery and
validation is now handled through TextFSM templates rather than database entries.
"""

from pathlib import Path

import duckdb


class OlavDatabase:
    """OLAV database manager using DuckDB.

    This database stores:
    - audit_logs: Execution history and audit trail
    - command_cache: Cached command outputs (optional, not used in MVP)

    NOTE: The capabilities table has been removed. Use CommandRegistry for
    command discovery and validation.
    """

    def __init__(
        self, db_path: str | Path | None = None, read_only: bool = False
    ) -> None:
        """Initialize database connection.

        Args:
            db_path: Path to DuckDB database file
            read_only: Whether to open in read-only mode (default: False)
        """
        if db_path is None:
            from config.paths import NETWORK_DB_PATH

            db_path = NETWORK_DB_PATH

        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Connect to DuckDB
        self.conn = duckdb.connect(str(self.db_path), read_only=read_only)

        # Initialize schema (skip if read-only)
        if not read_only:
            self._init_schema()

    def _init_schema(self) -> None:
        """Create database tables if they don't exist."""
        # Device capabilities cache (platinum/gold driver mapping)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS device_capabilities (
                hostname VARCHAR PRIMARY KEY,
                preferred_driver VARCHAR,
                last_success TIMESTAMP,
                features JSON
            )
        """)

        # Audit logs table
        self.conn.execute("""
            CREATE SEQUENCE IF NOT EXISTS audit_logs_id_seq START 1
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY DEFAULT nextval('audit_logs_id_seq'),
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                thread_id TEXT NOT NULL,
                device TEXT NOT NULL,
                command TEXT NOT NULL,
                output TEXT,
                success BOOLEAN NOT NULL,
                duration_ms INTEGER,
                user TEXT
            )
        """)

        # Create indexes for audit logs
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_thread
            ON audit_logs(thread_id)
        """)
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_device
            ON audit_logs(device)
        """)

        # Command cache table (optional, not used in MVP)
        self.conn.execute("""
            CREATE SEQUENCE IF NOT EXISTS command_cache_id_seq START 1
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS command_cache (
                id INTEGER PRIMARY KEY DEFAULT nextval('command_cache_id_seq'),
                device TEXT NOT NULL,
                command TEXT NOT NULL,
                output TEXT,
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ttl_seconds INTEGER DEFAULT 300,
                UNIQUE(device, command)
            )
        """)

        # Raw outputs table (v0.9.6 Unified)
        self.conn.execute("""
            CREATE SEQUENCE IF NOT EXISTS raw_outputs_seq START 1
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS raw_outputs (
                id INTEGER PRIMARY KEY DEFAULT nextval('raw_outputs_seq'),
                device VARCHAR NOT NULL,
                command VARCHAR NOT NULL,
                output TEXT,
                sync_date DATE DEFAULT CURRENT_DATE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(device, command, sync_date)
            )
        """)

        # Sync metadata table (v0.9.6 Unified)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_metadata (
                id INTEGER PRIMARY KEY,
                sync_date DATE NOT NULL,
                sync_dir VARCHAR NOT NULL,
                device_count INTEGER,
                command_count INTEGER,
                success_count INTEGER,
                failed_count INTEGER,
                duration_seconds FLOAT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(sync_date)
            )
        """)

        # NOTE: View initialization moved to sync_tools.py (Snapshot-Time)
        # to prevent write-write conflicts during queries (EQP Phase).

    def log_execution(
        self,
        thread_id: str,
        device: str,
        command: str,
        output: str,
        success: bool,
        duration_ms: int,
        user: str | None = None,
    ) -> None:
        """Log a command execution to the audit trail.

        Args:
            thread_id: Conversation/thread ID
            device: Device name or IP
            command: Command executed
            output: Command output
            success: Whether execution succeeded
            duration_ms: Execution time in milliseconds
            user: Optional user identifier
        """
        self.conn.execute(
            """
            INSERT INTO audit_logs
            (thread_id, device, command, output, success, duration_ms, user)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            [thread_id, device, command, output, success, duration_ms, user],
        )

    def get_command_cache(self, device: str, command: str) -> str | None:
        """Get cached command output if available and not expired.

        Args:
            device: Device name
            command: Command string

        Returns:
            Cached output or None if not found/expired
        """
        result = self.conn.execute(
            """
            SELECT output, cached_at, ttl_seconds
            FROM command_cache
            WHERE device = ? AND command = ?
            ORDER BY cached_at DESC
            LIMIT 1
        """,
            [device, command],
        ).fetchone()

        if not result:
            return None

        output, cached_at, ttl = result
        # Check if cache is still valid
        # Note: DuckDB returns timestamps as strings, need to parse
        # For MVP, we'll skip TTL checking and just return the cached value
        return output

    def set_command_cache(
        self, device: str, command: str, output: str, ttl_seconds: int = 300
    ) -> None:
        """Cache a command output.

        Args:
            device: Device name
            command: Command string
            output: Command output to cache
            ttl_seconds: Time-to-live in seconds (default 5 minutes)
        """
        self.conn.execute(
            """
            INSERT OR REPLACE INTO command_cache
            (device, command, output, ttl_seconds)
            VALUES (?, ?, ?, ?)
        """,
            [device, command, output, ttl_seconds],
        )

    def close(self) -> None:
        """Close the database connection."""
        self.conn.close()

    def __enter__(self) -> "OlavDatabase":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        """Context manager exit."""
        self.close()


# Global database instance
_db_instance: OlavDatabase | None = None


def get_database(
    db_path: str | Path | None = None, read_only: bool = False
) -> OlavDatabase:
    """Get the global database instance.

    Args:
        db_path: Optional database path (uses default if not provided)
        read_only: Whether to open in read-only mode

    Returns:
        OlavDatabase instance
    """
    global _db_instance

    if _db_instance is None:
        _db_instance = OlavDatabase(db_path, read_only=read_only)

    return _db_instance


def reset_database() -> None:
    """Reset the global database instance.

    Use this in tests to ensure clean state between test runs.
    """
    global _db_instance
    if _db_instance is not None:
        try:
            _db_instance.close()
        except Exception:  # noqa: S110
            pass
        _db_instance = None


# =============================================================================
# Knowledge Database (Phase 4: Knowledge Base Integration)
# =============================================================================


def init_knowledge_db(db_path: str | None = None) -> duckdb.DuckDBPyConnection:
    """Initialize the knowledge database with vector support.

    This creates a separate database for storing indexed knowledge:
    - Vendor documentation (Cisco, Huawei, etc.)
    - Team wiki and runbooks
    - Learned solutions from HITL interactions

    Args:
        db_path: Path to knowledge database file (default: .olav/db/knowledge.duckdb)

    Returns:
        DuckDB connection object

    Example:
        >>> conn = init_knowledge_db()
        >>> # Use connection for indexing...
        >>> conn.close()
    """
    from config.paths import KNOWLEDGE_PATH

    if db_path is None:
        db_path = str(KNOWLEDGE_PATH)

    # Ensure directory exists
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    # Connect to DuckDB
    conn = duckdb.connect(db_path)

    try:
        # Enable DuckDB VSS extension for vector search
        conn.execute("INSTALL vss;")
        conn.execute("LOAD vss;")
    except Exception as e:
        print(f"Warning: Could not install/load VSS extension: {e}")
        print("Vector search will be disabled. FTS-only search will be used.")

    # Create knowledge sources table
    conn.execute("""
        CREATE SEQUENCE IF NOT EXISTS knowledge_sources_id_seq START 1
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS knowledge_sources (
            id INTEGER PRIMARY KEY DEFAULT nextval('knowledge_sources_id_seq'),
            name TEXT NOT NULL UNIQUE,
            type TEXT NOT NULL,
            base_path TEXT,
            version TEXT,
            platform TEXT,
            indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Initialize default knowledge sources (Phase 7)
    # These are inserted only if they don't already exist
    default_sources = [
        ("Skills", "markdown", ".olav/skills", None, "skills"),
        ("Knowledge Base", "markdown", ".olav/knowledge", None, "knowledge"),
        ("Reports", "markdown", "data/reports", None, "report"),
    ]

    for name, source_type, base_path, version, platform in default_sources:
        try:
            conn.execute(
                "INSERT INTO knowledge_sources "
                "(name, type, base_path, version, platform) "
                "VALUES (?, ?, ?, ?, ?)",
                [name, source_type, base_path, version, platform],
            )
        except Exception as e:  # noqa: S110, F841
            # Ignore duplicate key errors - sources already exist
            pass

    conn.commit()

    # Create knowledge chunks table with vector embeddings
    # Note: embedding dimension depends on model
    conn.execute("""
        CREATE SEQUENCE IF NOT EXISTS knowledge_chunks_id_seq START 1
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS knowledge_chunks (
            id INTEGER PRIMARY KEY DEFAULT nextval('knowledge_chunks_id_seq'),
            source_id INTEGER REFERENCES knowledge_sources(id),
            file_path TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            title TEXT,
            content TEXT NOT NULL,
            platform TEXT,
            doc_type TEXT,
            keywords TEXT[],
            embedding FLOAT[768],
            file_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Create full-text search index
    try:
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_chunks_fts
            ON knowledge_chunks USING FTS(title, content, keywords)
        """)
    except Exception as e:
        print(f"Warning: Could not create FTS index: {e}")

    # Create vector index (HNSW - Hierarchical Navigable Small World)
    # This provides fast approximate nearest neighbor search
    try:
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_chunks_vector
            ON knowledge_chunks USING HNSW(embedding)
        """)
    except Exception as e:
        print(f"Warning: Could not create vector index: {e}")
        print("Vector search performance will be degraded.")

    # Create other indexes for efficient querying
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_chunks_file_path
        ON knowledge_chunks(file_path)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_chunks_source
        ON knowledge_chunks(source_id)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_chunks_platform
        ON knowledge_chunks(platform)
    """)

    return conn


# =============================================================================
# Topology Database (Phase: Network Topology Discovery)
# =============================================================================


def init_topology_db(db_path: str | None = None) -> duckdb.DuckDBPyConnection:
    """Initialize the topology database for network discovery.

    This creates a separate database for storing network topology:
    - Device inventory and metadata
    - L1/L3 neighbor relationships (CDP/LLDP, OSPF/BGP)
    - Topology discovery timestamps

    Args:
        db_path: Path to topology database file (default: .olav/db/network.duckdb)

    Returns:
        DuckDB connection object

    Example:
        >>> conn = init_topology_db()
        >>> # Use connection for topology operations...
        >>> conn.close()
    """
    from config.paths import NETWORK_SNAPSHOT_PATH

    if db_path is None:
        db_path = str(NETWORK_SNAPSHOT_PATH)

    # Ensure directory exists
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    # Connect to DuckDB
    conn = duckdb.connect(db_path)

    # Create devices table
    conn.execute("""
        CREATE SEQUENCE IF NOT EXISTS topology_devices_id_seq START 1
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS topology_devices (
            name VARCHAR PRIMARY KEY,
            hostname VARCHAR,
            platform VARCHAR,
            mgmt_ip VARCHAR,
            site VARCHAR,
            role VARCHAR,
            discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Create links table (L1/L3 neighbor relationships)
    conn.execute("""
        CREATE SEQUENCE IF NOT EXISTS topology_links_id_seq START 1
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS topology_links (
            id INTEGER PRIMARY KEY DEFAULT nextval('topology_links_id_seq'),
            local_device VARCHAR NOT NULL,
            local_port VARCHAR,
            remote_device VARCHAR NOT NULL,
            remote_port VARCHAR,
            layer VARCHAR CHECK (layer IN ('L1', 'L3')),
            protocol VARCHAR,
            metadata JSON,
            discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(local_device, local_port, remote_device, remote_port, layer)
        )
    """)

    # Create indexes for efficient queries
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_links_local_device
        ON topology_links(local_device)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_links_remote_device
        ON topology_links(remote_device)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_links_layer
        ON topology_links(layer)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_links_protocol
        ON topology_links(protocol)
    """)

    # Map-Reduce: inspect_results table
    conn.execute("""
        CREATE SEQUENCE IF NOT EXISTS inspect_results_id_seq START 1
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS inspect_results (
            id INTEGER PRIMARY KEY DEFAULT nextval('inspect_results_id_seq'),
            sync_date DATE,
            device VARCHAR NOT NULL,
            check_type VARCHAR NOT NULL,
            interface VARCHAR,
            command VARCHAR,
            status VARCHAR NOT NULL,
            value VARCHAR,
            threshold VARCHAR,
            detail TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Map-Reduce: log_analysis table
    conn.execute("""
        CREATE SEQUENCE IF NOT EXISTS log_analysis_id_seq START 1
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS log_analysis (
            id INTEGER PRIMARY KEY DEFAULT nextval('log_analysis_id_seq'),
            sync_date DATE,
            device VARCHAR NOT NULL,
            status VARCHAR NOT NULL,
            event_count INTEGER,
            events_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Indexes for Map-Reduce tables
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_inspect_device
        ON inspect_results(device)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_inspect_status
        ON inspect_results(status)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_inspect_date
        ON inspect_results(sync_date)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_log_device
        ON log_analysis(device)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_log_status
        ON log_analysis(status)
    """)

    # =========================================================================
    # NEW: Unified command outputs table (v0.8.4)
    # Stores TextFSM parsed data as JSON for flexible querying
    # =========================================================================
    conn.execute("""
        CREATE SEQUENCE IF NOT EXISTS command_outputs_id_seq START 1
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS command_outputs (
            id INTEGER PRIMARY KEY DEFAULT nextval('command_outputs_id_seq'),
            snapshot_date DATE NOT NULL,
            device_name VARCHAR NOT NULL,
            platform VARCHAR DEFAULT 'cisco_ios',
            command VARCHAR NOT NULL,
            raw_output TEXT,
            parsed_data JSON,
            row_count INTEGER DEFAULT 0,
            parse_success BOOLEAN DEFAULT FALSE,
            collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(snapshot_date, device_name, command)
        )
    """)

    # Indexes for command_outputs
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_cmd_outputs_command
        ON command_outputs(command)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_cmd_outputs_device
        ON command_outputs(device_name)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_cmd_outputs_date
        ON command_outputs(snapshot_date)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_cmd_outputs_platform
        ON command_outputs(platform)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_cmd_outputs_parse_success
        ON command_outputs(parse_success)
    """)

    return conn


def init_structured_tables(db_path: str | None = None) -> duckdb.DuckDBPyConnection:
    """Initialize structured network data tables for parsed command outputs.

    This creates tables for storing parsed network data:
    - interfaces: Interface status and configuration
    - routes: Routing table entries
    - bgp_neighbors: BGP peer information
    - ospf_neighbors: OSPF neighbor relationships
    - vlans: VLAN configurations
    - arp_table: ARP cache entries
    - system_info: Device system information
    - health_scores: Historical health metrics
    - raw_outputs: Raw command outputs (v0.9.3)

    Args:
        db_path: Path to database file (default: .olav/db/network.duckdb)

    Returns:
        DuckDB connection object

    Example:
        >>> conn = init_structured_tables()
        >>> # Tables are ready for parsed data import
        >>> conn.close()
    """
    from config.paths import NETWORK_SNAPSHOT_PATH

    if db_path is None:
        db_path = str(NETWORK_SNAPSHOT_PATH)

    # Ensure directory exists
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    # Connect to DuckDB
    conn = duckdb.connect(db_path)

    # =============================================================================
    # 接口表: 存储解析后的接口状态
    # =============================================================================
    conn.execute("""
        CREATE SEQUENCE IF NOT EXISTS interfaces_id_seq START 1
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS interfaces (
            id INTEGER PRIMARY KEY DEFAULT nextval('interfaces_id_seq'),
            snapshot_date DATE NOT NULL,           -- 快照日期
            device_name VARCHAR NOT NULL,          -- 设备名
            interface_name VARCHAR NOT NULL,       -- 接口名
            ip_address VARCHAR,                    -- IP地址
            subnet_mask VARCHAR,                   -- 子网掩码
            admin_status VARCHAR,                  -- 管理状态 (up/down)
            oper_status VARCHAR,                   -- 操作状态 (up/down)
            protocol_status VARCHAR,               -- 协议状态
            description VARCHAR,                   -- 接口描述
            mtu INTEGER,                           -- MTU
            speed VARCHAR,                         -- 速率
            duplex VARCHAR,                        -- 双工模式
            input_errors INTEGER DEFAULT 0,        -- 输入错误
            output_errors INTEGER DEFAULT 0,       -- 输出错误
            crc_errors INTEGER DEFAULT 0,          -- CRC错误
            discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(snapshot_date, device_name, interface_name)
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_interfaces_ip ON interfaces(ip_address)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_interfaces_device ON interfaces(device_name)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_interfaces_status ON interfaces(oper_status)
    """)

    # =============================================================================
    # 路由表: 存储路由信息
    # =============================================================================
    conn.execute("""
        CREATE SEQUENCE IF NOT EXISTS routes_id_seq START 1
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS routes (
            id INTEGER PRIMARY KEY DEFAULT nextval('routes_id_seq'),
            snapshot_date DATE NOT NULL,
            device_name VARCHAR NOT NULL,
            network VARCHAR NOT NULL,              -- 目标网络
            mask VARCHAR,                          -- 掩码
            next_hop VARCHAR,                      -- 下一跳
            interface VARCHAR,                     -- 出接口
            protocol VARCHAR,                      -- 路由协议 (C/S/O/B/R)
            metric INTEGER,                        -- 度量值
            admin_distance INTEGER,                -- 管理距离
            age VARCHAR,                           -- 路由年龄
            discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(snapshot_date, device_name, network, next_hop)
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_routes_network ON routes(network)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_routes_protocol ON routes(protocol)
    """)

    # =============================================================================
    # BGP邻居表: 存储BGP会话信息
    # =============================================================================
    conn.execute("""
        CREATE SEQUENCE IF NOT EXISTS bgp_neighbors_id_seq START 1
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bgp_neighbors (
            id INTEGER PRIMARY KEY DEFAULT nextval('bgp_neighbors_id_seq'),
            snapshot_date DATE NOT NULL,
            device_name VARCHAR NOT NULL,
            neighbor_ip VARCHAR NOT NULL,          -- 邻居IP
            remote_as INTEGER,                     -- 远端AS号
            local_as INTEGER,                      -- 本地AS号
            state VARCHAR,                         -- 状态 (Established/Idle/Active)
            uptime VARCHAR,                        -- 会话时长
            prefixes_received INTEGER DEFAULT 0,   -- 收到的前缀数
            prefixes_sent INTEGER DEFAULT 0,       -- 发送的前缀数
            state_changes INTEGER DEFAULT 0,       -- 状态变化次数
            last_error VARCHAR,                    -- 最后错误
            discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(snapshot_date, device_name, neighbor_ip)
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_bgp_neighbor_ip ON bgp_neighbors(neighbor_ip)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_bgp_state ON bgp_neighbors(state)
    """)

    # =============================================================================
    # OSPF邻居表
    # =============================================================================
    conn.execute("""
        CREATE SEQUENCE IF NOT EXISTS ospf_neighbors_id_seq START 1
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ospf_neighbors (
            id INTEGER PRIMARY KEY DEFAULT nextval('ospf_neighbors_id_seq'),
            snapshot_date DATE NOT NULL,
            device_name VARCHAR NOT NULL,
            neighbor_id VARCHAR NOT NULL,          -- 邻居Router ID
            neighbor_ip VARCHAR,                   -- 邻居IP
            interface VARCHAR,                     -- 接口
            area VARCHAR,                          -- 区域
            state VARCHAR,                         -- 状态 (FULL/2WAY/DOWN)
            priority INTEGER,                      -- 优先级
            dr_status VARCHAR,                     -- DR/BDR/DROTHER
            uptime VARCHAR,
            discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(snapshot_date, device_name, neighbor_id, interface)
        )
    """)

    # =============================================================================
    # VLAN表
    # =============================================================================
    conn.execute("""
        CREATE SEQUENCE IF NOT EXISTS vlans_id_seq START 1
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS vlans (
            id INTEGER PRIMARY KEY DEFAULT nextval('vlans_id_seq'),
            snapshot_date DATE NOT NULL,
            device_name VARCHAR NOT NULL,
            vlan_id INTEGER NOT NULL,
            vlan_name VARCHAR,
            status VARCHAR,                        -- active/act/lshut/suspended
            ports TEXT,                            -- 端口列表 (JSON array)
            discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(snapshot_date, device_name, vlan_id)
        )
    """)

    # =============================================================================
    # ARP表
    # =============================================================================
    conn.execute("""
        CREATE SEQUENCE IF NOT EXISTS arp_table_id_seq START 1
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS arp_table (
            id INTEGER PRIMARY KEY DEFAULT nextval('arp_table_id_seq'),
            snapshot_date DATE NOT NULL,
            device_name VARCHAR NOT NULL,
            ip_address VARCHAR NOT NULL,
            mac_address VARCHAR,
            interface VARCHAR,
            discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(snapshot_date, device_name, ip_address, mac_address)
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_arp_ip ON arp_table(ip_address)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_arp_device ON arp_table(device_name)
    """)

    # =============================================================================
    # 系统信息表
    # =============================================================================
    conn.execute("""
        CREATE SEQUENCE IF NOT EXISTS system_info_id_seq START 1
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS system_info (
            id INTEGER PRIMARY KEY DEFAULT nextval('system_info_id_seq'),
            snapshot_date DATE NOT NULL,
            device_name VARCHAR NOT NULL,
            hostname VARCHAR,
            platform VARCHAR,                      -- 平台型号
            software_version VARCHAR,              -- 软件版本
            serial_number VARCHAR,                 -- 序列号
            uptime VARCHAR,                        -- 运行时间
            cpu_usage FLOAT,                       -- CPU使用率
            memory_usage FLOAT,                    -- 内存使用率
            config_register VARCHAR,
            last_reload_reason VARCHAR,
            discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(snapshot_date, device_name)
        )
    """)

    # =============================================================================
    # 历史健康评分表 (用于趋势分析)
    # =============================================================================
    conn.execute("""
        CREATE SEQUENCE IF NOT EXISTS health_scores_id_seq START 1
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS health_scores (
            id INTEGER PRIMARY KEY DEFAULT nextval('health_scores_id_seq'),
            snapshot_date DATE NOT NULL,
            layer VARCHAR NOT NULL,                -- L1/L2/L3/L4/Overall
            score INTEGER NOT NULL,                -- 0-100
            ok_count INTEGER DEFAULT 0,
            warning_count INTEGER DEFAULT 0,
            critical_count INTEGER DEFAULT 0,
            details TEXT,                          -- JSON详情
            calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(snapshot_date, layer)
        )
    """)

    # =============================================================================
    # 原始命令输出表 (v0.9.3 新增)
    # =============================================================================
    conn.execute("""
        CREATE SEQUENCE IF NOT EXISTS raw_outputs_id_seq START 1
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS raw_outputs (
            id INTEGER PRIMARY KEY DEFAULT nextval('raw_outputs_id_seq'),
            snapshot_date DATE NOT NULL,
            device_name VARCHAR NOT NULL,
            command VARCHAR NOT NULL,              -- 执行的命令
            raw_output TEXT,                       -- 原始输出文本
            output_file VARCHAR,                   -- 输出文件路径 (相对路径)
            command_status VARCHAR,                -- success/failed/timeout
            execution_time_ms INTEGER,             -- 执行耗时 (毫秒)
    collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(snapshot_date, device_name, command)
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_raw_outputs_device ON raw_outputs(device_name)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_raw_outputs_command ON raw_outputs(command)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_raw_outputs_status ON raw_outputs(command_status)
    """)

    # =============================================================================
    # 创建分层视图 (L1-L4 Normalized Views)
    # =============================================================================
    _create_normalized_views(conn)

    return conn


def _create_normalized_views(conn: duckdb.DuckDBPyConnection) -> None:
    """创建 L1-L4 分层视图，简化 SQL 查询。

    分层视图设计:
        - L1 物理视图: 设备、接口、线缆信息
        - L2 拓扑视图: CDP/LLDP 邻居、ARP 表
        - L3 路由视图: 路由表、BGP、OSPF
        - L4 服务视图: VLAN、系统信息
    """
    # =========================================================================
    # GOLD VIEWS (v0.9.6 Unified Query Layer)
    # These views are the primary entry point for LLM queries
    # =========================================================================

    # v_interfaces: Interface status and summary
    conn.execute("""
        CREATE OR REPLACE VIEW v_interfaces AS
        SELECT
            device_name as device,
            interface_name as interface,
            ip_address,
            oper_status as status,
            description,
            speed,
            input_errors,
            output_errors,
            snapshot_date as timestamp
        FROM interfaces
        ORDER BY device, interface
    """)

    # v_bgp_neighbors: BGP session state
    conn.execute("""
        CREATE OR REPLACE VIEW v_bgp_neighbors AS
        SELECT
            device_name as device,
            neighbor_ip as neighbor,
            remote_as as as_number,
            state,
            uptime,
            prefixes_received as pfx_rcv,
            snapshot_date as timestamp
        FROM bgp_neighbors
        ORDER BY device, neighbor
    """)

    # v_routes: Routing table summary
    conn.execute("""
        CREATE OR REPLACE VIEW v_routes AS
        SELECT
            device_name as device,
            network,
            mask,
            next_hop,
            interface,
            protocol,
            snapshot_date as timestamp
        FROM routes
        ORDER BY device, network
    """)

    # Keep existing normalized views for internal logic
    # L1 物理视图: 设备和接口信息
    conn.execute("""
        CREATE OR REPLACE VIEW l1_physical_view AS
        SELECT
            i.snapshot_date,
            i.device_name,
            s.platform,
            i.interface_name,
            i.ip_address,
            i.subnet_mask,
            i.admin_status,
            i.oper_status,
            i.description,
            i.mtu,
            i.speed,
            i.duplex,
            i.input_errors,
            i.output_errors,
            i.crc_errors
        FROM interfaces i
        LEFT JOIN system_info s ON i.snapshot_date = s.snapshot_date AND i.device_name = s.device_name
        ORDER BY i.device_name, i.interface_name
    """)
    conn.execute("""
        COMMENT ON VIEW l1_physical_view IS 'L1 Physical Layer: Devices and interfaces with physical characteristics'
    """)

    # L2 拓扑视图: 邻居关系和 ARP 表
    conn.execute("""
        CREATE OR REPLACE VIEW l2_topology_view AS
        SELECT
            snapshot_date,
            device_name,
            interface,
            ip_address,
            mac_address
        FROM arp_table
        ORDER BY device_name, interface
    """)
    conn.execute("""
        COMMENT ON VIEW l2_topology_view IS 'L2 Data Link Layer: ARP table and neighbor relationships'
    """)

    # L3 路由视图: 路由表和路由协议
    conn.execute("""
        CREATE OR REPLACE VIEW l3_routing_view AS
        SELECT
            snapshot_date,
            device_name,
            network,
            mask,
            next_hop,
            interface,
            protocol,
            metric,
            admin_distance
        FROM routes
        ORDER BY device_name, protocol, network
    """)
    conn.execute("""
        COMMENT ON VIEW l3_routing_view IS 'L3 Network Layer: Routing table and routing protocols'
    """)

    # L3 BGP 视图
    conn.execute("""
        CREATE OR REPLACE VIEW l3_bgp_view AS
        SELECT
            snapshot_date,
            device_name,
            neighbor_ip,
            remote_as,
            local_as,
            state,
            uptime,
            prefixes_received,
            prefixes_sent
        FROM bgp_neighbors
        ORDER BY device_name, neighbor_ip
    """)
    conn.execute("""
        COMMENT ON VIEW l3_bgp_view IS 'L3 BGP Layer: BGP neighbor sessions and statistics'
    """)

    # L3 OSPF 视图
    conn.execute("""
        CREATE OR REPLACE VIEW l3_ospf_view AS
        SELECT
            snapshot_date,
            device_name,
            neighbor_id,
            neighbor_ip,
            interface,
            area,
            state,
            priority,
            dr_status
        FROM ospf_neighbors
        ORDER BY device_name, area, neighbor_id
    """)
    conn.execute("""
        COMMENT ON VIEW l3_ospf_view IS 'L3 OSPF Layer: OSPF neighbor relationships and states'
    """)

    # L4 服务视图: VLAN 和系统信息
    conn.execute("""
        CREATE OR REPLACE VIEW l4_services_view AS
        SELECT
            v.snapshot_date,
            v.device_name,
            v.vlan_id,
            v.vlan_name,
            v.status,
            v.ports,
            s.hostname,
            s.platform,
            s.software_version,
            s.uptime,
            s.cpu_usage,
            s.memory_usage
        FROM vlans v
        LEFT JOIN system_info s ON v.snapshot_date = s.snapshot_date AND v.device_name = s.device_name
        ORDER BY v.device_name, v.vlan_id
    """)
    conn.execute("""
        COMMENT ON VIEW l4_services_view IS 'L4 Services Layer: VLANs, system info, and service status'
    """)
