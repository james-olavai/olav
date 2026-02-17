#!/usr/bin/env python3
"""
Simplified Command Learner Workflow Demonstration

This script demonstrates the 6-step self-learning workflow for show ip bgp neighbors
using the existing NTC template as reference instead of generating a new one.
"""

import asyncio
import json
import sys
from pathlib import Path

# Add project paths
sys.path.insert(0, str(Path(__file__).parent / "src"))
sys.path.insert(0, str(Path(".olav/skills/command_learner/tools").absolute()))

# Import tools from Command Learner Agent
from execute_command import execute_command
from analyze_output import analyze_output
from ntc_search import search_ntc_templates
from template_reader import read_template_file
from template_saver import save_template


async def learn_bgp_neighbors_simplified():
    """Demonstrate 6-step Command Learner workflow on show ip bgp neighbors."""
    
    print("=" * 80)
    print("🧠 Command Learner - 自主学习 show ip bgp neighbors (简化演示)")
    print("=" * 80)
    print()
    print("📊 命令信息:")
    print("   - 命令: show ip bgp neighbors")
    print("   - 设备: R1 (Cisco IOS XE 17.1.1)")
    print("   - 平台: cisco_ios")
    print("   - 状态: NTC 中已存在 ✅")
    print("   - 目标: 演示完整的 6 步学习工作流")
    print()
    
    # =========================================================================
    # Step 1: Execute Command on R1
    # =========================================================================
    print("=" * 80)
    print("✅ Step 1/6: Execute Command on R1")
    print("=" * 80)
    print()
    print("📡 在 R1 上执行 'show ip bgp neighbors'...")
    print()
    
    exec_result = execute_command.invoke({
        "device": "R1",
        "command": "show ip bgp neighbors",
        "timeout": 30
    })
    
    if not exec_result.get("success"):
        print(f"❌ 命令执行失败: {exec_result.get('error')}")
        return
    
    output = exec_result.get("output", "")
    print(f"✅ 命令执行成功!")
    print(f"   输出大小: {len(str(output))} 字符")
    
    # Parse the output to understand structure
    try:
        output_list = json.loads(output) if isinstance(output, str) else output
        if isinstance(output_list, list):
            print(f"   解析记录: {len(output_list)} 条")
            print("\n📋 样本记录:")
            print(f"   {json.dumps(output_list[0] if output_list else {}, indent=2)[:500]}")
    except:
        pass
    
    print()
    
    # =========================================================================
    # Step 2: Analyze Output with LLM
    # =========================================================================
    print("=" * 80)
    print("✅ Step 2/6: Analyze Output with LLM")
    print("=" * 80)
    print()
    print("🤖 使用 LLM 分析输出并识别字段...")
    print()
    
    analyze_result = analyze_output.invoke({
        "command": "show ip bgp neighbors",
        "platform": "cisco_ios",
        "output": str(output)[:2000]
    })
    
    fields = analyze_result.get("fields", [])
    print(f"✅ LLM 分析完成!")
    print(f"   识别字段数: {len(fields)}")
    print(f"   覆盖估计: {analyze_result.get('coverage_estimate', 'N/A')}")
    
    if fields:
        print(f"\n📋 识别的字段:")
        for field in fields[:5]:
            print(f"   - {field.get('name')}: {field.get('type')}")
    
    print()
    
    # =========================================================================
    # Step 3: User Approval (HITL)
    # =========================================================================
    print("=" * 80)
    print("✅ Step 3/6: User Approval (HITL)")
    print("=" * 80)
    print()
    print("👤 人工审批步骤:")
    print("   在实际应用中，用户会在此审核识别的字段并确认。")
    print("   对于演示，我们自动批准所有字段。")
    print()
    
    approved_fields = fields
    print(f"✅ 批准的字段数: {len(approved_fields)}")
    if approved_fields:
        print(f"   字段列表: {[f.get('name') for f in approved_fields]}")
    
    print()
    
    # =========================================================================
    # Step 4: Search NTC Templates for References
    # =========================================================================
    print("=" * 80)
    print("✅ Step 4/6: Search NTC Templates for References")
    print("=" * 80)
    print()
    print("🔍 搜索 NTC 中的相似模板作为参考...")
    print()
    
    field_names = [f.get('name') for f in approved_fields]
    
    ntc_result = search_ntc_templates.invoke({
        "platform": "cisco_ios",
        "command": "show ip bgp neighbors",
        "approved_fields": field_names,
        "limit": 3
    })
    
    ntc_templates = ntc_result.get("results", [])
    print(f"✅ 搜索完成!")
    print(f"   找到 {len(ntc_templates)} 个参考模板")
    print()
    
    for i, template in enumerate(ntc_templates, 1):
        print(f"   {i}. {template.get('template_name')}")
        print(f"      匹配度: {template.get('score', 0):.2%}")
        print(f"      找到字段: {len(template.get('fields_found', []))} 个字段")
    
    print()
    
    # =========================================================================
    # Step 5: Load Existing NTC Template (instead of generating)
    # =========================================================================
    print("=" * 80)
    print("✅ Step 5/6: Load Existing NTC Template")
    print("=" * 80)
    print()
    print("📖 加载最匹配的 NTC 模板...")
    print()
    
    if ntc_templates:
        best_template_name = ntc_templates[0].get('template_name')
        best_template_path = ntc_templates[0].get('template_path')
        print(f"   最佳匹配: {best_template_name} (相似度: {ntc_templates[0].get('score', 0):.2%})")
        print(f"   模板路径: {best_template_path}")  # Debug: Print the path
        
        # Read the template file using the full path
        read_result = read_template_file.invoke({
            "template_path": best_template_path
        })
        
        if read_result.get("content"):
            template_content = read_result.get("content")
            print(f"✅ 模板加载成功!")
            print(f"   模板大小: {len(template_content)} 字符")
            print(f"\n📝 模板内容 (前 20 行):")
            lines = template_content.split("\n")[:20]
            for line in lines:
                print(f"   {line}")
            
            print()
            
            # =========================================================================
            # Step 6: Save Template & Auto-Reload
            # =========================================================================
            print("=" * 80)
            print("✅ Step 6/6: Save Template & Auto-Reload")
            print("=" * 80)
            print()
            print("💾 保存模板并自动重载...")
            print()
            
            # Generate custom filename
            custom_filename = "cisco_ios_show_ip_bgp_neighbors_learned.textfsm"
            
            # Prepare metadata
            ntc_metadata = read_result.get("fields", [])
            metadata = {
                "command": "show ip bgp neighbors",
                "platform": "cisco_ios",
                "fields": ntc_metadata,
                "source": "NTC templates",
                "learned": True
            }
            
            save_result = save_template.invoke({
                "template": template_content,
                "filename": custom_filename,
                "metadata": metadata
            })
            
            if save_result.get("saved_path") or not save_result.get("error"):
                print(f"✅ 模板保存成功!")
                if save_result.get("saved_path"):
                    print(f"   文件: {save_result.get('saved_path')}")
                if save_result.get("reload_triggered"):
                    print(f"   是否自动重载: 是")
                
                print()
                print("=" * 80)
                print("🎉 学习工作流完成！")
                print("=" * 80)
                print()
                print("📊 工作流总结:")
                print(f"   ✅ Step 1: 命令执行 - 输出已获取")
                print(f"   ✅ Step 2: 输出分析 - {len(fields)} 个字段识别")
                print(f"   ✅ Step 3: 用户批准 - {len(approved_fields)} 个字段批准")
                print(f"   ✅ Step 4: NTC 搜索 - {len(ntc_templates)} 个模板found")
                print(f"   ✅ Step 5: 模板加载 - {len(template_content)} 字符加载，找到 {len(read_result.get('fields', []))} 个字段")
                print(f"   ✅ Step 6: 模板保存 - 已保存到自定义目录")
                print()
                print(f"💡 下次执行 'show ip bgp neighbors' 时，将使用新学习的模板进行解析")
                
            else:
                print(f"❌ 保存失败: {save_result.get('error')}")
        else:
            print(f"❌ 读取失败: {read_result.get('error')}")
    else:
        print("❌ 未找到参考模板")


if __name__ == "__main__":
    asyncio.run(learn_bgp_neighbors_simplified())
