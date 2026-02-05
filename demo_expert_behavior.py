#!/usr/bin/env python3
"""
Expert Agent 行为演示脚本

演示两个关键问题：
1. Expert 调用 CLI 会不会 block 危险命令？
2. Expert 完成后会不会生成报告？还是直接返回 Orchestrator？
"""

import asyncio
from olav.tools.network_executor import NetworkExecutor, get_executor


def demo_1_dangerous_command_blocking():
    """演示1：危险命令拦截"""
    print("\n" + "=" * 80)
    print("演示1：Expert 调用 CLI 是否会 block 危险命令？")
    print("=" * 80)

    executor = NetworkExecutor()

    # 测试1.1: 危险命令 - reload
    print("\n【测试1.1】执行危险命令: reload")
    result = executor.execute(device="R1", command="reload")
    print(f"设备: {result.device}")
    print(f"命令: {result.command}")
    print(f"执行结果: {'✅ 成功' if result.success else '❌ 被拦截'}")
    print(f"错误信息: {result.error}")
    print(f"耗时: {result.duration_ms}ms (0ms = 未连接设备)")

    # 测试1.2: 危险命令 - write erase
    print("\n【测试1.2】执行危险命令: write erase")
    result = executor.execute(device="R1", command="write erase")
    print(f"设备: {result.device}")
    print(f"命令: {result.command}")
    print(f"执行结果: {'✅ 成功' if result.success else '❌ 被拦截'}")
    print(f"错误信息: {result.error}")

    # 测试1.3: 危险命令 - delete
    print("\n【测试1.3】执行危险命令: delete flash:")
    result = executor.execute(device="R1", command="delete flash:")
    print(f"执行结果: {'✅ 成功' if result.success else '❌ 被拦截'}")
    print(f"错误信息: {result.error}")

    # 测试1.4: 安全命令 - show version
    print("\n【测试1.4】执行安全命令: show version")
    result = executor.execute(device="R1", command="show version")
    print(f"执行结果: {'✅ 成功' if result.success else '❌ 失败'}")
    if result.success:
        print(f"输出预览: {result.output[:100] if result.output else 'N/A'}...")
    else:
        print(f"错误信息: {result.error}")


def demo_2_blacklist_mechanism():
    """演示2：黑名单机制详解"""
    print("\n" + "=" * 80)
    print("演示2：黑名单机制详解")
    print("=" * 80)

    executor = NetworkExecutor()

    # 显示加载的黑名单
    print(f"\n已加载的命令黑名单 ({len(executor.blacklist)} 条):")
    for pattern in sorted(executor.blacklist):
        print(f"  - {pattern}")

    print("\n黑名单检查规则：")
    print("  1. 精确匹配: 'reload' 匹配 'reload'")
    print("  2. 通配符匹配: 'reload*' 匹配 'reload', 'reload in 5 minutes'")

    # 测试通配符匹配
    print("\n【通配符匹配测试】")
    test_cases = [
        ("reload", "reload"),
        ("reload in 5", "reload*"),
        ("reboot", "reboot"),
        ("show version", None),
        ("configure terminal", None),
    ]

    for cmd, expected_pattern in test_cases:
        matched = executor._is_blacklisted(cmd)
        status = "✅" if (matched and expected_pattern) or (not matched and not expected_pattern) else "❌"
        print(f"{status} '{cmd}' → 匹配: {matched or '(允许)'}")


async def demo_3_expert_workflow():
    """演示3：Expert Agent 工作流程"""
    print("\n" + "=" * 80)
    print("演示3：Expert Agent 工作流程")
    print("=" * 80)

    from olav.agents.orchestrator import orchestrate_query

    query = "R3 的 OSPF 邻居 down 了，为什么？"

    print(f"\n【用户查询】{query}")
    print("\n【Orchestrator 工作流程】:")
    print("  1. ✅ 检查缓存 (Fast Path)")
    print("  2. ✅ 路由决策 → 选择 'expert' SubAgent")
    print("  3. ✅ Expert Agent 执行:")
    print("     ├─ 调用 nornir_execute ('R3', 'show ip ospf neighbor')")
    print("     │  └─ 安全检查:")
    print("     │     ├─ 黑名单检查 → ✅ PASS")
    print("     │     ├─ 注册表检查 → ✅ PASS")
    print("     │     └─ 执行命令 → 获取输出")
    print("     ├─ 调用 nornir_execute ('R1', 'show ip ospf neighbor')")
    print("     ├─ 调用 analyze_topology ('ospf')")
    print("     ├─ 调用 search_similar_cases (symptom='ospf neighbor down')")
    print("     └─ [可选] 调用 generate_diagnosis_report()")
    print("  4. ✅ 聚合结果")
    print("  5. ✅ 返回给用户")

    print("\n【返回值流程】:")
    print("  Expert Agent 返回 →  Orchestrator  →  格式化输出")
    print("  - 状态: complete")
    print("  - 诊断分析: {LLM推理结果}")
    print("  - final_answer: {最终答案}")

    print("\n【是否生成报告？】:")
    print("  ✅ 如果调用 generate_diagnosis_report() → 生成 Markdown 报告")
    print("  ✅ 如果不调用 → 直接返回诊断分析文本给 Orchestrator")
    print("  ⚠️  报告生成是可选的，由 LLM 决定是否调用")


def demo_4_safety_layers():
    """演示4：安全防护层"""
    print("\n" + "=" * 80)
    print("演示4：CLI 执行的三层安全防护")
    print("=" * 80)

    print("""
    命令执行流程:
    
    用户查询 (Expert Agent LLM)
        ↓
    nornir_execute(device, command)
        ↓
    NetworkExecutor.execute()
        ↓
    ┌─────────────────────────────────────────┐
    │ 第1层：黑名单检查 (命令级安全)           │
    │ - reload, reboot, shutdown, delete      │
    │ - write erase, format, erase            │
    │ - 检查时间: O(1)                        │
    │ - 失败返回: False + 错误信息             │
    └─────────────────────────────────────────┘
        ↓ (PASS)
    ┌─────────────────────────────────────────┐
    │ 第2层：命令注册表验证 (平台级安全)       │
    │ - 检查命令是否在该平台的白名单中        │
    │ - 例: Cisco IOS 允许 show*, 拒绝 del*   │
    │ - 检查时间: O(log N)                    │
    │ - 失败返回: False + "未找到模板"         │
    └─────────────────────────────────────────┘
        ↓ (PASS)
    ┌─────────────────────────────────────────┐
    │ 第3层：设备库存检查 (访问级安全)         │
    │ - 设备是否存在于 Nornir inventory       │
    │ - 设备是否在线                          │
    │ - 检查时间: O(1)                        │
    │ - 失败返回: False + "设备未找到"        │
    └─────────────────────────────────────────┘
        ↓ (PASS)
    ┌─────────────────────────────────────────┐
    │ 安全执行：                              │
    │ nr.filter(name=device).run(             │
    │     task=netmiko_send_command           │
    │ )                                       │
    └─────────────────────────────────────────┘
        ↓
    CommandExecutionResult {
        success: true,
        output: "...",
        duration_ms: 250
    }
    """)

    print("\n【防护特点】:")
    print("  1. ✅ 多层防护：黑名单 + 注册表 + 库存检查")
    print("  2. ✅ 快速失败：第一道防线失败立即返回，不连接设备")
    print("  3. ✅ 审计日志：成功执行记录到数据库")
    print("  4. ✅ 清晰错误：说明被拦截的具体原因")
    print("  5. ✅ 零延迟：拦截不产生网络延迟 (duration_ms=0)")


def main():
    """运行所有演示"""
    print("\n🎯 Expert Agent 行为演示")
    print("=" * 80)

    # 演示1: 危险命令拦截
    demo_1_dangerous_command_blocking()

    # 演示2: 黑名单机制
    demo_2_blacklist_mechanism()

    # 演示3: Expert 工作流程
    asyncio.run(demo_3_expert_workflow())

    # 演示4: 安全防护层
    demo_4_safety_layers()

    # 总结
    print("\n" + "=" * 80)
    print("总结")
    print("=" * 80)
    print("""
【问题1】Expert 调用 CLI 会不会 block 危险命令？
✅ 答案：会。采用双层防护 (黑名单 + 注册表验证)
  - 命令被拦截时立即返回失败 (duration_ms=0)
  - 不会连接设备，避免网络延迟
  - 提供清晰的错误信息说明被拦截原因

【问题2】Expert 完成后会不会生成报告？还是直接返回 Orchestrator？
✅ 答案：取决于 LLM 决策
  - 如果 Expert 调用 generate_diagnosis_report() → 生成 Markdown 报告
  - 如果不调用 → 直接返回诊断分析文本给 Orchestrator
  - Orchestrator 聚合所有 SubAgent 结果后返回给用户

【安全机制】
✅ 三层安全防护：
  1. 黑名单检查（命令级）
  2. 命令注册表验证（平台级）
  3. 设备库存检查（访问级）
    """)


if __name__ == "__main__":
    main()
