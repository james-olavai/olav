# 训练数据完整性审计报告

**日期**: 2026-03-17  
**版本**: v1.0  
**关于**: OLAV Agent 微调所需数据完整性分析

---

## 执行摘要

✅ **好消息**: 核心审计日志系统完整，所有事件都被记录

❌ **关键问题**: 当前导出格式**缺失工具调用链**，不适合训练 agent 工具使用能力

⚠️  **限制**: 现有导出仅适合简单的生成式文本微调 (SFT)，不适合工具调用序列学习

---

## 1. 当前数据结构与表现

### 1.1 审计数据库包含的内容 ✅

| 表名 | 记录数 | 内容 | 状态 |
|------|--------|------|------|
| `audit_runs` | 12 | 运行元数据 (agent_id, 状态, 时间戳) | ✅ |
| `audit_events` | 35 | 事件流 (user_input_received, llm_request_started, llm_usage) | ✅ |
| `audit_tool_calls` | 1 | 工具调用细节 (tool_name, input_args, output, duration_ms) | ⚠️ 极稀疏 |
| `audit_messages` | 2 | 对话消息 (user, assistant) | ⚠️ 最小化 |

**关键发现**:
- 数据库设计支持完整的工具调用跟踪
- 但真实运行中 `audit_tool_calls` 表几乎为空 (1/12 运行)
- `audit_messages` 表只记录最终的 user/assistant 对

### 1.2 当前导出格式示例

**输入**: SFT JSONL
```json
{
  "messages": [
    { "role": "user", "content": "show devices" },
    { "role": "assistant", "content": "Found 2 devices: router1, router2" }
  ],
  "metadata": {
    "run_id": "75df5c5b-...",
    "agent_id": "quick",
    "rule_score": 0.775
  }
}
```

**问题**: 
- ❌ 无 `tool_calls` 字段
- ❌ 无工具调用序列 (assistant → tool.query_devices → tool.result)
- ❌ 无"思考链" (reasoning/thinking 数据)
- ❌ 不符合 OpenAI API 工具调用格式

---

## 2. 微调能力差距分析

### 2.1 当前数据能支持的微调

```
✅ 文本生成式微调 (SFT)
   - 给定用户查询，生成响应文本
   - 简单的对话风格适配
   - 示例: "show devices" → "Found 2 devices"
   
⚠️  有限的查询理解
   - 解析用户意图
   - 识别查询类型
   - 问题: 无中间思考过程
   
❌ 工具调用能力微调 (无法做)
   - 不知道该调用哪个工具
   - 不知道如何组织工具输入
   - 不知道如何处理工具返回结果
   - 问题: 完全缺少 tool_calls 链
   
❌ 链式推理 (CoT) 微调 (无法做)
   - 无中间推理步骤数据
   - 无错误处理示例
   - 问题: 无 reasoning_block 事件
```

### 2.2 对 OLAV 特定能力的影响

| 能力 | 当前数据支持 | 数据要素缺失 |
|------|-------------|------------|
| 理解网络查询 | ✅ 部分 | 无思考链 |
| **调用正确工具** | ❌ 不支持 | `tool_calls` 完全缺失 |
| **组织工具参数** | ❌ 不支持 | 无 `input_args` 记录 |
| **处理工具结果** | ❌ 不支持 | 无 tool_result 处理 |
| 错误恢复 | ❌ 不支持 | 无失败路径数据 |
| SQL 查询生成 | ✅ 可能 | 需要实际查询运行 |

---

## 3. 数据缺失的根本原因

### 3.1 Callback 插件不完整

**文件**: `src/olav/plugins/callbacks/audit.py`

```python
# 当前实现 (不足):
async def on_tool_end(self, output: str, **kwargs):
    # 只记录事件，而不是调用 recorder.record_tool_call()
    await self.recorder.record(
        event_type="tool_call_completed",
        run_id=self.run_id,
        payload={"output": output[:512]}  # ⚠️ 512字符截断问题
    )
    
# 问题:
# 1. 不调用 recorder.record_tool_call() → audit_tool_calls 表不被填充
# 2. 输出截断到 512 字符 → 完整的工具结果丢失
# 3. 无 input_args 记录 → 不知道调用的参数
# 4. 无 duration_ms 记录 → 无性能数据
```

### 3.2 SFT 导出不包含工具调用

**文件**: `src/olav/enterprise/audit_dataset_export.py:650-680`

```python
# 当前实现:
for msg in redacted["messages"]:
    role = msg.get("role", "")
    if role in ("system", "user", "assistant"):  # ⚠️ 只要这3种
        sft_messages.append({
            "role": role,
            "content": msg.get("content", "")
        })
        
# 问题:
# 1. 完全忽略了 redacted["tool_calls"] 列表
# 2. 未生成 OpenAI tool_calls 格式的消息
# 3. 未生成 tool 角色的响应消息
```

---

## 4. 需要的改进方案

### 4.1 改进导出格式 (推荐)

```json
{
  "messages": [
    { "role": "user", "content": "show interfaces with errors" },
    {
      "role": "assistant",
      "content": "I'll help you find interfaces with errors.",
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
      "content": "[{\"interface\": \"Gi0/1\", \"errors\": 42}, ...]"
    },
    {
      "role": "assistant",
      "content": "Found 3 interfaces with errors on router1."
    }
  ],
  "metadata": {
    "run_id": "...",
    "agent_id": "netops",
    "tool_calls_count": 1,
    "tool_calls_success_rate": 1.0,
    "rule_score": 0.89,
    "score_components": {
      "tool_selection_relevance": 0.95,   // 新增
      "parameter_quality": 0.90,           // 新增
      "output_usage": 0.85,                 // 新增
      "reasoning_clarity": 0.85
    }
  }
}
```

### 4.2 必要的修改清单

#### Phase A: Callback 插件修复 (高优先级)

```python
# 文件: src/olav/plugins/callbacks/audit.py

# 修改 1: on_tool_start() - 记录完整的工具调用开始
async def on_tool_start(self, serialized: dict, input_str: str, **kwargs):
    self.current_tool_call = {
        "tool_name": serialized.get("name"),
        "input_args": input_str,  # 无截断
        "started_at": time.time()
    }

# 修改 2: on_tool_end() - 调用 recorder.record_tool_call()
async def on_tool_end(self, output: str, **kwargs):
    if not self.current_tool_call:
        return
    
    # 关键: 直接记录到 audit_tool_calls 表
    self.recorder.record_tool_call(
        run_id=self.run_id,
        tool_name=self.current_tool_call["tool_name"],
        input_args=self.current_tool_call["input_args"],
        output=output,  # 无截断
        status="completed",
        duration_ms=int((time.time() - self.current_tool_call["started_at"]) * 1000)
    )
    
# 修改 3: on_tool_error() - 记录失败情况
async def on_tool_error(self, error: Exception, **kwargs):
    # 记录失败的工具调用 - 重要的微调数据!
    self.recorder.record_tool_call(
        run_id=self.run_id,
        tool_name=self.current_tool_call["tool_name"],
        input_args=self.current_tool_call["input_args"],
        output=None,
        status="error",
        error=str(error),
        duration_ms=int((time.time() - self.current_tool_call["started_at"]) * 1000)
    )
```

#### Phase B: SFT 导出格式升级 (高优先级)

```python
# 文件: src/olav/enterprise/audit_dataset_export.py

def audit_to_sft_jsonl_with_tools(...):
    """Export with OpenAI tool_calls format."""
    
    for run_id in completed_run_ids:
        timeline = rebuild_run_timeline(conn, run_id)
        redacted = redact_audit_run(timeline)
        
        # 新的消息构建逻辑
        messages = []
        
        # 1. 系统消息 (如果有)
        if redacted.get("system_message"):
            messages.append({
                "role": "system",
                "content": redacted["system_message"]
            })
        
        # 2. 用户消息
        for msg in redacted["messages"]:
            if msg["role"] == "user":
                messages.append({
                    "role": "user",
                    "content": msg["content"]
                })
        
        # 3. 助手消息 + 工具调用 (新)
        assistant_content = None
        tool_calls_list = []
        
        for msg in redacted["messages"]:
            if msg["role"] == "assistant":
                assistant_content = msg["content"]
        
        for tc in redacted["tool_calls"]:
            tool_calls_list.append({
                "id": tc["call_id"],
                "type": "function",
                "function": {
                    "name": tc["tool_name"],
                    "arguments": tc["input_args"]  # JSON string
                }
            })
        
        if assistant_content or tool_calls_list:
            msg = {"role": "assistant", "content": assistant_content}
            if tool_calls_list:
                msg["tool_calls"] = tool_calls_list
            messages.append(msg)
        
        # 4. 工具结果消息 (新)
        for tc in redacted["tool_calls"]:
            messages.append({
                "role": "tool",
                "tool_call_id": tc["call_id"],
                "content": tc["output"]  # 工具返回内容
            })
        
        # 5. 最终助手消息 (如果有)
        # ... 处理最终回复
        
        sample = {
            "messages": messages,
            "metadata": {
                "run_id": run_id,
                "agent_id": ...,
                "tool_calls_count": len(redacted["tool_calls"]),
                "tool_calls_success_rate": ...,
                "score_components": {
                    "tool_selection_relevance": ...,
                    "parameter_quality": ...,
                    "output_usage": ...
                }
            }
        }
```

#### Phase C: 质量评分升级 (中优先级)

```python
# 新增评分维度，用于评估工具调用质量

def compute_tool_call_quality(timeline):
    """Evaluate tool call selection and parameter quality."""
    
    scores = {
        "tool_selection_relevance": 0.0,   // 选对了工具吗？
        "parameter_quality": 0.0,           // 参数正确吗？
        "output_usage": 0.0,                 // 有没有用工具的输出？
        "error_recovery": 0.0,               // 出错后怎么处理？
    }
    
    # 评分逻辑示例:
    # - tool_selection: 检查工具调用是否与用户查询相关
    # - parameter_quality: 检查参数格式/有效性
    # - output_usage: 最终响应是否使用了工具的输出
    # - error_recovery: 有错误时是否重试或降级
    
    return scores
```

---

## 5. 优先级与时间估算

| 任务 | 优先级 | 工作量 | 受益 | 依赖 |
|------|--------|--------|------|------|
| 修复 Callback 不记录工具调用 | 🔴 高 | 2h | 解锁工具调用数据 | 无 |
| SFT 导出格式包含 tool_calls | 🔴 高 | 4h | 可训练工具调用能力 | 见上 |
| 质量评分加入工具维度 | 🟡 中 | 3h | 自动筛选高质量样本 | 见上 |
| 支持工具结果重建 | 🟡 中 | 3h | 完整链式学习 | 见上 |
| Trajectory 导出优化 | 🟢 低 | 2h | 供高级用户分析 | 无 |

---

## 6. 立即可行的验证步骤

如果立即部署 ContainerLab E2E 测试，需要在导出前先验证：

```bash
# 1. 检查 audit_tool_calls 是否有正确数据
duckdb .olav/databases/audit.duckdb \
  "SELECT run_id, tool_name, input_args, output FROM audit_tool_calls LIMIT 5"

# 2. 检查导出中的 messages 结构
head -1 exports/audit_datasets/*/sft.jsonl | \
  python -m json.tool | grep -A20 "messages"

# 3. 验证是否有 tool_calls 字段
head -1 exports/audit_datasets/*/sft.jsonl | \
  python -c "import sys, json; d=json.load(sys.stdin); print('tool_calls' in str(d.get('messages', [])))"
```

**如果步骤 3 返回 False**:
- 说明当前导出格式不支持工具调用学习
- 需要优先完成 Phase B 导出格式升级

---

## 7. 建议行动计划

### 立即 (本周)
1. ✅ 审计完成 - 本文档
2. ⏳ 修复 Callback 插件 (src/olav/plugins/callbacks/audit.py)
3. ⏳ 升级 SFT 导出格式 (src/olav/enterprise/audit_dataset_export.py)

### 短期 (1-2周)
4. 增强质量评分（tool_selection_relevance 等）
5. 部署 ContainerLab E2E 验证真实数据
6. 运行一次完整 E2E 生成、导出、验证

### 中期 (2-4周)
7. 使用改进的数据微调小型模型
8. 评估工具调用准确率提升
9. 迭代评分权重基于真实微调结果

---

## 附录: 标准格式对比

### OpenAI API tool_calls 格式 (推荐标准)
```json
{
  "messages": [
    { "role": "user", "content": "What's the weather?" },
    {
      "role": "assistant",
      "content": null,
      "tool_calls": [
        {
          "id": "call_abc123",
          "type": "function",
          "function": {
            "name": "get_weather",
            "arguments": "{\"location\": \"San Francisco\"}"
          }
        }
      ]
    },
    {
      "role": "tool",
      "tool_call_id": "call_abc123",
      "content": "{\"temperature\": 72, \"condition\": \"sunny\"}"
    },
    {
      "role": "assistant",
      "content": "It's sunny and 72°F in San Francisco."
    }
  ]
}
```

### Anthropic API format (备选)
```json
{
  "messages": [
    { "role": "user", "content": "What's the weather?" },
    {
      "role": "assistant",
      "content": [
        { "type": "text", "text": "I'll check the weather for you." },
        {
          "type": "tool_use",
          "id": "tool_abc",
          "name": "get_weather",
          "input": { "location": "San Francisco" }
        }
      ]
    },
    {
      "role": "user",
      "content": [
        {
          "type": "tool_result",
          "tool_use_id": "tool_abc",
          "content": "{\"temperature\": 72, \"condition\": \"sunny\"}"
        }
      ]
    }
  ]
}
```

---

## 结论

**现状**: ✅ 审计日志系统工作完美，所有事件被记录  
**但**: ❌ 导出格式不支持工具调用学习  
**因此**: 需要优先级修复 Phase A + Phase B，否则微调效果有限

**目标**: 3 天内完成修复，将数据格式对齐到 OpenAI 标准，使 ContainerLab E2E 产生的数据可直接用于微调

---

*报告生成于 2026-03-17 - GitHub Copilot Audit Tool*
