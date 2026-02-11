#!/usr/bin/env python3
"""
Query Agent E2E 测试 - 测试数据生成脚本

生成网络拓扑和流量数据，用于摸底测试
"""

import random
import sys
from datetime import datetime, timedelta
import duckdb

# 数据生成参数
NUM_DEVICES = 80  # 设备数
INTERFACES_PER_DEVICE = 15  # 每设备接口数
DAYS_OF_STATS = 10  # 统计数据天数
SAMPLES_PER_DAY = 288  # 每天采样数（5分钟间隔）


def setup_schema(conn):
    """创建表结构"""
    print("📋 创建表结构...")
    
    # devices表
    conn.execute("""
    CREATE TABLE IF NOT EXISTS devices (
        device_id INTEGER PRIMARY KEY,
        name VARCHAR UNIQUE,
        device_type VARCHAR,
        mgmt_ip VARCHAR,
        location VARCHAR,
        vendor VARCHAR,
        model VARCHAR,
        site_id INTEGER,
        created_at TIMESTAMP,
        updated_at TIMESTAMP
    )
    """)
    
    # interfaces表
    conn.execute("""
    CREATE TABLE IF NOT EXISTS interfaces (
        interface_id INTEGER PRIMARY KEY,
        device_id INTEGER,
        interface_name VARCHAR,
        speed_gbps DOUBLE,
        speed_bps BIGINT,
        status VARCHAR,
        enabled BOOLEAN,
        mtu INTEGER,
        protocol VARCHAR,
        created_at TIMESTAMP,
        updated_at TIMESTAMP,
        FOREIGN KEY(device_id) REFERENCES devices(device_id)
    )
    """)
    
    # interface_stats表
    conn.execute("""
    CREATE TABLE IF NOT EXISTS interface_stats (
        stat_id BIGINT PRIMARY KEY,
        interface_id INTEGER,
        device_id INTEGER,
        timestamp TIMESTAMP,
        bytes_in BIGINT,
        bytes_out BIGINT,
        packets_in BIGINT,
        packets_out BIGINT,
        errors_in INTEGER,
        errors_out INTEGER,
        dropped_in INTEGER,
        dropped_out INTEGER,
        FOREIGN KEY(interface_id) REFERENCES interfaces(interface_id),
        FOREIGN KEY(device_id) REFERENCES devices(device_id)
    )
    """)
    
    # link_relationships表
    conn.execute("""
    CREATE TABLE IF NOT EXISTS link_relationships (
        relationship_id INTEGER PRIMARY KEY,
        local_interface_id INTEGER,
        remote_interface_id INTEGER,
        remote_device_id INTEGER,
        relationship_type VARCHAR,
        created_at TIMESTAMP,
        is_active BOOLEAN,
        FOREIGN KEY(local_interface_id) REFERENCES interfaces(interface_id),
        FOREIGN KEY(remote_interface_id) REFERENCES interfaces(interface_id),
        FOREIGN KEY(remote_device_id) REFERENCES devices(device_id)
    )
    """)
    
    # bgp_routes表
    conn.execute("""
    CREATE TABLE IF NOT EXISTS bgp_routes (
        route_id INTEGER PRIMARY KEY,
        device_id INTEGER,
        prefix VARCHAR,
        next_hop VARCHAR,
        asn INTEGER,
        path_length INTEGER,
        weight INTEGER,
        local_pref INTEGER,
        created_at TIMESTAMP,
        updated_at TIMESTAMP,
        last_update TIMESTAMP,
        FOREIGN KEY(device_id) REFERENCES devices(device_id)
    )
    """)
    
    # device_configs表
    conn.execute("""
    CREATE TABLE IF NOT EXISTS device_configs (
        config_id INTEGER PRIMARY KEY,
        device_id INTEGER,
        config_text VARCHAR,
        config_hash VARCHAR,
        snapshot_time TIMESTAMP,
        created_by VARCHAR,
        change_description VARCHAR,
        FOREIGN KEY(device_id) REFERENCES devices(device_id)
    )
    """)
    
    print("✅ 表结构创建完成")


def generate_devices(conn):
    """生成设备数据"""
    print(f"📍 生成 {NUM_DEVICES} 个设备...")
    
    device_types = ["Router", "Switch", "Firewall"]
    vendors = ["Cisco", "Juniper", "Arista", "Huawei"]
    locations = ["Beijing DC", "Shanghai DC", "Shenzhen DC", "Regional Office"]
    
    devices = []
    for i in range(NUM_DEVICES):
        device_type = random.choices(
            device_types,
            weights=[0.3, 0.5, 0.2]
        )[0]
        
        # 根据类型选择前缀
        if device_type == "Router":
            prefix = "R"
        elif device_type == "Switch":
            prefix = "SW"
        else:
            prefix = "FW"
        
        device_id = i + 1
        name = f"{prefix}{device_id:03d}"
        mgmt_ip = f"10.0.{i//256}.{i%256}"
        location = random.choice(locations)
        vendor = random.choice(vendors)
        
        created_at = (datetime.now() - timedelta(
            days=random.randint(30, 365)
        )).isoformat()
        
        devices.append({
            "device_id": device_id,
            "name": name,
            "device_type": device_type,
            "mgmt_ip": mgmt_ip,
            "location": location,
            "vendor": vendor,
            "model": f"{vendor}-{random.randint(1, 10)}",
            "site_id": i // 20,
            "created_at": created_at,
            "updated_at": created_at
        })
    
    # 批量插入
    conn.execute("DELETE FROM devices")
    for device in devices:
        conn.execute("""
        INSERT INTO devices VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """, [
            device["device_id"],
            device["name"],
            device["device_type"],
            device["mgmt_ip"],
            device["location"],
            device["vendor"],
            device["model"],
            device["site_id"],
            device["created_at"],
            device["updated_at"]
        ])
    
    conn.commit()
    print(f"✅ 生成了 {NUM_DEVICES} 个设备")
    return devices


def generate_interfaces(conn, devices):
    """生成接口数据"""
    total_interfaces = NUM_DEVICES * INTERFACES_PER_DEVICE
    print(f"🔌 生成 {total_interfaces} 个接口...")
    
    speeds = [1.0, 10.0, 100.0]  # Gbps
    speed_weights = [0.4, 0.5, 0.1]
    statuses = ["up"] * 85 + ["down"] * 10 + ["admin-down"] * 5
    
    conn.execute("DELETE FROM interfaces")
    
    interface_id = 1
    for device in devices:
        for iface_idx in range(INTERFACES_PER_DEVICE):
            speed_gbps = random.choices(speeds, speed_weights)[0]
            speed_bps = int(speed_gbps * 1_000_000_000)
            
            status = random.choice(statuses)
            enabled = status != "admin-down" and random.random() > 0.05
            
            interface_name = f"Gi{iface_idx//10}/{iface_idx%10}"
            
            # Parse device created_at and add random days
            device_created = datetime.fromisoformat(device["created_at"])
            created_at = (device_created + 
                         timedelta(days=random.randint(1, 30))).isoformat()
            
            conn.execute("""
            INSERT INTO interfaces VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """, [
                interface_id,
                device["device_id"],
                interface_name,
                speed_gbps,
                speed_bps,
                status,
                enabled,
                1500,  # MTU
                "IPv4",
                created_at,
                created_at
            ])
            
            interface_id += 1
    
    conn.commit()
    print(f"✅ 生成了 {total_interfaces} 个接口")


def generate_interface_stats(conn):
    """生成接口流量统计数据"""
    total_stats = NUM_DEVICES * INTERFACES_PER_DEVICE * DAYS_OF_STATS * SAMPLES_PER_DAY
    print(f"📊 生成 {total_stats:,} 条流量统计记录...")
    
    conn.execute("DELETE FROM interface_stats")
    
    # 获取所有接口
    interfaces = conn.execute("""
    SELECT interface_id, device_id, speed_bps FROM interfaces
    """).fetchall()
    
    stat_id = 1
    batch_size = 10000
    batch = []
    
    for interface_id, device_id, speed_bps in interfaces:
        for day_offset in range(DAYS_OF_STATS):
            for sample in range(SAMPLES_PER_DAY):
                timestamp = datetime.now() - timedelta(
                    days=DAYS_OF_STATS - day_offset - 1,
                    minutes=sample * 5
                )
                
                # 根据时间生成流量模式
                hour = timestamp.hour
                
                if 8 <= hour <= 18:  # 业务时段
                    bytes_in = random.randint(1_000_000, 10_000_000)
                    bytes_out = random.randint(1_000_000, 10_000_000)
                elif 22 <= hour or hour <= 6:  # 夜间备份
                    bytes_in = random.randint(5_000_000, 50_000_000)
                    bytes_out = random.randint(5_000_000, 50_000_000)
                else:  # 低活动期
                    bytes_in = random.randint(100_000, 1_000_000)
                    bytes_out = random.randint(100_000, 1_000_000)
                
                # 偶然概率接口没有流量（故障或未使用）
                if random.random() < 0.05:  # 5%概率
                    bytes_in = 0
                    bytes_out = 0
                
                batch.append([
                    stat_id,
                    interface_id,
                    device_id,
                    timestamp.isoformat(),
                    bytes_in,
                    bytes_out,
                    random.randint(10_000, 100_000),  # packets_in
                    random.randint(10_000, 100_000),  # packets_out
                    random.randint(0, 100),           # errors_in
                    random.randint(0, 100),           # errors_out
                    random.randint(0, 50),            # dropped_in
                    random.randint(0, 50)             # dropped_out
                ])
                
                stat_id += 1
                
                # 批量插入
                if len(batch) >= batch_size:
                    conn.executemany("""
                    INSERT INTO interface_stats VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, batch)
                    conn.commit()
                    print(f"   已插入 {len(batch)} 条记录...")
                    batch = []
    
    # 插入剩余的批量
    if batch:
        conn.executemany("""
        INSERT INTO interface_stats VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, batch)
        conn.commit()
    
    print(f"✅ 生成了 {total_stats:,} 条流量统计记录")


def generate_link_relationships(conn):
    """生成接口邻接关系"""
    print("🔗 生成接口邻接关系...")
    
    conn.execute("DELETE FROM link_relationships")
    
    # 获取所有接口和设备
    interfaces = conn.execute("""
    SELECT interface_id, device_id FROM interfaces 
    WHERE status = 'up' AND enabled = true
    ORDER BY device_id, interface_id
    """).fetchall()
    
    # 创建邻接（大约总接口的10%）
    relationship_id = 1
    interfaces_list = list(interfaces)
    
    for idx in range(0, len(interfaces_list) - 1, 20):  # 每20个接口创建一个邻接
        local_iface_id, local_device_id = interfaces_list[idx]
        remote_iface_id, remote_device_id = interfaces_list[idx + 1]
        
        if local_device_id != remote_device_id:
            rel_type = random.choice(["ethernet", "bgp", "mpls"])
            
            conn.execute("""
            INSERT INTO link_relationships VALUES (?, ?, ?, ?, ?, ?, ?)
            """, [
                relationship_id,
                local_iface_id,
                remote_iface_id,
                remote_device_id,
                rel_type,
                datetime.now().isoformat(),
                True  # is_active
            ])
            
            relationship_id += 1
    
    conn.commit()
    num_relationships = relationship_id - 1
    print(f"✅ 生成了 {num_relationships} 个邻接关系")


def generate_bgp_routes(conn):
    """生成BGP路由"""
    print("🌐 生成BGP路由...")
    
    conn.execute("DELETE FROM bgp_routes")
    
    # 获取路由器设备
    routers = conn.execute("""
    SELECT device_id FROM devices WHERE device_type = 'Router'
    """).fetchall()
    
    if not routers:
        print("⚠️  没有找到Router设备，跳过BGP路由生成")
        return
    
    router_ids = [r[0] for r in routers]
    route_id = 1
    
    for router_id in router_ids:
        # 每个路由器生成5-20条路由
        num_routes = random.randint(5, 20)
        
        for _ in range(num_routes):
            octet1 = random.randint(10, 172)
            octet2 = random.randint(0, 255)
            prefix_len = random.choice([8, 16, 24])
            prefix = f"{octet1}.{octet2}.0.0/{prefix_len}"
            
            next_hop = f"10.0.{random.randint(1, 254)}.{random.randint(1, 254)}"
            asn = 64512 + random.randint(0, 50)  # 私有ASN范围
            
            conn.execute("""
            INSERT INTO bgp_routes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                route_id,
                router_id,
                prefix,
                next_hop,
                asn,
                random.randint(1, 5),  # path_length
                random.randint(0, 100),  # weight
                random.randint(0, 100),  # local_pref
                datetime.now().isoformat(),
                datetime.now().isoformat(),
                datetime.now().isoformat()
            ])
            
            route_id += 1
    
    conn.commit()
    print(f"✅ 生成了 {route_id - 1} 条BGP路由")


def create_indices(conn):
    """创建查询性能优化的索引"""
    print("📑 创建索引...")
    
    indices = [
        ("idx_interface_stats_timestamp", 
         "CREATE INDEX IF NOT EXISTS idx_interface_stats_timestamp ON interface_stats(timestamp)"),
        ("idx_interface_stats_iface_timestamp",
         "CREATE INDEX IF NOT EXISTS idx_interface_stats_iface_timestamp ON interface_stats(interface_id, timestamp)"),
        ("idx_interfaces_device_id",
         "CREATE INDEX IF NOT EXISTS idx_interfaces_device_id ON interfaces(device_id)"),
        ("idx_interfaces_status",
         "CREATE INDEX IF NOT EXISTS idx_interfaces_status ON interfaces(status)"),
        ("idx_devices_location",
         "CREATE INDEX IF NOT EXISTS idx_devices_location ON devices(location)"),
        ("idx_devices_type",
         "CREATE INDEX IF NOT EXISTS idx_devices_type ON devices(device_type)")
    ]
    
    for idx_name, sql in indices:
        conn.execute(sql)
        print(f"   ✓ {idx_name}")
    
    conn.commit()
    print("✅ 索引创建完成")


def print_summary(conn):
    """打印数据摘要"""
    print("\n" + "="*60)
    print("📊 测试数据生成摘要")
    print("="*60)
    
    stats = {
        "devices": conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0],
        "interfaces": conn.execute("SELECT COUNT(*) FROM interfaces").fetchone()[0],
        "stats": conn.execute("SELECT COUNT(*) FROM interface_stats").fetchone()[0],
        "relationships": conn.execute("SELECT COUNT(*) FROM link_relationships").fetchone()[0],
        "routes": conn.execute("SELECT COUNT(*) FROM bgp_routes").fetchone()[0]
    }
    
    print(f"✅ 设备数量: {stats['devices']}")
    print(f"✅ 接口数量: {stats['interfaces']}")
    print(f"✅ 流量统计记录: {stats['stats']:,}")
    print(f"✅ 邻接关系: {stats['relationships']}")
    print(f"✅ BGP路由: {stats['routes']}")
    
    # 样本查询
    print("\n📝 样本数据:")
    
    devices = conn.execute("""
    SELECT device_id, name, device_type, location FROM devices LIMIT 3
    """).fetchall()
    
    print("\n  设备样本:")
    for row in devices:
        print(f"    {row[1]} ({row[2]}) at {row[3]}")
    
    top_interfaces = conn.execute("""
    SELECT i.device_id, i.interface_name, SUM(bytes_in + bytes_out) as total_bytes
    FROM interface_stats s
    JOIN interfaces i ON s.interface_id = i.interface_id
    GROUP BY i.interface_id, i.device_id, i.interface_name
    ORDER BY total_bytes DESC
    LIMIT 3
    """).fetchall()
    
    print("\n  流量TOP 3接口:")
    for device_id, iface, total_bytes in top_interfaces:
        print(f"    Device {device_id}, {iface}: {total_bytes / 1e9:.2f} GB")
    
    print("\n" + "="*60)
    print("✨ 测试数据已准备就绪！")
    print("="*60 + "\n")


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="生成Query Agent E2E测试数据")
    parser.add_argument("--db", default=".olav/db/test_network.duckdb",
                       help="DuckDB数据库路径")
    parser.add_argument("--clear", action="store_true",
                       help="清空现有数据重新生成")
    
    args = parser.parse_args()
    
    print(f"🚀 Query Agent E2E 测试 - 数据生成脚本")
    print(f"📂 数据库: {args.db}")
    
    # 连接数据库
    conn = duckdb.connect(args.db)
    
    try:
        # 清空现有数据
        if args.clear:
            print("🗑️  清空现有数据...")
            for table in ["device_configs", "bgp_routes", "link_relationships",
                         "interface_stats", "interfaces", "devices"]:
                try:
                    conn.execute(f"DROP TABLE {table}")
                except:
                    pass
            conn.commit()
        
        # 生成数据
        setup_schema(conn)
        devices = generate_devices(conn)
        generate_interfaces(conn, devices)
        generate_interface_stats(conn)
        generate_link_relationships(conn)
        generate_bgp_routes(conn)
        create_indices(conn)
        
        # 打印摘要
        print_summary(conn)
        
    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
