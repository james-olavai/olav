# 日志与微调数据完整性问题 - 快速导航

**发现日期**: 2026-03-17  
**优先级**: 🔴 **Critical (P0 - 阻挡发布)**  
**状态**: ⏳ 待修复  
**预期修复时间**: 4-6 小时 (DATA-1 + DATA-2)

---

## 🎯 核心问题

当前 OLAV 的训练数据导出系统**不支持工具调用链**，导致：

❌ **微调后的 Agent 无法学会工具使用能力**  
❌ **企业数据集导出功能形同虚设**  
❌ **ContainerLab E2E 的数据投入产出比打折 50-70%**

---

## 📋 追踪文档

### 权威来源 (官方追踪)

| 文档 | 内容 | 用途 |
|------|------|------|
| **[dev_docs/00. issues.md](dev_docs/00.%20issues.md)** | 3个Critical问题 + 完整描述 | Issue 追踪的权威来源 |
| **[dev_docs/01. tracking.md](dev_docs/01.%20tracking.md)** | Sprint 任务表 + 优先级 | 项目进度追踪 |

### 分析与修复方案

| 文档 | 内容 | 用途 |
|------|------|------|
| **[TRAINING_DATA_AUDIT.md](TRAINING_DATA_AUDIT.md)** | 140行 完整技术分析 | 理解问题的深度根源 |
| **[TRAINING_DATA_FIX_CHECKLIST.md](TRAINING_DATA_FIX_CHECKLIST.md)** | 快速参考 + 代码修改指南 | 实施修复的操作手册 |
| **[TRAINING_DATA_USER_RECOMMENDATION.md](TRAINING_DATA_USER_RECOMMENDATION.md)** | 决策建议 + 路线图 | 理解成本-收益 |

---

## 🔴 Critical Issues 速览

### DATA-1: Callback 不记录工具调用 (2h)

**文件**: `src/olav/plugins/callbacks/audit.py`

**问题**: `on_tool_end()` 只记录事件，不调用 `record_tool_call()`

**后果**: `audit_tool_calls` 表覆盖率 < 10% (仅 1/12 运行)

**修复**: 改为调用 `recorder.record_tool_call(...)`

[→ 详见 issues.md DATA-1](dev_docs/00.%20issues.md#data-1)  
[→ 详见 FIX_CHECKLIST Phase A](TRAINING_DATA_FIX_CHECKLIST.md#step-2修复-callback-插件-1-2小时)

---

### DATA-2: SFT 导出不含工具调用链 (4h)

**文件**: `src/olav/enterprise/audit_dataset_export.py`

**问题**: 导出只包含 `user` 和 `assistant` 消息，缺少：
- `tool_calls` 字段
- `tool` 角色消息

**后果**: 导出的 JSONL 无法用于工具调用微调

**修复**: 添加工具调用链重建逻辑，遵循 OpenAI 标准格式

[→ 详见 issues.md DATA-2](dev_docs/00.%20issues.md#data-2)  
[→ 详见 FIX_CHECKLIST Phase B](TRAINING_DATA_FIX_CHECKLIST.md#step-3升级导出格式-2-3小时)

---

### DATA-3: 缺少工具质量评分 (3h, 可选)

**文件**: `src/olav/enterprise/audit_dataset_export.py`

**问题**: 质量评分维度不包含工具相关评估

**后果**: 无法自动筛选高质量的工具调用示例

**修复**: 添加 `tool_selection_relevance`, `parameter_quality`, `output_usage` 维度

[→ 详见 issues.md DATA-3](dev_docs/00.%20issues.md#data-3)  
[→ 详见 FIX_CHECKLIST Phase C](TRAINING_DATA_FIX_CHECKLIST.md#step-4-3-工具调用相关的质量评分升级)

---

## 🚀 建议执行路径

```
🏃 立即 (今天):
   └─ 读完此文档
   └─ 打开 dev_docs/00. issues.md 查看完整问题描述
   └─ 打开 TRAINING_DATA_AUDIT.md 查看技术分析

📅 本周开始修复:
   ├─ DATA-1: src/olav/plugins/callbacks/audit.py (2h)
   │  └─ 验证: audit_tool_calls 表有数据
   │
   ├─ DATA-2: src/olav/enterprise/audit_dataset_export.py (4h)
   │  └─ 验证: sft.jsonl 包含 tool_calls 字段
   │
   └─ (可选) DATA-3: 质量评分扩展 (3h)
       └─ 验证: manifest.json 包含工具流量统计

⏹️  关键: 必须在 CLAB-2 开始前完成
   原因: 第一次 E2E 的数据必须能用于微调
```

---

## 📊 修复前后对比

### 修复前 (当前)
```
导出格式:
{
  "messages": [
    { "role": "user", "content": "..." },
    { "role": "assistant", "content": "..." }
  ]
}

问题:
  ⚠️  无法学会工具选择
  ⚠️  无法学会参数组织
  ⚠️  无法学会结果处理
```

### 修复后 (目标)
```
导出格式:
{
  "messages": [
    { "role": "user", "content": "..." },
    { 
      "role": "assistant",
      "tool_calls": [{
        "id": "call_001",
        "type": "function",
        "function": {
          "name": "query_interfaces",
          "arguments": "{...}"
        }
      }]
    },
    {
      "role": "tool",
      "tool_call_id": "call_001",
      "content": "[...]"
    },
    { "role": "assistant", "content": "..." }
  ]
}

优势:
  ✅ 可以学会工具选择
  ✅ 可以学会参数组织
  ✅ 可以学会结果处理
  ✅ 符合 OpenAI 标准
```

---

## ✅ 验证清单

修复完成后，运行以下验证：

```bash
# 1. 检查工具调用数据被记录
duckdb .olav/databases/audit.duckdb \
  "SELECT COUNT(*) FROM audit_tool_calls"
# 预期: > 5 (而不是 1)

# 2. 导出测试数据
olav log export sft --hours 24 --output exports/audit_datasets/verify

# 3. 检查 JSONL 包含 tool_calls
python -c "
import json
with open('exports/audit_datasets/verify/sft.jsonl') as f:
    line = f.readline()
    sample = json.loads(line)
    has_tools = any('tool_calls' in m for m in sample.get('messages', []))
    has_tool_result = any(m.get('role') == 'tool' for m in sample.get('messages', []))
    
    if has_tools and has_tool_result:
        print('✅ PASS: 包含完整工具调用链')
    else:
        print('❌ FAIL: 缺少工具调用链')
"
```

---

## 📞 相关联系人和参考

- **问题报告者**: GitHub Copilot (2026-03-17 审计发现)
- **分析文档**: TRAINING_DATA_AUDIT.md
- **实施指南**: TRAINING_DATA_FIX_CHECKLIST.md

---

## 🔗 文件关联图

```
dev_docs/00. issues.md (权威问题定义)
  ├─ DATA-1 → src/olav/plugins/callbacks/audit.py
  ├─ DATA-2 → src/olav/enterprise/audit_dataset_export.py
  └─ DATA-3 → src/olav/enterprise/audit_dataset_export.py

dev_docs/01. tracking.md (Sprint 任务)
  ├─ 记录 DATA-1,2,3 为 Critical BLOCKER
  ├─ 标记为 CLAB-2 的前置依赖
  └─ 预计 4-6 小时修复

TRAINING_DATA_AUDIT.md (技术分析)
  ├─ 140 行详细分析
  ├─ 修复方案 (Phase A/B/C)
  ├─ 标准格式对比
  └─ 可维护性建议

TRAINING_DATA_FIX_CHECKLIST.md (操作手册)
  ├─ 诊断步骤
  ├─ Step A: Callback 修复
  ├─ Step B: 导出格式升级
  ├─ Step C: 质量评分扩展
  └─ 验证和测试

src/olav/plugins/callbacks/audit.py (Callback 实现)
  ├─ 当前: 只记录事件
  └─ 修复: 调用 record_tool_call()

src/olav/enterprise/audit_dataset_export.py (导出实现)
  ├─ 当前: 仅 user/assistant 消息
  └─ 修复: 添加 tool_calls + tool 角色
```

---

## 💡 关键决策提示

**Q: 现在就修改，还是继续做 CLAB-2?**

A: **必须先修改 DATA-1,2**。原因：
- CLAB-2 会产生大量 E2E 数据
- 如果不修改导出格式，这些数据无法微调
- 修复成本 4-6h，但收益无限
- 不修复会导致多天的 E2E 投入打折

**Q: 修复的优先顺序?**

A: **DATA-1 → DATA-2 → (可选) DATA-3**

原因：
- DATA-1 解锁数据来源
- DATA-2 解锁数据格式
- DATA-3 优化数据质量

**Q: 预期修复时间准确吗?**

A: 根据代码量估算：
- Callback 改动: 20-30 行 ≈ 2h
- 导出格式改动: 80-100 行 ≈ 4h
- 质量评分改动: 40-50 行 ≈ 3h

实际可能 ±1h，因开发者熟悉度而异。

---

## 📌 记住这三个文件

1. **issues.md** - 问题的权威定义 (官方追踪)
2. **TRAINING_DATA_FIX_CHECKLIST.md** - 怎么修的操作指南 (执行参考)
3. **TRAINING_DATA_AUDIT.md** - 为什么要这样修 (理论背景)

一旦上述三个文件中有任何关于这个问题的信息，就以这些文件为准。

---

**最后更新**: 2026-03-17  
**状态**: 待修复  
**优先级**: 🔴 Critical (阻挡发布)  
**修复时间**: 4-6 小时

