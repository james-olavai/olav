# Expert Agent 行为特性分析

## 📋 目录
1. [CLI安全机制](#cli安全机制)
2. [执行流程](#执行流程)
3. [报告生成](#报告生成)
4. [返回值处理](#返回值处理)

---

## CLI安全机制

### ✅ 危险命令拦截

**Expert Agent调用CLI会block危险命令，采用双层防护机制**：

#### 第1层：命令黑名单检查
```python
# 文件: .olav/imports/commands/blacklist.txt
reload
reboot
shutdown
delete
erase
format
```

**检查逻辑** (network_executor.py, line 145-162):
```python
def _is_blacklisted(self, command: str) -> str | None:
    """Check if command is blacklisted"""
    cmd_lower = command.lower().strip()
    for pattern in self.blacklist:
        if pattern.endswith("*"):
            # Wildcard match: "reload*" matches "reload", "reload in 5"
            if cmd_lower.startswith(pattern[:-1]):
                return pattern
        else:
            # Exact match: "reload" matches "reload"
            if cmd_lower == pattern:
                return pattern
    return None
```

**执行时检查** (network_executor.py, line 204-211):
```python
# Check blacklist FIRST before executing
blacklisted_pattern = self._is_blacklisted(command)
if blacklisted_pattern:
    return CommandExecutionResult(
        device=device,
        command=command,
        success=False,
        error=f"Command is blacklisted (matches pattern: {blacklisted_pattern})",
    )
```

#### 第2层：命令注册表验证
```python
# network_executor.py, line 215-225
platform = self._detect_platform(device)
if platform:
    registry = get_command_registry()
    if not registry.validate_command(platform, command):
        return CommandExecutionResult(
            error=f"Command not allowed for platform {platform}"
        )
```

### 🛡️ 拦截结果

当危险命令被拦截时：

```json
{
    "device": "R1",
    "command": "reload",
    "success": false,
    "error": "Command is blacklisted (matches pattern: reload)",
    "duration_ms": 0
}
```

**特点**：
- ✅ 立即返回失败（无延迟）
- ✅ 不会连接设备（`duration_ms=0`）
- ✅ 清晰的错误消息说明被拦截的理由

### 📊 防护覆盖范围

| 命令类型 | 示例 | 状态 |
|---------|------|------|
| 配置查询 | `show version` | ✅ 允许 |
| 接口查询 | `show ip interface brief` | ✅ 允许 |
| OSPF/BGP | `show ip ospf neighbor` | ✅ 允许 |
| 重启设备 | `reload` | ❌ 拦截 |
| 清除配置 | `write erase` | ❌ 拦截 |
| 删除文件 | `delete flash:` | ❌ 拦截 |
| 配置保存 | `copy run start` | ⚠️ 需白名单 |

---

## 执行流程

### Expert Agent 处理步骤

**架构** (orchestrator.py, line 105-145):

```python
SubAgent(
    name="expert",
    description="高级问题分析专家 - 拓扑感知、动态扩展、根因定位",
    system_prompt="""
    Workflow:
    1. Analyze symptom and existing info from previous SubAgent
    2. Identify topology relationships (analyze_topology or query v_lldp/v_bgp_neighbors)
    3. Dynamically expand scope (get_device_peers, expand_scope_by_role)
    4. Execute correlation queries (execute_join_query or query_database with JOIN)
    5. Root cause analysis (search_similar_cases for historical context)
    6. Generate professional report (generate_diagnosis_report)
    """,
    tools=[
        analyze_topology,        # 拓扑分析
        get_device_peers,       # 邻居发现
        expand_scope_by_role,   # 范围扩展
        execute_join_query,     # 智能JOIN查询
        query_database,         # SQL查询
        query_network,          # 反应式查询
        nornir_execute,         # CLI执行 (含安全检查)
        search_similar_cases,   # 历史案例
        generate_diagnosis_report,  # 报告生成
        discover_data,          # 知识库检索
        DuckDuckGoSearchResults, # 联网搜索
    ]
)
```

### CLI调用的安全检查顺序

```
用户查询
    ↓
Expert Agent 调用 nornir_execute(device, command)
    ↓
NetworkExecutor.execute() [network_executor.py]
    ↓
┌─────────────────────────────────────┐
│ 1. 黑名单检查 (_is_blacklisted)     │ ← 第一道防线
│    - 精确匹配：reload               │
│    - 通配符匹配：reload*             │
└─────────────────────────────────────┘
    ↓ (PASS)
┌─────────────────────────────────────┐
│ 2. 命令注册表验证                    │ ← 第二道防线
│    - 检查命令是否在平台白名单中     │
│    (show version, show interface)   │
└─────────────────────────────────────┘
    ↓ (PASS)
┌─────────────────────────────────────┐
│ 3. 设备库存检查                      │ ← 第三道防线
│    - 设备是否存在于Nornir inventory │
└─────────────────────────────────────┘
    ↓ (PASS)
┌─────────────────────────────────────┐
│ 4. 执行命令                          │ ← 安全执行
│    nr.filter(name=device).run(...)  │
└─────────────────────────────────────┘
    ↓
CommandExecutionResult {
    success: true,
    output: "...",
    duration_ms: 250
}
```

---

## 报告生成

### ❓ Expert Agent 生成报告吗？

**答案：取决于查询类型**

#### 情况1：直接调用 generate_diagnosis_report

如果Expert Agent主动调用 `generate_diagnosis_report` 工具：

```python
# expert_tools.py, line 475-530
@tool
async def generate_diagnosis_report(
    diagnosis: str,
    affected_devices: list[str],
    root_cause: str,
    recommendations: list[str],
    evidence: str | None = None,
) -> str:
    """生成专业诊断报告"""
    # 返回 Markdown 格式的报告
```

**输出示例**：
```markdown
# 网络诊断报告

## 故障症状
R3 的 OSPF 邻居关系 down

## 根本原因
IP 地址子网不匹配导致OSPF邻接失败
- R3 IP: 10.1.13.5/30 (子网 10.1.13.4/30)
- R1 IP: 10.1.13.1/24 (子网 10.1.13.0/24)

## 受影响设备
- R3
- R1

## 解决方案
1. 修改 R3 IP 为 10.1.13.6/24（与 R1 同子网）
2. 验证 OSPF 邻接恢复
3. 检查 BGP 会话状态

## 验证步骤
```
show ip ospf neighbor
show ip bgp summary
```
```

#### 情况2：不调用报告生成工具

如果Expert Agent不显式调用 `generate_diagnosis_report`：

- ✅ **直接返回诊断结果**给Orchestrator
- ✅ **Orchestrator处理最终输出格式**
- ✅ **不生成中间报告**

### 返回值处理流程

```
Expert Agent 执行 (orchestrator.py)
    ↓
    ├─ 使用多个工具进行分析
    ├─ 可选：调用 generate_diagnosis_report()
    └─ 生成 LLM 最终响应
    ↓
SubAgent Response {
    status: "success",
    analysis: "诊断分析文本",
    final_answer: "最终答案或报告",
    tools_called: [
        "analyze_topology",
        "nornir_execute",
        "search_similar_cases"
    ]
}
    ↓
Orchestrator 收集结果
    ↓
    ├─ 缓存结果
    ├─ 更新状态
    └─ 返回给用户
```

---

## 返回值处理

### Expert Agent 直接返回 Orchestrator

**关键设计**：Expert Agent **不生成用户格式的输出**，而是：

1. **返回结构化诊断数据** → Orchestrator 聚合
2. **返回 LLM 推理结果** → Orchestrator 渲染

```python
# orchestrator.py - Expert SubAgent 响应处理
result = {
    "status": "complete",
    "messages": [...],      # 对话历史
    "final_answer": "...",  # LLM 最终诊断
    "tools_used": [...]     # 调用的工具列表
}
```

### 完整调用链

```
用户查询
    ↓
Orchestrator.orchestrate(query)
    ↓
    ├─ 检查缓存
    ├─ 路由到子专家 (query/analysis/cli/expert)
    ├─ Expert Agent 执行诊断
    │   ├─ 调用 analyze_topology()
    │   ├─ 调用 nornir_execute()  ← CLI with 安全检查
    │   ├─ 调用 search_similar_cases()
    │   └─ 返回诊断结果
    ├─ 聚合多个SubAgent结果
    ├─ 可选：生成最终报告
    └─ 缓存结果
    ↓
最终输出 (Markdown/JSON)
```

---

## 测试验证

### 验证安全机制

```bash
# 测试1：危险命令应被拦截
uv run python -c "
from olav.tools.network_executor import NetworkExecutor
executor = NetworkExecutor()
result = executor.execute('R1', 'reload')
print('❌ BLOCKED' if not result.success else '⚠️ NOT BLOCKED')
# 输出: ❌ BLOCKED
"

# 测试2：安全命令应执行
uv run python -c "
from olav.tools.network_executor import NetworkExecutor
executor = NetworkExecutor()
result = executor.execute('R1', 'show version')
print('✅ SUCCESS' if result.success else '❌ FAILED')
# 输出: ✅ SUCCESS
"
```

### 验证报告流程

参考：[docs/实战测试执行报告_20250205.md](实战测试执行报告_20250205.md)
- ✅ Expert Agent 诊断成功
- ✅ 使用了 nornir_execute (CLI 工具)
- ✅ 调用了多个分析工具
- ✅ 返回结构化诊断结果

---

## 总结

| 特性 | 状态 | 说明 |
|------|------|------|
| **危险命令拦截** | ✅ 是 | 双层防护 (黑名单 + 注册表) |
| **报告自动生成** | ⚠️ 可选 | 调用 generate_diagnosis_report() 时生成 |
| **直接返回结果** | ✅ 是 | Expert Agent 返回诊断到 Orchestrator |
| **工具链容错** | ✅ 是 | 部分工具失败不影响诊断 |
| **性能优化** | ✅ 是 | 使用缓存和并行执行 |

---

**文档版本**: v0.10.0  
**最后更新**: 2025-02-05  
**适用范围**: OLAV Expert Agent CLI 调用安全分析
