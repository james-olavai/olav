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

    def __init__(self, db_path: str | Path | None = None, read_only: bool = False) -> None:
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
        # Devices table (device metadata - v0.11.0 unified with Nornir import)
        # Note: This is auto-populated by devices_import.py from hosts.yaml
        # DO NOT modify schema manually - always use devices_import.py for updates
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS devices (
                device_id VARCHAR PRIMARY KEY,
                name VARCHAR,
                hostname VARCHAR,
                platform VARCHAR,
                mgmt_ip VARCHAR,
                device_type VARCHAR,
                device_role VARCHAR,
                site VARCHAR,
                location VARCHAR,
                vendor VARCHAR,
                model VARCHAR,
                site_id VARCHAR,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE
            )
        """)
        
        # Device capabilities cache (platinum/gold driver mapping)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS device_capabilities (
                hostname VARCHAR PRIMARY KEY,
                preferred_driver VARCHAR,
                last_success TIMESTAMP,
                features JSON
            )
        """)

        # Topology links table (v0.10.2 - network topology with history)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS topology_links (
                link_id VARCHAR PRIMARY KEY,
                source_device VARCHAR NOT NULL,
                source_interface VARCHAR NOT NULL,
                destination_device VARCHAR NOT NULL,
                destination_interface VARCHAR NOT NULL,
                discovery_protocol VARCHAR,
                link_type VARCHAR,
                link_status VARCHAR DEFAULT 'up',
                link_speed VARCHAR,
                first_seen TIMESTAMP NOT NULL,
                last_seen TIMESTAMP NOT NULL,
                last_verified TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status_changes INTEGER DEFAULT 0,
                sync_date DATE NOT NULL,
                platform VARCHAR,
                UNIQUE(source_device, source_interface, destination_device, destination_interface, sync_date)
            )
        """)
        
        # Indexes for topology queries
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_topology_src ON topology_links(source_device)
        """)
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_topology_dst ON topology_links(destination_device)
        """)
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_topology_sync_date ON topology_links(sync_date)
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

        # Knowledge chunks table (v0.10.1 - Unified with knowledge base)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_chunks (
                chunk_id VARCHAR PRIMARY KEY DEFAULT uuid(),
                file_path VARCHAR NOT NULL,
                content TEXT NOT NULL,
                embedding FLOAT[768],
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create indexes for knowledge chunks
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_knowledge_file_path
            ON knowledge_chunks(file_path)
        """)
        
        # Audit logs table (Phase 3: Command execution audit trail)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                log_id VARCHAR PRIMARY KEY DEFAULT uuid(),
                thread_id VARCHAR,
                device VARCHAR NOT NULL,
                command VARCHAR NOT NULL,
                output TEXT,
                success BOOLEAN DEFAULT TRUE,
                duration_ms INTEGER,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Index for audit logs queries
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_device ON audit_logs(device)
        """)
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_logs(timestamp)
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
    ) -> None:
        """Log command execution to audit trail.
        
        Phase 3: Audit logging for network command execution.
        
        Args:
            thread_id: Session/thread identifier
            device: Device name or IP
            command: Executed command
            output: Command output (truncated if too large)
            success: Whether execution succeeded
            duration_ms: Execution duration in milliseconds
        """
        # Truncate output if too large (prevent database bloat)
        max_output_size = 100_000
        if len(output) > max_output_size:
            output = output[:max_output_size] + "\n... (truncated)"
        
        try:
            self.conn.execute("""
                INSERT INTO audit_logs (thread_id, device, command, output, success, duration_ms)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (thread_id, device, command, output, success, duration_ms))
        except Exception as e:
            # Don't fail the entire execution if audit logging fails
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to log execution to audit trail: {e}")

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


def get_database(db_path: str | Path | None = None, read_only: bool = False) -> OlavDatabase:
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

    # Create knowledge chunks table with full-text search (v0.9.8: no vector embeddings)
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
            file_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Create full-text search index (v0.9.8: keyword-based search only)
    try:
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_chunks_fts
            ON knowledge_chunks USING FTS(title, content, keywords)
        """)
    except Exception as e:
        print(f"Warning: Could not create FTS index: {e}")

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
    # 解析命令输出表 (v0.13.0) - 简洁设计, 仅存储JSON解析结果
    # =============================================================================
    conn.execute("""
        CREATE SEQUENCE IF NOT EXISTS parsed_outputs_id_seq START 1
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS parsed_outputs (
            id INTEGER PRIMARY KEY DEFAULT nextval('parsed_outputs_id_seq'),
            device_name VARCHAR NOT NULL,
            command VARCHAR NOT NULL,              -- 执行的命令 (e.g., "show version")
            parsed_data JSON NOT NULL,             -- TextFSM 解析结果 (JSON格式)
            snapshot_date DATE NOT NULL,           -- 采集日期
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(device_name, command, snapshot_date)
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_parsed_device ON parsed_outputs(device_name)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_parsed_command ON parsed_outputs(command)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_parsed_date ON parsed_outputs(snapshot_date)
    """)

    return conn
