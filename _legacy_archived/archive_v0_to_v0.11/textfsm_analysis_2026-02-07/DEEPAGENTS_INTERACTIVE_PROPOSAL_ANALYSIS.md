# DeepAgents Plan + ReAct Agent 方案深度分析

**提案日期:** 2026-02-07 | **提案人:** User  
**方案名称:** "用户交互型TextFSM自动化模板生成系统"  
**核心改进:** 从LAngGraph自动化 → DeepAgents交互式 + 人工审批

---

## 1. 用户提案的完整流程图

### 理想流程

```
┌─────────────────────────────────────────────────────────────┐
│ User Input                                                  │
│ ┌─ command: "show bgp summary"                             │
│ └─ host: "R1.cisco.ios"                                    │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 1: Execute Command (Agent Action)                      │
│ ├─ Connect to R1                                            │
│ ├─ Run "show bgp summary"                                  │
│ └─ Return: raw_output (600 lines)                          │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 2: Analyze Required Data (LLM Thinking)               │
│ ├─ LLM analyzes output structure                            │
│ ├─ Identifies:                                              │
│ │  - "Router ID": mandatory                                │
│ │  - "Neighbors": 1-N relationship                         │
│ │  - "State": mandatory for each neighbor                 │
│ │  - "AS Number": optional                                │
│ └─ Returns: structured analysis                            │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 3: User Review & Approval                             │
│ ┌─ Show to user:                                           │
│ │  "I'll extract these fields:                             │
│ │   □ Router ID                                            │
│ │   □ Neighbors (list)                                     │
│ │   □ Neighbor State                                       │
│ │   □ AS Number"                                           │
│ ├─ User can:                                               │
│ │  ✓ Approve                                              │
│ │  ✓ Add field ("RouterUptime")                           │
│ │  ✓ Remove field ("AS Number")                           │
│ │  ✓ Reorder fields                                       │
│ └─ Returns: approved_extraction_spec                       │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 4: Retrieve NTC References (Tool Call)                │
│ ├─ Search NTC for "show bgp summary"                      │
│ ├─ Find: cisco_ios_show_bgp_summary.textfsm               │
│ ├─ Find: cisco_ios_show_bgp_neighbors.textfsm             │
│ └─ Retrieve top 2 most relevant templates                  │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 5: Generate Initial Template (LLM)                    │
│ ├─ Input:                                                   │
│ │  - approved_extraction_spec                             │
│ │  - NTC reference templates                              │
│ │  - raw_output                                           │
│ └─ Output: v1 TextFSM template                             │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 6: ReAct Loop (Test & Iterate)                        │
│ ┌─ Try 1:                                                   │
│ │  Test: 45% success                                      │
│ │  Error: Missing "Neighbor AS" value                     │
│ ├─ Try 2:                                                   │
│ │  Refine: Add "Neighbor AS" value                        │
│ │  Test: 75% success                                      │
│ ├─ Try 3:                                                   │
│ │  Refine: Fix regex for "State"                          │
│ │  Test: 92% success                                      │
│ └─ Success! (>80%)                                         │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 7: Save Template                                      │
│ ├─ Path: ~/.olav/templates/custom/                         │
│ ├─ Name: cisco_ios_show_bgp_summary.textfsm               │
│ ├─ Metadata: {                                             │
│ │   "command": "show bgp summary",                        │
│ │   "platform": "cisco_ios",                              │
│ │   "generated_by": "deepagents",                         │
│ │   "success_rate": 0.92,                                 │
│ │   "user_approved_fields": [...]                         │
│ │ }                                                        │
│ └─ Return: path, success_rate, ready_to_use               │
└──────────────────────────────────────────────────────────────┘
```

---

## 2. 方案优点分析 ✅

### 优点 1: 用户控制权 (重大优势)

**当前（无审批）:**
```
LLM 猜测 → 模板 → 可能错误 ❌
```

**提案（有审批）:**
```
LLM 建议 → 用户审批/修改 → 模板来自用户意愿 ✅
```

**收益:**
- 用户知道系统要提取什么
- 可以添加、删除、修改字段
- 提高用户信任度
- 减少"我不知道模板在做什么"的抱怨

---

### 优点 2: 自动数据分析

**关键创新：** 由LLM自动分析"需要提取什么数据"

```python
# 当前（用户指定命令和输出）:
generate_template(
    raw_output=raw_output,
    command_name="show bgp summary"
)
# LLM 盲目生成

# 提案（LLM先思考）:
analysis = await analyze_required_fields(
    raw_output=raw_output,
    command_name="show bgp summary"
)
# 返回: {"fields": ["Router ID", "Neighbors", "State", ...]}
# 用户审批 ✓
# 然后才生成
```

**收益:**
- 模板的设计理念透明化
- 用户可以参与设计决策
- 减少"模板不完整"的情况

---

### 优点 3: NTC参考集成简化

**提案的优势:**
```
用户已确认需要提取的字段 → 搜索NTC
                          ↓
      更精确的相关性匹配 (因为知道目标)
```

**vs 当前:**
```
盲目搜NTC(command_name) → 返回所有可能相关的模板
```

**收益:**
- NTC参考的相关性更高
- LLM更容易学到"相关"的模板写法

---

### 优点 4: 人机协作感更强 (UX优势)

**用户体验:**
```
"我执行了命令，系统建议提取这些字段，我同意，现在它在自动优化模板"

vs 当前:

"我执行了命令，系统在神秘地做什么...最后返回一个模板"
```

**收益:**
- 用户感到被赋权
- 减少"黑箱"感觉
- 更好的可解释性

---

## 3. 方案挑战分析 ⚠️

### 挑战 1: 交互复杂性提升

**引入的新问题:**

```
当前 (LangGraph 自动):
  generate_template() 
     ↓
  template

提案 (交互型):
  Step 1: execute_command()
  Step 2: analyze_fields()
  Step 3: [等待用户输入] ← 异步交互点 (新增复杂性！)
  Step 4: fetch_ntc_reference()
  Step 5: generate_template()
  Step 6: test_template() (ReAct loop)
  Step 7: save_template()
```

**新增问题:**
- ❌ 系统必须支持"等待用户"的状态
- ❌ 用户不回应怎么办？(timeout?)
- ❌ CLI vs Web vs API？用户如何提交审批？
- ❌ 需要会话管理 (session state)

**复杂度提升:** 从 3-node graph → 7-step interactive workflow

---

### 挑战 2: 用户界面 (UX实现难度)

**需要实现:**
```
CLI审批界面？
  $ olav textfsm generate show bgp summary on R1
  
  System proposes:
    ✓ Router ID
    ✓ Neighbors (list)
    ✓ State
    ✗ AS Number
  
  Approve? [y/n/edit]
  > edit
  
  Which field to modify?
  > Add "RouterUptime"
  
  OK? [y/n]
  > y
  
  [等待模板生成...]
  ✓ Generated: cisco_ios_show_bgp_summary.textfsm (92% success)
```

**实现需求:**
- 交互式CLI (需要 prompt_toolkit 或类似)
- Web UI 选项？
- REST API 支持？

**估计工作量:** 额外 40-80 小时 UI 开发

---

### 挑战 3: 异步状态管理

**当前设计（同步）:**
```python
result = await orchestrate_query("generate template for show bgp summary")
# 等待结果，完成
```

**提案设计（异步交互）:**
```python
# 步骤1: start generation
job_id = await start_template_generation(
    command="show bgp summary",
    host="R1"
)

# 步骤2-3: LLM分析，等待用户
proposed_fields = await get_proposed_fields(job_id)  # 可能需要等

# 步骤4: 用户提交审批
await approve_fields(job_id, approved_fields)

# 步骤5-7: 生成完成
result = await wait_for_template(job_id)
```

**需要:**
- Job queue / state persistence
- WebSocket 或 polling 机制
- Timeout 和 retry 逻辑

---

### 挑战 4: 用户交互的"宽松契约"

**问题:** LLM 分析"需要提取什么字段"的准确性

```python
# 理想情况
raw_output = """
BGP router ID: 1.1.1.1
Neighbors:
  2.2.2.2   Active
  3.3.3.3   Idle
"""

# LLM analyze_fields() 应该返回
{
    "mandatory": ["Router ID", "Neighbors", "State"],
    "optional": ["AS Number", "Uptime"],
    "relationships": {"Neighbors": "1-to-N with State"}
}

# 但如果输出格式奇怪...
raw_output = """
R1>show bgp summary
[非标准格式，LLM可能无法正确分析]
"""
# LLM 可能返回错误的字段列表，用户得批准错误的分析
```

**风险:** 
- LLM 的 analyze_fields() 可能有 20-30% 的错误率
- 用户需要能够识别并修正这些错误
- 需要"帮助文本"说明每个字段的含义

---

## 4. 架构对标：当前 vs 提案

### 当前方案 (LangGraph 自动化)

```
输入: raw_output + command_name
                  ↓
              LLM generates
                  ↓
           test & iterate (3x)
                  ↓
         save template (auto)
                  ↓
              输出: template
```

**优点:**
- 简单直接
- 无需用户交互
- 时间快 (2-5秒)
- 集成容易

**缺点:**
- 用户无法控制
- "黑箱"感觉
- 可能生成不需要的字段

### 提案方案 (交互式 DeepAgents)

```
Step 1: execute
Step 2: analyze → 提示用户
        ↓
      [等待用户] ← 用户交互点
        ↓
        审批
        ↓
Step 4: fetch NTC
Step 5: generate
Step 6: test & iterate (3x)
Step 7: save
```

**优点:**
- 用户完全控制
- 透明、可解释
- 可以调整字段
- 更高的最终满意度

**缺点:**
- 复杂性大幅提升
- 需要UI实现
- 时间慢 (需等待用户输入)
- 异步状态管理复杂

---

## 5. 技术可行性评估

### 是否适合 DeepAgents Plan Agent？

**DeepAgents 的核心能力:**
- ✅ 多步骤规划 (planning)
- ✅ Tool calling (执行命令、测试模板)
- ✅ ReAct thinking (思考 → 行动)
- ❓ 人机交互 (不是 DeepAgents 的核心设计)

**问题:**

```python
# DeepAgents 可以做
agent = DeepAgent(
    system_prompt="...",
    tools=[execute_command, test_template, save_template]
)
await agent.ainvoke("Generate template for show bgp summary on R1")

# 但中间的 [等待用户] 步骤无法由 DeepAgents 原生处理
# DeepAgents 的工具要么自动完成，要么失败
# 不支持 "暂停等待人工输入" 的中间状态
```

**解决方案:**

选项 1: 自定义中间件 (复杂)
```python
# 需要自写中间件来暂停 DeepAgents 工作流
class UserApprovalMiddleware:
    async def handle_pause(self, job_id):
        # DeepAgents 工作流暂停
        # 等待用户输入
        # 恢复工作流
```

选项 2: 工作流编排器 (更合适)
```
DeepAgents agents 处理自动部分
  ├─ Agent 1: Execute command
  └─ Agent 2: ReAct generate & test

外部编排器处理交互部分
  ├─ Capture user input
  ├─ Manage state
  └─ Trigger agents
```

**结论:** DeepAgents 可用，但需要**外层编排器**来处理用户交互

---

## 6. 工作量估计

### 实现完整方案需要

| 组件 | 工作量 | 难度 | 风险 |
|------|--------|------|------|
| **Step 1-2: 命令执行 + 字段分析** | 20h | ⭐⭐ | 低 |
| **Step 3: 用户审批UI** | 60h | ⭐⭐⭐ | 中 |
| **Step 4: NTC检索** | 10h | ⭐ | 低 |
| **Step 5-6: 模板生成(DeepAgents)** | 30h | ⭐⭐⭐ | 中 |
| **Step 7: 保存和元数据** | 15h | ⭐⭐ | 低 |
| **会话管理 + 状态持久化** | 40h | ⭐⭐⭐⭐ | 高 |
| **完整测试** | 50h | ⭐⭐ | 中 |
| **文档 + 示例** | 20h | ⭐ | 低 |
| **TOTAL** | **245h** | | |

**时间:** 5-6周 (4人 or 8周 1人)  
**成本:** 中等-高

---

## 7. 对标：三个可行方案

### 方案 A: "智能自动化" (LangGraph 当前方案 + Phase 1-3 改进)

```
用户: "生成 show bgp summary 的模板"
系统: [自动执行，1-2秒]
结果: TextFSM 模板 (88-96% 质量)

优: 快速，简单
缺: 无用户控制，结构化反馈少
成本: 100-150h
收益: 88-96% 成功率
推荐: ✅ 现在做
```

---

### 方案 B: "半交互式" (提案的轻量版)

```
用户: "生成 show bgp summary 的模板"
系统: 
  1. 分析字段: "我会提取 Router ID, Neighbors, State"
  2. 用户确认: "看起来可以，继续"
  3. 自动生成 (3秒)
结果: 用户同意的模板

优: 用户控制 + 速度
缺: UI 仍需实现，但简化了
成本: 150-200h
收益: 用户满意度 ↑, 成功率 92-96%
推荐: 🟡 可考虑 (Q2)
```

---

### 方案 C: "完整交互式" (你的完整提案)

```
用户: "生成 show bgp summary 的模板"
系统:
  1. 执行命令: ✓
  2. 分析字段: "建议提取 ..."
  3. 用户审批: ✓ (可修改)
  4. 检索 NTC: ✓
  5. ReAct 生成: ✓ (自动 3x 迭代)
  6. 保存: ✓
结果: 完全由用户控制的模板

优: 最大用户控制，最高透明度
缺: 最复杂，最慢 (需等待用户)
成本: 240-280h
收益: 用户体验顶级，成功率 92-96%
推荐: 🟢 理想方案，但需要时间
```

---

## 8. 我的建议

### 短期策略 (Q1 2月-3月)

```
✅ 完成方案 A (LangGraph 当前)
   目标: 88-96% 自动化成功率
   时间: 4-6周
   成本: 100-150小时
```

### 中期策略 (Q2 4月-5月)

```
🟡 实施方案 B (半交互式)
   选项1: 用户CLI审批
   选项2: 简化的Web UI
   目标: 用户控制 + 速度平衡
   时间: 4-5周
   成本: 150-200小时
```

### 长期策略 (Q3+ 6月+)

```
🟢 升级方案 C (完整交互式)
   基于方案B的基础建设
   增加: 完整UI、ReAct独立Agent、保存管理
   目标: 完全的人机协作工作流
   时间: 4-5周 (如果有方案B基础)
   成本: 100-150小时 (增量)
```

---

## 9. 更好的折中方案

### 推荐: 方案 B+"简化方案C"混合

```
现在 (Q1):
  ✅ 完成 Phase 1 架构改进 + NTC (80-92%)

Q2 (4-5周):
  ✅ 实施方案 B (半交互式)
     用户可以设定 filter:
     
     olav textfsm import --auto \
       --command "show bgp summary" \
       --host "R1" \
       --filter "Router ID, Neighbors, State" \  ← 用户指定要什么
       --approve-auto                             ← 可自动批准
     
     vs 完整方案 C 的复杂性，这个更轻量

Q3:
  ✅ 后续改进为完整方案 C (如需要)
```

**这个策略的优点:**
- 现在 (Q1) 获得 88-96%
- Q2 增加轻量级用户控制
- Q3 升级到完整交互式 (可选)
- 分阶段，风险递减

---

## 10. 你的完整提案是否"合适"？

### 答案：✅ 在概念上完全合适，但需要分阶段。

### 具体评价

```
├─ 概念 (是否有意义)
│  ✅ YES - 用户控制 + 人机协作是正确方向
│
├─ 技术 (是否可行)
│  ✅ YES - 可以用 DeepAgents + 轻量编排层实现
│
├─ 成本 (ROI如何)
│  ⚠️ MEDIUM - 240h 对于"用户满意度"来说有点贵
│         但分阶段(方案B)可以更经济
│
├─ 风险 (会不会出问题)
│  ⚠️ MEDIUM - 异步状态管理有风险
│             但可通过充分测试缓解
│
└─ 优先级 (现在做吗)
   ❌ NO - 现在不是时候
   ✅ YES - 6-8周后可以开始
```

---

## 11. 优化你的提案

### 如果要现在实施提案，建议这样改进

**改进1: 离线审批模式**
```python
# 不要在线等待用户，改为离线审批
olav textfsm generate show bgp summary on R1 --save-proposal

# 系统保存提案到文件/数据库
# ~/.olav/templates/proposals/R1_show_bgp_summary.yaml
# 包含: 提议字段、NTC参考、成功率预估

# 用户稍后审批
olav textfsm approve <proposal_id> --fields "Router ID,Neighbors,State"

# 启动最终生成
```

**优点:** 无需实时UI，用户可异步审批

---

**改进2: 默认-自定义混合模式**
```python
# 用户可以选择:
olav textfsm generate \
  --command "show bgp summary" \
  --auto                         # 自动批准 (88-92%)
  
olav textfsm generate \
  --command "show bgp summary" \
  --approve                      # 等待用户审批 (完全控制)
  
olav textfsm generate \
  --command "show bgp summary" \
  --fields "Router ID,Neighbors" # 指定字段 (混合模式)
```

**优点:** 用户可以选择自动或审批

---

**改进3: 渐进式模板精化**
```
# 第一版 (快速, 60%)
template_v1 = auto_generate(...)

# 用户反馈: "缺少 BGP State"
# 第二版 (改进, 85%)
template_v2 = refine(template_v1, user_feedback)

# 用户再次反馈: "Router ID 格式错误"
# 第三版 (完善, 92%)
template_v3 = refine(template_v2, user_feedback)
```

**优点:** 用户可以迭代改进，而不是一次性批准

---

## 总结表

| 方面 | 评价 | 理由 |
|------|------|------|
| **概念** | ✅ 优秀 | 用户控制 + 人机协作很对 |
| **技术** | ✅ 可行 | DeepAgents + 编排可实现 |
| **时机** | ⚠️ 有点早 | 建议先做 Phase 1 (88-96%) |
| **成本** | ⚠️ 偏高 | 240h 不小，建议分阶段 |
| **推荐** | 🟡 Q2/Q3 | 现在 do Phase 1, 之后升级 |

---

