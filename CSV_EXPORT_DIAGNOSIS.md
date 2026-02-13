# CSV 导出失败诊断报告

**日期**: 2026-02-13  
**问题**: E2E测试中3个CSV导出相关测试失败

## 🔍 问题诊断

### 失败的测试
```
❌ test_query_export_to_csv
   - 查询: "save all devices to a csv file"
   - 期望: 在 exports/ 目录创建CSV文件
   - 实际: 无文件生成

❌ test_exports_dir_override
   - 问题: 自定义导出目录不工作

❌ test_parallel_exports_isolation
   - 问题: 并行导出隔离不工作
```

## 🎯 根本原因

### 原因 #1: Guard 路由错误

**问题**: Guard 将导出查询分类为 `SIMPLE` 路由

```python
# Guard分类结果
Query: "save all devices to csv"
Route: SIMPLE (数据库直接查询)
Confidence: 0.90

Query: "export devices to csv file"  
Route: SIMPLE
Confidence: 0.90
```

**为什么有问题**:
- SIMPLE 路由 = 直接数据库查询，无工具调用
- 导出需要: 数据库查询 + format_and_export 工具
- 应该路由到: EXPERT 或需要工具链的路由

### 原因 #2: SIMPLE 路由不处理导出

```python
# execution_dispatcher.py - _execute_simple_route()
def _execute_simple_route(self, query: str, decision: dict):
    """执行SIMPLE路由 - 仅数据库查询"""
    from olav.agents.orchestrator import orchestrate_query_sync
    
    # ❌ 只调用 orchestrate_query_sync，不调用导出工具
    result = orchestrate_query_sync(query)
    
    # 返回表格数据，不处理文件导出
    return {"status": "complete", "data": result["result"]}
```

### 原因 #3: 缺少导出目录配置

```python
# 测试期望在 CLITestEnvironment.exports_dir 中找到文件
# 但 SIMPLE 路由只返回数据，不执行导出
# 默认的 exports_dir 位置可能也没有轮转
```

## 📊 当前系统架构

```
┌─────────────────────────────────────────────────────────┐
│ 用户查询: "save all devices to csv"                     │
└────────────────┬────────────────────────────────────────┘
                 │
                 ▼
           ╔══════════════╗
           ║ Guard Router ║
           ╚════┬═════════╝
                │
     ┌──────────┴──────────┐
     │ Route: SIMPLE       │
     │ Confidence: 0.90    │
     └──────────┬──────────┘
                │
                ▼
        ╔═══════════════════╗
        │ExecutionDispatcher│
        │_execute_simple()  │
        └────┬──────────────┘
             │
             ▼
   ╔══════════════════════╗
   │orchestrate_query_sync│  ◄── ❌ 只查询，不导出
   │ SELECT * FROM ...    │
   └────┬─────────────────┘
        │
        ▼
   ┌──────────────┐
   │表格数据     │
   │(不生成CSV)   │
   └──────────────┘
```

## ✅ 解决方案

### 方案 A: 改进 Guard 分类 (推荐)

**步骤 1**: 创建 Guard 规则文件

```yaml
# .olav/skills/guard/SKILL.md [新建]

export_patterns:
  - keywords: ["export", "save", "write"]
    format: ["csv", "json", "yaml", "file"]
    route: "EXPERT"  # 或新建 "EXPORT" 路由
    confidence: 0.95
```

**步骤 2**: 修改 Guard 分类逻辑

```python
# security_classifier.py
def _classify_heuristic(self, query: str) -> tuple[str, float]:
    # 检测导出关键字
    export_keywords = ["export", "save", "write", "output"]
    export_formats = ["csv", "json", "yaml", "file"]
    
    has_export_keyword = any(kw in query.lower() for kw in export_keywords)
    has_format = any(fmt in query.lower() for fmt in export_formats)
    
    if has_export_keyword and has_format:
        return "EXPERT", 0.95  # 或 EXPORT 路由
    
    # ...其他分类...
```

**预期结果**:
```
Query: "save all devices to csv"
Route: EXPERT ✅
Confidence: 0.95
```

### 方案 B: 扩展 SIMPLE 路由处理导出 (替代方案)

```python
# execution_dispatcher.py
def _execute_simple_route(self, query: str, decision: dict):
    # 1. 先执行数据库查询
    result = orchestrate_query_sync(query)
    
    # 2. 检查是否需要导出
    if self._should_export(query):
        from olav.core.tools import get_tool
        export_tool = get_tool("format_and_export")
        
        # 3. 调用导出工具
        export_result = export_tool(
            data=result["result"],
            filename=self._infer_filename(query),
            format=self._infer_format(query)
        )
        
        return {"status": "complete", "export_path": export_result["path"]}
    
    return {"status": "complete", "data": result["result"]}
```

## 🏗️ 架构改进方案

```
修改后流程:
┌─────────────────────────────┐
│ 用户: "save devices to csv" │
└────────────┬────────────────┘
             │
             ▼
      ╔══════════════╗
      ║ Guard Router ║
      ╚════┬─────────╝
           │
        ┌──┴──┐
        │ EXPORT 路由  ✅
        │ (新增)
        └──┬──┘
           │
           ▼
  ╔═════════════════════════════╗
  │ orchestrate_query_sync()    │
  │ SELECT * FROM devices       │
  └──┬────────────────────────┬─╝
     │ 数据                   │
     ▼                        ▼
  ┌──────────┐        ╔════════════════╗
  │表格数据  │   ──► │format_and_export│
  └──────────┘        ║ 生成CSV文件     ║
                      ╚════════════════╝
                           │
                           ▼
                    ┌─────────────┐
                    │✅ CSV文件   │
                    │  exports/   │
                    │  devices.csv│
                    └─────────────┘
```

## 📋 实现检查清单

- [ ] 创建或更新 `.olav/skills/guard/SKILL.md`
- [ ] 添加导出关键字检测规则
- [ ] 修改 Guard 分类逻辑
- [ ] 可选: 创建新的 EXPORT 路由或扩展 SIMPLE
- [ ] 可选: 在 execution_dispatcher 中处理导出
- [ ] 测试导出查询路由
- [ ] 验证 CSV 文件生成
- [ ] 运行 E2E 测试验证

## 🔗 相关代码位置

```
Guard 分类:
  - src/olav/agents/guard.py (line 254)
  - src/olav/agents/security_classifier.py (line ~100)

路由执行:
  - src/olav/agents/execution_dispatcher.py (line 296)
  - src/olav/agents/query_orchestrator.py (line 21)

导出工具:
  - .olav/skills/shared/tools/data_export.py (line 30)
  - TOOL: format_and_export

E2E 测试:
  - tests/e2e/test_cli_scenarios.py (line 155)
```

## ⏱️ 预计工作量

- **分类规则**: 30 分钟
- **代码修改**: 1 小时
- **测试验证**: 30 分钟
- **总计**: ~2 小时

---

**结论**: CSV 导出失败的根本原因是 Guard 错误地将导出查询分类为 SIMPLE 路由，导致没有调用 format_and_export 工具。需要改进 Guard 的分类逻辑来正确识别导出意图。

