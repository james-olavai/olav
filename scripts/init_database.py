#!/usr/bin/env python3
"""Initialize OLAV Main Database

Creates the unified database with standard schema for:
- Device inventory
- Network interfaces  
- CLI outputs
- Audit logs
- Knowledge base

Usage:
    uv run python scripts/init_database.py
    
    # With test data
    uv run python scripts/init_database.py --with-test-data
"""

import argparse
import sys
from pathlib import Path

import duckdb

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from config.paths import get_database_path
from config.settings import settings


def create_schema(conn: duckdb.DuckDBPyConnection):
    """Create standard OLAV database schema."""
    
    print("Creating database schema...")
    
    # 1. 设备表（核心表）
    conn.execute("""
    CREATE TABLE IF NOT EXISTS devices (
        id INTEGER PRIMARY KEY,
        name TEXT UNIQUE NOT NULL,
        hostname TEXT,
        ip TEXT,
        platform TEXT,
        device_role TEXT,
        site TEXT,
        vendor TEXT,
        model TEXT,
        version TEXT,
        serial_number TEXT,
        description TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    print("  ✅ devices")
    
    # 2. 接口表
    conn.execute("""
    CREATE TABLE IF NOT EXISTS interfaces (
        id INTEGER PRIMARY KEY,
        device TEXT NOT NULL,
        interface_name TEXT NOT NULL,
        ip_address TEXT,
        subnet_mask TEXT,
        status TEXT,
        protocol_status TEXT,
        description TEXT,
        mtu INTEGER,
        speed TEXT,
        duplex TEXT,
        vlan INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(device, interface_name)
    );
    """)
    print("  ✅ interfaces")
    
    # 3. CLI原始输出表
    conn.execute("""
    CREATE TABLE IF NOT EXISTS raw_outputs (
        id INTEGER PRIMARY KEY,
        device TEXT NOT NULL,
        command TEXT NOT NULL,
        output TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        platform TEXT,
        success BOOLEAN DEFAULT true,
        error_message TEXT
    );
    """)
    print("  ✅ raw_outputs")
    
    # 4. 设备能力表
    conn.execute("""
    CREATE TABLE IF NOT EXISTS device_capabilities (
        id INTEGER PRIMARY KEY,
        device TEXT UNIQUE NOT NULL,
        platform TEXT,
        features JSON,
        protocols JSON,
        discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    print("  ✅ device_capabilities")
    
    # 5. 审计日志表
    conn.execute("""
    CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        skill TEXT,
        device TEXT,
        command TEXT,
        status TEXT,
        error TEXT,
        user_id TEXT,
        session_id TEXT
    );
    """)
    print("  ✅ audit_logs")
    
    # 6. 知识库源表
    conn.execute("""
    CREATE TABLE IF NOT EXISTS knowledge_sources (
        id INTEGER PRIMARY KEY,
        source_type TEXT NOT NULL,
        source_path TEXT UNIQUE NOT NULL,
        title TEXT,
        description TEXT,
        metadata JSON,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    print("  ✅ knowledge_sources")
    
    # 7. 知识库向量表
    conn.execute("""
    CREATE TABLE IF NOT EXISTS knowledge_chunks (
        id INTEGER PRIMARY KEY,
        source_id INTEGER NOT NULL,
        chunk_text TEXT NOT NULL,
        chunk_index INTEGER,
        embedding JSON,
        metadata JSON,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (source_id) REFERENCES knowledge_sources(id)
    );
    """)
    print("  ✅ knowledge_chunks")
    
    # 8. 命令缓存表
    conn.execute("""
    CREATE TABLE IF NOT EXISTS command_cache (
        id INTEGER PRIMARY KEY,
        device TEXT NOT NULL,
        command TEXT NOT NULL,
        output TEXT,
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        ttl_seconds INTEGER DEFAULT 300,
        UNIQUE(device, command)
    );
    """)
    print("  ✅ command_cache")
    
    # 9. 同步元数据表
    conn.execute("""
    CREATE TABLE IF NOT EXISTS sync_metadata (
        id INTEGER PRIMARY KEY,
        sync_type TEXT NOT NULL,
        last_sync TIMESTAMP,
        status TEXT,
        records_processed INTEGER DEFAULT 0,
        error_message TEXT
    );
    """)
    print("  ✅ sync_metadata")
    
    # 10. 拓扑链接表（可选）
    conn.execute("""
    CREATE TABLE IF NOT EXISTS topology_links (
        id INTEGER PRIMARY KEY,
        local_device TEXT NOT NULL,
        local_interface TEXT NOT NULL,
        remote_device TEXT,
        remote_interface TEXT,
        link_type TEXT,
        discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(local_device, local_interface)
    );
    """)
    print("  ✅ topology_links")
    
    # Create indexes for performance
    print("\nCreating indexes...")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_devices_role ON devices(device_role);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_devices_site ON devices(site);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_interfaces_device ON interfaces(device);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_raw_outputs_device ON raw_outputs(device);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_raw_outputs_timestamp ON raw_outputs(timestamp);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_logs_device ON audit_logs(device);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_logs_timestamp ON audit_logs(timestamp);")
    print("  ✅ Indexes created")


def insert_test_data(conn: duckdb.DuckDBPyConnection):
    """Insert test data for development/demo."""
    
    print("\nInserting test data...")
    
    # Test devices
    test_devices = [
        (1, "R1", "r1.lab.local", "10.1.1.1", "cisco_ios", "border", "LAB", "Cisco", "CSR1000V", "17.3.1"),
        (2, "R2", "r2.lab.local", "10.1.1.2", "cisco_ios", "border", "LAB", "Cisco", "CSR1000V", "17.3.1"),
        (3, "R3", "r3.lab.local", "10.1.1.3", "cisco_ios", "core", "LAB", "Cisco", "CSR1000V", "17.3.1"),
        (4, "R4", "r4.lab.local", "10.1.1.4", "cisco_ios", "core", "LAB", "Cisco", "CSR1000V", "17.3.1"),
        (5, "SW1", "sw1.lab.local", "10.1.1.5", "cisco_ios", "access", "LAB", "Cisco", "C9300", "16.12.3"),
        (6, "SW2", "sw2.lab.local", "10.1.1.6", "cisco_ios", "access", "LAB", "Cisco", "C9300", "16.12.3"),
    ]
    
    conn.executemany("""
        INSERT INTO devices 
        (id, name, hostname, ip, platform, device_role, site, vendor, model, version)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (id) DO UPDATE SET
            name = EXCLUDED.name,
            hostname = EXCLUDED.hostname,
            ip = EXCLUDED.ip,
            platform = EXCLUDED.platform,
            device_role = EXCLUDED.device_role,
            site = EXCLUDED.site,
            vendor = EXCLUDED.vendor,
            model = EXCLUDED.model,
            version = EXCLUDED.version
    """, test_devices)
    print(f"  ✅ Inserted {len(test_devices)} test devices")
    
    # Test interfaces
    test_interfaces = [
        (1, "R1", "GigabitEthernet0/0", "192.168.1.1", "255.255.255.0", "up", "up", "LAN Interface", 1500, "1000", "full", None),
        (2, "R1", "GigabitEthernet0/1", "10.0.0.1", "255.255.255.252", "up", "up", "WAN to R2", 1500, "1000", "full", None),
        (3, "R2", "GigabitEthernet0/0", "192.168.2.1", "255.255.255.0", "up", "up", "LAN Interface", 1500, "1000", "full", None),
        (4, "R2", "GigabitEthernet0/1", "10.0.0.2", "255.255.255.252", "up", "up", "WAN to R1", 1500, "1000", "full", None),
    ]
    
    conn.executemany("""
        INSERT INTO interfaces
        (id, device, interface_name, ip_address, subnet_mask, status, protocol_status, 
         description, mtu, speed, duplex, vlan)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (id) DO UPDATE SET
            device = EXCLUDED.device,
            interface_name = EXCLUDED.interface_name,
            ip_address = EXCLUDED.ip_address,
            status = EXCLUDED.status
    """, test_interfaces)
    print(f"  ✅ Inserted {len(test_interfaces)} test interfaces")
    
    # Test raw outputs
    test_outputs = [
        (1, "R1", "show version", "Cisco IOS XE Software, Version 17.3.1\nUptime: 30 days", "cisco_ios", True, None),
        (2, "R2", "show version", "Cisco IOS XE Software, Version 17.3.1\nUptime: 25 days", "cisco_ios", True, None),
    ]
    
    conn.executemany("""
        INSERT INTO raw_outputs
        (id, device, command, output, platform, success, error_message)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (id) DO UPDATE SET
            device = EXCLUDED.device,
            command = EXCLUDED.command,
            output = EXCLUDED.output
    """, test_outputs)
    print(f"  ✅ Inserted {len(test_outputs)} test CLI outputs")


def main():
    parser = argparse.ArgumentParser(description="Initialize OLAV database")
    parser.add_argument(
        "--with-test-data",
        action="store_true",
        help="Insert test data for development/demo"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Recreate database even if it exists"
    )
    args = parser.parse_args()
    
    # Get database path from configuration
    db_path = get_database_path()
    
    print(f"OLAV Database Initialization")
    print(f"=" * 60)
    print(f"Database path: {db_path}")
    print(f"Config source: {settings.database.main_db}")
    print()
    
    # Check if database exists
    if db_path.exists() and not args.force:
        print(f"⚠️  Database already exists: {db_path}")
        response = input("Recreate database? This will DELETE all data. (yes/no): ")
        if response.lower() != "yes":
            print("Aborted.")
            return
        print()
    
    # Ensure directory exists
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Create/connect to database
    print(f"Creating database: {db_path}")
    conn = duckdb.connect(str(db_path))
    
    try:
        # Create schema
        create_schema(conn)
        
        # Insert test data if requested
        if args.with_test_data:
            insert_test_data(conn)
        
        # Verify
        print("\nVerifying database...")
        tables = conn.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'main'
            ORDER BY table_name
        """).fetchall()
        
        print(f"\nCreated tables ({len(tables)}):")
        for table in tables:
            count = conn.execute(f"SELECT COUNT(*) FROM {table[0]}").fetchone()[0]
            status = "✅" if count > 0 or not args.with_test_data else "⚪"
            print(f"  {status} {table[0]}: {count} rows")
        
        print(f"\n✅ Database initialized successfully!")
        print(f"Location: {db_path}")
        
        if not args.with_test_data:
            print("\n💡 Tip: Run with --with-test-data to insert sample devices")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
