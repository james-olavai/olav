# 自我改进循环

OLAV 最独特的设计之一：它会从自己的错误中学习。每次操作——无论成功还是失败——都被记录下来，成为改进的依据。

!!! abstract "功能声明"
    | ID | 声明 | 状态 |
    |----|------|------|
    | C-L2-24 | `/trace-review` 分析失败模式并写入 LanceDB 记忆 | ✅ v0.10.0 |
    | C-L2-22 | `olav log export trajectory` 导出训练数据 | ✅ v0.10.0 |

---

## 核心思路

传统的 AI 助手犯了错，下次可能还会犯同样的错。OLAV 不同——它把错误转化为"经验教训"，存入向量记忆库，下次遇到类似情况时自动参考，避免重蹈覆辙。

```
日常使用 OLAV
    ↓
审计日志自动记录：每次工具调用、错误、Token 消耗、用户问题
    ↓
运行 /trace-review 或让 Config Agent 分析
    ↓
LLM 识别失败模式 → 提取"约束"（下次该避免什么）→ 写入 LanceDB 记忆
    ↓
未来的查询在执行前搜索记忆 → Agent 自动规避已知陷阱
```

---

## /trace-review：一键触发改进

在交互模式（TUI）中运行：

```bash
olav        # 启动交互模式
/trace-review
```

它会做什么：

1. 查询 `audit.duckdb`，找出最近 **7 天**内的失败运行
2. 逐一分析每次失败的工具调用轨迹和错误信息
3. 将失败记录分批发送给 LLM，提取**约束**（下次应该怎么做）
4. 将学到的约束写入 **LanceDB** 向量记忆库
5. 之后的每次运行，Agent 会在行动前搜索记忆库，自动避开已知问题

输出示例：

```
Analyzed 12 failed runs

Extracted constraints (written to LanceDB memory):
  1. 调用 execute_sql 时必须使用 schema.table 格式，不能只写表名
  2. list_services 工具不接受参数，传入参数会导致 TypeError
  3. 用户说"最近的错误"时，应查看过去 48h 而非 24h
```

这些约束是**持久的**——即使重启 OLAV，Agent 也会在下次运行时自动查询这些记忆。

---

## 通过 Config Agent 触发分析

除了 `/trace-review`，你也可以用自然语言让 Config Agent 分析：

```bash
olav --agent config "分析最近的失败记录并建议改进"
olav --agent config "哪些工具被调用得最多？"
olav --agent config "有哪些查询是当前工具无法处理的？"
```

---

## 改进了什么

| 方面 | 改进方式 |
|------|---------|
| **工具使用错误** | 约束写入 LanceDB，Agent 在每次运行前自动查询并避免 |
| **路由盲区** | Config Agent 识别出没有 Agent 能很好处理的查询类型 |
| **系统提示词** | 根据失败模式，Config Agent 建议修改 AGENT.md |
| **工具描述** | 如果路由不准确，可能是 `@tool` 函数的 docstring 不够清晰 |

---

## 审计数据 → 训练数据

自我改进之外，审计日志还可以导出为 LLM 训练数据。成功的操作轨迹可以用来微调你自己的模型：

```bash
olav log export trajectory --output ./exports/train/
```

将成功的运行转化为工具调用轨迹 JSONL 格式，适合微调工具调用能力。

详见 [审计与日志 →](../guides/audit-and-logs.md)

---

## 设计哲学

OLAV 将提示工程（Prompt Engineering）视为一个**运维问题**——由真实使用数据驱动，而非凭直觉调整。

- 每次失败都是证据
- 每条约束都是一课
- 工作空间随着使用时间的增长，越来越贴合你的实际使用模式

你不需要成为 Prompt 工程专家。正常使用 OLAV，它会自己变得更好。
