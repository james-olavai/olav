#!/usr/bin/env python3
"""建立devices表并导入设备数据"""

import duckdb
from pathlib import Path
from datetime import datetime
import json

def create_devices_table():
    """创建devices表"""
    
    # 使用olav_cache.db作为主数据库
    db_path = Path(".olav/cache/olav_cache.db")
    print(f"📝 正在创建devices表...")
    print(f"数据库: {db_path}\n")
    
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
        
        print("✅ devices表创建成功！")
        print("   字段: hostname, ip_address, vendor, model, ios_version, device_role, site\n")
        
        return conn
        
    except Exception as e:
        print(f"❌ 创建表失败: {e}")
        conn.close()
        return None

def import_devices(conn):
    """导入Nornir中的设备"""
    
    print("📋 导入设备数据...\n")
    
    # 实验室网络中的设备
    devices_data = [
        {
            "device_id": "R1",
            "hostname": "R1",
            "ip_address": "192.168.100.101",
            "device_type": "cisco_ios",
            "vendor": "Cisco",
            "model": "ISR4321",
            "ios_version": "16.12.03",
            "serial_number": "FCW2222L1001",
            "device_role": "core",
            "site": "lab",
        },
        {
            "device_id": "R2",
            "hostname": "R2",
            "ip_address": "192.168.100.102",
            "device_type": "cisco_ios",
            "vendor": "Cisco",
            "model": "ISR4321",
            "ios_version": "16.12.03",
            "serial_number": "FCW2222L1002",
            "device_role": "core",
            "site": "lab",
        },
        {
            "device_id": "R3",
            "hostname": "R3",
            "ip_address": "192.168.100.103",
            "device_type": "cisco_ios",
            "vendor": "Cisco",
            "model": "ISR4321",
            "ios_version": "16.12.03",
            "serial_number": "FCW2222L1003",
            "device_role": "core",
            "site": "lab",
        },
        {
            "device_id": "R4",
            "hostname": "R4",
            "ip_address": "192.168.100.104",
            "device_type": "cisco_ios",
            "vendor": "Cisco",
            "model": "ISR4321",
            "ios_version": "16.12.03",
            "serial_number": "FCW2222L1004",
            "device_role": "core",
            "site": "lab",
        },
        {
            "device_id": "SW1",
            "hostname": "SW1",
            "ip_address": "192.168.100.105",
            "device_type": "cisco_ios",
            "vendor": "Cisco",
            "model": "Catalyst 3750",
            "ios_version": "15.2.7",
            "serial_number": "FCW3333L1001",
            "device_role": "distribution",
            "site": "lab",
        },
        {
            "device_id": "SW2",
            "hostname": "SW2",
            "ip_address": "192.168.100.106",
            "device_type": "cisco_ios",
            "vendor": "Cisco",
            "model": "Catalyst 3750",
            "ios_version": "15.2.7",
            "serial_number": "FCW3333L1002",
            "device_role": "distribution",
            "site": "lab",
        },
    ]
    
    try:
        for device in devices_data:
            conn.execute("""
                INSERT INTO devices 
                (device_id, hostname, ip_address, device_type, vendor, model, ios_version, 
                 serial_number, device_role, site, created_at, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                device["device_id"],
                device["hostname"],
                device["ip_address"],
                device["device_type"],
                device["vendor"],
                device["model"],
                device["ios_version"],
                device["serial_number"],
                device["device_role"],
                device["site"],
                datetime.now(),
                datetime.now(),
            ])
        
        print("✅ 导入完成！\n")
        print("📊 设备统计:")
        
        # 统计信息
        stats = conn.execute("""
            SELECT 
                COUNT(*) as total_devices,
                COUNT(DISTINCT vendor) as vendors,
                COUNT(DISTINCT device_role) as roles
            FROM devices
        """).fetchall()[0]
        
        print(f"   总设备数: {stats[0]}")
        print(f"   供应商数: {stats[1]}")
        print(f"   角色类型: {stats[2]}\n")
        
        # 显示导入的设备
        devices = conn.execute("""
            SELECT hostname, device_type, vendor, device_role, ip_address
            FROM devices
            ORDER BY hostname
        """).fetchall()
        
        print("📋 设备列表:")
        for device in devices:
            print(f"   {device[0]:4} | {device[1]:12} | {device[2]:8} | {device[3]:12} | {device[4]}")
        
        return True
        
    except Exception as e:
        print(f"❌ 导入失败: {e}")
        return False

def main():
    """主函数"""
    
    print("=" * 100)
    print("实施devices表 - 建立设备目录")
    print("=" * 100 + "\n")
    
    # 步骤1: 建表
    conn = create_devices_table()
    if not conn:
        return False
    
    # 步骤2: 导入数据
    if not import_devices(conn):
        conn.close()
        return False
    
    # 步骤3: 验证
    print("=" * 100)
    print("验证查询")
    print("=" * 100 + "\n")
    
    # 查询1: 所有Cisco设备
    print("【查询1】所有Cisco设备:")
    result = conn.execute("""
        SELECT hostname, model, ios_version 
        FROM devices 
        WHERE vendor='Cisco'
        ORDER BY hostname
    """).fetchall()
    
    for row in result:
        print(f"   {row[0]}: {row[1]} ({row[2]})")
    
    # 查询2: 核心路由器
    print("\n【查询2】核心角色设备:")
    result = conn.execute("""
        SELECT hostname, device_role, ip_address
        FROM devices
        WHERE device_role='core'
        ORDER BY hostname
    """).fetchall()
    
    for row in result:
        print(f"   {row[0]}: {row[1]} ({row[2]})")
    
    # 查询3: 设备按供应商分组
    print("\n【查询3】设备分布统计:")
    result = conn.execute("""
        SELECT vendor, device_role, COUNT(*) as count
        FROM devices
        GROUP BY vendor, device_role
        ORDER BY vendor, device_role
    """).fetchall()
    
    for row in result:
        print(f"   {row[0]} - {row[1]}: {row[2]} 个")
    
    conn.close()
    
    print("\n" + "=" * 100)
    print("✅ devices表实施完成！")
    print("=" * 100)
    
    return True

if __name__ == "__main__":
    main()
