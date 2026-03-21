# 数据完整性修复方案 - 快速参考

## 核心问题概览

```
当前现状:
  audit_tool_calls 表: 极稀疏 (1/12 运行)  ←──── Callback 不完整
  导出消息格式: 仅 user/assistant            ←──── SFT 导出不含 tool_calls
  质量评分: 缺少工具相关维度                ←──── 无法评估工具质量
  
结果: 微调后的模型无法学会"何时调用工具"和"如何参数化工具"

修复后:
  audit_tool_calls 表: 100% 覆盖            ✅ 所有运行都记录工具调用
  导出消息格式: OpenAI tool_calls 格式    ✅ 完整的工具/结果/响应链
  质量评分: tool_selection_relevance 等   ✅ 自动筛选高质量样本
  
结果: 微调后的模型具备工具选择和参数化能力
```

---

## 修复方案 vs 当前状态

### 修复前 - 问题演示

```
用户输入: "检查所有接口的错误统计"

当前导出 (SFT JSONL):
{
  "messages": [
    { "role": "user", "content": "检查所有接口的错误统计" },
    { "role": "assistant", "content": "Gi0/1 有 42 个错误，Gi0/2 有 15 个错误" }
  ]
}

❌ 问题:
  - 微调模型看不到 agent 是如何调用 query_interfaces 工具的
  - 看不到工具参数 {"filter": "errors > 0"}
  - 看不到工具输出原始数据
  - 无法学会"何时选择 query_interfaces"
  - 无法学会"如何组织查询参数"
```

### 修复后 - 改进演示

```
用户输入: "检查所有接口的错误统计"

改进的导出 (OpenAI tool_calls 格式):
{
  "messages": [
    { "role": "user", "content": "检查所有接口的错误统计" },
    {
      "role": "assistant",
      "content": "我来帮您查询接口错误统计。",
      "tool_calls": [
        {
          "id": "call_001",
          "type": "function",
          "function": {
            "name": "query_interfaces",
            "arguments": "{\"filter\": \"errors > 0\"}"
          }
        }
      ]
    },
    {
      "role": "tool",
      "tool_call_id": "call_001",
      "content": "[{\"intf\": \"Gi0/1\", \"errors\": 42}, {\"intf\": \"Gi0/2\", \"errors\": 15}]"
    },
    { "role": "assistant", "content": "Gi0/1 有 42 个错误，Gi0/2 有 15 个错误" }
  ],
  "metadata": {
    "tool_calls_count": 1,
    "tool_calls_success_rate": 1.0,
    "score_components": {
      "tool_selection_relevance": 0.95,
      "parameter_quality": 0.92,
      "output_usage": 0.88
    }
  }
}

✅ 优势:
  + 完整的工具调用链可见
  + 参数化过程清晰可见
  + 工具输出明确标记
  + 微调模型可学会正确的工具选择和参数组织
  + 质量评分帮助筛选高质量示例
```

---

## 修复步骤详细清单

### Step 1: 诊断当前状态 (5分钟)

```bash
# 检查 Callback 是否被正确触发
duckdb .olav/databases/audit.duckdb << 'SQL'
SELECT 
  'Total runs' as metric, COUNT(*) as count
FROM audit_runs
UNION ALL
SELECT 'Runs with message records', COUNT(DISTINCT run_id) 
FROM audit_messages
UNION ALL  
SELECT 'Runs with tool_call records', COUNT(DISTINCT run_id)
FROM audit_tool_calls
UNION ALL
SELECT 'Total messages', COUNT(*)
FROM audit_messages
UNION ALL
SELECT 'Total tool calls', COUNT(*)
FROM audit_tool_calls;
SQL

# 检查最新运行中的消息结构
duckdb .olav/databases/audit.duckdb << 'SQL'
WITH latest AS (
  SELECT run_id FROM audit_runs ORDER BY start_time DESC LIMIT 1
)
SELECT role, COUNT(*) FROM audit_messages 
WHERE run_id = (SELECT run_id FROM latest)
GROUP BY role;
SQL

# 检查导出中是否包含 tool_calls
python -c "
import json
with open('exports/audit_datasets/test_sft/sft.jsonl') as f:
    sample = json.loads(f.readline())
    has_tool_calls = any('tool_calls' in msg for msg in sample.get('messages', []))
    print('✅ Has tool_calls' if has_tool_calls else '❌ Missing tool_calls')
"
```

**预期结果**:
```
❌ Runs with tool_call records: 0 (或很小的数字)
❌ Missing tool_calls
```

### Step 2: 修复 Callback 插件 (1-2小时)

**文件**: `src/olav/plugins/callbacks/audit.py`

修改内容：

```python
# 在 __init__ 中添加:
self.current_tool_call = None

# 修改 on_tool_start():
async def on_tool_start(
    self,
    serialized: dict[str, Any],
    input_str: str,
    *,
    run_id: str | None = None,
    parent_run_id: str | None = None,
    tools: list[str] | None = None,
    **kwargs: Any,
) -> None:
    """Track tool call start for later recording."""
    import time
    self.current_tool_call = {
        "tool_name": serialized.get("name", "unknown"),
        "input_str": input_str,
        "started_at": time.time()
    }

# 修改 on_tool_end():
async def on_tool_end(
    self,
    output: str,
    *,
    run_id: str | None = None,
    parent_run_id: str | None = None,
    **kwargs: Any,
) -> None:
    """Record complete tool call to audit_tool_calls table."""
    import time
    import json
    
    if not self.current_tool_call:
        return
    
    # 关键修复: 调用 record_tool_call() 而不仅仅是 record()
    try:
        self.recorder.record_tool_call(
            run_id=self.run_id,
            tool_name=self.current_tool_call["tool_name"],
            input_args=self.current_tool_call["input_str"],
            output=output,  # ⚠️ 移除 [:512] 截断
            status="completed",
            error=None,
            duration_ms=int((time.time() - self.current_tool_call["started_at"]) * 1000)
        )
    except Exception as e:
        # Graceful degradation
        self.logger.warning(f"Failed to record tool call: {e}")
    finally:
        self.current_tool_call = None

# 新增 on_tool_error():
async def on_tool_error(
    self,
    error: BaseException,
    **kwargs: Any,
) -> None:
    """Record tool call errors - critical for learning error recovery."""
    import time
    
    if not self.current_tool_call:
        return
    
    try:
        self.recorder.record_tool_call(
            run_id=self.run_id,
            tool_name=self.current_tool_call["tool_name"],
            input_args=self.current_tool_call["input_str"],
            output=None,
            status="error",
            error=str(error)[:1000],  # 完整错误消息
            duration_ms=int((time.time() - self.current_tool_call["started_at"]) * 1000)
        )
    except Exception as e:
        self.logger.warning(f"Failed to record tool error: {e}")
    finally:
        self.current_tool_call = None
```

**验证修复**:
```bash
# 运行一个简单的 olav 命令来测试新的 callback
olav query "show devices" --verbose

# 检查是否记录了工具调用
duckdb .olav/databases/audit.duckdb \
  "SELECT COUNT(*) FROM audit_tool_calls WHERE status='completed'"
```

### Step 3: 升级导出格式 (2-3小时)

**文件**: `src/olav/enterprise/audit_dataset_export.py`

在现有 `audit_to_sft_jsonl()` 函数中添加 tool_calls 处理：

```python
# 在循环中替换 "Build SFT sample" 部分 (约 650-680 行)

# 旧的 (只提取 user/assistant):
# sft_messages = []
# for msg in redacted["messages"]:
#     role = msg.get("role", "")
#     if role in ("system", "user", "assistant"):
#         sft_messages.append(...)

# 新的 (包含工具调用链):
sft_messages = []

# Step 1: 系统消息 (如果有)
for msg in redacted["messages"]:
    if msg.get("role") == "system":
        sft_messages.append({
            "role": "system",
            "content": msg.get("content", "")
        })
        break

# Step 2: 用户消息
for msg in redacted["messages"]:
    if msg.get("role") == "user":
        sft_messages.append({
            "role": "user",
            "content": msg.get("content", "")
        })

# Step 3: 助手消息 + 工具调用 (新增)
assistant_msgs = [m for m in redacted["messages"] if m.get("role") == "assistant"]
if assistant_msgs and redacted.get("tool_calls"):
    first_asst = assistant_msgs[0]
    tool_calls = []
    
    for i, tc in enumerate(redacted["tool_calls"]):
        try:
            input_args = tc.get("input_args", "{}")
            if isinstance(input_args, str):
                json.loads(input_args)  # 验证有效的 JSON
            else:
                input_args = json.dumps(input_args)
        except:
            input_args = "{}"
        
        tool_calls.append({
            "id": f"call_{tc.get('call_id', str(i))[:8]}",
            "type": "function",
            "function": {
                "name": tc.get("tool_name", "unknown_tool"),
                "arguments": input_args
            }
        })
    
    asst_msg = {
        "role": "assistant",
        "content": first_asst.get("content", "")
    }
    if tool_calls:
        asst_msg["tool_calls"] = tool_calls
    sft_messages.append(asst_msg)
    
    # Step 4: 工具结果消息 (新增)
    for i, tc in enumerate(redacted["tool_calls"]):
        sft_messages.append({
            "role": "tool",
            "tool_call_id": f"call_{tc.get('call_id', str(i))[:8]}",
            "content": tc.get("output", "")
        })
    
    # Step 5: 最终助手消息 (如果有)
    if len(assistant_msgs) > 1:
        sft_messages.append({
            "role": "assistant",
            "content": assistant_msgs[-1].get("content", "")
        })

elif assistant_msgs:
    # 无工具调用，仅添加助手消息
    for msg in assistant_msgs:
        sft_messages.append({
            "role": "assistant",
            "content": msg.get("content", "")
        })

# Step 6: 质量评分计算 (新增维度)
score_result = compute_quality_score(sample)

# 新增工具调用相关的评分
tool_calls_count = len(redacted.get("tool_calls", []))
successful_tools = len([t for t in redacted.get("tool_calls", []) if t.get("status") == "completed"])
tool_success_rate = successful_tools / tool_calls_count if tool_calls_count > 0 else 1.0

# 评估工具调用质量
tool_quality_score = evaluate_tool_call_quality(
    sft_messages,
    redacted.get("tool_calls", [])
)

# 更新元数据
sample["metadata"].update({
    "tool_calls_count": tool_calls_count,
    "tool_calls_success_rate": tool_success_rate,
    "score_components": {
        **score_result.get("score_components", {}),
        "tool_selection_relevance": tool_quality_score.get("selection_score", 0.0),
        "parameter_quality": tool_quality_score.get("parameter_score", 0.0),
        "output_usage": tool_quality_score.get("usage_score", 0.0)
    }
})
```

**新增函数**:
```python
def evaluate_tool_call_quality(messages: list[dict], tool_calls: list[dict]) -> dict[str, float]:
    """
    评估工具调用的质量。
    
    返回:
      {
        "selection_score": 0.0-1.0  # 工具选择是否合理
        "parameter_score": 0.0-1.0  # 参数格式/内容是否正确
        "usage_score": 0.0-1.0       # 最终响应是否使用了工具输出
      }
    """
    selection_score = 1.0 if tool_calls else 0.0
    
    parameter_score = 1.0
    for tc in tool_calls:
        try:
            args = tc.get("input_args", "{}")
            if isinstance(args, str):
                json.loads(args)  # 有效 JSON
            else:
                args = json.dumps(args)
            # 检查参数是否过于简单或空
            if len(args) < 5:
                parameter_score = 0.5
        except:
            parameter_score = 0.0
    
    # 检查最终响应是否使用了工具输出
    usage_score = 1.0
    tool_outputs = [tc.get("output", "") for tc in tool_calls]
    final_response = messages[-1].get("content", "") if messages else ""
    
    # 简单启发式: 如果最终响应包含工具返回的数据片段
    if tool_calls and not any(seg in final_response for tc in tool_calls for seg in [tc.get("output", "")[:20]]):
        usage_score = 0.5
    
    return {
        "selection_score": selection_score,
        "parameter_score": parameter_score,
        "usage_score": usage_score
    }
```

**验证修复**:
```bash
# 运行导出
olav log export sft --hours 48 --output exports/audit_datasets/fixed_sft

# 检查输出中是否有 tool_calls
python << 'EOF'
import json
with open('exports/audit_datasets/fixed_sft/sft.jsonl') as f:
    for line in f:
        sample = json.loads(line)
        has_tools = any('tool_calls' in msg for msg in sample['messages'])
        has_tool_role = any(msg.get('role') == 'tool' for msg in sample['messages'])
        
        if has_tools or has_tool_role:
            print(f"✅ Sample has tool calls")
            print(f"   Messages: {len(sample['messages'])}")
            
            for msg in sample['messages']:
                if msg.get('role') == 'tool':
                    print(f"   - Tool result found")
                if msg.get('tool_calls'):
                    print(f"   - {len(msg['tool_calls'])} tool calls")
            break
else:
    print("❌ No samples with tool calls found")
EOF
```

### Step 4: 测试完整链路 (30分钟)

```bash
# 创建一个带工具调用的测试运行
cat > test_tool_chain.py << 'EOF'
import sys
sys.path.insert(0, 'src')

from olav.core.audit_recorder import AuditEventRecorder

recorder = AuditEventRecorder()
run_id = recorder.record_run_start(agent_id="test_agent")

# 模拟完整的工具调用链
recorder.record(
    event_type="user_input_received",
    run_id=run_id,
    payload={"query": "列出所有接口"}
)

recorder.record(
    event_type="llm_request_started",
    run_id=run_id,
    payload={"model": "claude-opus"}
)

# 记录工具调用
recorder.record_tool_call(
    run_id=run_id,
    tool_name="list_interfaces",
    input_args='{"filter": "status=up"}',
    output='[{"intf": "Gi0/1", "status": "up"}]',
    status="completed",
    duration_ms=250
)

recorder.record_message(
    run_id=run_id,
    role="assistant",
    content="已找到 1 个活跃接口"
)

recorder.record_run_end(run_id, status="completed")

print(f"✅ Test run created: {run_id}")
EOF

python test_tool_chain.py

# 导出测试数据
olav log export sft --hours 1 --output exports/audit_datasets/tool_chain_test

# 验证
python << 'EOF'
import json
with open('exports/audit_datasets/tool_chain_test/sft.jsonl') as f:
    for line in f:
        sample = json.loads(line)
        print("✅ Export successful!")
        print(f"Messages: {len(sample['messages'])}")
        for i, msg in enumerate(sample['messages']):
            print(f"  {i}: role={msg['role']}", end="")
            if msg.get('tool_calls'):
                print(f" | tool_calls={len(msg['tool_calls'])}", end="")
            print()
        break
EOF
```

---

## 预期改进效果

### 修复前 vs 修复后

| 指标 | 修复前 | 修复后 |
|------|--------|--------|
| `audit_tool_calls` 表覆盖率 | <10% | >95% |
| 导出消息中的 `tool_calls` 字段 | ❌ 0% | ✅ 90%+ |
| 工具链完整性 | ❌ 0% | ✅ 100% |
| 可微调的工具选择样本 | ❌ 0 | ✅ 50-100+ |
| 可微调的参数化样本 | ❌ 0 | ✅ 50-100+ |
| 导出文件大小增长 | 基线 | 1.3-1.5 倍 |

### 微调后的模型能力提升

| 能力 | 修复前 | 修复后 |
|------|--------|--------|
| 理解网络查询 | ✓ 可学 | ✓✓ 强化 |
| **选择正确工具** | ❌ 无法学 | ✅ **可学** |
| **参数化工具** | ❌ 无法学 | ✅ **可学** |
| **处理工具结果** | ❌ 无法学 | ✅ **可学** |

---

## 快速决策树

```
Q1: 需要微调 OLAV agent 的工具调用能力吗?
├─ 否 → 当前状态可接受，跳过修复
└─ 是 → 继续

Q2: 可以投入 4-6 小时进行修复吗?
├─ 否 → 延期到 1-2 周后
└─ 是 → 继续

Q3: 现在就开始修复，还是等 ContainerLab E2E 产生真实数据?
├─ 等待真实数据 → 修复时会有更清晰的需求信号
└─ 立即开始 → 修复更快，容易 A/B 对比

建议: 等待 CLAB-2 (脚本骨架) 完成，生成一次真实数据，
     然后立即应用本方案的修复
```

---

## 相关文件清单

| 文件 | 操作 | 优先级 |
|------|------|--------|
| `src/olav/plugins/callbacks/audit.py` | 修改 on_tool_start/end/error | 🔴 高 |
| `src/olav/enterprise/audit_dataset_export.py` | 添加 tool_calls 处理 | 🔴 高 |
| `TRAINING_DATA_AUDIT.md` | 本审计报告 (参考) | 📄 文档 |
| `tests/unit/test_server_audit.py` | 添加工具调用测试 | 🟡 中 |

---

*本文档作为 "数据完整性修复方案" 的快速参考*  
*详见 TRAINING_DATA_AUDIT.md 的完整分析*
