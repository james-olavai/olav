# OLAV Platform

> 用自然语言操控你的基础设施。

**v0.10.0** — [立即开始 →](getting-started/installation.md)

!!! abstract "功能声明 · [C-L1-01 ✅ v0.10.0]"
    本页为平台 Level 1 声明。验证状态见 [功能声明注册表 →](reference/claim-registry.md)

---

## OLAV 是什么？

OLAV 是一个 AI 原生的基础设施运维平台。你只需要用自然语言描述需求，OLAV 会自动选择合适的 AI Agent 来完成任务——查询数据、执行命令、分析日志、生成报告，无需手写 SQL 或记忆复杂的 CLI 参数。

```bash
olav "有多少台设备在线？"
olav "最近一小时有哪些接口 down 了？"
olav --agent core "执行健康检查"
olav log list   # 查看所有操作记录
```

---

## 核心能力

| 能力 | 说明 |
|------|------|
| **自然语言查询** | 用日常语言提问，OLAV 自动转换为 SQL / API 调用并返回结果 |
| **多 Agent 协作** | 不同 Agent 专注不同领域（快速查询、配置管理、代码执行），自动路由到最合适的 Agent |
| **连接任意 API** | 一行命令注册 OpenAPI 服务，立即可用自然语言查询 |
| **完整审计日志** | 每一次操作自动记录，支持回溯、导出训练数据 |
| **自我改进** | 从历史错误中学习，Agent 会越用越好 |
| **团队协作** | 多用户、角色权限、共享工作空间，支持 LDAP/AD/OIDC |
| **多层缓存** | LLM SQLiteCache + SemanticCache 双缓存，命中时 0 token 消耗、<1ms 返回（实测 2000x+ 加速） |
| **LLM 微调支持** | 审计轨迹一键导出为 SFT / ATIF 训练格式，微调后替换模型无需改代码 |
| **Agent Harness** | 三层代码沙箱 + HITL 危险命令审批 + Prompt 注入扫描 + 全量审计，生产安全可控 |

---

## 三种使用方式

=== "命令行 (CLI)"
    ```bash
    olav "查询所有 BGP 邻居状态"
    ```
    适合脚本集成和快速一次性查询。

=== "交互终端 (TUI)"
    ```bash
    olav
    ```
    启动交互式终端，支持多轮对话，适合探索和分析。

=== "Web 界面"
    ```bash
    olav service web start
    # 浏览器访问 http://localhost:2280
    ```
    团队共享的浏览器界面，支持实时流式响应。

---

## 快速导航

<div class="grid cards" markdown>

- :rocket: **[快速开始](getting-started/installation.md)** — 5 分钟完成安装，运行第一个查询
- :electric_plug: **[使用指南](guides/connect-a-service.md)** — 连接服务、构建技能、管理工作空间
- :bulb: **[核心概念](concepts/agents-and-skills.md)** — 理解 Agent、Skill、Workspace 的设计思路
- :books: **[参考手册](reference/cli.md)** — CLI 命令、配置项、HTTP API 完整参考

</div>

---

*本文档由 [olav-core](https://github.com/org/olav-core) 维护。网络运维扩展文档由 [olav-netops](https://github.com/org/olav-netops) 维护。*
