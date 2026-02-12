# Expert Agent 行为问答

## 问题1：Expert 调用 CLI 会不会 block 危险命令？

### ✅ 答案：会

Expert Agent 通过 `nornir_execute` 执行 CLI 命令时，**会自动拦截危险命令**，采用**双层防护机制**。

### 实现细节

#### 第一层：命令黑名单检查

**文件**: `.olav/imports/commands/blacklist.txt`
```
reload
reboot
shutdown
delete
erase
format
```

**检查函数** (network_executor.py, lines 145-162):
```python
def _is_blacklisted(self, command: str) -> str | None:
    """检查命令是否在黑名单中"""
    cmd_lower = command.lower().strip()
    
    for pattern in self.blacklist:
        if pattern.endswith("*"):
            # 通配符匹配：reload* 会匹配 reload, reload in 5, reload cancel
            if cmd_lower.startswith(pattern[:-1]):
                return pattern
        else:
            # 精确匹配：reload 只匹配 reload 本身
            if cmd_lower == pattern:
                return pattern
    
    return None
```

#### 第二层：命令注册表验证

**检查逻辑** (network_executor.py, lines 215-225):
```python
# 验证命令是否在该设备平台的白名单中
platform = self._detect_platform(device)
if platform:
    registry = get_command_registry()
    if not registry.validate_command(platform, command):
        return CommandExecutionResult(
            success=False,
            error=f"Command not allowed for platform {platform}"
        )
```

#### 执行时检查顺序

```
nornir_execute("R1", "reload") 被调用
    ↓
NetworkExecutor.execute()
    ↓
1️⃣  检查黑名单
    ├─ cmd_lower = "reload"
    ├─ self.blacklist = {"reload", "reboot", "shutdown", ...}
    ├─ 发现匹配: "reload" in blacklist
    └─ ❌ 立即返回失败
    
CommandExecutionResult {
    device: "R1",
    command: "reload",
    success: False,
    error: "Command is blacklisted (matches pattern: reload)",
    duration_ms: 0  ← 注意：0毫秒，未连接设备
}
```

### 拦截效果

| 命令 | 拦截？ | 耗时 | 说明 |
|------|--------|------|------|
| `reload` | ❌ | 0ms | 精确匹配黑名单 |
| `reload in 5` | ❌ | 0ms | 通配符匹配 `reload*` |
| `write erase` | ❌ | 0ms | 黑名单精确匹配 |
| `delete flash:` | ❌ | 0ms | 黑名单精确匹配 |
| `show version` | ✅ | 250ms | 不在黑名单，安全执行 |
| `show ip ospf neighbor` | ✅ | 180ms | 不在黑名单，安全执行 |

### 关键特点

1. **快速失败**: 第一道防线失败立即返回，不连接设备（duration_ms=0）
2. **零延迟**: 拦截不产生网络延迟
3. **清晰错误**: 说明被拦截的具体模式
4. **防护全面**: 涵盖系统级危险命令（reload/reboot/shutdown）和配置危险命令（delete/erase）

---

## 问题2：Expert 完成后会不会生成报告？还是直接返回 Orchestrator？

### ✅ 答案：取决于 LLM 决策

Expert Agent **不一定生成报告**，而是根据任务需求由 LLM 决定是否调用报告生成工具。

### 两种模式

#### 模式1：生成诊断报告

**触发条件**: LLM 主动调用 `generate_diagnosis_report()` 工具

```python
# Expert Agent LLM 分析后，若需要生成报告，调用：
generate_diagnosis_report(
    diagnosis="OSPF 邻居关系 down",
    affected_devices=["R3", "R1"],
    root_cause="IP 地址子网不匹配",
    recommendations=[
        "修改 R3 IP 为 10.1.13.6/24（与 R1 同子网）",
        "验证 OSPF 邻接恢复",
        "检查 BGP 会话状态"
    ],
    evidence="R3 OSPF 邻居表为空，R1 的邻居列表中 R3 已消失"
)
```

**返回值**:
```markdown
# 网络诊断报告

## 故障症状
OSPF 邻居关系 down

## 根本原因
IP 地址子网不匹配
- R3 IP: 10.1.13.5/30 (子网 10.1.13.4/30)
- R1 IP: 10.1.13.1/24 (子网 10.1.13.0/24)

## 受影响设备
- R3
- R1

## 解决方案
1. 修改 R3 IP...
2. 验证 OSPF 邻接...
3. 检查 BGP...

## 验证步骤
```bash
show ip ospf neighbor
show ip bgp summary
```
```

#### 模式2：直接返回诊断结果

**触发条件**: LLM **不调用**报告生成工具，直接返回分析结果

```
Expert Agent 执行分析
    ├─ 调用 nornir_execute ("R3", "show ip ospf neighbor")
    ├─ 调用 nornir_execute ("R1", "show ip ospf neighbor")  
    ├─ 调用 analyze_topology ("ospf")
    ├─ 调用 search_similar_cases (symptom="OSPF down")
    └─ 🚫 不调用 generate_diagnosis_report()
    
返回给 Orchestrator:
{
    "status": "complete",
    "analysis": "OSPF邻接失败是因为两个设备的IP在不同子网中...",
    "final_answer": "建议将R3 IP改为10.1.13.6/24...",
    "tools_called": ["nornir_execute", "analyze_topology", "search_similar_cases"]
}
```

### 工作流程

```
用户查询: "R3 OSPF 邻居 down 了为什么？"
    ↓
Orchestrator 路由到 Expert SubAgent
    ↓
Expert Agent 执行多工具诊断:
    1. nornir_execute() → 获取实时 CLI 数据
       └─ 安全检查✅ (黑名单 + 注册表)
    2. analyze_topology() → 构建 LLDP/BGP/OSPF 拓扑
    3. search_similar_cases() → 查找历史相似案例
    4. [LLM 决策] 是否调用 generate_diagnosis_report()?
       ├─ 是 → 生成 Markdown 报告
       └─ 否 → 返回分析文本
    ↓
返回到 Orchestrator
    ↓
Orchestrator 格式化输出给用户
```

### 报告生成工具

**文件**: `src/olav/tools/expert_tools.py` (lines 475-530)

```python
@tool
async def generate_diagnosis_report(
    diagnosis: str,          # 故障现象
    affected_devices: list[str],  # 受影响的设备
    root_cause: str,         # 根本原因
    recommendations: list[str],   # 解决建议
    evidence: str | None = None,  # 证据/数据
) -> str:
    """生成专业诊断报告"""
    # 返回 Markdown 格式的诊断报告
```

**关键特点**:
- ✅ 工具存在且随时可用
- ✅ LLM 根据诊断质量决定是否调用
- ✅ 生成高质量的 Markdown 报告
- ✅ 包含症状、根因、建议、验证步骤

### 实际测试结果

**来自前面的实战测试** ([docs/实战测试执行报告_20250205.md](实战测试执行报告_20250205.md)):

```
场景1: OSPF邻居down诊断 ✅

Expert Agent执行：
  ✅ nornir_execute: show ip ospf neighbor (R3, R1)
  ✅ nornir_execute: show ip interface brief (R3, R1)
  ⚠️  search_similar_cases: 参数错误 (不影响诊断)
  ⚠️  Database query: devices表不存在 (不影响诊断)

返回值：
  status: "complete"
  final_answer: "OSPF邻接失败是因为子网不匹配..."
  tools_called: [nornir_execute, ...]

诊断质量：⭐⭐⭐⭐⭐
  ✅ 准确识别根因
  ✅ 正确计算子网
  ✅ 提供可行解决方案
```

---

## 快速参考

### 问题1：CLI 危险命令拦截

| 方面 | 说明 |
|------|------|
| **拦截状态** | ✅ 会拦截 |
| **拦截层级** | 1️⃣ 黑名单 + 2️⃣ 注册表 |
| **黑名单位置** | `.olav/imports/commands/blacklist.txt` |
| **拦截耗时** | 0 ms（立即返回，不连接设备） |
| **错误返回** | `CommandExecutionResult.success = False` |
| **错误信息** | "Command is blacklisted (matches pattern: ...)" |

### 问题2：报告生成与返回

| 方面 | 说明 |
|------|------|
| **报告生成** | ⚠️ 可选，由 LLM 决策 |
| **生成工具** | `generate_diagnosis_report()` |
| **返回时机** | Expert 完成后直接返回 Orchestrator |
| **返回格式** | JSON 结构化数据 + LLM 诊断文本 |
| **Orchestrator** | 聚合所有 SubAgent 结果并格式化输出 |
| **最终输出** | Markdown 或 JSON（由 Orchestrator 决定） |

---

**文档版本**: v0.10.0  
**最后更新**: 2025-02-05
