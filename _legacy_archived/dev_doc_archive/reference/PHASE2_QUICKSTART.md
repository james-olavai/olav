# 🚀 v0.12.0 第二阶段 - 快速启动指南

**目标**: 在 4-6 小时内完成剩余 6 个工具  
**状态**: 即将开始  
**预计完成**: 2026-02-14 14:00

---

## 🎯 你需要知道的一切

### 已完成 (不要修改!)

✅ 5 个工具已迁移:
- query_database.py
- nornir_execute.py
- list_devices.py
- inspect_schema.py
- discover_data.py

**这些文件是参考**。使用它们作为模板。

### 待做 (按此顺序)

1️⃣ **6 个工具的 Pydantic 迁移** (2.5h)
2️⃣ **6 个工具的 @tool 装饰** (1.5h)  
3️⃣ **所有 11 个工具的 @retry** (1h)
4️⃣ **测试和验证** (2.5h)

---

## 📋 简化设置步骤

### 步骤 1: 查看完成的工具 (参考)

打开 **任何已完成的工具** 看看结构:

例如: `.olav/shared/tools/query_database.py`

**寻找这些模式**:

```python
# 1. Pydantic 导入
from pydantic import BaseModel, Field, validator

# 2. 输入模型
class QueryDatabaseInput(BaseModel):
    sql: str = Field(..., min_length=1)
    timeout: int = Field(default=30, ge=1, le=300)

# 3. 输出模型
class QueryDatabaseOutput(BaseModel):
    data: list[dict] | None = None
    status: str
    error: str | None = None

# 4. @tool 装饰
from langchain_core.tools import tool

@tool
def query_database(sql: str, timeout: int = 30) -> dict:
    """Execute SQL query"""
    return main({"sql": sql, "timeout": timeout})

# 5. 原始实现
def main(params: dict) -> dict:
    # ... 业务逻辑 ...
```

**这就是你需要复制的全部内容。**

---

## 🎬 开始工作

### 工具 1: network_executor.py

**时间**: 30 分钟

**文件**: `.olav/shared/tools/network_executor.py`

**步骤**:

1. **复制结构** (从 query_database.py 或 nornir_execute.py)
2. **创建输入模型**:
   ```python
   class NetworkExecutorInput(BaseModel):
       command: str = Field(..., min_length=1, max_length=1000)
       host_ip: str = Field(...)  # IP 验证
       username: str = Field(default="admin")
       timeout: int = Field(default=30, ge=5, le=300)
       
       @validator('host_ip')
       def validate_host_ip(cls, v):
           # IP 格式验证
           return v
   ```

3. **创建输出模型**:
   ```python
   class NetworkExecutorOutput(BaseModel):
       result: str | None = None
       host_ip: str
       status: str
       error: str | None = None
   ```

4. **添加 @tool 装饰**:
   ```python
   @tool
   def network_executor(command: str, host_ip: str, 
                       username: str = "admin", 
                       timeout: int = 30) -> dict:
       """Execute command on network device via SSH"""
       return main({...})
   ```

5. **验证**:
   ```bash
   python3 -c "from olav_tools.network_executor import network_executor; print(network_executor)"
   ```

### 工具 2: batch_executor.py

**时间**: 0 分钟

**注意**: 此文件已有 Pydantic，仅需添加 @tool 装饰！

**步骤**:
1. 打开文件
2. 添加 `from langchain_core.tools import tool`
3. 在 `def batch_executor()` 上添加 `@tool`

### 工具 3: textfsm_templates.py

**时间**: 20 分钟

**步骤** (同工具 1):
1. 创建 `TextfsmInput` 模型
2. 创建 `TextfsmOutput` 模型
3. 添加 `@tool def textfsm_templates()`

### 工具 4: guard_analyzer.py

**时间**: 25 分钟

**步骤** (同工具 1):
1. 创建 `GuardAnalyzerInput` 模型
2. 创建 `GuardAnalyzerOutput` 模型
3. 添加 `@tool def guard_analyzer()`

### 工具 5: diagnostic_analyzer.py

**时间**: 30 分钟

**步骤** (同工具 1):
1. 创建 `DiagnosticAnalyzerInput` 模型
2. 创建 `DiagnosticAnalyzerOutput` 模型
3. 添加 `@tool def diagnostic_analyzer()`

### 工具 6: json_formatter.py

**时间**: 10 分钟

**步骤** (同工具 1):
1. 创建 `JsonFormatterInput` 模型
2. 创建 `JsonFormatterOutput` 模型
3. 添加 `@tool def json_formatter()`

---

## ⚡ 速度技巧

### 复制-粘贴快速启动

1. **打开已完成工具** (query_database.py)
2. **选择 Pydantic 模型部分** (第 1-30 行)
3. **复制到新工具**
4. **修改类名和字段**
5. **完成!**

**示例**:

```python
# FROM query_database.py:
class QueryDatabaseInput(BaseModel):
    sql: str = Field(...)
    timeout: int = Field(...)

# TO network_executor.py (修改):
class NetworkExecutorInput(BaseModel):
    command: str = Field(...)
    host_ip: str = Field(...)
    timeout: int = Field(...)
```

### 快速验证命令

完成每个工具后，运行:

```bash
# 1. 检查语法
python3 -m py_compile /path/to/tool.py

# 2. 检查 @tool 存在
grep "@tool" /path/to/tool.py

# 3. 检查 Pydantic 导入
grep "from pydantic" /path/to/tool.py

# 4. 完整测试
python3 -c "from tool_name import tool_name; print('✅ OK')"
```

---

## 📊 进度追踪

使用此表追踪进度:

| # | 工具 | Pydantic | @tool | 状态 | 时间 |
|---|------|----------|-------|------|------|
| 1 | network_executor | ⏳ | ⏳ | 开始 | 30m |
| 2 | batch_executor | ✅ | ⏳ | 待做 | 5m |
| 3 | textfsm_templates | ⏳ | ⏳ | 待做 | 20m |
| 4 | guard_analyzer | ⏳ | ⏳ | 待做 | 25m |
| 5 | diagnostic_analyzer | ⏳ | ⏳ | 待做 | 30m |
| 6 | json_formatter | ⏳ | ⏳ | 待做 | 10m |

**总计 Pydantic**: 2.5 小时  
**总计 @tool**: 1.5 小时  
**总计**: 4 小时 (包括缓冲)

---

## 🔧 常见问题和解决方案

### 问: "我不确定创建什么输入/输出模型？"

**答**: 看看现有的 main() 函数:

```python
def main(params: dict) -> dict:
    device = params.get("device")      # → InputModel.device
    command = params.get("command")    # → InputModel.command
    
    result = execute()                 # → OutputModel.result
    error = None                       # → OutputModel.error
    return {"result": result, ...}     # → OutputModel fields
```

**规则**: 
- 每个 `params.get()` 对应输入模型的一个字段
- 每个返回值对应输出模型的一个字段

### 问: "我应该包含什么字段约束？"

**答**: 复制模式:

- **字符串**: `min_length=1, max_length=100`
- **整数**: `ge=1, le=300` (范围)
- **可选字段**: `Field(default=None)`
- **必需字段**: `Field(...)`

### 问: "我怎样验证 @tool 有效？"

**答**:

```python
from langchain_core.tools import tool

# 应该为真
assert hasattr(query_database, 'invoke')
assert hasattr(query_database, 'name')
print(f"Tool name: {query_database.name}")
```

### 问: "我需要添加 @retry 吗？"

**答**: 不是现在。第 3 步会做这个。现在专注于 Pydantic + @tool。

---

## 🎓 学习资源

**已完成的工具** (参考实现):
- `.olav/shared/tools/query_database.py` ⭐ 最简单，先看
- `.olav/shared/tools/nornir_execute.py` ⭐ 有 validators，复杂点

**参考文档**:
- V0.12.0_IMPLEMENTATION_CHECKLIST.md (代码示例)
- SESSION_EXECUTIVE_SUMMARY.md (总体概览)

---

## ✅ 完成标准

每个工具完成后，检查:

- [ ] 文件可导入 (无 syntax errors)
- [ ] 有 Pydantic 输入模型
- [ ] 有 Pydantic 输出模型
- [ ] 有 @tool 装饰函数
- [ ] Docstring 完整
- [ ] CLI 仍然工作
- [ ] 向后兼容

---

## 🚀 现在开始

1. **打开** `.olav/shared/tools/network_executor.py`
2. **对照** `.olav/shared/tools/query_database.py`
3. **复制** 结构
4. **修改** 字段名
5. **验证** 语法
6. **提交** 代码

**预计时间**: 30 分钟

**然后移到下一个工具...**

---

## 📞 需要帮助?

如果卡住了:
1. 看已完成的相似工具
2. 查阅 V0.12.0_IMPLEMENTATION_CHECKLIST.md
3. 检查 Pydantic 文档示例

---

**你可以做到！🎉**

*预计 4-6 小时完成所有 6 个工具。加油！*

