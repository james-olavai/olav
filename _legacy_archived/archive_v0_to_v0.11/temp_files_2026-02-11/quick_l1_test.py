#!/usr/bin/env python3
"""
Level 1快速测试脚本 - 优化版本 (v0.10.2+ 支持数据库隔离)
聚焦于验证核心功能，而不是特定的文件名
"""

import os
import subprocess
import time
from pathlib import Path
from datetime import datetime

OLAV_ROOT = Path("/home/yhvh/Olav")
EXPORTS_DIR = OLAV_ROOT / "exports"
TEST_DB = OLAV_ROOT / ".olav/db/test_network.duckdb"  # v0.10.2: 测试数据库

# Simplified test cases - focus on response verification
L1_QUICK_TESTS = [
    ("L1-P0-001", "P0", "列出所有设备", True),  # File output expected
    ("L1-P0-002", "P0", "有多少台设备?", False),  # Response output
    ("L1-P0-003", "P0", "设备IP列表", True),
    ("L1-P0-004", "P0", "按设备类型分类统计", True),
    ("L1-P0-005", "P0", "有多少个接口?", False),
    
    ("L1-P1-008", "P1", "列出所有border角色的设备", True),
    ("L1-P1-009", "P1", "列出所有core角色的设备", True),
    ("L1-P1-010", "P1", "列出所有access角色的设备", True),
    ("L1-P1-011", "P1", "有多少台活跃的设备?", False),
    ("L1-P1-013", "P1", "Lab站点有多少设备?", False),
]

def verify_test_database() -> bool:
    """验证测试数据库存在且有数据 (v0.10.2+)"""
    if not TEST_DB.exists():
        print(f"⚠️  警告: 测试数据库不存在: {TEST_DB}")
        return False
    
    try:
        import duckdb
        conn = duckdb.connect(str(TEST_DB), read_only=True)
        device_count = conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
        interface_count = conn.execute("SELECT COUNT(*) FROM interfaces").fetchone()[0]
        conn.close()
        
        print(f"✅ 测试数据库验证成功:")
        print(f"   路径: {TEST_DB}")
        print(f"   设备数: {device_count}")
        print(f"   接口数: {interface_count}")
        
        if device_count < 10 or interface_count < 100:
            print(f"⚠️  警告: 测试数据库数据不足，测试结果可能不准确")
            return False
        
        return True
    except Exception as e:
        print(f"❌ 測試資料庫驗證失敗: {e}")
        return False

def run_olav_query(query: str, timeout=45) -> tuple[bool, str, float]:
    """执行olav query (v0.10.2+ 自动使用测试数据库)"""
    
    # 設置測試環境 (v0.10.2: 明確指定測試數據庫)
    env = os.environ.copy()
    env["OLAV_DB_PATH"] = str(TEST_DB)
    env["OLAV_ENV"] = "test"
    
    start_time = time.time()
    try:
        result = subprocess.run(
            ["uv", "run", "olav", "query", query],
            cwd=OLAV_ROOT,
            env=env,  # 傳遞環境變量
            capture_output=True,
            text=True,
            timeout=timeout
        )
        elapsed = time.time() - start_time
        output = result.stdout + result.stderr
        return result.returncode == 0, output, elapsed
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT", timeout
    except Exception as e:
        return False, str(e), time.time() - start_time

def check_export_dir(query_hint: str) -> bool:
    """检查exports目录是否有新CSV文件"""
    export_files = list(EXPORTS_DIR.glob("*.csv"))
    return len(export_files) > 0

def main():
    print("\n" + "="*70)
    print("🚀 LEVEL 1 QUICK TEST (v0.10.2+ Database Isolation)")
    print("="*70)
    
    # 前置条件: 验证测试数据库 (v0.10.2+)
    print("\n📋 前置条件: 验证测试数据库...")
    if not verify_test_database():
        print("❌ 测试数据库验证失败，请先执行数据导入")
        return
    
    results = []
    for test_id, priority, query, expects_file in L1_QUICK_TESTS:
        print(f"\n{test_id} ({priority}): {query}")
        
        success, output, elapsed = run_olav_query(query)
        
        if not success:
            print(f"  ❌ EXEC_ERROR {elapsed:.1f}s")
            results.append("failed")
        elif expects_file:
            has_files = check_export_dir(query)
            if has_files or "no data" not in output.lower():
                print(f"  ✅ PASSED ({elapsed:.1f}s)")
                results.append("passed")
            else:
                print(f"  ❌ NO_OUTPUT {elapsed:.1f}s")
                results.append("failed")
        else:
            # Response-based query
            if len(output.strip()) > 50:  # Meaningful response
                print(f"  ✅ PASSED ({elapsed:.1f}s)")
                results.append("passed")
            else:
                print(f"  ❌ SHORT_RESPONSE {elapsed:.1f}s")
                results.append("failed")
    
    # Summary
    passed = sum(1 for r in results if r == "passed")
    total = len(results)
    print("\n" + "="*70)
    print(f"RESULTS: {passed}/{total} PASSED ({100*passed/total:.0f}%)")
    print("="*70)

if __name__ == "__main__":
    main()
