#!/usr/bin/env python3
"""
快速验证 Query Agent 能力的测试脚本
"""

import os
import sys
from pathlib import Path

# 设置路径
OLAV_ROOT = Path("/home/yhvh/Olav")
DB_PATH = OLAV_ROOT / ".olav" / "db" / "test_network.duckdb"
EXPORTS_PATH = OLAV_ROOT / "exports"

def check_environment():
    """检查环境"""
    print("\n📋 环境检查")
    print("=" * 50)
    
    # 检查Python
    print(f"✅ Python版本: {sys.version.split()[0]}")
    
    # 检查必要目录
    if not OLAV_ROOT.exists():
        print(f"❌ OLAV根目录不存在: {OLAV_ROOT}")
        return False
    print(f"✅ OLAV根目录: {OLAV_ROOT}")
    
    # 检查脚本
    script = OLAV_ROOT / "scripts" / "generate_e2e_test_data.py"
    if not script.exists():
        print(f"❌ 脚本不存在: {script}")
        return False
    print(f"✅ 脚本存在: {script.name}")
    
    # 检查exports目录
    EXPORTS_PATH.mkdir(parents=True, exist_ok=True)
    print(f"✅ Exports目录: {EXPORTS_PATH}")
    
    return True

def check_database():
    """检查数据库"""
    print("\n📊 数据库检查")
    print("=" * 50)
    
    try:
        import duckdb
        print("✅ DuckDB模块可用")
    except ImportError:
        print("❌ DuckDB模块不可用")
        return False
    
    # 尝试连接
    try:
        if DB_PATH.exists():
            print(f"✅ 数据库文件存在: {DB_PATH.name}")
            conn = duckdb.connect(str(DB_PATH))
            
            # 检查表
            tables = conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_catalog='memory' OR table_schema != 'information_schema'"
            ).fetchall()
            
            if tables:
                print(f"✅ 发现 {len(tables)} 个表:")
                for table in tables:
                    count = conn.execute(f"SELECT COUNT(*) FROM {table[0]}").fetchone()[0]
                    print(f"   - {table[0]}: {count} 行")
            else:
                print("⚠️ 数据库存在但无表")
            
            conn.close()
            return True
        else:
            print(f"⚠️ 数据库文件不存在: {DB_PATH}")
            print("   → 需要运行数据生成脚本")
            return True  # 这不是错误，只是还没有生成数据
    except Exception as e:
        print(f"❌ 数据库错误: {e}")
        return False

def main():
    """主程序"""
    print("\n" + "="*50)
    print("🔍 Query Agent 能力验证 - 快速检查")
    print("="*50)
    
    # 环境检查
    if not check_environment():
        print("\n❌ 环境检查失败，无法继续")
        return False
    
    # 数据库检查
    if not check_database():
        print("\n❌ 数据库检查失败")
        return False
    
    print("\n" + "="*50)
    print("✅ 快速检查完成，环境就绪")
    print("="*50)
    print("\n📝 下一步:")
    print("1. 运行: uv run python /home/yhvh/Olav/scripts/generate_e2e_test_data.py --clear")
    print("2. 验证: python verify_agent_capability.py")
    print("3. 手动测试: uv run olav ask '列出所有设备'")
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
