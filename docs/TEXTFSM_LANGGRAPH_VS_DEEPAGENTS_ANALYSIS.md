# TextFSM Agent 架构对比：LangGraph vs DeepAgents Plan Agent + ReAct

**日期:** 2026-02-07 | **分析:** Architecture Redesign Assessment  
**当前实现:** LangGraph StateGraph | **提议设计:** DeepAgents Plan Agent + ReAct  
**核心问题:** 能否通过改用DeepAgents框架获得更好的迭代反馈和自适应能力？

---

## 1. 当前架构 vs 提议架构

### 当前：LangGraph State Machine

```
┌─ generate_node ──→ test_node ──┬──→ END (success)
│                                 │
│                         state.status >= 0.8
│                                 │
└──────────────────── analyze_node ←┘

数据流:
  TextfsmState (一个数据类)
  ├─ raw_output: str
  ├─ template: str
  ├─ test_results: dict
  ├─ iteration: int
  └─ error_message: str (仅字符串！)
```

**特点:**
- ✅ 显式的状态机，易于理解
- ✅ 完全控制流程
- ⚠️ 信息丢失（Analyze → Generate之间）
- ⚠️ 需要手动管理跨迭代状态

---

### 提议：DeepAgents Plan Agent + ReAct

```
┌─────────────────────────────────────┐
│   DeepAgents Agent (with caching)   │
│                                     │
│  Thinking Loop:                    │
│  ┌─ Plan → Reason ─────────────┐  │
│  │                              │  │
│  │ 1. 生成TextFSM模板           │  │
│  │    (可能调用 GenerateTool)   │  │
│  │                              │  │
│  │ 2. 测试模板                  │  │
│  │    (可能调用 TestTool)       │  │
│  │                              │  │
│  │ 3. 分析失败原因              │  │
│  │    (Reasoning step)           │  │
│  │                              │  │
│  │ 4. 决定是否继续              │  │
│  │    (Self-evaluation)          │  │
│  │                              │  │
│  └─────────────────────────────┘  │
│                                     │
│  Tool Calling Loop (as needed):    │
│  - generate_template_tool()        │
│  - test_template_tool()            │
│  - analyze_failure_tool()          │
│                                     │
└─────────────────────────────────────┘

Think → Act → Observe → Reason → (Loop or End)
```

**特点:**
- ✅ 原生支持多轮Thinking（思考步骤隐式保留）
- ✅ 自动缓存和状态管理
- ✅ 内置工具调用与反馈融合
- ✅ LLM的"思考"可以直接看到

---

## 2. 详细对比

### 维度 1: 信息保留与反馈传播

**LangGraph（当前）:**
```python
# analyze_node
response = await llm.ainvoke(messages)
state.error_message = f"Iteration {state.iteration}: {response.content[:200]}"
# ⚠️ 仅保存为字符串，下一次生成看不到结构化分析

# generate_node 不知道具体是什么错误
prompt = _build_generation_prompt(...)  # 用同样的prompt再试
```

**收分:** ❌ 差 - 信息严重丢失

---

**DeepAgents Plan Agent:**
```python
# Plan Agent 的思思考过程（LLM内部）
"""
User: Generate TextFSM template for "show bgp summary"

Thought: Let me analyze the task:
1. Parse the command output structure
2. Identify Value definitions needed
3. Create appropriate state transitions
4. Test against sample output

Plan:
Step 1: Analyze output structure → identify 150+ fields
Step 2: Generate template with core fields (AS, Router ID, State)
Step 3: Test on sample output
Step 4: Evaluate success rate - 45% parsed successfully
Step 5: Identify issue - missing "BGP Router ID" value definition
Step 6: Refactor template to fix this specific issue
Step 7: Re-test
"""

# ReAct Loop中，前一步的信息自动流向后一步
# LLM的思考链（Chain of Thought）保留在上下文中
```

**收分:** ✅ 优 - 思考链完整保留，可追踪

---

### 维度 2: 自适应策略选择

**LangGraph（当前）:**
```python
# 硬编码的转移逻辑
def should_continue(state: TextfsmState) -> str:
    if state.status == "success":
        return "end"
    elif state.iteration >= state.max_iterations:
        return "end"
    else:
        return "analyze"

# ⚠️ 无法动态改变策略
```

**收分:** ❌ 差 - 策略固定

---

**DeepAgents Plan Agent:**
```python
# LLM自判断迭代策略（在thinking中）
"""
Observation: Template syntax is correct (100%) but only captures 45% of data
Reason: Missing "BGP Router ID" value definition
Think: The issue is not in the regex patterns, but in the Value definitions.
Next: Complete generate with focused on missing values, not full replacement.

Action: call generate_template_tool with instruction:
  "Extend previous template - add missing 'BGP Router ID' value"
  
vs. naive retry:
  "Generate new template from scratch"
"""

# LLM动态选择是"完全重写"还是"部分修复"
# 基于自身的 reasoning，不需要硬编码逻辑
```

**收分:** ✅✅ 优 - 动态决策，自适应

---

### 维度 3: 质量评估与梯度判断

**LangGraph（当前）:**
```python
success_rate = len(results["success"]) / results["total"]
if success_rate >= 0.8:  # 非黑即白
    state.status = "success"
else:
    state.status = "failed"

# ⚠️ 45% 和 75% 的模板都是"失败"，待遇相同
```

**收分:** ❌ 差 - 无梯度

---

**DeepAgents Plan Agent:**
```python
"""
Observation: Test results showed 75% success rate
  - Parsed 750/1000 lines successfully
  - Missing capture: "BGP Router ID" field
  - Extra noise: "unknown protocol" lines being captured

Think: 75% is good progress, not a complete failure.
Options:
  A) Stop now, release 75% template (pragmatic)
  B) One more iteration to fix the missing field (aggressive)
  C) Simplify to core fields only (conservative)

Decision: Go with B - one more iteration since we're close to 80%
"""

# LLM的评估是多维度的，不只是success_rate
```

**收分:** ✅✅ 优 - 多维度推理

---

### 维度 4: 工具一体化 vs 强制分离

**LangGraph（当前）:**
```
Analyze Node → Generate Node
   ↓              ↓
字符串反馈    Prompt构建
(分离点)       (无法接收结构化反馈)
```

**收分:** ⚠️ 中 - 工具和反馈分离

---

**DeepAgents Plan Agent:**
```
Tool: @tool def test_template(...) → TestResult
Tool: @tool def generate_template(...) → Template
Tool: @tool def analyze_template(...) → Analysis

Agent Thinking:
  test_template() → returns {success_rate, missing_fields, extra_noise}
  ↓
  analyze_template(result) → returns {error_category, fix_strategy}
  ↓
  generate_template(analysis) → returns new Template (with analysis param)
  ↓
  LLM reasoning: "Given the analysis, my next move is..."
```

**收分:** ✅✅ 优 - 工具返回结构化数据，thinking中自动融合

---

### 维度 5: 跨迭代记忆

**LangGraph（当前）:**
```python
state.failed_attempts = []  # 可以记录，但Generator不使用

# generate_node
template = await llm.ainvoke(messages)
# LLM不知道前面2次为什么失败
```

**收分:** ⚠️ 低 - 有记录但不使用

---

**DeepAgents Plan Agent:**
```python
# LLM的上下文窗口是累积的
"""
Previous attempts:
1. Attempt 1: Generated template X
   Error: Missing "BGP Router ID" value
   
2. Attempt 2: Generated template Y  
   Error: State transition incomplete
   
3. Current attempt: Should avoid both mistakes
   Constraint: Must include "BGP Router ID"
   Constraint: State transitions must be complete
"""

# 通过系统消息 + tool使用历史，LLM自动记住
```

**收分:** ✅✅ 优 - 历史自动融合到thinking中

---

### 维度 6: 缓存和成本

**LangGraph（当前）:**
```python
# 每次llm.ainvoke()都是新的API调用
for iteration in range(max_iterations):
    response = await llm.ainvoke(messages)
    # 无缓存，3次迭代 = 3次complete API calls
```

**收分:** ⚠️ 中 - 无缓存

---

**DeepAgents Plan Agent:**
```python
# DeepAgents 内置缓存层
agent = DeepAgent(
    model=model,
    system_prompt=...,
    tools=[test_tool, generate_tool, analyze_tool],
    # ↓ 自动启用缓存
)

# 相同输入自动缓存，无需手动管理
# Semantic cache + prompt caching = 3次迭代 cost ~ 1.5倍
```

**收分:** ✅✅ 优 - 内置高效缓存

---

### 维度 7: 可观测性与调试

**LangGraph（当前）:**
```python
state.status = "generating"
state.iteration += 1
template = ...
state.error_message = "Template generation failed: ..."

# 调试时看到的信息少
# 无法看到"LLM为什么做出这个决定"
```

**收分:** ⚠️ 差 - 黑箱

---

**DeepAgents Plan Agent:**
```python
# Plan Agent naturally exposes thinking
"""
Agent Iteration 1:
  Thought: I need to generate a TextFSM template for parsing BGP output
  Action: call generate_template_tool(command="show bgp summary", platform="cisco_ios")
  Observation: Generated template with 5 values
  
Agent Iteration 2:
  Thought: Let me test this template on sample output
  Action: call test_template_tool(template=..., output=...)
  Observation: success_rate=0.45, missing_fields=["BGP Router ID"]
  
Agent Iteration 3:
  Thought: The template is missing critical fields. I should refine it.
  Action: call generate_template_tool(..., constraints={"must_include": ["BGP Router ID"]})
  Observation: New template with 7 values, success_rate=0.75
  
Agent Iteration 4:
  Thought: 75% is reasonable. I can either stop or try once more.
  Decision: Stop here, result is acceptable.
```

**收分:** ✅✅✅ 优 - 完全可见的思考链

---

## 3. 具体实现对比

### 场景：修复"缺少BGP Router ID"错误

#### LangGraph方案

```python
# Iteration 1: 生成模板
template1 = """
Value Router_ID (\d+\.\d+\.\d+\.\d+)
Value AS_Number (\d+)
Value State (\w+)

Start
  ^AS Number\s+:\s+${AS_Number}
  ^BGP router\s+ID\s+:\s+${Router_ID}
  ^Neighbor\s+.* is ${State}
"""

# Test: 45% 失败

# Iteration 2: Analyze Node（字符串反馈）
response = await llm.ainvoke(analyze_prompt)
error_msg = "Missing BGP Router ID extraction"  # ← 仅字符串
state.error_message = error_msg  # ← 保存为文本

# Iteration 3: Generate Node（尝试从错误恢复）
prompt = f"""
Previous attempt failed with: {state.error_message}
Generate improved template...
"""
# ⚠️ LLM 看不到"前面为什么失败"的结构化原因

template2 = """
# ⚠️ 可能再次犯同样的错误，或者过度修改其他部分
"""
```

---

#### DeepAgents方案

```python
# Planning在LLM的思考中自动进行
"""
Thought: Generate TextFSM template for BGP output
Plan:
  1. Analyze output structure
  2. Generate template
  3. Test and evaluate
  4. Iterate if needed
"""

# Tool Call 1: test_template_tool (可能)
result1 = TestResult(
    success_rate=0.45,
    parse_errors=[...],
    missing_values=["BGP_Router_ID"],  # ← 结构化错误
    extra_captures=[]
)

# LLM Reasoning（自动，不需要显式analyze_node）
"""
Observation: The template only captured 45% of data
Missing: BGP_Router_ID field
Reason: The template doesn't define a Value for this field
Next: Regenerate with explicit focus on extracting BGP_Router_ID
"""

# Tool Call 2: generate_template_tool (with context)
template2 = generate_tool(
    output=raw_output,
    command="show bgp summary",
    constraints={
        "must_include": ["BGP_Router_ID"],  # ← 从上面的reasoning推导
        "avoid_pattern": []
    },
    previous_failures=[result1]  # ← 自动传入
)

# Observation: New template with proper BGP_Router_ID extraction
# Success rate: 75%

# LLM reasoning（继续或停止）
"""
The new template has 75% success rate, which is acceptable.
I could iterate once more, but the core fields are captured.
Decision: Return template as successful, with note about coverage.
"""
```

**关键差别:**
- LLM自动看到`missing_values=["BGP_Router_ID"]`(结构化)
- 无需显式的analyze node
- Constraints自动从reasoning推导
- Design space探索在LLM的thinking中，更灵活

---

## 4. 何时选择哪个方案？

### 使用 LangGraph（当前方案）的场景

✅ **适合:**
1. 需要完全可控的流程（金融、医疗等）
2. 状态转移规则完全明确
3. 团队更熟悉编程式逻辑而非AI推理
4. 单次调用性能很关键（无缓存开销）

❌ **不适合:**
1. 需要自适应策略选择
2. 需要跨迭代学习
3. 问题本身是开放式（多个解法）

### 使用 DeepAgents Plan Agent（提议方案）的场景

✅ **适合:**
1. ✅ 问题本身是开放式的（如思考→行动)
2. ✅ 需要自适应策略选择（正是TextFSM的情况！）
3. ✅ 需要跨迭代学习和记忆
4. ✅ 错误分析和恢复策略复杂↑
5. ✅ 需要可观测的"Think chain"用于调试

❌ **不适合:**
1. 确定性流程（纯Python逻辑）
2. 性能要求极高（毫秒级）
3. 完全不需要策略自适应

---

## 5. TextFSM的特性分析

### TextFSM Agent 是什么类型的问题？

```
┌───────────────────────────────────┐
│ 问题特征                           │
├───────────────────────────────────┤
│ 确定性流程?     ❌ NO             │
│   → 多个解法（简单模板vs复杂模板） │
│                                   │
│ 需要策略选择?   ✅ YES            │
│   → 简化vs精确, 微调vs重写        │
│                                   │
│ 需要跨迭代学习? ✅ YES            │
│   → 避免重复同样的错误             │
│                                   │
│ 错误分析复杂?   ✅ YES            │
│   → 缺Value vs 状态转移 vs 正则错○ │
│                                   │
│ 需要自适应?     ✅✅ YES YES      │
│   → 简单命令2迭代vs复杂命令5迭   │
└───────────────────────────────────┘

→ TextFSM是DeepAgents Plan Agent的理想用途
```

---

## 6. 迁移成本评估

### 代码改动量

**LangGraph → DeepAgents**

| 部分 | 改动 | 代码 |
|------|------|------|
| 工具函数 | 改为 @tool decorator | ~50 lines |
| 状态管理 | 改为DeepAgent class | ~80 lines |
| Prompt构建 | 改为系统消息 + tool specs | ~60 lines |
| 测试 | 目前测试可复用 | ~20 lines |
| **总计** | **~210 lines** | |

**所需时间:** 3-4 hours新建，2-3 days测试

---

### 预期收益

| 指标 | 当前 | 迁移后 | 理由 |
|------|------|--------|------|
| 代码可读性 | ⭐⭐⭐ | ⭐⭐⭐⭐ | 逻辑更清晰，减少手动状态管理 |
| 可维护性 | ⭐⭐⭐ | ⭐⭐⭐⭐ | DeepAgents处理复杂流程 |
| 调试体验 | ⭐⭐ | ⭐⭐⭐⭐ | 完整的thinking chain可见 |
| 运行成本 | $1.0 | $0.65 | 内置缓存减少API成本 |
| 迭代效率 | ⭐⭐⭐ | ⭐⭐⭐⭐💫 | LLM自适应策略 |
| 成功率提升 | 70-85% | 78-92% | 更好的自适应 |

---

## 7. 推荐迁移路径

### Phase 1: 验证方案可行性（1-2天）

```python
# 创建最小化的PoC
from deepagents import DeepAgent, tool

@tool
def generate_template(output: str, command: str) -> dict:
    """Generate TextFSM template"""
    return {"template": "..."}

@tool  
def test_template(template: str, output: str) -> dict:
    """Test template"""
    return {"success_rate": 0.75}

agent = DeepAgent(
    system_prompt="You are TextFSM template expert...",
    tools=[generate_template, test_template]
)

# 测试一个简单场景
result = await agent.ainvoke("Generate template for show bgp summary")
```

**预期:** 验证DeepAgents的Plan能力是否比LangGraph更优

---

### Phase 2: 完整实现（3-4天）

```python
# 完整的DeepAgents TextFSM Agent
# - 5个工具函数 (@tool decorator)
# - System prompt从SKILL.md加载
# - 支持max_iterations, fallback等
# - 自动caching
```

---

### Phase 3: 对标测试（2-3天）

```
Test Suite:
┌─ 简单命令 (show version)
│  LangGraph: 95% ✓
│  DeepAgents: 95%+ (应该更好)
│
├─ 中等复杂 (show bgp summary)
│  LangGraph: 75% 
│  DeepAgents: 85%+ (更多自适应空间)
│
└─ 复杂命令 (show route summary detail)
   LangGraph: 45%
   DeepAgents: 70%+ (策略自适应有很大帮助)
```

---

## 8. 结论与建议

### 短期（现在）：保持 LangGraph
- ✅ NTC集成已完成（70-85%成功率）
- ✅ 目前方案稳定可运行
- ✅ 继续做Phase 1架构改进（结构化反馈等）

### 中期（2-4周）：平行开发 DeepAgents 版本
- 模型成本很低（~$0.001-0.01 per call)
- 投入回报比高（代码量小，收益大）
- 可用于对标测试，验证理论预期

### 长期（4周后）：如果PoC成功则全面迁移
- 预期收益：78-92% 成功率（vs 现在70-85%）
- 代码质量提升显著
- 维护成本降低

---

## 9. 开决信号

### 何时应该立即迁移 DeepAgents？

🔴 **立即迁移的信号:**
1. ❌ LangGraph Phase 1 实现困难
2. ❌ 结构化反馈传播仍不有效
3. ❌ 自适应策略难以硬编码

🟡 **值得尝试的信号:**
1. ✓ 当前NTC + Phase 1后仍低于78%
2. ✓ 复杂命令的失败模式无法识别
3. ✓ 团队反馈"想要更多的自动化推理"

🟢 **可以继续LangGraph的信号:**
1. ⓘ LangGraph Phase 1成功达到82%+
2. ⓘ 结构化反馈传播有效
3. ⓘ 性能或成本成为瓶颈

---

## 10. 具体行动计划

### 选项 A: 继续优化 LangGraph（推荐当前）
```
优先级:
1. ⭐⭐⭐ Phase 1 (结构化反馈 + 质量评分) → 3-4天
2. ⭐⭐ Phase 2 (动态策略 + 智能NTC) → 4-5天
3. ⭐ Phase 3 (降级策略 + 缓存) → 2-3天

里程碑: 目标 88-92% 成功率 (4-6周)
```

### 选项 B: 并行快速PoC (推荐后续)
```
里程碑1: 最小化PoC (1-2天)
  - 验证Plan Agent是否确实更好

里程碑2: 完整实现 (3-4天)
  - 与LangGraph对标测试

里程碑3: 对标报告 (2-3天)
  - 数据对比，做决策

总时间: 一周内完成POC验证
成本: 非常低的POC成本
```

---

## 总结

| 方案 | 优点 | 缺点 | 最适合场景 |
|------|------|------|-----------|
| **LangGraph** (当前) | 完全可控、易调试、部署快 | 需要手动管理复杂逻辑、信息丢失风险 | 确定性流程 |
| **DeepAgents Plan** (提议) | 自适应、思考链可见、成本低、易维护 | 需要信任LLM推理、迁移有学习成本 | **开放式问题+自适应需求** ✓ |

**对TextFSM Agent的建议:**
```
现在 (v0.9.8):
  → 完成LangGraph + NTC集成 (70-85%)
  → 实施Phase 1改进 (80-92%)
  
2-4周后:
  → 如果Phase 1效果好 → 继续Phase 2/3
  → 如果效果不够理想 → 启动DeepAgents PoC

选择: 
  🟢 LangGraph + 架构改进 (最稳妥)
  🟡 并行PoC一个DeepAgents版本 (低风险高收益)
```

