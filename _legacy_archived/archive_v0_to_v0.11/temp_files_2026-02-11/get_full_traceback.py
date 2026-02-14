#!/usr/bin/env python3
"""
获取完整的错误traceback
"""

import sys
import logging
import traceback

# 启用详细日志
logging.basicConfig(level=logging.DEBUG, format='%(name)s: %(message)s')

try:
    print("=" * 70)
    print("导入必要的模块...")
    print("=" * 70)
    
    from olav.agents.orchestrator import create_orchestrator
    
    print("\n创建orchestrator...")
    agent = create_orchestrator()
    
    print("\n执行查询...")
    result = agent.invoke({"messages": [{"role": "user", "content": "有多少个接口?"}]})
    
    print(f"\n结果: {result}")
    
except Exception as e:
    print("\n" + "=" * 70)
    print("❌ 捕捉到错误:")
    print("=" * 70)
    
    # 打印完整traceback
    exc_type, exc_value, exc_tb = sys.exc_info()
    print(f"\n异常类型: {exc_type.__name__}")
    print(f"异常信息: {exc_value}")
    print(f"\n完整 traceback:")
    traceback.print_exc()
    
    # 提取最内层的几个frames
    print("\n" + "-" * 70)
    print("错误发生的最近3个位置:")
    print("-" * 70)
    
    tb_list = traceback.extract_tb(exc_tb)
    for frame in tb_list[-3:]:
        print(f"\n文件: {frame.filename}")
        print(f"函数: {frame.name}")
        print(f"行号: {frame.lineno}")
        print(f"代码: {frame.line}")
