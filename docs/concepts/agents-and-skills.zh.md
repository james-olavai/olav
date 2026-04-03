# Agent 与 Skill

理解 Agent 和 Skill 的关系，是掌握 OLAV 的关键。

!!! info "本页为概念说明页。相关功能声明见 [使用 Agent](../guides/using-agents.md)、[构建技能](../guides/build-a-skill.md)、[管理工作空间](../guides/manage-workspace.md)。"

---

## Agent：专注特定任务的 AI 助手

你可以把 Agent 想象成团队中的不同角色。每个 Agent 有明确的职责和专属工具，擅长处理特定类型的问题。

一个 Agent 由三部分组成：

| 组成 | 说明 | 对应文件 |
|------|------|---------|
| **系统提示词** | 定义 Agent 的角色、行为准则和输出风格 | `AGENT.md` 中的 `system_prompt_file` |
| **工具集** | Agent 可以调用的函数（查数据库、调 API、执行代码…） | 通过子 Agent 和 Skill 加载 |
| **路由关键词** | 当用户问题匹配这些关键词时，OLAV 自动选择此 Agent | `MANIFEST.yaml` 中的 `route_keywords` |

### AGENT.md 示例

```yaml
---
name: quick-orchestrator
description: "Quick Query Agent — 快速 SQL/CLI 查询"
system_prompt_file: prompts/system.md
subagents: []
static_context:
  - path: ./references/SCHEMA_REFERENCE.md
---

## 概述
Quick Agent 是 OLAV 的默认入口。
它跳过复杂的多步推理循环，追求一步到位的快速响应。
```

`static_context` 字段指定了 Agent 在每次运行时自动加载的参考资料（如数据库 schema），帮助 LLM 更准确地理解问题。

---

## Skill：赋予 Agent 新能力的工具包

Skill 是一组 Python `@tool` 函数的集合，可以独立开发、安装和共享。按来源分为三类：

| 类型 | 说明 | 示例 |
|------|------|------|
| **内置** | OLAV 自带 | `core`（代码执行）、`config`（系统管理） |
| **生成** | 由 Creator Agent 从 OpenAPI 自动生成 | Zabbix 工具、NetBox 工具 |
| **自定义** | 你自己编写，通过 `olav skill install` 安装 | 工单查询、自动化脚本 |

### MANIFEST.yaml 示例

```yaml
kind: Agent
name: quick
version: "0.11.0"
description: "Quick Agent — 快速 SQL 查询、CLI 执行、知识库搜索"
route_keywords:
  - quick query
  - show me
  - list devices
  - what is
  - how many
tools_dir: tools/
requires:
  - olav-platform>=0.11
```

`route_keywords` 决定了语义路由器何时将问题分配给这个 Agent。`tools_dir` 指定工具函数所在的目录。

---

## Agent 如何加载工具

Agent 获取工具有两种方式：

### 静态绑定（在 AGENT.md 中声明）

```yaml
subagents:
  - path: ./creator/SKILL.md
  - path: ./knowledge/SKILL.md
```

适合内置的、稳定的工具绑定。Agent 每次启动都会加载这些子技能。

### 动态发现（通过 `olav skill install`）

```bash
olav skill install ./my-tools/
```

安装后，工具写入 `.olav/workspace/<name>/`。OLAV 启动 Agent 时会自动扫描工作空间，发现并注入所有已安装技能的工具。无需手动修改 AGENT.md。

---

## 工具调用循环

当你提问后，Agent 内部的处理流程如下：

```
你的问题
    ↓
Agent 看到所有可用工具（每个工具有名称和描述）
    ↓
LLM 决定调用哪个工具，传入参数
    ↓
工具执行，返回结果
    ↓
LLM 分析结果，决定是否需要调用更多工具
    ↓
所有信息充足后，综合生成最终回答
    ↓
每次工具调用自动写入审计日志
```

---

## 内置 Agent 一览

| Agent | 角色 | 擅长 |
|-------|------|------|
| `quick` *(默认)* | 快速查询助手 | 单步查询，一问一答 |
| `config` | 系统管理员 | 服务注册、技能生成、工作空间健康检查 |
| `core` | 全能工程师 | 代码执行、SQL、Shell、Web 搜索 |

```bash
olav list   # 查看所有可用 Agent
```

---

## 什么时候该创建什么？

| 需求 | 方案 |
|------|------|
| 给现有 Agent 增加新能力 | 安装一个新的 **Skill** |
| 需要完全不同的 AI 助手角色 | 创建一个新的 **Agent**（新建 AGENT.md） |
| 给现有 Skill 补充几个工具 | `olav skill install --merge-into` |

大多数场景下，你只需要安装新的 Skill 即可。只有当你需要不同的系统提示词、不同的行为模式时，才需要创建新 Agent。
