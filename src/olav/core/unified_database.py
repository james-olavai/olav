"""Unified database layer for cross-database queries.

This module provides a unified query interface across all three OLAV databases:
- network_main.duckdb: Topology, parsed data, structured network data
- network_commands.duckdb: Capabilities, audit logs, command cache
- knowledge.duckdb: Documents, embeddings, fault patterns

Uses DuckDB's ATTACH mechanism to enable cross-database JOINs.
"""

from typing import Any

import duckdb
import threading

from config.paths import KNOWLEDGE_PATH, NETWORK_COMMANDS_PATH, NETWORK_SNAPSHOT_PATH


class UnifiedDatabase:
    """Unified database query layer for cross-database operations.

    This class creates an in-memory DuckDB connection and attaches all three
    OLAV databases, enabling SQL queries that join data across databases.

    Example:
        >>> udb = UnifiedDatabase()
        >>> # Query device health with command capabilities
        >>> result = udb.query('''
        ...     SELECT d.name, d.platform, COUNT(c.id) as cmd_count
        ...     FROM main.topology_devices d
        ...     LEFT JOIN commands.capabilities c ON c.platform = d.platform
        ...     GROUP BY d.name, d.platform
        ... ''')
        >>> udb.close()
    """

    _lock = threading.RLock()

    def __init__(self):
        """Initialize unified database with all three databases attached."""
        with UnifiedDatabase._lock:
            # Create a private connection for this instance (Ephemeral Model)
            self.conn = duckdb.connect()

            # 1. Define paths
            snapshot_path = str(NETWORK_SNAPSHOT_PATH)
            commands_path = str(NETWORK_COMMANDS_PATH)
            knowledge_path = str(KNOWLEDGE_PATH)

            # Track attached paths to prevent "Unique file handle conflict"
            attached_paths = set()

            # 2. Attach Commands (User-Local Cache - Primary RW)
            import time
            from pathlib import Path
            from config.paths import USER_CACHE_PATH
            
            # Ensure user cache directory exists
            try:
                Path(USER_CACHE_PATH).parent.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
                
            user_cache_path = str(USER_CACHE_PATH)
            
            for attempt in range(3):
                try:
                    # Attempt 1: Mount User-Local Cache as 'commands' (Read-Write)
                    self.conn.execute(f"ATTACH IF NOT EXISTS '{user_cache_path}' AS commands")
                    attached_paths.add(user_cache_path)
                    break
                except Exception as e:
                    if attempt < 2 and "being detached" in str(e):
                        time.sleep(0.2)
                        continue
                    
                    try:
                        # Fallback: Mount Shared Commands as 'commands' (Read-Only)
                        # This allows reading pre-seeded semantic cache if user cache fails
                        self.conn.execute(f"ATTACH IF NOT EXISTS '{commands_path}' AS commands (READ_ONLY)")
                        attached_paths.add(commands_path)
                        break
                    except Exception:
                        if attempt < 2:
                            time.sleep(0.2)
                            continue
                        pass

            # 3. Attach Snapshot (Skip if already attached as commands)
            if snapshot_path not in attached_paths:
                try:
                    self.conn.execute(f"ATTACH IF NOT EXISTS '{snapshot_path}' AS db_snapshot")
                    attached_paths.add(snapshot_path)
                except Exception:
                     pass
            
            # 4. Attach Knowledge (Skip if already attached)
            if knowledge_path not in attached_paths:
                try:
                    self.conn.execute(f"ATTACH IF NOT EXISTS '{knowledge_path}' AS knowledge")
                    attached_paths.add(knowledge_path)
                except Exception:
                    pass

            # Update search path dynamically based on attached catalogs
            catalogs = self.conn.execute("SELECT catalog_name FROM information_schema.schemata").fetchall()
            attached = {c[0] for c in catalogs}
            paths = ["main", "commands", "db_snapshot", "knowledge"]
            active_paths = [p for p in paths if p in attached or p == "main"]
            self.conn.execute(f"SET search_path = '{','.join(active_paths)}'")

            # 5. Create compatibility views in 'main'
            try:
                # Core views that MUST exist for agents to function
                # Mapping: view_name -> source_table
                CORE_VIEWS = {
                    "v_interfaces": "v_interfaces",
                    "v_bgp_neighbors": "v_bgp_neighbors",
                    "v_routes": "v_routes",
                    "v_ospf_neighbors": "v_ospf_neighbors",
                    "v_device_status": "v_device_status",
                    "v_arp": "v_arp",
                    "v_cdp_neighbors": "v_cdp_neighbors",
                    "v_cpu_utilization": "v_cpu_utilization",
                    "v_memory_utilization": "v_memory_utilization",
                    "v_device_capabilities": "v_device_capabilities"
                }

                source = "commands" # Primary catalog
                # Verify if 'commands' catalog is actually attached
                catalogs = self.conn.execute("SELECT catalog_name FROM information_schema.schemata").fetchall()
                is_commands_attached = any(c[0] == "commands" for c in catalogs)

                if is_commands_attached:
                    # Method 1: Dynamic exposure (if schemas are ready)
                    try:
                        views = self.conn.execute(f"SELECT table_name FROM {source}.information_schema.tables WHERE table_name LIKE 'v_%'").fetchall()
                        for v in views:
                            self.conn.execute(f"CREATE OR REPLACE VIEW main.{v[0]} AS SELECT * FROM {source}.{v[0]}")
                    except Exception:
                        # Method 2: Static fallback (if info_schema is stubborn)
                        for view_name in CORE_VIEWS:
                            try:
                                self.conn.execute(f"CREATE VIEW IF NOT EXISTS main.{view_name} AS SELECT * FROM {source}.{view_name}")
                            except Exception:
                                pass
            except Exception:
                pass
            
            # 6. Initialize Semantic Cache table (Safe check)
            try:
                if is_commands_attached:
                    # Ensure schema exists (User-local DB might be empty)
                    self.conn.execute("CREATE SCHEMA IF NOT EXISTS commands.main")
                    
                    self.conn.execute("""
                        CREATE TABLE IF NOT EXISTS commands.main.semantic_cache (
                            query_text TEXT,
                            query_embedding FLOAT[768],
                            action_json JSON,
                            confidence FLOAT,
                            last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        );

                        -- Create Session History table (Phase 8)
                        CREATE TABLE IF NOT EXISTS commands.main.session_history (
                            id UUID DEFAULT uuid(),
                            session_id UUID,
                            role TEXT,
                            content TEXT,
                            metadata JSON,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        );
                    """)
            except Exception:
                pass

    def query(self, sql: str, params: list[Any] | None = None) -> list[tuple]:
        """Execute SQL query across attached databases.
        
        This method is thread-safe.
        """
        with UnifiedDatabase._lock:
            if params:
                return self.conn.execute(sql, params).fetchall()
            return self.conn.execute(sql).fetchall()

    def query_df(self, sql: str, params: list[Any] | None = None) -> Any:
        """Execute SQL query and return pandas DataFrame.
        
        This method is thread-safe.
        """
        with UnifiedDatabase._lock:
            if params:
                return self.conn.execute(sql, params).df()
            return self.conn.execute(sql).df()

    def find_ip_location(self, ip: str) -> dict[str, Any]:
        """Find which device and interface has this IP address.
        
        This method is thread-safe.
        """
        with UnifiedDatabase._lock:
            result = self.conn.execute(
                """
                SELECT device, interface, hardware_address
                FROM main.v_arp
                WHERE address = ?
                LIMIT 1
            """,
                [ip],
            ).fetchone()

            if result:
                return {
                    "device_name": result[0],
                    "interface": result[1],
                    "mac_address": result[2],
                }
            return {}

    def get_device_health(self, device: str) -> dict[str, Any]:
        """Get comprehensive health status for a device.
        
        This method is thread-safe.
        """
        with UnifiedDatabase._lock:
            # Get device info from version view
            device_info = self.conn.execute(
                """
                SELECT device, version, hostname
                FROM main.v_device_status
                WHERE device = ? OR hostname = ?
            """,
                [device, device],
            ).fetchone()

            if not device_info:
                return {"error": f"Device {device} not found in version data"}

            # Get counts using main schema views
            arp_count = self.conn.execute("SELECT COUNT(*) FROM main.v_arp WHERE device = ?", [device_info[0]]).fetchone()[0]
            route_count = self.conn.execute("SELECT COUNT(*) FROM main.v_routes WHERE device = ?", [device_info[0]]).fetchone()[0]
            int_count = self.conn.execute("SELECT COUNT(*) FROM main.v_interfaces WHERE device = ?", [device_info[0]]).fetchone()[0]

            return {
                "device_name": device_info[0],
                "version": device_info[1],
                "hostname": device_info[2],
                "arp_entries": arp_count,
                "routes": route_count,
                "interfaces": int_count,
            }

    def get_network_summary(self) -> dict[str, Any]:
        """Get network-wide summary statistics using main schema views."""
        with UnifiedDatabase._lock:
            device_count = self.conn.execute("SELECT COUNT(DISTINCT device) FROM main.v_device_status").fetchone()[0]
            arp_count = self.conn.execute("SELECT COUNT(*) FROM main.v_arp").fetchone()[0]
            route_count = self.conn.execute("SELECT COUNT(*) FROM main.v_routes").fetchone()[0]

            return {
                "devices": device_count,
                "arp_entries": arp_count,
                "routes": route_count,
            }

    def search_ip_across_network(self, ip_pattern: str) -> list[dict]:
        """Search for IP addresses matching pattern across all devices.
        
        This method is thread-safe.
        """
        with UnifiedDatabase._lock:
            results = self.conn.execute(
                """
                SELECT 
                    device_name,
                    ip_address,
                    mac_address,
                    interface,
                    snapshot_date
                FROM main.arp_table
                WHERE ip_address LIKE ?
                ORDER BY device_name, ip_address
            """,
                [ip_pattern],
            ).fetchall()

            return [
                {
                    "device": r[0],
                    "ip": r[1],
                    "mac": r[2],
                    "interface": r[3],
                    "date": str(r[4]),
                }
                for r in results
            ]

    def audit_command_authorization(self, hours: int = 24) -> list[dict[str, Any]]:
        """Audit recent commands against whitelist.
        
        This method is thread-safe.
        """
        with UnifiedDatabase._lock:
            results = self.conn.execute(
                f"""
                SELECT 
                    a.timestamp,
                    a.device,
                    d.role,
                    a.command,
                    CASE 
                        WHEN c.id IS NOT NULL THEN 'authorized'
                        WHEN a.command LIKE 'show%' THEN 'unknown_read'
                        ELSE 'unauthorized_write'
                    END as status,
                    c.is_write
                FROM commands.audit_logs a
                JOIN main.topology_devices d ON a.device = d.name
                LEFT JOIN commands.capabilities c 
                    ON a.command LIKE '%' || c.name || '%' 
                    AND c.platform = d.platform
                WHERE a.timestamp > NOW() - INTERVAL {hours} HOUR
                ORDER BY 
                    CASE 
                        WHEN c.id IS NULL THEN 0 
                        ELSE 1 
                    END,
                    a.timestamp DESC
            """
            ).fetchall()

            return [
                {
                    "timestamp": str(r[0]),
                    "device": r[1],
                    "role": r[2],
                    "command": r[3],
                    "status": r[4],
                    "is_write": r[5],
                }
                for r in results
            ]

    def search_semantic_cache(self, embedding: list[float], threshold: float = 0.95) -> dict[str, Any] | None:
        """Search the semantic cache for a similar query.
        
        This method is thread-safe.
        """
        import json
        with UnifiedDatabase._lock:
            try:
                res = self.conn.execute("""
                    SELECT action_json, array_cosine_similarity(query_embedding, ?::FLOAT[]) as score
                    FROM commands.main.semantic_cache
                    WHERE score > ?
                    ORDER BY score DESC
                    LIMIT 1
                """, [embedding, threshold]).fetchone()
                
                if res:
                    action_json = res[0]
                    # Update last_used
                    try:
                        self.conn.execute(
                            "UPDATE commands.main.semantic_cache SET last_used = CURRENT_TIMESTAMP WHERE action_json = ?",
                            [action_json]
                        )
                    except Exception:
                        pass
                    return json.loads(action_json)
            except Exception:
                pass
                
            return None

    def save_semantic_cache(self, query: str, embedding: list[float], action: dict[str, Any], confidence: float = 1.0) -> None:
        """Save a successful query and its action to the semantic cache.
        
        This method is thread-safe.
        """
        import json
        with UnifiedDatabase._lock:
            try:
                self.conn.execute("""
                    INSERT INTO commands.main.semantic_cache (query_text, query_embedding, action_json, confidence)
                    VALUES (?, ?::FLOAT[], ?, ?)
                """, [query, embedding, json.dumps(action), confidence])
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Save semantic cache failed: {e}")

    def close(self) -> None:
        """Close database connection."""
        if self.conn:
            with UnifiedDatabase._lock:
                try:
                    self.conn.close()
                except Exception:
                    pass
                self.conn = None

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
