# 功能声明注册表

本页是 OLAV 平台所有功能声明（Claim）的唯一索引。每条声明对应一个可验证的平台能力。

**方法论：** Doc-Driven Testing（详见 `dev_docs/22. WEB_AND_DOCS_SITE.md` §7）

```
文档声明功能 → CLI 验证 → E2E 测试 → 验证通过 or 收窄/删除
```

**状态说明：**

- ✅ Verified — 已通过 CLI 端到端验证，记录在 `dev_docs/23. CLI_VERIFICATION_LOG.md`
- ⬜ Pending — 代码已实现，待 CLI 验证
- ⚠️ Narrowed — 部分条件下可用，已收窄声明范围
- 🔶 Env-Blocked — 需要外部环境（运行中的服务、CLAB 等）才能验证

---

## Level 1 — 平台核心能力

| ID | 声明 | 文档页 | 状态 |
|----|------|--------|------|
| C-L1-01 | OLAV 让你用自然语言操控基础设施 | [首页](../index.md) | ⬜ |

---

## Level 2 — 功能级声明

### 基础命令

| ID | 声明 | CLI 指令 | 文档页 | 状态 | 版本 |
|----|------|---------|--------|------|------|
| C-L2-01 | CLI 正确报告版本号和系统信息 | `olav version` | [安装](../getting-started/installation.md) | ✅ | v0.12.0 |
| C-L2-02 | CLI 列出所有可用 Agent 及描述 | `olav list` | [第一个查询](../getting-started/first-query.md) | ✅ | v0.12.0 |
| C-L2-03 | 列出并切换活跃 workspace | `olav workspace list/use` | [管理工作空间](../guides/manage-workspace.md) | ✅ | v0.12.0 |
| C-L2-13 | 初始化项目目录结构 | `olav init` | [安装](../getting-started/installation.md) | ✅ | v0.12.0 |
| C-L2-27 | 重置 Agent 对话历史 | `olav reset --agent <name>` | [CLI 命令](cli.md) | ✅ | v0.12.0 |

### 技能管理

| ID | 声明 | CLI 指令 | 文档页 | 状态 | 版本 |
|----|------|---------|--------|------|------|
| C-L2-04 | 从本地目录安装 Skill | `olav skill install <path>` | [构建技能](../guides/build-a-skill.md) | ✅ | v0.12.0 |
| C-L2-25 | 从 Git URL 安装 Skill | `olav skill install <url>` | [构建技能](../guides/build-a-skill.md) | ✅ | v0.12.0 |
| C-L2-06 | 追加工具到已有 workspace | `olav skill install --merge-into` | [构建技能](../guides/build-a-skill.md) | ✅ ⚠️ | v0.12.0 |
| C-L2-36 | 列出和查看已安装技能状态 | `olav skill list/status` | [管理工作空间](../guides/manage-workspace.md) | ✅ | v0.12.0 |
| C-L2-37 | Skill 声明 Python 依赖自动创建隔离 venv | `requires_packages` in MANIFEST | [构建技能](../guides/build-a-skill.md) | ✅ | v0.12.0 |

### 服务注册

| ID | 声明 | CLI 指令 | 文档页 | 状态 | 版本 |
|----|------|---------|--------|------|------|
| C-L2-19 | 一行命令注册 OpenAPI 服务 | `olav registry register <url>` | [连接服务](../guides/connect-a-service.md) | ✅ | v0.12.0 |
| C-L2-20 | Creator Agent 从 OpenAPI 生成 Skill 代码 | `olav --agent config "onboard..."` | [Creator Agent](../guides/creator-agent.md) | 🔶 | |

### 审计与日志

| ID | 声明 | CLI 指令 | 文档页 | 状态 | 版本 |
|----|------|---------|--------|------|------|
| C-L2-08 | 查询审计日志、列出最近操作 | `olav log list/errors` | [审计与日志](../guides/audit-and-logs.md) | ✅ | v0.12.0 |
| C-L2-22 | 导出审计数据为训练格式 | `olav log export trajectory/sft/atif` | [审计与日志](../guides/audit-and-logs.md) | ✅ | v0.12.0 |
| C-L2-12 | 多用户并发 Audit 无写冲突 | 5 并发 `olav log list` | [审计与日志](../guides/audit-and-logs.md) | ✅ | v0.12.0 |

### 后台服务

| ID | 声明 | CLI 指令 | 文档页 | 状态 | 版本 |
|----|------|---------|--------|------|------|
| C-L2-16 | Web 服务提供浏览器界面和 REST API | `olav service web start` | [后台服务](../guides/services.md) | ✅ | v0.12.0 |
| C-L2-17 | Daemon 加速 CLI 响应 | `olav service daemon start` | [后台服务](../guides/services.md) | ✅ | v0.12.0 |
| C-L2-18 | Syslog 接收器接收网络设备日志 | `olav service logs start` | [后台服务](../guides/services.md) | ✅ | v0.12.0 |

### HTTP API

| ID | 声明 | CLI 指令 | 文档页 | 状态 | 版本 |
|----|------|---------|--------|------|------|
| C-L2-29 | SSE 流式查询接口 | `POST /runs/stream` | [HTTP API](http-api.md) | ✅ | v0.12.0 |
| C-L2-30 | 多轮对话线程管理 | `POST /threads` | [HTTP API](http-api.md) | ✅ | v0.12.0 |

### 交互模式

| ID | 声明 | CLI 指令 | 文档页 | 状态 | 版本 |
|----|------|---------|--------|------|------|
| C-L2-14 | TUI 交互模式支持多轮对话 | `olav`（无参数） | [第一个查询](../getting-started/first-query.md) | ✅ | v0.12.0 |
| C-L2-15 | 恢复之前的会话 | `olav --session <id>` | [第一个查询](../getting-started/first-query.md) | ✅ | v0.12.0 |
| C-L2-24 | /trace-review 分析失败模式写入记忆 | `/trace-review` | [自我改进](../concepts/self-improving-loop.md) | ✅ | v0.12.0 |
| C-L2-26 | 跳过工具调用确认 | `olav --auto-approve` | [使用 Agent](../guides/using-agents.md) | ✅ | v0.12.0 |

### 知识库与记忆

| ID | 声明 | CLI 指令 | 文档页 | 状态 | 版本 |
|----|------|---------|--------|------|------|
| C-L2-21 | 知识库索引文档并支持语义搜索 | `olav --agent config "index..."` | [知识库](../guides/knowledge-base.md) | ✅ | v0.12.0 |

### 用户与认证

| ID | 声明 | CLI 指令 | 文档页 | 状态 | 版本 |
|----|------|---------|--------|------|------|
| C-L2-23 | 管理员创建/管理用户和令牌 | `olav admin "add-user..."` | [用户与角色](users-and-roles.md) | ✅ | v0.12.0 |
| C-L2-28 | 支持多种认证模式 | `auth.mode` 配置 | [安全模型](../concepts/security-model.md) | ✅ | v0.12.0 |

### Core Agent 工具

| ID | 声明 | CLI 指令 | 文档页 | 状态 | 版本 |
|----|------|---------|--------|------|------|
| C-L2-31 | Core Agent 执行 Python 代码 | `olav --agent core "run python:..."` | [Core Agent](../guides/core-agent.md) | ✅ | v0.12.0 |
| C-L2-32 | Core Agent 执行 SQL 查询 | `olav --agent core "what tables..."` | [Core Agent](../guides/core-agent.md) | ✅ | v0.12.0 |
| C-L2-33 | Core Agent Web 搜索 | `olav --agent core "search:..."` | [Core Agent](../guides/core-agent.md) | ✅ | v0.12.0 |
| C-L2-34 | Core Agent 执行 Shell 命令 | `olav --agent core "run: df -h"` | [Core Agent](../guides/core-agent.md) | ✅ | v0.12.0 |
| C-L2-35 | Config Agent 工作空间健康检查 | `olav --agent config "health check"` | [Core Agent](../guides/core-agent.md) | ✅ | v0.12.0 |

### 导出与集成

| ID | 声明 | CLI 指令 | 文档页 | 状态 | 版本 |
|----|------|---------|--------|------|------|
| C-L2-10 | 导出 Claude 兼容 plugin | `olav export claude-plugin` | [CLI 命令](cli.md) | ✅ | v0.12.0 |
| C-L2-11 | 自动截断大型 API 响应 | Python SDK | [CLI 命令](cli.md) | ✅ | v0.12.0 |

### 配置

| ID | 声明 | CLI 指令 | 文档页 | 状态 | 版本 |
|----|------|---------|--------|------|------|
| C-L2-38 | 为不同 Agent 指定不同 LLM 模型 | `agent_overrides` in api.json | [配置](configuration.md) | ✅ | v0.12.0 |
| C-L2-39 | 环境变量覆盖配置文件 | `OLAV_LLM_*` | [配置](configuration.md) | ✅ | v0.12.0 |

---

## 统计

| 状态 | 数量 |
|------|------|
| ✅ Verified | 34 |
| ⬜ Pending | 1 |
| 🔶 Env-Blocked | 1 |
| **合计** | **36** |

---

## 验证流程

```bash
# 对每条 ⬜ Claim 执行：
# 1. 运行 CLI 指令
olav <claim 对应的命令>

# 2. 记录结果到 dev_docs/23. CLI_VERIFICATION_LOG.md
# 3. 通过 → 状态改为 ✅，补充版本号
# 4. 失败 → 修代码 or 收窄声明 or 删除 Claim

# 对 🔶 Claim：需要先搭建环境（LLM API Key / 运行中的外部服务）
```
