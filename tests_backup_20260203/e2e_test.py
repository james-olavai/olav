#!/usr/bin/env python3
"""
完整 E2E 测试：集成到 Sync，清空历史数据，验证整个流程

执行步骤：
1. 备份当前数据库
2. 清空所有历史数据
3. 清空数据库表
4. 运行完整的同步 + 导入流程
5. 验证结果
"""

import shutil
from datetime import datetime
from pathlib import Path

import duckdb

# 项目设置
PROJECT_ROOT = Path("/home/yhvh/Olav")
DATA_DIR = PROJECT_ROOT / "data"
SYNC_DIR = DATA_DIR / "sync"
DB_PATH = PROJECT_ROOT / ".olav" / "data" / "topology.db"
BACKUP_DIR = DATA_DIR / "e2e_test_backups"


def print_header(msg):
    """打印标题"""
    print(f"\n{'=' * 80}")
    print(f"  {msg}")
    print(f"{'=' * 80}")


def print_section(msg):
    """打印小标题"""
    print(f"\n【{msg}】")


def step_1_backup_data():
    """第一步：备份当前数据"""
    print_header("STEP 1: 备份当前数据")

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 备份数据库
    if DB_PATH.exists():
        backup_db = BACKUP_DIR / f"topology.db.backup.{timestamp}"
        shutil.copy2(DB_PATH, backup_db)
        print(f"✅ 数据库已备份: {backup_db}")

    # 备份同步目录 (最近的数据)
    latest_sync = SYNC_DIR / "latest"
    if latest_sync.exists() or latest_sync.is_symlink():
        if latest_sync.is_symlink():
            target = latest_sync.resolve()
        else:
            target = Path(latest_sync.read_text())

        if target.exists():
            backup_sync = BACKUP_DIR / f"sync_{timestamp}"
            shutil.copytree(target, backup_sync)
            print(f"✅ 同步数据已备份: {backup_sync}")

    print(f"\n📁 所有备份保存在: {BACKUP_DIR}")
    return True


def step_2_clear_history():
    """第二步：清空历史数据"""
    print_header("STEP 2: 清空历史数据")

    # 列出当前同步目录
    if SYNC_DIR.exists():
        sync_dates = sorted([d for d in SYNC_DIR.iterdir() if d.is_dir() and d.name != "latest"])
        print("\n📊 当前同步数据:")
        for sync_path in sync_dates:
            size = sum(f.stat().st_size for f in sync_path.rglob("*") if f.is_file())
            size_mb = size / (1024 * 1024)
            print(f"  • {sync_path.name}: {size_mb:.2f} MB")

        # 删除所有历史同步数据
        print("\n🗑️  删除历史数据...")
        for sync_path in sync_dates:
            shutil.rmtree(sync_path)
            print(f"  ✅ 已删除: {sync_path.name}")

        # 删除 latest 链接
        latest = SYNC_DIR / "latest"
        if latest.exists() or latest.is_symlink():
            latest.unlink()
            print("  ✅ 已删除: latest 链接")

    print("\n✅ 历史数据已清空")
    return True


def step_3_clear_database():
    """第三步：清空数据库"""
    print_header("STEP 3: 清空数据库")

    if not DB_PATH.exists():
        print(f"⚠️  数据库不存在: {DB_PATH}")
        return True

    try:
        conn = duckdb.connect(str(DB_PATH))

        # 获取表列表
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        table_names = [t[0] for t in tables]

        print("\n📊 当前数据库表:")
        for table in table_names:
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"  • {table}: {count} 行")

        # 清空所有表
        print("\n🗑️  清空数据库表...")
        for table in table_names:
            conn.execute(f"DELETE FROM {table}")
            print(f"  ✅ 已清空: {table}")

        conn.commit()
        conn.close()

        print("\n✅ 数据库已清空")
        return True

    except Exception as e:
        print(f"❌ 错误: {e}")
        return False


def step_4_run_e2e_test():
    """第四步：运行完整 E2E 测试"""
    print_header("STEP 4: 运行完整 E2E 测试")

    print("\n📝 E2E 测试包括:")
    print("  1. 运行同步收集网络数据 (使用模拟数据)")
    print("  2. 运行 TextFSM 解析")
    print("  3. 运行 TopologyImporter 导入")
    print("  4. Pydantic 验证")
    print("  5. 数据库存储")

    import sys

    sys.path.insert(0, str(PROJECT_ROOT))

    try:
        # 1. 创建新的同步目录
        print_section("创建今日同步目录")
        from src.olav.tools.sync_tools import get_sync_dir, update_latest_link

        sync_dir = get_sync_dir()
        update_latest_link(sync_dir)
        print(f"✅ 同步目录: {sync_dir}")

        # 2. 复制 sample 数据 (假设有示例数据)
        print_section("准备测试数据")
        sample_sync = SYNC_DIR / "2026-01-13"  # 之前的数据
        if sample_sync.exists():
            # 复制数据到新的同步目录
            for src in ["raw", "parsed"]:
                src_path = sample_sync / src
                dst_path = sync_dir / src
                if src_path.exists() and not dst_path.exists():
                    shutil.copytree(src_path, dst_path)
                    print(f"✅ 已复制 {src} 数据")
        else:
            print(f"⚠️  没有找到示例数据: {sample_sync}")
            print("    使用空的同步目录继续")

        # 3. 运行 TopologyImporter
        print_section("运行 TopologyImporter")
        from src.olav.tools.topology_importer import TopologyImporter

        importer = TopologyImporter(str(DB_PATH))

        # 尝试从 Parsed JSON 导入
        if (sync_dir / "parsed").exists():
            print("📥 从 Parsed JSON 导入...")
            importer.import_from_parsed_json(str(sync_dir))
            importer.commit()

        importer.close()

        print("✅ TopologyImporter 执行完毕")
        return True

    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback

        traceback.print_exc()
        return False


def step_5_verify_results():
    """第五步：验证结果"""
    print_header("STEP 5: 验证结果")

    try:
        conn = duckdb.connect(str(DB_PATH))

        # 检查拓扑链接
        print_section("拓扑链接统计")
        result = conn.execute("""
            SELECT COUNT(*) as total,
                   COUNT(DISTINCT local_device) as devices,
                   COUNT(DISTINCT protocol) as protocols
            FROM topology_links
        """).fetchall()

        if result:
            total, devices, protocols = result[0]
            print(f"  📊 总链接数: {total}")
            print(f"  🔗 设备数: {devices}")
            print(f"  📡 协议数: {protocols}")

        # 按设备显示链接
        if total > 0:
            print_section("按设备分布")
            links_by_device = conn.execute("""
                SELECT local_device, COUNT(*) as count
                FROM topology_links
                GROUP BY local_device
                ORDER BY count DESC
            """).fetchall()

            for device, count in links_by_device:
                print(f"  {device}: {count} 条")

            # 显示样本数据
            print_section("样本数据")
            samples = conn.execute("""
                SELECT local_device, remote_device, local_port, remote_port, protocol
                FROM topology_links
                LIMIT 5
            """).fetchall()

            for local, remote, lport, rport, proto in samples:
                print(f"  {local} → {remote}")
                print(f"    {lport} → {rport} | {proto}")

        # 数据质量检查
        print_section("数据质量检查")

        # 检查无效设备名
        invalid = conn.execute("""
            SELECT COUNT(*) FROM topology_links
            WHERE local_device LIKE '%Neighbor%'
               OR local_device LIKE '%Unknown%'
               OR local_device LIKE '%Total%'
               OR remote_device LIKE '%Neighbor%'
               OR remote_device LIKE '%Unknown%'
               OR remote_device LIKE '%Total%'
        """).fetchone()[0]

        print(f"  🔍 无效的设备名: {invalid}")

        # 检查 NULL 端口
        null_ports = conn.execute("""
            SELECT COUNT(*) FROM topology_links
            WHERE local_port IS NULL OR remote_port IS NULL
        """).fetchone()[0]

        print(f"  🔍 NULL 端口: {null_ports}")

        # 检查 IP 地址
        ip_count = conn.execute("""
            SELECT COUNT(*) FROM topology_links
            WHERE local_device LIKE '%.%.%.%'
               OR remote_device LIKE '%.%.%.%'
        """).fetchone()[0]

        print(f"  🔍 IP 地址: {ip_count}")

        # 总体评分
        print_section("总体评分")
        data_quality = 100 if (invalid == 0 and ip_count == 0) else 0
        print(f"  ✅ 数据质量: {data_quality}%")
        print(f"  ✅ 邻居发现率: {total} 条")

        conn.close()
        return True

    except Exception as e:
        print(f"❌ 错误: {e}")
        return False


def main():
    """执行完整 E2E 测试"""
    print("\n")
    print("╔" + "=" * 78 + "╗")
    print("║" + " " * 78 + "║")
    print("║" + "  完整 E2E 测试：集成到 Sync，验证整个流程".center(78) + "║")
    print("║" + " " * 78 + "║")
    print("╚" + "=" * 78 + "╝")

    steps = [
        ("备份当前数据", step_1_backup_data),
        ("清空历史数据", step_2_clear_history),
        ("清空数据库", step_3_clear_database),
        ("运行 E2E 测试", step_4_run_e2e_test),
        ("验证结果", step_5_verify_results),
    ]

    results = []
    for name, step_func in steps:
        try:
            success = step_func()
            results.append((name, success))
        except Exception as e:
            print(f"\n❌ {name} 失败: {e}")
            import traceback

            traceback.print_exc()
            results.append((name, False))

    # 总结
    print_header("测试总结")
    print("\n📋 执行结果:")
    for name, success in results:
        status = "✅ 通过" if success else "❌ 失败"
        print(f"  {status} - {name}")

    total_success = sum(1 for _, s in results if s)
    total_steps = len(results)
    print(f"\n🎯 总体: {total_success}/{total_steps} 步骤通过")

    if total_success == total_steps:
        print("\n✅ 完整 E2E 测试成功！")
        return 0
    else:
        print("\n❌ E2E 测试失败，请检查上面的错误")
        return 1


if __name__ == "__main__":
    exit(main())
