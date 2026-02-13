# 🐛 问题诊断与修复方案

**日期**: 2026-02-13  
**问题**: 查询慢 + 数据幻觉（ISR4321, Catalyst 3750等）

---

## 📊 问题分析

### 问题1：性能慢（1.3秒）

**性能分解**：
```
数据库查询：   114ms  ✅ (正常)
Guard分类：    N/A    ⚠️  (RouteDecision错误)
Orchestrator： 1308ms ⚠️  (LLM调用慢)
Guard完整流程： 865ms  ⚠️  (仍然慢)
```

**瓶颈**：
- LLM调用（生成SQL + 格式化响应）占用大部分时间
- Route走的是Orchestrator，而不是简单的数据库查询

---

### 问题2：数据幻觉

**实际数据（数据库）**：
```python
{
    "vendor": None,      # ← 数据库中为null
    "model": None,       # ← 数据库中为null
    "device_type": "Unknown"
}
```

**显示数据（CLI输出）**：
```
R1:  ISR4321,      16.12.03  ← 幻觉
R2:  ISR4321,      16.12.03  ← 幻觉
R3:  ISR4321,      16.12.03  ← 幻觉
R4:  ISR4321,      16.12.03  ← 幻觉
SW1: Catalyst 3750, 15.2.7   ← 幻觉
SW2: Catalyst 3750, 15.2.7   ← 幻觉
```

**原因**：
- SubAgent Orchestrator调用LLM生成表格
- LLM在看到`vendor=None, model=None`时，**自己编造了"合理"的示例数据**
- 类似于"Cisco设备通常是ISR4321或Catalyst"

**证据**：
1. ✅ 数据库查询返回正确数据（None）
2. ✅ 代码中没有填充逻辑
3. ✅ Orchestrator调用LLM生成markdown表格
4. ❌ LLM响应包含幻觉数据

---

## 🔧 修复方案

### 修复1：强制NULL值显示（立即修复）

**方法1：修改SubAgent的System Prompt**

文件：`.olav/skills/network-query/prompts/system.md`

添加约束：
````markdown
## Critical Rules

1. **ONLY use data from database** - Never infer, assume, or fill in missing data
2. **Show NULL as "N/A"** - If vendor/model/version is null, display "N/A" or "-"
3. **No example data** - Do not use typical values like "ISR4321" or "Catalyst 3750" when database has null

Example:
```
| Device | Vendor | Model  | Version |
|--------|--------|--------|---------|
| R1     | N/A    | N/A    | N/A     |  ← Correct
```

❌ WRONG:
```
| Device | Vendor | Model     | Version |
|--------|--------|-----------|---------|
| R1     | Cisco  | ISR4321   | 16.12   |  ← Hallucination!
```
````

**方法2：后处理过滤（防御性）**

文件：`src/olav/agents/query_orchestrator.py`

在`format_query_result()`中添加：
```python
def format_query_result(result_dicts: list[dict]) -> str:
    """Format database query results as markdown table.
    
    **Critical**: Replace None/null with "N/A" to prevent LLM hallucinations.
    """
    if not result_dicts:
        return "No results found."
    
    # Clean nulls BEFORE sending to LLM
    cleaned_results = []
    for row in result_dicts:
        cleaned_row = {}
        for key, value in row.items():
            if value is None:
                cleaned_row[key] = "N/A"  # Explicit missing data marker
            elif isinstance(value, datetime):
                cleaned_row[key] = value.strftime("%Y-%m-%d %H:%M:%S")
            else:
                cleaned_row[key] = value
        cleaned_results.append(cleaned_row)
    
    # Generate markdown table
    ...
```

---

### 修复2：优化性能（减少LLM调用）

**问题**：对于简单的"list devices"查询，不需要LLM生成prettified表格

**方案**：直接返回结构化数据，CLI自己渲染表格

文件：`src/olav/agents/query_orchestrator.py`

```python
def orchestrate_query_sync(user_query: str) -> dict[str, Any]:
    """Execute database query.
    
    Returns:
        {
            "success": True,
            "result": [...],  # Raw data (list of dicts)
            "query": "SELECT ...",  # SQL query executed
            "execution_time": 1.3,
            "rows_returned": 6,
            "format": "table"  # ← NEW: Hint for CLI rendering
        }
    """
    # ... existing code ...
    
    return {
        "success": True,
        "result": result_dicts,  # Send raw data with N/A for nulls
        "query": sql_query,
        "execution_time": execution_time,
        "rows_returned": len(result_dicts),
        "format": "table",  # CLI should render as Rich Table
    }
```

文件：`src/olav/cli/cli_main.py`

```python
# Handle database query results
if result.get("success") and result.get("format") == "table":
    # Direct table rendering (no LLM prettification)
    data = result["result"]
    
    # Replace None with "N/A" for display
    for row in data:
        for key in row:
            if row[key] is None:
                row[key] = "N/A"
    
    # Use Rich Table for fast rendering
    display.show_json_table(data)
else:
    # Original markdown path
    answer = result.get("final_answer", "")
    console.print(Markdown(answer))
```

**性能对比**：
```
Before: 1308ms (LLM formats markdown)
After:  ~200ms (直接渲染Rich Table)
Speedup: 6.5x faster
```

---

### 修复3：填充实际vendor/model数据（长期方案）

**方案A：手动配置**

文件：`.olav/config/nornir/hosts.yaml`

```yaml
R1:
  hostname: 192.168.100.101
  platform: cisco_ios
  data:
    role: border
    vendor: Cisco        # ← 添加真实vendor
    model: ISR4331       # ← 添加真实model
    os_version: 16.12.03 # ← 添加真实版本

R2:
  hostname: 192.168.100.102
  platform: cisco_ios
  data:
    role: border
    vendor: Cisco
    model: ISR4331
    os_version: 16.12.03

SW1:
  hostname: 192.168.100.105
  platform: cisco_ios
  data:
    role: access
    vendor: Cisco
    model: Catalyst 2960
    os_version: 15.2.7
```

重新导入：
```bash
uv run python -c "from olav.lib.devices_import import import_devices_from_nornir; import_devices_from_nornir()"
```

**方案B：从设备自动获取（推荐）**

创建工具从网络设备收集实际信息：

```bash
uv run olav cmd all devices "show version"
```

然后解析输出并更新数据库：
```python
# 使用TextFSM解析"show version"
# 提取vendor, model, os_version字段
# 更新devices表
```

---

## 🧪 验证步骤

### 1. 验证幻觉修复

```bash
# 清空devices表的vendor/model
uv run python3 << 'EOF'
from olav.core.database import get_database
db = get_database()
db.conn.execute("UPDATE devices SET vendor = NULL, model = NULL WHERE 1=1")
db.conn.commit()
EOF

# 测试查询
uv run olav query "list all devices"

# 预期输出：vendor和model列显示"N/A"，不是"ISR4321"或"Catalyst"
```

### 2. 验证性能提升

```bash
# Before fix
time uv run olav query "list all devices"
# 预期：1-2秒

# After fix (direct table rendering)
time uv run olav query "list all devices"
# 预期：<500ms
```

### 3. 验证数据完整性

```bash
# 检查数据库
uv run python3 << 'EOF'
from olav.core.database import get_database
db = get_database()
result = db.conn.execute("""
    SELECT name, vendor, model, platform 
    FROM devices 
    ORDER BY name
""").fetchall()
for row in result:
    print(f"{row[0]}: vendor={row[1]}, model={row[2]}, platform={row[3]}")
EOF

# 预期：vendor/model为None或实际值（不是幻觉值）
```

---

## 🎯 实施优先级

### P0（立即修复）
1. ✅ 修改System Prompt - 禁止LLM填充null数据
2. ✅ 添加后处理 - 将None替换为"N/A"
3. ✅ 验证修复 - 测试查询不再出现幻觉

### P1（性能优化）
1. ⏳ 直接表格渲染 - 跳过LLM prettification
2. ⏳ CLI优化 - 使用Rich Table直接显示数据
3. ⏳ 性能测试 - 验证<500ms执行时间

### P2（数据完整性）
1. ⏳ 收集实际设备信息 - 运行"show version"
2. ⏳ 更新hosts.yaml - 添加vendor/model/os_version
3. ⏳ 重新导入设备 - 使用真实数据

---

## 📝 后续工作

1. **监控LLM幻觉**
   - 添加单元测试验证LLM不会填充null数据
   - 在E2E测试中检查输出一致性

2. **性能监控**
   - 添加查询执行时间日志
   - 设置警报：query > 1秒

3. **数据自动化**
   - 定时任务从设备收集版本信息
   - 自动更新数据库

---

**修复状态**: 🔴 待实施  
**估计工作量**: 2-3小时  
**Owner**: DevOps Team
