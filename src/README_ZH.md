<p align="center">
  <img src="olav_logo.png" alt="OLAV Logo" width="200">
</p>

<h1 align="center">OLAV 🐺</h1>

<p align="center">
  <strong>Online Analytical Vertex for Agentic Operations</strong><br>
  AI 原生的自主运维智能体平台。
</p>

<p align="center">
  <a href="">
    <img src="https://img.shields.io/badge/version-v0.10.0-blue" alt="Version">
  </a>
  <a href="">
    <img src="https://img.shields.io/badge/license-BSL--1.1-green" alt="License">
  </a>
  <a href="">
    <img src="https://img.shields.io/badge/python-3.11+-yellow" alt="Python">
  </a>
  <a href="">
    <img src="https://img.shields.io/badge/docs-TBA-lightgrey" alt="Docs">
  </a>
</p>

<p align="center">
  <a href="../README.md">English</a>
</p>

> 用自然语言操控你的基础设施。连接任意 API，部署专业 AI Agent，编排运维工作流——无需手写 SQL 或记忆 CLI 参数。

```bash
olav "有多少台设备在线？"
olav "哪些 BGP 邻居状态异常？"
olav --agent core "对所有端点执行健康检查"
```

[快速开始](#快速开始) | [English](../README.md)

---

## 为什么选择 OLAV？

### API-as-Tool — 一行命令把任何 API 变成 Agent 工具

不写代码、不维护 MCP Server。注册 OpenAPI 服务后，Agent 自动获得调用能力：

```bash
olav registry register http://netbox.example.com/api/schema/
olav "机柜 A1 里有多少台设备？"   # 立即可用
```

Creator Agent 还能从 OpenAPI schema 自动生成可编辑的 Python `@tool` 函数，实现深度定制。

### Agent Harness — 四层执行治理

所有 Agent 决策都必须经过的执行控制层：

```
Layer 0: AAA        Token/LDAP/OIDC 认证 → RBAC 授权 → 全量审计
Layer 1: Middleware  HITL 危险命令拦截 + 记忆注入 + 输出约束
Layer 2: Sandbox    Pre-scan → DuckDB 只读强制 → 网络命名空间隔离
Layer 3: Output     凭证自动脱敏 + SSE JSON 编码 + HttpOnly Cookie
```

Hard Constraints（DuckDB 只读）不可绕过；Soft Constraints（注入扫描、网络隔离）可按需配置。

### 自我改进循环 — Agent 越用越好

```
使用 OLAV → 审计日志记录每次工具调用和错误
    → /trace-review 提取失败约束 → 写入 LanceDB 记忆
    → 下次运行前自动召回约束 → 已知陷阱自动规避
```

数据驱动的自动改进，不靠手调 Prompt。

### 多层缓存 — 实测 2000x+ 加速

```
Tier-0: SemanticCache（LanceDB 向量相似匹配，~10ms）
Tier-1: LLM SQLiteCache（精确 prompt 命中，<1ms，0 token）
Tier-2: LLM API 调用（真正的网络请求）
```

用户级隔离。Anthropic 模型自动启用 Prompt Caching（system prompt 只计费一次）。

### 联邦专家 Agent 架构

不是一个万能 Agent，而是**多个专家协作**：

- 语义路由器根据 `route_keywords` 自动分派到最合适的 Agent
- 每个 Agent 只持有自己职责范围内的工具（最小权限原则）
- Per-Agent 模型分配：高频查询用便宜模型，复杂分析用强力模型——Token 成本降低 40-70%
- Skill 热插拔：`olav skill install` 即时扩展能力，无需重启

### AAA — 认证、授权、审计

- **认证**：none / token / LDAP / AD / OIDC；令牌以 SHA256 加盐哈希存储
- **授权**：三级角色（admin/user/readonly）× 五种操作，精细到 Agent/Skill 级别
- **审计**：每次操作写入 DuckDB（4 张表），SHA256 防篡改（NIST AU-9），凭证自动脱敏

### 全栈可观测 — 审计即数据资产

审计日志不只是合规工具，而是**持续积累的数据资产**：

- 用 DuckDB SQL 查询任意维度（Token 消耗、缓存命中率、工具调用频次、错误模式）
- 多用户并发安全（DuckDB 原子写入，每条记录标记 user_id）

---

## 快速开始

=== "pip install（推荐）"
    ```bash
    # 1. 安装
    pip install olav

    # 2. 初始化项目
    olav init                                   # 创建 .olav/ 目录和配置骨架

    # 3. 配置 API Key（编辑生成的文件）
    #    在 .olav/config/api.json 中设置 shared.api_key
    #    或使用环境变量：
    export OLAV_LLM_API_KEY="sk-..."           # LLM 提供商 API Key

    # 4. 连接服务并开始查询
    olav registry register http://netbox.example.com/api/schema/
    olav "机柜 A1 里有多少台设备？"

    # 或安装社区技能
    olav skill install https://github.com/olav-ai/skill-netbox
    olav "列出欧洲所有站点"
    ```

=== "从源码安装（开发模式）"
    ```bash
    # 1. 克隆并安装
    git clone https://github.com/olav-ai/olav.git && cd olav
    uv sync

    # 2. 初始化并配置
    uv run olav init                           # 创建 .olav/ 目录和配置骨架
    # 编辑 .olav/config/api.json → 设置 shared.api_key
    # 或：export OLAV_LLM_API_KEY="sk-..."
    uv run olav registry register http://netbox.example.com/api/schema/
    uv run olav "机柜 A1 里有多少台设备？"
    ```

### 其他使用方式

```bash
olav                            # 交互式终端（多轮对话）
olav service web start          # Web 界面 http://localhost:2280
olav --agent core "run: df -h"  # 通过 Core Agent 执行 Shell 命令
```

---

## 三种使用方式

| 接口 | 命令 | 适用场景 |
|------|------|---------|
| **CLI** | `olav "你的问题"` | 脚本集成、一次性查询、CI/CD |
| **TUI** | `olav` | 多轮对话、探索式分析 |
| **Web UI** | `olav service web start` | 团队共享、浏览器访问 |

---

## 架构

```
用户查询
    ↓
语义路由器 → 选择最合适的 Agent（或 --agent 指定）
    ↓
Agent Harness → AAA → Middleware → Sandbox
    ↓
LLM + 工具调用循环（调用工具、获取结果、综合回答）
    ↓
返回结果 + 审计日志（自动，每次运行）
```

**技术栈**：LangChain + LangGraph + DeepAgents + DuckDB + LanceDB + FastAPI

---

## 仓库结构

```
src/olav/          ← OLAV 平台核心（本仓库）
src/README_ZH.md   ← 中文文档
src/olav_logo.png  ← Logo
.olav/workspace/   ← 平台 Agent 定义（config/ + core/）
.olav/config/      ← 运行时配置（已 gitignore——包含 API 密钥）
.olav/databases/   ← 运行时数据（已 gitignore——审计日志、业务数据）
```

---

## 文档

文档站：**TBA**（即将上线 `docs.olavai.com`）

---

## 许可证

[BSL-1.1](LICENSE) — Business Source License 1.1
