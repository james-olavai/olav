#!/usr/bin/env python3
"""
Level 1-P0 能力验证脚本 (修正版)
使用正确的 olav query 命令
"""

import subprocess
import json
from pathlib import Path
import csv
import time

OLAV_ROOT = Path("/home/yhvh/Olav")
EXPORTS_DIR = OLAV_ROOT / "exports"
REPORT_FILE = OLAV_ROOT / "docs" / "plan" / "LEVEL1_P0_RESULTS_20260208.md"

def run_olav_query(query: str, timeout=45) -> tuple[bool, str, float]:
    """运行olav query命令"""
    start_time = time.time()
    try:
        result = subprocess.run(
            ["uv", "run", "olav", "query", query],
            cwd=OLAV_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        elapsed = time.time() - start_time
        return result.returncode == 0, result.stdout + result.stderr, elapsed
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT", timeout
    except Exception as e:
        return False, str(e), time.time() - start_time

def run_olav_devices() -> tuple[bool, str, float]:
    """运行olav devices命令"""
    start_time = time.time()
    try:
        result = subprocess.run(
            ["uv", "run", "olav", "devices"],
            cwd=OLAV_ROOT,
            capture_output=True,
            text=True,
            timeout=30
        )
        elapsed = time.time() - start_time
        return result.returncode == 0, result.stdout + result.stderr, elapsed
    except Exception as e:
        return False, str(e), time.time() - start_time

def count_csv_rows(filename: str) -> int:
    """统计CSV文件行数"""
    file_path = EXPORTS_DIR / filename
    if not file_path.exists():
        return -1
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            next(reader)  # 跳过header
            return sum(1 for _ in reader)
    except:
        return -1

# 运行测试
print("\n" + "="*70)
print("🧪 Level 1-P0: 基础能力验证")
print("="*70)

results = []

# 测试1: List devices
print("\n[1/3] Listing devices...")
success, output, elapsed = run_olav_devices()
print(f"✅ Setup" if success else f"❌ Failed")
results.append({
    "test": "olav devices",
    "passed": success,
    "time_ms": int(elapsed*1000)
})

# 测试2: Query - 列出所有设备
print("\n[2/3] Query: 列出所有设备")
success, output, elapsed = run_olav_query("列出所有设备")
query_passed = success
device_count = count_csv_rows("all_devices.csv") if EXPORTS_DIR.exists() else -1
print(f"Query: {'✅' if success else '❌'} (Time: {elapsed*1000:.0f}ms)")
print(f"File: all_devices.csv - {device_count} rows")

results.append({
    "test": "Query: 列出所有设备",
    "passed": success and device_count > 0,
    "time_ms": int(elapsed*1000),
    "rows": device_count
})

# 测试3: Query - 有多少个接口
print("\n[3/3] Query: 有多少个接口")
success, output, elapsed = run_olav_query("有多少个接口")
print(f"Query: {'✅' if success else '❌'} (Time: {elapsed*1000:.0f}ms)")

results.append({
    "test": "Query: 有多少个接口",
    "passed": success,
    "time_ms": int(elapsed*1000)
})

# 生成报告
print("\n" + "="*70)
print("📊 测试结果汇总")
print("="*70)

passed = sum(1 for r in results if r.get("passed", False))
total = len(results)

for r in results:
    status = "✅" if r.get("passed", False) else "❌"
    time_str = f"{r['time_ms']}ms"
    rows_str = f"({r['rows']} rows)" if "rows" in r else ""
    print(f"{status} {r['test']:40s} {time_str:>10s} {rows_str}")

print(f"\n📈 Pass Rate: {passed}/{total} = {passed*100//total}%")

# 保存报告
report_md = f"""# Level 1-P0 能力验证报告
**日期**: 2026-02-08  
**状态**: {'✅ PASS' if passed == total else '⚠️ PARTIAL' if passed > 0 else '❌ FAIL'}

## 执行结果
| 测试 | 状态 | 时间 | 备注 |
|------|------|------|------|
"""

for r in results:
    status = "✅ PASS" if r.get("passed", False) else "❌ FAIL"
    rows_note = f"{r['rows']} rows" if "rows" in r else "-"
    report_md += f"| {r['test']} | {status} | {r['time_ms']}ms | {rows_note} |\n"

report_md += f"""
## 汇总
- **通过**: {passed}/{total}
- **通过率**: {passed*100//total}%
- **建议**: {'✅ Ready for L1 full suite' if passed == total else '⚠️ Debug queries'}

## 导出文件检查
"""

if EXPORTS_DIR.exists():
    csv_files = sorted(EXPORTS_DIR.glob("*.csv"))
    report_md += f"- CSV文件数: {len(csv_files)}\n"
    for f in csv_files[-5:]:
        rows = count_csv_rows(f.name)
        report_md += f"  - {f.name}: {rows} rows\n"

REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
with open(REPORT_FILE, 'w', encoding='utf-8') as f:
    f.write(report_md)

print(f"\n💾 报告已保存: {REPORT_FILE}")
