#!/usr/bin/env python3
"""
单步验证: L1-P0-001 - 列出所有设备
这是最基础的验证，确认Query Agent是否能执行
"""

import subprocess
import sys
from pathlib import Path

OLAV_ROOT = Path("/home/yhvh/Olav")

def test_basic():
    """测试基础功能：列出所有设备"""
    print("\n" + "="*70)
    print("🧪 Level 1-P0-001: 列出所有设备 (基础能力验证)")
    print("="*70)
    
    query = "列出所有设备"
    print(f"\n📝 查询: {query}")
    print(f"📍 工作目录: {OLAV_ROOT}")
    print(f"📂 导出目录: {OLAV_ROOT / 'exports'}")
    
    # 检查exports目录
    exports_dir = OLAV_ROOT / "exports"
    print(f"\n📊 执行前exports目录内容:")
    if exports_dir.exists():
        files = list(exports_dir.glob("*.csv")) + list(exports_dir.glob("*.md"))
        print(f"   找到 {len(files)} 个文件")
        for f in sorted(files)[-5:]:
            print(f"   - {f.name}")
    else:
        print("   ❌ 目录不存在")
    
    # 执行查询
    print(f"\n▶  执行 uv run olav ask '{query}'...")
    print("-" * 70)
    
    try:
        result = subprocess.run(
            ["uv", "run", "olav", "ask", query],
            cwd=OLAV_ROOT,
            capture_output=False,  # 直接输出
            text=True,
            timeout=45,
        )
        
        if result.returncode == 0:
            print("✅ 命令执行成功 (Exit Code: 0)")
        else:
            print(f"❌ 命令执行失败 (Exit Code: {result.returncode})")
        
    except subprocess.TimeoutExpired:
        print("❌ 命令超时 (>45秒)")
    except Exception as e:
        print(f"❌ 执行错误: {e}")
    
    # 检查输出文件
    print(f"\n📂 执行后exports目录内容:")
    if exports_dir.exists():
        csv_files = list(exports_dir.glob("*.csv"))
        print(f"   找到 {len(csv_files)} 个CSV文件")
        for f in sorted(csv_files)[-5:]:
            size = f.stat().st_size
            print(f"   - {f.name} ({size:,} bytes)")
        
        # 检查all_devices.csv
        all_devices = exports_dir / "all_devices.csv"
        if all_devices.exists():
            print(f"\n✅ 文件已生成: all_devices.csv")
            with open(all_devices, 'r') as f:
                lines = f.readlines()
                print(f"   行数: {len(lines)}")
                if lines:
                    print(f"   Header: {lines[0][:80]}")
                    if len(lines) > 1:
                        print(f"   首行数据: {lines[1][:80]}")
        else:
            print(f"\n❌ 文件未生成: all_devices.csv")

if __name__ == "__main__":
    test_basic()
