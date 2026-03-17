# OLAV 开发进度追踪

**Last Updated:** 2026-03-15  
**Tests:** 146 passed  
**Version:** v0.11.0

---

## 1. 里程碑总览

| 里程碑 | 状态 | 完成日期 | 主要文档 |
|---|---|---|---|
| P1–P4 Agent Trace 系统 | ✅ 完成 | 2026-03-14 | `agent_traces.md` |
| CLI route_query 接线修复 | ✅ 完成 | 2026-03-15 | `agent_traces.md` P2 行 |
| Agentic 闭环文档（doc 09） | ✅ 完成 | 2026-03-15 | `docs/09_AGENTIC_FEATURES.md` |
| Core Concepts §6 自我进化 | ✅ 完成 | 2026-03-15 | `docs/03_CORE_CONCEPTS.md` |
| **AAA 设计方案** | ✅ 设计完成 | 2026-03-15 | `olav_aaa.md` |
| **企业版功能清单** | ✅ 设计完成 | 2026-03-15 | `ent_features.md` |
| AAA 实现 P0（user_id 填充） | ⬜ 待实现 | — | `olav_aaa.md §6` |
| AAA 实现 P1（auth 骨架） | ⬜ 待实现 | — | `olav_aaa.md §6` |
| AAA 实现 P2（admin CLI） | ⬜ 待实现 | — | `olav_aaa.md §6` |
| AAA 实现 P3（WebUI login） | ⬜ 待实现 | — | `olav_aaa.md §6` |

---

## 2. 当前 Sprint：AAA 实现（开源基础层）

**目标**：实现 `olav_aaa.md` 中 P0–P2 阶段，整体不超过 ~350 行新代码，零新 pip 依赖。

### P0 — OS Identity → user_id 填充（2 行）

| 任务 | 文件 | 状态 |
|---|---|---|
| `record_run_start()` 传入 `os.environ["USER"]` — interactive loop | `src/olav/cli/main.py:535` | ⬜ |
| `record_run_start()` 传入 `os.environ["USER"]` — single query | `src/olav/cli/main.py:618` | ⬜ |
| `record_run_start()` 传入 `user_id` — API server | `src/olav/api/server.py:106` | ⬜ |

### P1 — Auth 骨架 + Token Auth（~200 行）

| 任务 | 文件 | 状态 |
|---|---|---|
| `UserIdentity` dataclass | `src/olav/core/auth/identity.py` | ⬜ |
| `AuthProvider` Protocol + 工厂函数 | `src/olav/core/auth/provider.py` | ⬜ |
| `OSIdentityProvider`（Tier 0） | `src/olav/core/auth/os_identity.py` | ⬜ |
| `TokenAuthProvider`（Tier 1，`~/.olav/token`） | `src/olav/core/auth/token.py` | ⬜ |
| users.duckdb schema + 初始化 | `src/olav/core/auth/token.py` | ⬜ |
| Onboard admin token 生成 + 打印 | `src/olav/cli/onboard.py` 或 `main.py` | ⬜ |
| CLI inline login gate（`simple_cli()` 前置） | `src/olav/cli/main.py` | ⬜ |
| API Bearer 验证 middleware | `src/olav/api/server.py` | ⬜ |
| API Bearer auth 接入 `UserIdentity` | `src/olav/api/server.py` | ⬜ |
| **GAP-1：`redact_sensitive()` + audit_messages 调用点** | `src/olav/core/audit_recorder.py` | ⬜ |
| login_success / login_failed 审计事件 | `src/olav/core/auth/token.py` | ⬜ |
| `api.json` 新增 `auth` 节（mode/token_file/users_db） | `.olav/config/api.json` | ⬜ |
| `ConfigLoader` 读取 auth 节 | `src/olav/core/config.py` | ⬜ |

### P2 — Admin CLI 子命令（~150 行）

| 任务 | 文件 | 状态 |
|---|---|---|
| `olav admin add-user <username> [--role user]` | `src/olav/cli/admin_cmd.py` | ⬜ |
| `olav admin list-users` | `src/olav/cli/admin_cmd.py` | ⬜ |
| `olav admin revoke-token <username>` | `src/olav/cli/admin_cmd.py` | ⬜ |
| `olav admin rotate-token`（admin 自身） | `src/olav/cli/admin_cmd.py` | ⬜ |
| GAP-2 audit manifest：每日 sha256 → `.manifest` 文件 | `src/olav/core/audit_recorder.py` 或 cron | ⬜ |
| GAP-5 保留策略配置读取 | `src/olav/core/config.py` | ⬜ |

### P3 — WebUI 登录页（~100 行，WebUI 对外暴露时）

| 任务 | 文件 | 状态 |
|---|---|---|
| `ServerTokenProvider`（JupyterLab-style） | `src/olav/core/auth/server_token.py` | ⬜ |
| `olav service start` 生成并打印 server token | `src/olav/cli/main.py` service 子命令 | ⬜ |
| FastAPI `/login` GET（返回 login.html） | `src/olav/api/server.py` | ⬜ |
| FastAPI `/login` POST（验证 token，写 session cookie） | `src/olav/api/server.py` | ⬜ |
| **GAP-4：Cookie 安全标志**（HttpOnly/Secure/SameSite） | `src/olav/api/server.py` | ⬜ |
| HTTP middleware（检查 cookie 或 Bearer，排除 /login /health） | `src/olav/api/server.py` | ⬜ |
| `static/login.html`（最小 HTML，无前端框架） | `src/olav/api/static/login.html` | ⬜ |

---

## 3. 企业功能待办（Enterprise Backlog）

> 完整功能列表见 `ent_features.md`。以下为路线图视图。

| 编号 | 内容 | 触发条件 |
|---|---|---|
| E-A1 | LDAP / AD / OIDC SSO | 企业客户要求 AD 集成 |
| E-A2 | 速率限制 + 暴力破解保护 | 多团队 / 互联网暴露场景 |
| E-A3 | Admin 强制轮换 + 双人确认 | ISO 27001 A.9 合规审计 |
| E-1 | 高级脱敏引擎（字段级+哈希映射） | 合规要求去标识化 |
| E-2/3/4 | SFT / Trajectory / Harbor 导出 | 企业内部模型微调需求 |
| E-5 | 审计哈希链（防篡改） | SOC2 Type II / NIST AU-9 |
| E-6 | 长期保留 + S3/GCS 归档 | ISO 27001 A.12.4.1 |

---

## 4. 已知技术债务

| 编号 | 描述 | 严重程度 | 文档引用 |
|---|---|---|---|
| TD-1 | `audit_messages` 可能包含设备配置明文密码/社区字符串 | 🔴 高危 | `olav_aaa.md` GAP-1 |
| TD-2 | `audit.duckdb` 无防篡改保护，管理员可直接删改 | 🟡 中危 | `olav_aaa.md` GAP-2 |
| TD-3 | Admin token 无过期时间（`expires_at = NULL`） | 🟡 中危 | `olav_aaa.md` GAP-3 |
| TD-4 | WebUI session cookie 未设置安全标志（如果启用 WebUI） | 🔴 高危（WebUI 暴露时） | `olav_aaa.md` GAP-4 |
| TD-5 | `audit.duckdb` 无保留/归档策略，无限增长 | 🟢 低危 | `olav_aaa.md` GAP-5 |
| TD-6 | `users.duckdb` schema 及 migration 文件不存在，auth P1 硬前置 | 🔴 高危 | `olav_aaa.md §5` |
| TD-7 | `onboard.py` 平移至 `olav-netops` 独立二进制；平台层仅保留 `olav init` | 🟢 设计完成 | `olav_platform.md §3.1` |
| TD-8 | Agent/Skill 注册无机器可读声明，新域包插入需手动编辑 `AGENT.md` | 🟡 中危 | `olav_platform.md §6` |
| TD-9 | 无 `src/olav/platform/` 公开 API 层，域包只能 import 内部模块 | 🔴 高危 | `olav_platform.md §11` |
| TD-10 | `IngestManager` 绑定网络专用表，K8s/ITSM 等域无法注册自己的 DuckDB 表 | 🔴 高危 | `olav_platform.md §11.4` |
| TD-11 | CLI 子命令硬编码 → **消解**：域 CLI 改为独立二进制 (`olav-netops`)，G4 不复存在 | 🟢 消解 | `olav_platform.md §11.3` |
| TD-12 | `quick` Agent `subagents: []` 无法接受 scaffold 生成的只读域 Agent 注入 | 🟡 中危 | `olav_platform.md §11.6` |
| TD-13 | `main.duckdb` 扁平表（无 Schema 隔离），新域数据无法与网络数据逻辑分离 | 🔴 高危 | `olav_platform.md §12` |
| TD-14 | `field_classifications` LanceDB 集合名未含域前缀，多域共存时会冲突 | 🟡 中危 | `olav_platform.md §12.5` |

---

## 5. Platform 泛化 Sprint（AAA 之后）

**目标**：完成阶段零，使 `olav-platform` 可独立初始化，奠定通用域扩展能力基础。

| 任务 | 文件 | 优先级 |
|---|---|---|
| 新建 `users.duckdb` migration 文件 | `src/olav/core/migrations/v0_12_users.py` | 🔴 P0（auth 前置） |
| `cli/commands/init.py` 平台级 InitCommand | `src/olav/cli/commands/init.py` | 🟡 P1 |
| `olav-netops` 独立 CLI 注册（迁移 `onboard.py` 逻辑） | `olav-netops/src/olav_netops/cli.py` + `pyproject.toml [scripts]` | 🟡 P1 |
| `get_domain_prompt()` 注入点 | `src/olav/cli/main.py` | 🟡 P1 |
| `main.duckdb` → `domain.duckdb` 重命名 + `BaseIngestTable.schema_name` | `src/olav/core/config.py` + `ingest_base.py` | 🟡 P1 |
| `olav-netops` 迁移脚本（扁平表 → `netops.*` Schema） | `olav-netops/migrations/v0_12_schema_split.py` | 🟡 P1 |
| 现有 Agent 补写 `MANIFEST.yaml` | `.olav/workspace/*/MANIFEST.yaml` | 🟢 P2 |
| `core/agent_registry.py` MANIFEST 发现逻辑 | `src/olav/core/agent_registry.py` | 🟢 P2 |
| discovery 工具新增 `scaffold_domain_agent` | `.olav/workspace/config/discovery/tools/scaffold_domain_agent.py` | 🟢 P2 |
| `olav workspace status` 命令（含版本比对） | `src/olav/cli/commands/workspace.py` | 🟢 P2 |

---

## 6. 设计文档索引

| 文档 | 内容 | 状态 |
|---|---|---|
| `dev_docs/olav_aaa.md` | AAA 全套设计（Auth/Authz/Accounting 分层、切割矩阵、GAP 分析） | ✅ 完成 |
| `dev_docs/ent_features.md` | 企业版功能清单（AAA 企业层 + 审计企业层） | ✅ 完成 |
| `dev_docs/log_rector.md` | 审计事件系统改造方案 | ✅ 完成 |
| `dev_docs/agent_traces.md` | Agent Trace 系统（融合进 audit.duckdb） | ✅ 完成 |
| `dev_docs/plugin_rector.md` | 插件框架设计（开源/企业 entry points 分离） | ✅ 完成 |
| `dev_docs/olav_platform.md` | 平台/域拆分方案（三包架构、域 CLI 独立二进制、声明式注册、Config 升格、Domain Extension Contract、数据库 Schema 隔离） | ✅ v0.6 |
| `dev_docs/api_discovery.md` | 语义字段分类引擎设计（含 TextFSM 离线路径、scaffold_domain_agent 起点） | ✅ v0.2 |
| `docs/09_AGENTIC_FEATURES.md` | Agentic 自进化特性（EN） | ✅ 完成 |
| `docs/cn/09_AGENTIC_FEATURES.md` | Agentic 自进化特性（CN） | ✅ 完成 |
