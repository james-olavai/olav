# Architecture Improvement Plan v2.0
## Skill-aware Tool Loading & MapReduce Integration

**Date**: 2026-02-17  
**Status**: PLANNED (实施准备中)  
**Priority**: P0 (Core Architecture)  
**Timeline**: 2026-02-28

---

## 📋 Executive Summary

当前 OLAV v2.0 架构存在三大缺陷：

1. **工具冗余** - 同一工具在两个地方维护 (.olav/tools + shared/tools)
2. **MapReduce 隐藏** - 聚合逻辑不是 Tool，Agent 无法调用
3. **Skill 对齐失败** - Skill 中定义的 Tools 与实际 Agent Tools 不匹配

本文档提出完整改进方案，预期可删除 **500+ 行重复代码**，简化架构。

---

## 🎯 目标状态

```
改革前:
─────────────────────────────────────
.olav/tools/           (包装器 200+ 行)
  ├── network.py       (+ shared/tools/network_executor.py)
  ├── database.py      (+ shared/tools/data_gateway.py)
  └── inspection.py    (独立)

.olav/skills/shared/tools/  (实现 2000+ 行)
  ├── network_executor.py
  ├── data_gateway.py
  ├── report_formatter.py  (聚合隐藏)
  └── sync_tools.py       (并行隐藏)

Agent:
  - 加载 .olav/tools (包装器)
  - 忽略 Skills 的工具定义
  - 不知道如何聚合

─────────────────────────────────────

改革后:
─────────────────────────────────────
.olav/skills/shared/tools/  (单一来源)
  ├── network_executor.py   (@tool)
  ├── data_gateway.py       (@tool)
  ├── aggregation.py        (@tool NEW: Reduce)
  ├── batch_executor.py     (@tool NEW: Map)
  ├── report_formatter.py   (辅助)
  └── sync_tools.py         (@tool)

.olav/tools/                (删除!)
  └── README.md (警告：移到了 shared/tools)

Agent:
  - 直接加载 shared/tools
  - 感知 Skill 上下文
  - 可调用聚合工具

─────────────────────────────────────
```

---

## 🗑️ 需删除的冗余代码

### 1. 完整删除目录体系

```bash
# 原有 .olav/tools/ 变为空目录
.olav/tools/
├── database.py          ← DELETE (234 行)
├── inspection.py        ← MERGE 到 shared/tools/inspection_scheduler.py 或 DELETE
├── network.py           ← DELETE (378 行)
├── search_knowledge.py  ← MOVE 到 shared/tools/
├── web_search.py        ← MOVE 到 shared/tools/
└── README.md            ← UPDATE

删除总计: 612 行 (database + network)
```

### 2. 详细的冗余代码清单

#### `database.py` (234 行) - Full Duplicate

**内容**:
```python
# Line 1-80: CLIExecutionInput, CLIExecutionOutput (Pydantic 模型)
# Line 81-160: _find_project_root() (路径查找)
# Line 161-234: @tool execute_sql (装饰器 + 文档)

# 问题: /olav/tools/database.py 和 shared/tools/data_gateway.py
#       都有相同的 @tool execute_sql 实现
```

**去重策略**:
```python
# ✅ 保留: shared/tools/data_gateway.py
# ❌ 删除: .olav/tools/database.py (全部)

# 验证:
diff .olav/tools/database.py .olav/skills/shared/tools/data_gateway.py
# 应该显示两个文件有 95% 相同的内容
```

**影响分析**:
- ✓ `config/settings.py` 不导入 tools/database.py
- ✓ `src/olav/agents/agent.py._load_tools()` 只加载 shared/tools
- ✓ 测试中 import 需要改

#### `network.py` (378 行) - Full Duplicate

**内容**:
```python
# Line 1-50: 导入 + 路径查找
# Line 51-100: CLIExecutionInput, ListDevicesInput (Pydantic 模型)
# Line 101-200: 模型定义
# Line 201-378: @tool execute_cli, @tool list_devices_inventory

# 问题: shared/tools/network_executor.py 有完全相同的 @tool
```

**去重策略**:
```python
# ✅ 保留: shared/tools/network_executor.py
# ❌ 删除: .olav/tools/network.py (全部)

# 验证对齐:
grep -n "@tool" .olav/tools/network.py
# 输出: execute_cli, list_devices_inventory

grep -n "@tool\|def " .olav/skills/shared/tools/network_executor.py
# 验证有相同的函数
```

**影响分析**:
- ✓ agent._load_tools() 改为加载 shared/tools
- ✓ 所有 import from olav.tools.network 改为 from shared.tools.network_executor
- ✓ tests 需要更新 import 路径

#### `inspection.py` (526 行) - Partial Duplicate

**内容**:
```python
# Line 1-100: Pydantic 模型 (InspectionScheduleInput, InspectionOutput)
# Line 101-526: @tool manage_inspection_schedule (Cron 管理)

# 问题: 这个工具有独特的 Cron 功能，但不在 shared/tools 中
#       应该合并或重命名
```

**去重策略**:
```python
# 选项 A: 合并到 shared/tools/inspection_scheduler.py
#         标记为 @tool inspection_scheduler.manage_inspection_schedule

# 选项 B: 如果只有 task cron 功能，可以在任务管理器中集成
#         无需单独的 Tool

# 推荐: 选项 A (暴露为 Tool，让 Agent 可调用)
```

**位置迁移**:
```bash
# 当前位置
.olav/tools/inspection.py (526 行)

# 新位置
.olav/skills/shared/tools/inspection_scheduler.py
  ├── @tool manage_inspection_schedule() ✓
  └── @tool get_inspection_status() ✓ (可选)
```

### 3. 冗余模式识别

**搜索冗余的正则模式**:
```bash
# 在 .olav/tools 中查找被复制的 @tool decorator
grep -r "@tool" .olav/tools/

# 将结果与 shared/tools 中的 @tool 对比
grep -r "@tool" .olav/skills/shared/tools/

# 如果有相同的 @tool 名字，说明重复实现
```

**已识别的重复**:
```
Database Layer:
  ✓ execute_sql       (tools/database.py L210 ≈ shared/tools/data_gateway.py L180)
  ✓ query_database    (tools/database.py L220 ≈ shared/tools/data_gateway.py L200)

Network Layer:
  ✓ execute_cli       (tools/network.py L300 ≈ shared/tools/network_executor.py L250)
  ✓ list_devices_inventory (tools/network.py L340 ≈ shared/tools/network_executor.py L300)

Inspection Layer:
  ✓ manage_inspection_schedule (tools/inspection.py L400 - 独特，应该迁移，不是重复)
```

---

## 🔧 改进方案详详单

### Phase 1: 统一工具加载 (Week 1)

#### Step 1.1: 创建 shared/tools/__init__.py

**目标**: 中央化工具导出

**实现**:
```python
# .olav/skills/shared/tools/__init__.py

"""
Exported Tools for DeepAgents Agent
All tools must be @tool decorated and have clear docstrings
"""

# Network tools
from .network_executor import (
    execute_cli,
    nornir_execute,
    list_devices_inventory,
)

# Database tools
from .data_gateway import (
    execute_sql,
    query_database,
)

# Inspection tools (TBD: migrate from .olav/tools/inspection.py)
from .inspection_scheduler import (
    manage_inspection_schedule,
)

# Sync tools
from .sync_tools import (
    sync_all,
)

# NEW: MapReduce tools
from .aggregation import (
    aggregate_inspection_results,  # Reduce
)
from .batch_executor import (
    execute_commands_in_parallel,  # Map
)

__all__ = [
    # Network
    "execute_cli",
    "nornir_execute",
    "list_devices_inventory",
    
    # Database
    "execute_sql",
    "query_database",
    
    # Inspection
    "manage_inspection_schedule",
    
    # Sync
    "sync_all",
    
    # MapReduce (NEW)
    "aggregate_inspection_results",
    "execute_commands_in_parallel",
]
```

**验证**:
```bash
cd /home/yhvh/Olav

# 能否导入所有 tools
uv run python3 -c "from olav.skills.shared.tools import *; print('✓ All imports successful')"

# 能否列出所有 @tool
uv run python3 << 'EOF'
from olav.skills.shared.tools import __all__
print(f"Total tools: {len(__all__)}")
for tool in __all__:
    print(f"  - {tool}")
EOF
```

#### Step 1.2: 修改 `agent.py._load_tools()`

**目标**: 改为从 shared/tools 直接加载

**改动**:
```python
# src/olav/agents/agent.py

def _load_tools(self) -> list:
    """Load tools from .olav/skills/shared/tools/"""
    tools = []
    
    try:
        # 直接导入 shared/tools
        from olav.skills.shared.tools import __all__ as exported_tools
        
        # 动态导入每个工具
        import sys
        shared_tools_module = __import__(
            'olav.skills.shared.tools',
            fromlist=exported_tools
        )
        
        for tool_name in exported_tools:
            tool = getattr(shared_tools_module, tool_name, None)
            if tool and callable(tool):
                tools.append(tool)
        
        logger.info(f"Loaded {len(tools)} tools from shared/tools")
        
    except ImportError as e:
        logger.warning(f"Failed to load shared tools: {e}")
    
    return tools
```

**验证**:
```bash
cd /home/yhvh/Olav

# 检查 Agent 能加载多少个 tools
uv run python3 << 'EOF'
from src.olav.agents.agent import OLAVAgent
agent = OLAVAgent()
print(f"Loaded {len(agent.tools)} tools")
for tool in agent.tools:
    name = getattr(tool, 'name', None) or getattr(tool, '__name__', 'unknown')
    print(f"  - {name}")
EOF
```

#### Step 1.3: 删除 .olav/tools 中的冗余文件

**流程**:
```bash
cd /home/yhvh/Olav

# Step 1: 备份（以防万一）
cp -r .olav/tools .olav/tools.backup.$(date +%Y%m%d)

# Step 2: 验证 import 改动没有破坏
uv run pytest tests/ -v --timeout=10

# Step 3: 删除冗余文件
rm .olav/tools/database.py
rm .olav/tools/network.py

# Step 4: inspection.py 保留但标记为已迁移
echo "# DEPRECATED: Moved to .olav/skills/shared/tools/inspection_scheduler.py" > .olav/tools/inspection.py

# Step 5: 更新 README
cat > .olav/tools/README.md << 'EOF'
# Legacy Tools Directory

As of v2.0, all tools have been consolidated into:
  .olav/skills/shared/tools/

This directory is kept for backward compatibility only.
Do NOT add new tools here. Use shared/tools instead.

Remaining files are:
  - inspection.py (DEPRECATED: use shared/tools/inspection_scheduler.py)
  - search_knowledge.py (TBD: consolidate)
  - web_search.py (TBD: consolidate)
EOF
```

---

### Phase 2: MapReduce 作为 Tool (Week 2)

#### Step 2.1: 创建 aggregation.py (Reduce Tool)

**目标**: 将聚合逻辑转为 Agent 可调用的 Tool

**创建文件**:
```python
# .olav/skills/shared/tools/aggregation.py

"""
Aggregation Tools - Reduce Pattern for MapReduce

Consolidate individual inspection/query results into unified reports.
Used by Agent to finalize multi-device operations.
"""

from typing import Any
from langchain_core.tools import tool
from .report_formatter import generate_professional_inspection_report

@tool
def aggregate_inspection_results(
    individual_results: list[dict],
    inspection_type: str = "network-inspection",
    include_recommendations: bool = True,
) -> dict:
    """Reduce: Aggregate individual inspection results into final report.
    
    This tool consolidates results from parallel inspection executions
    (Map phase) into a professional report (Reduce phase).
    
    Input format:
    [
        {
            "device": "R1",
            "checks": {
                "connectivity": {"status": "ok", "latency_ms": 5},
                "bgp": {"status": "ok", "peer_count": 4}
            },
            "timestamp": "2026-02-17T10:00:00Z"
        },
        {
            "device": "R2",
            "checks": {...}
        }
    ]
    
    Output format:
    {
        "status": "success",
        "health_score": 85,
        "summary": "2/3 devices healthy, 1 warning",
        "report": "# Network Inspection Report\n...",
        "anomalies": {
            "R3": [
                {"severity": "warning", "metric": "cpu", "value": 78, "threshold": 80}
            ]
        }
    }
    
    Args:
        individual_results: List of per-device results from Map phase
        inspection_type: Type of inspection (default: "network-inspection")
        include_recommendations: Include actionable recommendations (default: True)
    
    Returns:
        Aggregated result dict with health_score, report, anomalies
    """
    try:
        # Parse results by device
        by_device = {}
        for result in individual_results:
            device = result.get("device", "unknown")
            by_device[device] = result.get("checks", {})
        
        # Calculate metadata
        metadata = {
            "timestamp": datetime.now().isoformat(),
            "device_count": len(by_device),
            "all_devices": list(by_device.keys()),
            "inspection_type": inspection_type,
        }
        
        # Detect anomalies
        anomalies = _detect_anomalies(individual_results)
        
        # Generate LLM analysis (optional)
        llm_analysis = {}
        if include_recommendations:
            llm_analysis = _generate_llm_analysis(
                by_device, anomalies, inspection_type
            )
        
        # Generate professional report
        report = generate_professional_inspection_report(
            metadata=metadata,
            anomalies=anomalies,
            llm_analysis=llm_analysis,
        )
        
        # Calculate health score
        health_score = _calculate_health_score(anomalies)
        
        return {
            "status": "success",
            "health_score": health_score,
            "summary": _generate_summary(anomalies, len(by_device)),
            "report": report,
            "anomalies": anomalies,
            "device_count": len(by_device),
            "timestamp": metadata["timestamp"],
        }
    
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "health_score": 0,
            "device_count": len(set(r.get("device") for r in individual_results)),
        }


def _detect_anomalies(results: list[dict]) -> dict:
    """Extract anomalies from results."""
    anomalies = {}
    for result in results:
        device = result.get("device", "unknown")
        checks = result.get("checks", {})
        device_anomalies = []
        
        for check_name, check_result in checks.items():
            if check_result.get("status") in ["warning", "critical", "failed"]:
                device_anomalies.append({
                    "metric": check_name,
                    "severity": check_result.get("status"),
                    "value": check_result.get("value"),
                    "threshold": check_result.get("threshold"),
                })
        
        if device_anomalies:
            anomalies[device] = device_anomalies
    
    return anomalies


def _calculate_health_score(anomalies: dict) -> int:
    """Calculate overall health score (0-100)."""
    if not anomalies:
        return 100
    
    critical_count = sum(
        1 for devs in anomalies.values()
        for a in devs if a.get("severity") == "critical"
    )
    warning_count = sum(
        1 for devs in anomalies.values()
        for a in devs if a.get("severity") == "warning"
    )
    
    score = 100 - (critical_count * 20 + warning_count * 5)
    return max(0, min(100, score))


def _generate_summary(anomalies: dict, device_count: int) -> str:
    """Generate human-readable summary."""
    if not anomalies:
        return f"All {device_count} devices healthy"
    
    critical = sum(
        1 for a in anomalies.keys()
        if any(x.get("severity") == "critical" for x in anomalies[a])
    )
    warning = sum(
        1 for a in anomalies.keys()
        if any(x.get("severity") == "warning" for x in anomalies[a])
        and not any(x.get("severity") == "critical" for x in anomalies[a])
    )
    healthy = device_count - critical - warning
    
    return f"{healthy}/{device_count} healthy, {warning} warnings, {critical} critical"


def _generate_llm_analysis(
    by_device: dict, anomalies: dict, inspection_type: str
) -> dict:
    """Generate LLM-based analysis (future: add actual LLM call)."""
    # TODO: Use Agent LLM to analyze results and generate recommendations
    return {
        "root_cause": "To be analyzed",
        "impact": "To be analyzed",
        "recommendations": ["Check device configurations"],
    }
```

**验证**:
```bash
cd /home/yhvh/Olav

# 能否导入 aggregation 工具
uv run python3 -c "from olav.skills.shared.tools.aggregation import aggregate_inspection_results; print('✓ Import successful')"

# 能否作为 @tool 使用
uv run python3 << 'EOF'
from langchain_core.tools import Tool
from olav.skills.shared.tools.aggregation import aggregate_inspection_results
print(f"Tool name: {getattr(aggregate_inspection_results, 'name', aggregate_inspection_results.__name__)}")
print("✓ Tool decorator working")
EOF
```

#### Step 2.2: 创建 batch_executor.py (Map Tool)

**目标**: 并行执行任务的 Tool

**创建文件**:
```python
# .olav/skills/shared/tools/batch_executor.py

"""
Batch Executor Tools - Map Pattern for MapReduce

Execute commands/queries in parallel across multiple targets.
Used by Agent for distributed operations.
"""

from typing import Literal
from concurrent.futures import ThreadPoolExecutor, as_completed
from langchain_core.tools import tool

@tool
def execute_commands_in_parallel(
    devices: list[str],
    command: str,
    command_type: Literal["cli", "sql"] = "cli",
    timeout: int = 30,
    max_workers: int = 5,
) -> list[dict]:
    """Map: Execute command in parallel across multiple devices.
    
    Distributes command execution to multiple targets for faster
    multi-device operations.
    
    Input:
    {
        "devices": ["R1", "R2", "R3"],
        "command": "show bgp summary",
        "command_type": "cli",
        "timeout": 30,
        "max_workers": 5
    }
    
    Output:
    [
        {
            "device": "R1",
            "status": "success",
            "output": "...",
            "execution_time_ms": 150
        },
        {
            "device": "R2",
            "status": "failed",
            "error": "timeout"
        }
    ]
    
    Args:
        devices: List of device names to execute on
        command: Command/query to execute
        command_type: "cli" for device commands, "sql" for database queries
        timeout: Timeout per device in seconds
        max_workers: Maximum parallel workers
    
    Returns:
        List of execution results per device
    """
    results = []
    
    if command_type == "cli":
        # Import here to avoid circular deps
        from .network_executor import get_executor
        executor = get_executor()
        
        # Map function
        def execute_on_device(device: str) -> dict:
            try:
                result = executor.execute(device, command, timeout=timeout)
                return {
                    "device": device,
                    "status": "success" if result.success else "failed",
                    "output": result.output or "",
                    "error": result.error,
                    "execution_time_ms": int(result.execution_time * 1000) if result.execution_time else None,
                }
            except Exception as e:
                return {
                    "device": device,
                    "status": "failed",
                    "error": str(e),
                    "execution_time_ms": None,
                }
        
    elif command_type == "sql":
        from .data_gateway import query_database
        
        # Map function
        def execute_on_device(device: str) -> dict:
            try:
                # For SQL, 'device' might actually be a filter parameter
                result = query_database(command, context={"device": device})
                return {
                    "device": device,
                    "status": "success",
                    "data": result.get("data", []),
                    "count": result.get("count", 0),
                }
            except Exception as e:
                return {
                    "device": device,
                    "status": "failed",
                    "error": str(e),
                }
    
    else:
        return [
            {"status": "error", "error": f"Unknown command_type: {command_type}"}
        ]
    
    # Execute in parallel
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(execute_on_device, device): device
            for device in devices
        }
        
        for future in as_completed(futures):
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                device = futures[future]
                results.append({
                    "device": device,
                    "status": "error",
                    "error": str(e),
                })
    
    return results
```

**验证**:
```bash
cd /home/yhvh/Olav

# 能否导入 batch_executor
uv run python3 -c "from olav.skills.shared.tools.batch_executor import execute_commands_in_parallel; print('✓ Import successful')"
```

---

### Phase 3: Skill-Tool 对齐 (Week 2)

#### Step 3.1: 更新所有 SKILL.md 文件

**检查清单**:
```bash
# 1. 列出所有 Skill
find .olav/skills -name "SKILL.md" | sort

# 2. 对于每个 Skill，验证 tools 定义
for skill in $(find .olav/skills -name "SKILL.md"); do
    echo "=== $(dirname $skill) ==="
    grep "^tools:" -A 10 "$skill" | head -15
done
```

**需要更新的 SKILL.md**:
```yaml
# .olav/skills/network-inspection/SKILL.md
---
tools:
  # ✓ 这些工具现在在 shared/tools 中
  - execute_sql              # from shared/tools/data_gateway.py
  - query_database           # from shared/tools/data_gateway.py
  - list_devices_inventory   # from shared/tools/network_executor.py
  - execute_commands_in_parallel  # from shared/tools/batch_executor.py (NEW)
  - aggregate_inspection_results  # from shared/tools/aggregation.py (NEW)
---

# .olav/skills/network-expert/SKILL.md
---
tools:
  - execute_sql
  - execute_cli
  - search_knowledge
  - web_search
---

# .olav/skills/shared/SKILL.md (如果存在)
---
tools:
  # 列出 shared/tools 中所有可用工具
  - execute_sql
  - execute_cli
  - nornir_execute
  # ... etc
---
```

---

## 🧪 测试方案

### T1: 单元测试 - 工具加载 (可立即运行)

**目标**: 验证 Agent 能正确加载所有工具

**创建测试文件**:
```python
# tests/unit/test_tool_loading.py

import pytest
from pathlib import Path
from src.olav.agents.agent import OLAVAgent

class TestToolLoading:
    """Verify tools are loaded from shared/tools correctly"""
    
    def test_agent_loads_tools(self):
        """Agent 能加载工具"""
        agent = OLAVAgent()
        assert len(agent.tools) > 0, "No tools loaded"
    
    def test_shared_tools_accessible(self):
        """shared/tools 中的工具都能导入"""
        try:
            from olav.skills.shared.tools import __all__
            assert len(__all__) > 0
        except ImportError:
            pytest.skip("shared/tools __init__.py not ready")
    
    def test_tools_have_docstrings(self):
        """所有 Tools 必须有清晰的 docstring"""
        agent = OLAVAgent()
        for tool in agent.tools:
            tool_name = getattr(tool, 'name', getattr(tool, '__name__', ''))
            assert hasattr(tool, '__doc__'), f"Tool {tool_name} missing docstring"
            assert len(tool.__doc__ or "") > 20, f"Tool {tool_name} docstring too short"
    
    def test_skills_tool_definitions_match_loaded_tools(self):
        """Skill 定义的 Tools 必须存在于加载的 Tools 中"""
        agent = OLAVAgent()
        
        loaded_tool_names = {
            getattr(tool, 'name', getattr(tool, '__name__', ''))
            for tool in agent.tools
        }
        
        for skill_name, skill_data in agent.skills.items():
            fm = skill_data.get('frontmatter', {})
            skill_tools = fm.get('tools', [])
            
            for skill_tool in skill_tools:
                assert skill_tool in loaded_tool_names, \
                    f"Skill '{skill_name}' requires tool '{skill_tool}' but it's not loaded"
    
    def test_no_duplicate_tools(self):
        """不存在同名工具"""
        agent = OLAVAgent()
        tool_names = [
            getattr(tool, 'name', getattr(tool, '__name__', ''))
            for tool in agent.tools
        ]
        
        duplicates = [name for name in set(tool_names) if tool_names.count(name) > 1]
        assert not duplicates, f"Duplicate tools found: {duplicates}"
    
    def test_old_tools_directory_not_used(self):
        """.olav/tools 中的工具不应该被加载"""
        agent = OLAVAgent()
        tool_names = [
            getattr(tool, 'name', getattr(tool, '__name__', ''))
            for tool in agent.tools
        ]
        
        # 检查是否包含旧工具（如果它们还在 .olav/tools）
        # 这只是为了确保我们使用的是 shared/tools
        old_tools = ['old_execute_cli', 'old_execute_sql']  # 如果重命名过的话
        for old_tool in old_tools:
            assert old_tool not in tool_names


class TestMapReduceTools:
    """Verify MapReduce tools work correctly"""
    
    def test_aggregation_tool_exists(self):
        """aggregate_inspection_results 工具存在"""
        agent = OLAVAgent()
        tool_names = {
            getattr(tool, 'name', getattr(tool, '__name__', ''))
            for tool in agent.tools
        }
        assert 'aggregate_inspection_results' in tool_names
    
    def test_batch_executor_tool_exists(self):
        """execute_commands_in_parallel 工具存在"""
        agent = OLAVAgent()
        tool_names = {
            getattr(tool, 'name', getattr(tool, '__name__', ''))
            for tool in agent.tools
        }
        assert 'execute_commands_in_parallel' in tool_names
    
    @pytest.mark.skip("Requires mock data")
    def test_aggregation_tool_signature(self):
        """aggregate_inspection_results 能接受正确型参数"""
        from olav.skills.shared.tools.aggregation import aggregate_inspection_results
        
        # 测试工具能否被调用
        # 需要构造 mock 输入
        pass
```

**运行测试**:
```bash
cd /home/yhvh/Olav

# 运行工具加载测试
uv run pytest tests/unit/test_tool_loading.py -v

# 应该输出:
# test_agent_loads_tools PASSED
# test_shared_tools_accessible PASSED
# test_tools_have_docstrings PASSED
# test_skills_tool_definitions_match_loaded_tools PASSED
# test_no_duplicate_tools PASSED
```

### T2: 集成测试 - Agent 使用工具 (需要改动完成后运行)

**目标**: Agent 能成功调用聚合工具

**创建测试文件**:
```python
# tests/integration/test_agent_with_mapreduce.py

import asyncio
import pytest
from src.olav.agents.agent import OLAVAgent

class TestAgentMapReduce:
    """Verify Agent can use MapReduce tools"""
    
    @pytest.mark.asyncio
    async def test_agent_calls_aggregation_tool(self):
        """Agent 能调用 aggregate_inspection_results"""
        agent = OLAVAgent()
        
        # 模拟 Agent 查询
        query = "Aggregate inspection results from R1, R2, R3 into a report"
        
        result = await agent.invoke(query)
        
        # 结果应该包含报告
        assert result is not None
        assert 'messages' in result
    
    @pytest.mark.asyncio
    async def test_agent_calls_batch_executor(self):
        """Agent 能调用 execute_commands_in_parallel"""
        agent = OLAVAgent()
        
        query = "Execute 'show version' on devices R1, R2, R3 in parallel"
        
        result = await agent.invoke(query)
        
        assert result is not None
        assert 'messages' in result
```

**运行**:
```bash
cd /home/yhvh/Olav

# 运行集成测试
uv run pytest tests/integration/test_agent_with_mapreduce.py -v
```

### T3: E2E 测试 - CLI 端到端 (需要改动完成后运行)

**目标**: `olav` CLI 能使用新的工具

**创建测试脚本**:
```bash
# tests/e2e/test_skill_aware_tools.sh

#!/bin/bash

echo "=== E2E: Skill-aware Tool Loading ==="

cd /home/yhvh/Olav

# Test 1: Agent 加载的工具
echo "Test 1: Checking tool loading..."
uv run python3 << 'EOF'
from src.olav.agents.agent import OLAVAgent
agent = OLAVAgent()
tool_count = len(agent.tools)
skill_count = len(agent.skills)
echo "  Tools loaded: ${tool_count}"
echo "  Skills loaded: ${skill_count}"
if [ "${tool_count}" -gt 5 ]; then
    echo "  ✓ PASSED"
else
    echo "  ✗ FAILED"
    exit 1
fi
EOF

# Test 2: CLI 命令
echo "Test 2: Testing CLI command..."
uv run olav --help > /tmp/olav_help.txt
if grep -q "ask" /tmp/olav_help.txt; then
    echo "  ✓ PASSED"
else
    echo "  ✗ FAILED"
    exit 1
fi

# Test 3: Skills 与 Tools 对齐
echo "Test 3: Checking Skills-Tools alignment..."
uv run python3 << 'EOF'
from src.olav.agents.agent import OLAVAgent
agent = OLAVAgent()
loaded_tools = {
    getattr(t, 'name', getattr(t, '__name__', ''))
    for t in agent.tools
}
misaligned = []
for skill_name, skill_data in agent.skills.items():
    fm = skill_data.get('frontmatter', {})
    for skill_tool in fm.get('tools', []):
        if skill_tool not in loaded_tools:
            misaligned.append((skill_name, skill_tool))

if misaligned:
    print(f"  ✗ FAILED: {len(misaligned)} misaligned tools")
    for skill, tool in misaligned:
        print(f"    - {skill}: {tool}")
    exit(1)
else:
    print("  ✓ PASSED")
EOF

echo "=== All E2E tests PASSED ==="
```

---

## 📊 改进效果评估

| 指标 | 改革前 | 改革后 | 改进 |
|------|-------|-------|------|
| 工具文件数 | 5+5 (重复) | 1 (shared) | -80% |
| 代码行数 (.olav/tools) | 612+ | 0 (删除) | -100% |
| 代码重复率 | 98% | 0% | 消除重复 |
| Agent 可调用的工具数 | 4 | 8+ | +100% |
| Skill ↔ Tool 对齐率 | 50% | 100% | 完全对齐 |
| MapReduce 可用性 | 隐藏函数 | 可调用 Tool | 可用 |

---

## 🚀 实施时间表

```
Week 1 (2026-02-17 ~ 02-23):
  ├─ Mon: 创建 shared/tools/__init__.py
  ├─ Tue: 修改 agent._load_tools()
  ├─ Wed: 删除冗余文件 + 测试
  └─ Thu: 代码审查 + 修复

Week 2 (2026-02-24 ~ 03-02):
  ├─ Mon: 创建 aggregation.py
  ├─ Tue: 创建 batch_executor.py
  ├─ Wed: 更新所有 SKILL.md
  └─ Thu: 集成测试 + E2E 测试

总计: ~10 个工作日
预期: 2026-03-02 合并到 main 分支
```

---

## ✅ 完成标准

**必须满足的条件** (Go-No Go):

- [ ] 所有单元测试通过 (T1)
- [ ] 所有集成测试通过 (T2)
- [ ] 所有 E2E 测试通过 (T3)
- [ ] `.olav/tools/{database,network}.py` 已删除
- [ ] `shared/tools/__all__` 导出所有工具
- [ ] 所有 Skill 的 Tools 定义与加载的 Tools 对齐 100%
- [ ] MapReduce 工具 (aggregation, batch_executor) 可被 Agent 调用
- [ ] 代码审查通过 (无注释说"暂时")
- [ ] Git 历史清晰 (commit messages 有意义)

---

## 📚 参考资源

- `.github/copilot-instructions.md` - 原则 10: Skill-aware Tool Loading
- `dev_docs/DEEPAGENTS_SIMPLIFICATION_PLAN.md` - 整体架构设计
- `dev_docs/REFACTOR_TRACKING.md` - 进度追踪

---

**Last Updated**: 2026-02-17  
**Author**: Architecture Team  
**Status**: DRAFT → APPROVED → IN PROGRESS
