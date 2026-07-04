<p align="center">
  <img src="olav_logo.png" alt="OLAV Logo" width="200">
</p>

<h1 align="center">OLAV 🐺</h1>

<p align="center">
  <strong>Online Analytical Vertex for Agentic Operations</strong><br>
  AI 原生的自主运维智能体平台。
</p>

<p align="center">
  <a href="https://pypi.org/project/olav/">
    <img src="https://img.shields.io/badge/version-v0.13.0-blue" alt="Version">
  </a>
  <a href="">
    <img src="https://img.shields.io/badge/license-BSL--1.1-green" alt="License">
  </a>
  <a href="">
    <img src="https://img.shields.io/badge/python-3.11+-yellow" alt="Python">
  </a>
  <a href="https://docs.olavai.com">
    <img src="https://img.shields.io/badge/docs-docs.olavai.com-blue" alt="Docs">
  </a>
  <a href="https://olavai.com">
    <img src="https://img.shields.io/badge/website-olavai.com-blueviolet" alt="Website">
  </a>
</p>

<p align="center">
  <a href="../README.md">English</a>
</p>

> 用自然语言操控你的基础设施。一条命令接入任何 REST API，即时查询，生成环境感知的自动化脚本——不需要 MCP 服务器，不生成代码，零运行时复杂度。

```bash
pip install olav
olav --agent admin "注册 NetBox 服务 http://netbox:8000"   # 接入任何 API
olav --agent admin "NetBox 里有多少台设备？"               # 即时查询
olav --agent core "写一个备份脚本"                            # 生成真实脚本
```

[快速开始](#快速开始) | [博客：v0.13 发布](https://olavai.com/blog/olav-v013) | [English](../README.md)

---

## 为什么选择 OLAV？

### API-as-Service — 超越 MCP

MCP 需要为每个服务维护一个 server 进程、stdio/HTTP 传输、框架适配器。OLAV 的方式不同：

```
MCP:   服务 → MCP server 进程 → stdio/HTTP → 适配器 → agent
OLAV:  服务 → olav registry register → reference markdown → api_request → 完成
```

一条命令。无 server 进程。不生成代码。零运行时开销。

```bash
# 注册一次
olav --agent admin "注册 NetBox 服务 http://netbox:8000"

# 任何 agent 都能查询
olav "NetBox 里有多少台设备？"
olav --agent admin "对比 OLAV 数据库和 NetBox 的设备清单"
```

`api_request` 工具**感知 API 结构** — 读取注册时生成的 API 参考文档，自动处理分页（DRF/NetBox 风格），自动管理认证（JWT/Bearer/API-key）。

### 四个顶层 Agent — 职责清晰

v0.18.1 canonical set（Round 18 Step D lite 后）：

```
olav "快速问题"                          → Core Agent（日常 80%，含脚本生成）
olav --agent admin "查询 NetBox"       → Services Agent（API 集成、服务注册）
olav --agent netops "模拟链路故障"           → Ops Agent（网络运维 + lab / probe 子 agent）
olav --agent audit "执行健康检查"         → Audit Agent（profile 作者 + 执行器）
```

每个 agent **只有它需要的工具**。Audit 不能 SSH。Services 不能改路由。最小权限原则，由 harness 强制执行。

### Core Agent — 写「你的」脚本，不是模板

Core Agent 先查你的数据库，再写代码：

```bash
olav --agent core "写一个脚本备份所有路由器配置"
```

它发现你有 R1（192.168.100.101，Juniper）、R2-R4（Cisco IOS）、SW1-SW2，然后生成 158 行 bash 脚本：
- 平台感知命令（`show run` vs `show configuration`）
- `--dry-run` 标志、错误处理、依赖检查
- 导出到 `exports/scripts/backup-configs.sh` — 真正的文件，不是对话文本

### 7 层写安全

AI agent 写入生产环境，仅靠 HITL 审批不够：

| 层 | 防御 | 可绕过？ |
|----|------|:---:|
| `--enable-api-write` | 写模式默认锁死 | 不能 |
| `services.yaml readonly_only` | 按服务控读写 | 仅配置 |
| Dry-run 模拟 | 必须通过才能审批 | 不能 |
| HITL 审批 | 用户看到 diff 后确认 | **不能** |
| `sandbox_guard hard_block` | 隔离沙箱内拦截 HTTP 写 | **不能** |
| `unshare --net` | 内核级网络隔离 | **不能** |
| 审计日志 | 全链路记录 | — |

`--dangerously-skip-permissions` 绕过工具审批（仅测试用）— 但**不能**绕过 API 写审批。网络设备永远只读。

### Agent Harness — AI Agent 的操作系统

每个 agent 决策都经过强制执行控制层：

```
Layer 0: AAA        Token/LDAP/OIDC 认证 → RBAC → 全量审计
Layer 1: Middleware  HITL 拦截 + 记忆注入
Layer 2: Sandbox    Pre-scan → DuckDB 只读 → 网络命名空间隔离
Layer 3: Output     凭证脱敏 + SSE 编码
```

### 自我改进循环

```
使用 OLAV → 审计日志记录每次工具调用
    → 失败模式提取 → 写入 LanceDB 记忆
    → 下次运行前自动召回约束
```

7,650+ 条审计消息已捕获。导出训练数据：`olav log export sft`。

---

## 快速开始

```bash
# 1. 安装
pip install olav

# 2. 直接运行 —— 首次启动自动完成全部初始化，只会询问一次 LLM API key
olav

# 3. 接入服务
olav registry register http://netbox:8000

# 4. 查询
olav "NetBox 里有多少台设备？"

# 5. 生成脚本
olav --agent core "写一个备份所有路由器配置的脚本"
```

> 脚本化/CI 场景：`olav init` 保留非交互式的等价初始化（key 用
> `OPENAI_API_KEY` 环境变量或编辑 `.olav/config/api.json`）。
> 随时用 `olav doctor`（TUI 内 `/doctor`）做零 LLM 健康体检。

### 软件理解人，而不是人理解软件

- **零仪式上手** —— 首次裸 `olav` 自动建好目录/数据库/Agent/本地嵌入模型，唯一要提供的就是 LLM key
- **首屏显示真实状态** —— 不是随机提示语：嵌入后端不可用会直说、netops 没数据会指路导入、回访时会接上"上次我们在查 R1 的 BGP flap"
- **对话式改配置** —— "把 LLM 换成 deepseek-chat"先对真实 provider 验证再落盘，坏 key 直接拒绝、原配置不动；每次变更自动快照，"回滚配置"一句话撤销
- **操作可撤销** —— 文件写入 / cron 变更自动记录，"撤销刚才的操作"即可还原
- **故障带出路** —— 运行中 401/配额错误会附上诊断命令和回滚指引，而不是甩一段堆栈

### 网络运维（可选）

```bash
pip install olav-netops

olav --agent netops "/netops_init"                    # SSH 采集设备数据
olav --agent netops "模拟 R2 链路故障"                 # What-If 分析
olav --agent netops "部署数字孪生（CAB 验证）"         # ContainerLab 验证（由 ops orchestrator 委派到 ops/lab 子 agent）
```

### 其他使用方式

```bash
olav                            # 交互式终端
olav service web start          # Web 界面 localhost:2280
olav --agent core "run: df -h"  # 通过 Core Agent 执行 Shell
```

---

## 架构

```
olav v0.13 (pip install olav)
├── core     — 工具层：api_request, execute_sql, sandbox, export
├── quick    — 快速问答（默认 agent）
├── infra    — API 查询 + 写操作（--enable-api-write）
├── devops   — 环境感知脚本生成
├── audit    — 合规审计
└── config   — 平台管理

olav-netops v0.13 (pip install olav-netops)
├── ops 编排器
│   ├── analysis — Dijkstra + ECMP 模拟（networkx）
│   ├── probe    — 并行 SSH + 命令白名单（Nornir）
│   ├── diff     — 跨快照漂移检测
│   └── lab      — ContainerLab 数字孪生 + commit-validate
└── netops.*     — DuckDB 表 + TextFSM 采集流水线
```

**技术栈**：LangChain · LangGraph · DeepAgents · DuckDB · LanceDB · FastAPI · NetworkX

---

## 数字

| 指标 | 数值 |
|------|:----:|
| 测试 | 1,358 通过 |
| DDD Claims | 44 已验证 |
| 已关闭 Issues | 62+ |
| 文档页面 | 28（中英双语） |
| 审计消息 | 7,650+ |

---

## 文档

**文档站**：[docs.olavai.com](https://docs.olavai.com) · **官网**：[olavai.com](https://olavai.com) · **博客**：[v0.13 发布](https://olavai.com/blog/olav-v013)

---

## 许可证

[BSL-1.1](LICENSE) — Business Source License 1.1

---

## 联系我们

<p align="center">
  <img src="wechat.jpeg" width="200" alt="微信公众号">
</p>
