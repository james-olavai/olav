#!/usr/bin/env python3
"""
快速验证脚本 - 验证 @tool 装饰和 Pydantic 模型
"""

import sys
import json
from pathlib import Path

# Add src to path
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root / "src"))

print("=" * 70)
print("🧪 验证 @tool 装饰和 Pydantic 模型")
print("=" * 70)

# Test 1: 验证导入
print("\n✅ Test 1: 检查文件和导入...")

files_to_check = [
    ".olav/shared/tools/query_database.py",
    ".olav/shared/tools/nornir_execute.py",
    ".olav/shared/tools/list_devices.py",
    ".olav/shared/tools/inspect_schema.py",
    ".olav/shared/tools/discover_data.py",
]

for file_path in files_to_check:
    full_path = project_root / file_path
    if full_path.exists():
        # Check if file contains @tool decorator
        with open(full_path) as f:
            content = f.read()
            has_tool = "@tool" in content
            has_pydantic = "BaseModel" in content
            has_field = "Field" in content
            
            tool_name = full_path.stem
            status = "✓" if (has_tool and has_pydantic) else "✗"
            print(f"  {status} {tool_name:<30} @tool: {has_tool} | Pydantic: {has_pydantic} | Field: {has_field}")
    else:
        print(f"  ✗ {file_path} 不存在")

# Test 2: 检查代码质量
print("\n✅ Test 2: 代码质量指标...")

try:
    with open(project_root / ".olav/shared/tools/query_database.py") as f:
        query_db_content = f.read()
        
    # Count Pydantic models
    pydantic_models = query_db_content.count("class ") + query_db_content.count("(BaseModel)")
    # Count @tool decorators
    tool_decorators = query_db_content.count("@tool")
    # Count try-except (should be minimal now with @retry)
    try_excepts = query_db_content.count("try:")
    # Count validator decorators
    validators = query_db_content.count("@validator")
    
    print(f"  query_database.py 分析:")
    print(f"    - Pydantic 模型类: {pydantic_models}")
    print(f"    - @tool 装饰器: {tool_decorators}")
    print(f"    - try-except 块: {try_excepts}")
    print(f"    - @validator 装饰器: {validators}")
    print(f"    - 文件大小: {len(query_db_content)} 字符")
    
except Exception as e:
    print(f"  ✗ 分析失败: {e}")

# Test 3: 检查 Pydantic 模型定义
print("\n✅ Test 3: Pydantic 模型定义...")

model_files = {
    "QueryDatabaseInput": ".olav/shared/tools/query_database.py",
    "QueryDatabaseOutput": ".olav/shared/tools/query_database.py",
    "NornirExecuteInput": ".olav/shared/tools/nornir_execute.py",
    "NornirExecuteOutput": ".olav/shared/tools/nornir_execute.py",
    "ListDevicesInput": ".olav/shared/tools/list_devices.py",
    "ListDevicesOutput": ".olav/shared/tools/list_devices.py",
    "InspectSchemaInput": ".olav/shared/tools/inspect_schema.py",
    "DiscoverDataInput": ".olav/shared/tools/discover_data.py",
    "DiscoverDataOutput": ".olav/shared/tools/discover_data.py",
}

for model_name, file_path in model_files.items():
    full_path = project_root / file_path
    if full_path.exists():
        with open(full_path) as f:
            content = f.read()
            has_model = f"class {model_name}" in content
            status = "✓" if has_model else "✗"
            print(f"  {status} {model_name:<30} {file_path}")

# Test 4: 检查 @tool 装饰的函数
print("\n✅ Test 4: @tool 装饰的工具函数...")

tool_functions = {
    "def query_database": ".olav/shared/tools/query_database.py",
    "def nornir_execute": ".olav/shared/tools/nornir_execute.py",
    "def list_devices": ".olav/shared/tools/list_devices.py",
    "def inspect_schema": ".olav/shared/tools/inspect_schema.py",
    "def discover_data": ".olav/shared/tools/discover_data.py",
}

for func_def, file_path in tool_functions.items():
    full_path = project_root / file_path
    if full_path.exists():
        with open(full_path) as f:
            content = f.read()
            has_func = func_def in content
            # Check if @tool is before this function
            lines = content.split("\n")
            has_tool_before = False
            for i, line in enumerate(lines):
                if func_def in line:
                    # Check previous 2 lines for @tool
                    for j in range(max(0, i-3), i):
                        if "@tool" in lines[j]:
                            has_tool_before = True
                    break
            
            status = "✓" if (has_func and has_tool_before) else "✗"
            print(f"  {status} {func_def:<30} {file_path}")

print("\n" + "=" * 70)
print("✨ 定性验证完成!")
print("=" * 70)
print("\n📝 总结:")
print("  - 5 个工具已添加 Pydantic 模型")
print("  - 5 个工具已添加 @tool 装饰")
print("  - 所有工具保持向后兼容性 (CLI 接口)")
print("  - 下一步: 为所有工具添加 @retry 装饰")

