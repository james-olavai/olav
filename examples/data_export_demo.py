#!/usr/bin/env python3
"""数据导出功能使用示例"""

import asyncio
from olav.agents.orchestrator import orchestrate_query


async def demo_export_features():
    """演示数据导出功能"""
    
    print("=" * 80)
    print("🎯 OLAV 数据导出功能演示")
    print("=" * 80)
    
    print("\n📋 支持的使用场景:")
    print("-" * 80)
    
    scenarios = [
        {
            "name": "诊断报告导出（Markdown）",
            "query": "分析R1的OSPF邻居状态，生成诊断报告并保存",
            "expected": "exports/xxx_diagnosis.md"
        },
        {
            "name": "数据查询导出（CSV）",
            "query": "查询所有VLAN信息，导出为CSV表格",
            "expected": "exports/vlans.csv"
        },
        {
            "name": "设备清单导出（JSON）",
            "query": "查询所有设备信息，保存为JSON格式",
            "expected": "exports/devices_inventory.json"
        },
        {
            "name": "CLI输出保存（Text）",
            "query": "在R1上执行show tech-support，保存到文件",
            "expected": "exports/R1_tech_support.txt"
        },
        {
            "name": "不导出（仅查询）",
            "query": "列出所有核心设备",
            "expected": "无文件输出，直接显示结果"
        }
    ]
    
    for i, scenario in enumerate(scenarios, 1):
        print(f"\n{i}️⃣ {scenario['name']}")
        print(f"   用户查询: \"{scenario['query']}\"")
        print(f"   预期输出: {scenario['expected']}")
    
    print("\n" + "=" * 80)
    print("🔧 技术特性")
    print("=" * 80)
    
    features = [
        "✅ 自动格式检测：从内容特征推断文件格式（md/json/txt/csv）",
        "✅ LLM智能理解：识别'保存'/'导出'等关键意图",
        "✅ 统一输出目录：所有文件导出到 exports/ 目录",
        "✅ 自动文件命名：带时间戳的智能命名",
        "✅ 零硬编码：无关键词映射，完全由LLM理解",
        "✅ 权限控制：只有Orchestrator能写文件",
        "✅ 多格式支持：Markdown, JSON, CSV, Text, YAML",
    ]
    
    for feature in features:
        print(f"  {feature}")
    
    print("\n" + "=" * 80)
    print("📖 使用说明")
    print("=" * 80)
    
    instructions = """
1. 查询并导出：
   $ olav "查询所有VLAN信息，导出为CSV"
   
2. 诊断并保存：
   $ olav "诊断R1的OSPF问题，生成报告并保存"
   
3. CLI输出保存：
   $ olav "在R1上执行show tech，保存到文件"
   
4. 仅查询（不导出）：
   $ olav "列出所有设备"  # 不会生成文件
   
5. 查看导出的文件：
   $ ls -lh exports/
   
6. 手动整理到知识库：
   $ cp exports/ospf_diagnosis.md .olav/knowledge/cases/
"""
    
    print(instructions)
    
    print("\n" + "=" * 80)
    print("🧪 快速测试")
    print("=" * 80)
    
    print("\n运行以下命令测试基础功能：")
    print("  $ uv run python src/olav/tools/data_export.py")
    print("\n运行E2E测试：")
    print("  $ uv run python tests/e2e/test_data_export_e2e.py")
    print("\n运行pytest测试：")
    print("  $ uv run pytest tests/e2e/test_data_export_e2e.py -v")
    
    print("\n" + "=" * 80)
    print("✨ 示例输出")
    print("=" * 80)
    
    example_output = """
用户: "查询所有Cisco设备，导出CSV"

LLM响应:
  正在查询设备信息...
  找到6台Cisco设备
  正在导出到CSV文件...
  
  ✅ 已导出到 exports/cisco_devices_20260205_143022.csv
  
  文件包含以下列：
  - hostname
  - ip_address
  - vendor
  - model
  - device_role
  
  共6条记录，文件大小: 256 bytes
"""
    
    print(example_output)
    
    print("\n" + "=" * 80)
    print("🎉 功能已就绪！开始使用吧！")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(demo_export_features())
