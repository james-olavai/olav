#!/usr/bin/env python3
"""在正确的数据库位置建立devices表"""

import duckdb
from pathlib import Path
from datetime import datetime

def setup_devices_in_main_db():
    """在主数据库中建立devices表"""
    
    # 主数据库路径
    db_path = Path(".olav/db/main.duckdb")
    print(f"📝 在主数据库中建立devices表...")
    print(f"数据库路径: {db_path}\n")
    
    if not db_path.exists():
        print(f"⚠️  数据库不存在，将创建新数据库\n")
    
    conn = duckdb.connect(str(db_path))
    
    try:
        # 删除旧表（如果存在）
        conn.execute("DROP TABLE IF EXISTS devices CASCADE")
        
        # 创建新表
        conn.execute("""
            CREATE TABLE devices (
                device_id VARCHAR(255) PRIMARY KEY,
                hostname VARCHAR(255) NOT NULL UNIQUE,
                ip_address VARCHAR(15) NOT NULL,
                device_type VARCHAR(50),
                vendor VARCHAR(50),
                model VARCHAR(100),
                ios_version VARCHAR(50),
                serial_number VARCHAR(100),
                device_role VARCHAR(50),
                site VARCHAR(100),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE
            )
        """)
        
        # 创建索引
        conn.execute("CREATE INDEX idx_devices_hostname ON devices(hostname)")
        conn.execute("CREATE INDEX idx_devices_vendor ON devices(vendor)")
        conn.execute("CREATE INDEX idx_devices_role ON devices(device_role)")
        
        print("✅ devices表创建成功！\n")
        
        # 导入设备数据
        print("📋 导入设备数据...\n")
        
        devices_data = [
            ("R1", "R1", "192.168.100.101", "cisco_ios", "Cisco", "ISR4321", "16.12.03", "FCW2222L1001", "core", "lab"),
            ("R2", "R2", "192.168.100.102", "cisco_ios", "Cisco", "ISR4321", "16.12.03", "FCW2222L1002", "core", "lab"),
            ("R3", "R3", "192.168.100.103", "cisco_ios", "Cisco", "ISR4321", "16.12.03", "FCW2222L1003", "core", "lab"),
            ("R4", "R4", "192.168.100.104", "cisco_ios", "Cisco", "ISR4321", "16.12.03", "FCW2222L1004", "core", "lab"),
            ("SW1", "SW1", "192.168.100.105", "cisco_ios", "Cisco", "Catalyst 3750", "15.2.7", "FCW3333L1001", "distribution", "lab"),
            ("SW2", "SW2", "192.168.100.106", "cisco_ios", "Cisco", "Catalyst 3750", "15.2.7", "FCW3333L1002", "distribution", "lab"),
        ]
        
        for device in devices_data:
            conn.execute("""
                INSERT INTO devices 
                (device_id, hostname, ip_address, device_type, vendor, model, ios_version, 
                 serial_number, device_role, site, created_at, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, list(device) + [datetime.now(), datetime.now()])
        
        print("✅ 数据导入完成！\n")
        
        # 验证查询
        print("=" * 100)
        print("验证查询")
        print("=" * 100 + "\n")
        
        # 统计
        count = conn.execute("SELECT COUNT(*) FROM devices").fetchall()[0][0]
        print(f"✅ devices表中有 {count} 个设备\n")
        
        # 列出所有设备
        print("设备列表:")
        devices = conn.execute("""
            SELECT hostname, device_type, vendor, device_role, ip_address
            FROM devices
            ORDER BY hostname
        """).fetchall()
        
        for device in devices:
            print(f"   {device[0]:4} | {device[1]:12} | {device[2]:8} | {device[3]:12} | {device[4]}")
        
        # 按供应商统计
        print("\n按供应商统计:")
        vendor_stats = conn.execute("""
            SELECT vendor, COUNT(*) as count
            FROM devices
            GROUP BY vendor
        """).fetchall()
        
        for vendor, count in vendor_stats:
            print(f"   {vendor}: {count} 个设备")
        
        # 按角色统计
        print("\nbyRole统计:")
        role_stats = conn.execute("""
            SELECT device_role, COUNT(*) as count
            FROM devices
            GROUP BY device_role
            ORDER BY device_role
        """).fetchall()
        
        for role, count in role_stats:
            print(f"   {role}: {count} 个设备")
        
        conn.commit()
        print("\n✅ 数据库操作完成！")
        return True
        
    except Exception as e:
        print(f"❌ 建表失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        conn.close()

if __name__ == "__main__":
    success = setup_devices_in_main_db()
    exit(0 if success else 1)
