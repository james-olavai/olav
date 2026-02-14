#!/usr/bin/env python3
"""
OLAV Skill 改进 - 实施指南 (方案C)

工作量: 2小时
效果: 成功率 57.8% → 68-70%

改进内容:
1. 添加零值检测规则到 Skill
2. 改进 orchestrator 的结果解释
3. 改进错误恢复逻辑
"""

import os
from pathlib import Path

# ============================================================================
# 第1步: 需要修改的文件和位置
# ============================================================================

FILES_TO_MODIFY = {
    ".olav/skills/network-query/SKILL.md": {
        "description": "添加零值检测和错误诊断规则",
        "changes": [
            {
                "after_line": "3. **CASE Statements**",
                "add": """
11. **ZERO VALUE DETECTION** - 区分"无结果"vs"全是0"
    
    When query returns empty result (), execute validation:
    
    ✅ DO THIS:
       1. COUNT total rows in table: SELECT COUNT(*) FROM {table}
       2. Compare with WHERE result count
       3. If total > 0 but WHERE = 0:
          → This means "condition has no matches" NOT "no data"
    
    返回格式:
       "✅ 已检查 {total} 条记录，{matching} 条匹配"
       或
       "✅ 已检查 {total} 条记录，无匹配项"
       "💡 这可能表示状况正常(如:无错误=好消息)"

12. **ERROR DIAGNOSIS** - 诊断式错误提示
    
    When query_database() returns error:
    
    IF error contains "column ... does not exist":
       1. Call inspect_schema(table_name) to get real columns
       2. Show available column names
       3. Suggest similar column names based on user input
       4. Provide alternative suggestions
       
    IF error contains "table ... does not exist":
       1. Call inspect_schema() to get all tables
       2. Show available tables
       3. Suggest similar table names
    
    返回格式:
       "❌ {error_message}"
       "🔍 可能的原因: [列出几个]"
       "✅ 建议:
           - 运行 inspect_schema() 查看可用的表/字段
           - 尝试这些替代名称: [列表]"
"""
            }
        ]
    },
    
    "src/olav/agents/orchestrator.py": {
        "description": "改进结果返回和错误处理逻辑",
        "changes": [
            {
                "function": "orchestrate_query() 或 orchestrate_query_sync()",
                "add_after_getting_result": """
# 改进1: 零值检测
if isinstance(result, list) and len(result) == 0:
    # 检查是"无数据"还是"数据为0"
    try:
        check_sql = f"SELECT COUNT(*) as total FROM {inferred_table}"
        check_result = conn.execute(check_sql).fetchone()
        total_rows = check_result[0] if check_result else 0
        
        if total_rows > 0:
            # 有数据，但条件过滤后为0 - 这很正常
            message = f"✅ 已检查 {total_rows} 条记录，无匹配项"
            message += "\\n💡 这可能是正常的 (例如: 无错误 = 网络状况良好)"
            explanation = f"Database returned 0 matches for the condition, but {total_rows} total records exist in the table."
        else:
            # 真的无数据
            message = "⚠️ 表中无数据"
            explanation = "The table appears to be empty or not yet populated."
    except:
        pass  # 如果检查失败，使用默认消息
"""
            },
            {
                "function": "错误处理部分",
                "add_after_error": """
# 改进2: 错误诊断
if error_message and "does not exist" in error_message:
    if "column" in error_message:
        # 字段不存在 - 提示可能的替代
        column_name = extract_column_name(error_message)
        
        try:
            inspect_result = inspect_schema(inferred_table)
            available_columns = inspect_result.get('columns', [])
            
            suggestions = suggest_similar_names(column_name, available_columns)
            
            error_message += f"\\n🔍 可能的字段名: {suggestions}"
            error_message += f"\\n✅ 完整字段列表: {', '.join(available_columns[:5])}..."
            error_message += "\\n💡 运行 inspect_schema('table_name') 查看所有字段"
        except:
            pass
    
    elif "table" in error_message:
        # 表不存在 - 提示可用的表
        try:
            all_tables = inspect_schema()
            available_tables = all_tables.get('tables', [])
            
            table_name = extract_table_name(error_message)
            suggestions = suggest_similar_names(table_name, available_tables)
            
            error_message += f"\\n🔍 可用的表: {', '.join(available_tables[:5])}"
            error_message += f"\\n✅ 建议尝试: {suggestions}"
        except:
            pass

return {
    'success': success,
    'result': result if success else [],
    'message': message,
    'explanation': explanation if 'explanation' in locals() else None,
    'suggestions': get_user_suggestions(user_query, should_fix_error=not success)
}
"""
            }
        ]
    }
}

# ============================================================================
# 第2步: 辅助函数
# ============================================================================

def extract_column_name(error_msg: str) -> str:
    """从错误消息中提取列名"""
    import re
    match = re.search(r"column ['\"]?(\w+)['\"]?", error_msg, re.IGNORECASE)
    return match.group(1) if match else ""

def extract_table_name(error_msg: str) -> str:
    """从错误消息中提取表名"""
    import re
    match = re.search(r"table ['\"]?(\w+)['\"]?", error_msg, re.IGNORECASE)
    return match.group(1) if match else ""

def suggest_similar_names(input_name: str, available_names: list) -> list:
    """建议相似的名称"""
    from difflib import get_close_matches
    return get_close_matches(input_name, available_names, n=3, cutoff=0.6)

def get_user_suggestions(query: str, should_fix_error: bool = False) -> list:
    """根据查询类型提供建议"""
    suggestions = []
    
    if "error" in query.lower() and "crc" in query.lower():
        suggestions.append("💡 在模拟器中，错误计数通常为0。这表示网络健康。")
        suggestions.append("   如果需要测试错误处理，请尝试查询真实网络数据。")
    
    if "predict" in query.lower() or "fail" in query.lower():
        suggestions.append("💡 预测功能需要历史数据。目前只有当前快照可用。")
    
    if should_fix_error:
        suggestions.append("💡 运行 inspect_schema() 来探索可用的表和字段。")
    
    return suggestions

# ============================================================================
# 第3步: 测试框架
# ============================================================================

TESTS = [
    {
        "name": "零值检测测试",
        "query": "Which interfaces have CRC errors?",
        "expected": "✅ 已检查",  # 应该包含这个文本
        "success": True
    },
    {
        "name": "空结果解释测试",
        "query": "Show interfaces with input_errors > 1000",
        "expected": "已检查",
        "success": True
    },
    {
        "name": "错误诊断测试",
        "query": "Show devices with nonexistent_field",
        "expected": "🔍 可能的",  # 应该包含诊断信息
        "success": False  # 预期返回错误但有好建议
    },
    {
        "name": "工作查询测试",
        "query": "List all devices",
        "expected": True,
        "success": True
    }
]

# ============================================================================
# 执行步骤
# ============================================================================

def main():
    print("="*70)
    print("OLAV Skill 改进 - 方案C 执行指南")
    print("="*70)
    print()
    
    print("📋 要修改的文件:")
    print()
    for filepath, info in FILES_TO_MODIFY.items():
        print(f"  1. {filepath}")
        print(f"     → {info['description']}")
        print()
    
    print("📝 改动摘要:")
    print()
    print("  Skill.md:")
    print("    + 第11条规则: ZERO VALUE DETECTION (15行)")
    print("    + 第12条规则: ERROR DIAGNOSIS (20行)")
    print()
    print("  orchestrator.py:")
    print("    + 零值检测逻辑 (15行)")
    print("    + 错误诊断逻辑 (25行)")
    print()
    
    print("⏱️  时间投入:")
    print("    - Skill.md 修改: 30分钟")
    print("    - orchestrator.py 修改: 30分钟")
    print("    - 测试验证: 1小时")
    print("    - 总计: 2小时")
    print()
    
    print("📈 预期效果:")
    print("    - 成功率: 57.8% → 68-70%")
    print("    - 用户困惑度: ↓ 显著降低")
    print("    - 错误诊断: ↑ 明显改善")
    print()
    
    print("🧪 测试用例:")
    for i, test in enumerate(TESTS, 1):
        print(f"    {i}. {test['name']}")
        print(f"       Query: {test['query']}")
        print(f"       Expected: {test['expected']}")
    print()
    
    print("✅ 建议: 立即开始!\n")
    print("  1. 打开 .olav/skills/network-query/SKILL.md")
    print("  2. 在第30行左右添加规则11和12")
    print("  3. 打开 src/olav/agents/orchestrator.py")
    print("  4. 改进结果处理和错误处理逻辑")
    print("  5. 运行测试验证")
    print()

if __name__ == "__main__":
    main()
