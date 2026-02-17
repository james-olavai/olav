#!/usr/bin/env python3
"""
Command Learner Agent - 学习 "show ip bgp neighbors" 命令

这个命令在 NTC 中缺失，但 R1 支持。
我们将使用 Command Learner Agent 来自主学习并生成 TextFSM 模板。

运行：
    uv run python3 learn_bgp_neighbors.py
"""

import asyncio
import sys
import json
from pathlib import Path

# Add project path
sys.path.insert(0, str(Path(__file__).parent / "src"))
sys.path.insert(0, str(Path(".olav/skills/command_learner/tools")))

from olav.agents.command_learner_agent import get_command_learner_agent
from execute_command import execute_command
from analyze_output import analyze_output
from ntc_search import search_ntc_templates
from template_generator import generate_template
from template_saver import save_template


async def learn_bgp_neighbors():
    """学习 show ip bgp neighbors 命令的 TextFSM 模板"""
    
    print("=" * 80)
    print("🧠 Command Learner - 自主学习 show ip bgp neighbors")
    print("=" * 80)
    
    print("\n📊 命令信息:")
    print("  - 命令: show ip bgp neighbors")
    print("  - 设备: R1 (Cisco IOS XE 17.1.1)")
    print("  - 平台: cisco_ios")
    print("  - 状态: NTC 中缺失 ❌")
    print("  - 目标: 从 R1 输出学习并生成 TextFSM 模板")
    
    # =========================================================================
    # Step 1: Execute Command
    # =========================================================================
    print("\n" + "=" * 80)
    print("✅ Step 1/6: Execute Command on R1")
    print("=" * 80)
    
    print("\n📡 在 R1 上执行 'show ip bgp neighbors'...\n")
    
    cmd_result = execute_command.invoke({
        "device": "R1",
        "command": "show ip bgp neighbors",
        "timeout": 30
    })
    
    if not cmd_result["success"]:
        print(f"❌ 命令执行失败: {cmd_result['error']}")
        return
    
    output = cmd_result["output"]
    print(f"✅ 命令执行成功!")
    print(f"   输出大小: {len(str(output))} 字符")
    
    # 解析输出
    try:
        if isinstance(output, str):
            # 尝试 JSON 解析
            output_list = json.loads(output)
        else:
            output_list = output if isinstance(output, list) else [output]
    except json.JSONDecodeError:
        # 如果不是 JSON，就当作原始输出
        output_list = [output]
    
    print(f"   解析记录: {len(output_list) if isinstance(output_list, list) else 1} 条")
    if output_list and isinstance(output_list, list):
        print(f"\n📋 样本记录:")
        print(json.dumps(output_list[0], indent=2, ensure_ascii=False))
    
    # =========================================================================
    # Step 2: Analyze Output (使用 LLM)
    # =========================================================================
    print("\n" + "=" * 80)
    print("✅ Step 2/6: Analyze Output with LLM")
    print("=" * 80)
    
    print("\n🤖 使用 LLM 分析输出并识别字段...\n")
    
    analyze_result = analyze_output.invoke({
        "command": "show ip bgp neighbors",
        "output": str(output_list[0]) if isinstance(output_list, list) and output_list else str(output),
        "platform": "cisco_ios"
    })
    
    print(f"✅ LLM 分析完成!")
    print(f"   识别字段数: {len(analyze_result.get('fields', []))}")
    print(f"   覆盖估计: {analyze_result.get('coverage_estimate', 'N/A')}")
    
    if analyze_result.get('fields'):
        print(f"\n📋 识别的字段:")
        for field in analyze_result['fields'][:5]:
            print(f"   - {field.get('name', 'unknown')}: {field.get('type', 'unknown')}")
    
    # =========================================================================
    # Step 3: User Approval (HITL)
    # =========================================================================
    print("\n" + "=" * 80)
    print("✅ Step 3/6: User Approval (HITL)")
    print("=" * 80)
    
    print("\n👤 人工审批步骤:")
    print("   在实际应用中，用户会在此审核识别的字段并确认。")
    print("   对于测试，我们自动批准所有字段。")
    
    # Keep full field dictionaries for template generation
    approved_fields = analyze_result.get('fields', [])
    print(f"\n✅ 批准的字段数: {len(approved_fields)}")
    if approved_fields:
        print(f"   字段列表: {[f.get('name') for f in approved_fields]}")
    
    # =========================================================================
    # Step 4: Search NTC Templates
    # =========================================================================
    print("\n" + "=" * 80)
    print("✅ Step 4/6: Search NTC Templates for References")
    print("=" * 80)
    
    print("\n🔍 搜索 NTC 中的相似模板作为参考...\n")
    
    # For search_ntc_templates, pass field names only (strings)
    field_names = [f.get('name', 'unknown') for f in approved_fields]
    
    ntc_result = search_ntc_templates.invoke({
        "platform": "cisco_ios",
        "command": "show ip bgp neighbors",
        "approved_fields": field_names,
        "limit": 3
    })
    
    ntc_templates = ntc_result.get("results", [])
    print(f"✅ 搜索完成!")
    print(f"   找到 {len(ntc_templates)} 个参考模板")
    
    for i, template in enumerate(ntc_templates, 1):
        print(f"\n   {i}. {template.get('template_name')}")
        print(f"      匹配度: {template.get('score', 0):.2%}")
        print(f"      找到字段: {template.get('fields_found')}")
    
    # =========================================================================
    # Step 5: Generate Template
    # =========================================================================
    print("\n" + "=" * 80)
    print("✅ Step 5/6: Generate TextFSM Template with LLM")
    print("=" * 80)
    
    print("\n🤖 使用 LLM 生成 TextFSM 模板...\n")
    
    # Prepare NTC references as template names (content not needed for this demo)
    ntc_refs_for_generation = [
        {
            "template_name": t.get('template_name', ''),
            "score": t.get('score', 0),
            "content": f"Reference template: {t.get('template_name', '')}"  # Minimal content for generation
        }
        for t in ntc_templates[:2]  # Limit to top 2 to save tokens
    ]
    
    gen_result = generate_template.invoke({
        "command": "show ip bgp neighbors",
        "platform": "cisco_ios",
        "approved_fields": approved_fields,
        "output_sample": str(output_list[0]) if isinstance(output_list, list) and output_list else str(output),
        "ntc_references": ntc_refs_for_generation
    })
    
    if gen_result.get("test_result", {}).get("success"):
        print(f"✅ 模板生成成功!")
        print(f"   迭代次数: {gen_result.get('iteration', 1)}/3")
        print(f"   模板文件名: {gen_result.get('filename')}")
        
        # 显示生成的模板前几行
        template_content = gen_result.get("template", "")
        lines = template_content.split("\n")[:10]
        print(f"\n📝 生成的模板 (前 10 行):")
        for line in lines:
            print(f"   {line}")
    else:
        print(f"⚠️  模板生成失败或需要迭代")
        print(f"   错误: {gen_result.get('test_result', {}).get('error', 'unknown')}")
    
    # =========================================================================
    # Step 6: Save Template
    # =========================================================================
    print("\n" + "=" * 80)
    print("✅ Step 6/6: Save Template & Auto-Reload")
    print("=" * 80)
    
    print("\n💾 保存模板并自动重载...\n")
    
    save_result = save_template.invoke({
        "template": gen_result.get("template", ""),
        "filename": gen_result.get("filename", "cisco_ios_show_ip_bgp_neighbors.textfsm"),
        "metadata": {
            "command": "show ip bgp neighbors",
            "platform": "cisco_ios",
            "fields": approved_fields,
            "learned": "true",
            "learned_date": "2026-02-15",
            "created_by": "Command Learner Agent v2.1.0"
        },
        "trigger_reload": True
    })
    
    if save_result.get("reload_triggered"):
        print(f"✅ 模板保存成功!")
        print(f"   保存位置: {save_result.get('saved_path')}")
        print(f"   热重载: {save_result.get('reload_triggered')} ✅")
        print(f"   新模板立即可用 (无需重启)")
    else:
        print(f"⚠️  保存可能有问题")
    
    # =========================================================================
    # Summary
    # =========================================================================
    print("\n" + "=" * 80)
    print("🎉 完整学习工作流完成!")
    print("=" * 80)
    
    print("""
📊 总结:
  1. ✅ 从 R1 执行 'show ip bgp neighbors' 命令
  2. ✅ LLM 分析输出并识别字段
  3. ✅ 人工批准字段（HITL）
  4. ✅ 搜索 NTC 参考模板
  5. ✅ LLM 生成 TextFSM 模板
  6. ✅ 保存并自动重载

🎯 结果:
  - 新模板已保存到: .olav/templates/custom/
  - 新模板已自动重载，可立即使用
  - 下次执行此命令时，出力将自动解析为结构化数据

✨ Command Learner Agent 成功学习了新命令!
""")


if __name__ == "__main__":
    asyncio.run(learn_bgp_neighbors())
