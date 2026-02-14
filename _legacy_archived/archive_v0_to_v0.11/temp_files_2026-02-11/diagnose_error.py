#!/usr/bin/env python3
"""
快速诊断脚本 - 捕捉错误的完整traceback
"""

import sys
import traceback
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent / "src"))

try:
    print("1️⃣ 导入orchestrator...")
    from olav.agents.orchestrator import Orchestrator
    
    print("2️⃣ 创建orchestrator实例...")
    orchestrator = Orchestrator()
    
    print("3️⃣ 执行查询...")
    result = orchestrator.query_sync("有多少个接口?")
    
    print(f"✅ 查询成功: {result}")
    
except Exception as e:
    print(f"\n❌ 捕捉到错误:\n")
    print("="*70)
    traceback.print_exc()
    print("="*70)
    
    # 提取关键信息
    error_type = type(e).__name__
    error_msg = str(e)
    
    # 查看traceback找具体位置
    tb = sys.exc_info()[2]
    tb_lines = traceback.extract_tb(tb)
    
    print(f"\n🔍 错误分析:")
    print(f"   类型: {error_type}")
    print(f"   信息: {error_msg}")
    print(f"\n   发生位置 (最近的三个):")
    for frame in tb_lines[-3:]:
        print(f"   - {frame.filename}:{frame.lineno} in {frame.name}")
        print(f"     {frame.line}")
