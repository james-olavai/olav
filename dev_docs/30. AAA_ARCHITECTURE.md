# OLAV AAA Architecture Design
**Updated:** 2026-03-17  
**Status:** Design Document (P0-P3 implemented; RBAC baseline landed, runtime enforcement still partial)

---

## 1. 设计决策记录

### D1: Auth 代码位置 — `src/olav/core/auth/`

Auth 是 CLI、API server、agent 三条路径的共同强依赖，**不是可选插件**。

- ✅ `src/olav/core/auth/`  — 认证逻辑代码（Provider、Identity、工厂函数）
- ✅ `.olav/databases/users.duckdb` — 运行时用户库、token hash（全局共享）
- ✅ `~/.olav/token` — 每用户本地 token 文件（用户私有，chmod 600）
- ❌ `.olav/workspace/` — 不放，workspace 是 agent 定义
- ❌ `src/olav/plugins/` — 不放，plugins 是可选横切逻辑

### D2: 认证模型 — CLI 和 WebUI 分层

参考 JupyterLab token 模型，但按渠道分层：

| 渠道 | 认证方式 | 说明 |
|---|---|---|
| **CLI（本地）** | OS Identity (`$USER`) + per-user `~/.olav/token` | 多用户 Linux，每人 HOME 隔离 |
| **WebUI / API** | Server token（JupyterLab-style） | `olav service start` 时生成，印到控制台，Bearer 传入 |
| **API（程序调用）** | Bearer token（用户个人 token） | `Authorization: Bearer olav_xxx` |

**JupyterLab-style WebUI token 流程：**
```
olav service start
  → 生成 server_token（进程内，存 .olav/run/server.token，chmod 600）
  → 打印: "WebUI: http://localhost:8080/?token=olav_srv_xxxx"
  → 首次访问后写 session cookie，后续免 token
```

### D3: Onboard 一次性 Admin Token

类比 Kubernetes bootstrap token / Vault root token：

```
olav onboard
  → 初始化数据库、workspace、config
  → 生成 admin_token = "olav_admin_" + random_hex(32)
  → sha256(admin_token) 存入 .olav/databases/users.duckdb
  → 终端输出（仅一次）:
      ╔══════════════════════════════════════════════════════╗
      ║  OLAV Admin Token (shown once, save immediately):   ║
      ║  olav_admin_a3f7...                                  ║
      ╚══════════════════════════════════════════════════════╝
  → 此后 admin 用此 token 创建其他用户
```

**安全要求：**
- Token hash 使用 `hashlib.sha256` + salt，**明文不落盘**
- `~/.olav/token` 权限 `0o600`，启动时自动 `chmod`

### D4: 最小 RBAC — 三角色基线 + agent/skill/action 模型

KISS 原则下，先不引入自定义用户组与通用策略引擎，采用：

1. **三角色固定基线**：`admin` / `user` / `readonly`
2. **agent/skill/action 模型可表达 skill 粒度**：但当前显式接线仍主要覆盖 `workspace` 生命周期与 `api` 写操作审批
3. **控制面与分析面分离**：安装、升级、启停、删除等 workspace lifecycle 仅 `admin` 可执行

| Role | 权限 | 默认可用能力 | 典型人员 |
|---|---|---|---|
| `admin` | 用户管理 + workspace install/upgrade/remove + 全配置 + 全 agent | 全部 | 平台负责人（1-2人） |
| `user` | 运行业务 agent + 只读 discovery + 非控制面 skill | query / ops / sync / config.discovery | 网络工程师（默认） |
| `readonly` | 只读查询与审计观察 | query / audit / 只读 discovery | 审计员、观察者 |

`readonly` 存在理由：SOC2 CC6.3 要求不可修改的只读账号用于合规审计。

**明确边界：**

- `workspace install|upgrade|disable|remove|rollback` 是 **admin 控制面职责**
- `config agent` 在设计上不整体设为 admin-only，而是按 subagent / skill 动作授权；但当前运行时还未统一把 `config.*` 控制面命令接入 `require_permission()`
- 自定义用户组不是当前阶段目标；先用三角色 + skill 权限矩阵覆盖 80% 场景

### D6: RBAC 分层 — 基线内置，策略编辑可后置/企业化

RBAC 本身属于平台**安全基线**，不应作为企业付费能力拆出。当前分层原则：

1. **开源 / 默认内置**：固定三角色 + 默认 skill 权限矩阵 + admin-only workspace lifecycle
2. **开源可选增强**：允许 admin 通过静态配置文件覆盖默认矩阵（若后续需要）
3. **企业版增强**：提供 RBAC 策略编辑、审批、版本化、用户组与审计 UI/CLI

因此：

- skill 不应直接修改 RBAC
- skill 最多生成 RBAC 变更建议或安装建议
- 真正的授权变更必须通过 admin 控制面执行

### D6.1: RBAC 基线实现状态（v0.11.0）

以下已作为**开源基线**实现并通过 23 项单元测试验证：

| 组件 | 文件 | 说明 |
|---|---|---|
| 权限规则模型 | `src/olav/core/auth/authz.py` | `PermissionRule` frozen dataclass + `DEFAULT_PERMISSIONS`（9 条规则） |
| 授权引擎 | `src/olav/core/auth/authz.py` | `check_permission()` 基于 specificity 匹配；`require_permission()` 拒绝时抛 `AuthorizationError` |
| 数据库迁移 | `src/olav/core/migrations/v0_13_rbac.py` | `role_skill_permissions` 表 DDL + 默认种子行（幂等），**但运行时尚未从表加载** |

**Reality check（必须与当前代码保持一致）：**

- 当前**运行时权限 SSOT 仍是 `DEFAULT_PERMISSIONS`**，不是 `role_skill_permissions`。
- 当前**显式接线点**只有 `WorkspaceCommand` 和 `ApiActionService`；`config evolve`、`log export grant-local-train` 等控制面命令尚未统一纳入 RBAC。
- 因此，“skill 粒度 RBAC 已完整落地”是不准确的；准确表述应为：**RBAC 模型与默认矩阵已落地，运行时接线仍部分完成**。

**默认权限矩阵（DEFAULT_PERMISSIONS）：**

| 角色 | agent_id | skill_name | action | 允许 |
|---|---|---|---|---|
| `admin` | `*` | `*` | `*` | ✅ |
| `user` | `*` | `*` | `use` | ✅ |
| `user` | `*` | `*` | `mutate` | ✅ |
| `user` | `workspace` | `*` | `install` | ❌ |
| `user` | `workspace` | `*` | `admin` | ❌ |
| `readonly` | `*` | `*` | `use` | ✅ |
| `readonly` | `*` | `*` | `mutate` | ❌ |
| `readonly` | `*` | `*` | `install` | ❌ |
| `readonly` | `*` | `*` | `admin` | ❌ |

**开源基线 vs 企业增强边界（RBAC-4）：**

| 能力 | 开源基线（已实现） | 企业增强（`ent_rbac_policy_management`） |
|---|---|---|
| 三角色固定模型 | ✅ `admin` / `user` / `readonly` | — |
| 默认权限矩阵 | ✅ `DEFAULT_PERMISSIONS` 硬编码 | — |
| Workspace lifecycle admin-only | ✅ `install`/`admin` action 拒绝 non-admin | — |
| `ApiActionService` submit/approve 鉴权 | ✅ `mutate` / `admin` 接线 | — |
| `check_permission()` / `require_permission()` 运行时鉴权 | ✅ specificity-based 匹配 | — |
| `role_skill_permissions` 表持久化 | ✅ migration/seed 已完成 | 后续可用于策略同步 / UI / CLI |
| Admin 通过静态配置覆盖默认矩阵 | 🔶 可选（后续如需） | — |
| `admin rbac list/grant/revoke` CLI | — | ✅ |
| 用户组 / 组成员 / 组到 skill 权限映射 | — | ✅ |
| RBAC 策略版本化与回滚 | — | ✅ |
| 高危授权变更审批流 / 双人确认 | — | ✅ |
| WebUI 权限矩阵管理页 | — | ✅ |
| RBAC 变更审计事件 | — | ✅ |

> 企业版的价值不是"有没有 RBAC"，而是"能否灵活管理和审计 RBAC"。
> 完整企业功能清单见 `ent_features.md` § `ent_rbac_policy_management`。

### D5: Skill 安装模型 — Admin 控制面 + 1.5 热插拔

Skill / domain 的安装与启用采用 **1.5 级热插拔** 模型：

1. `.olav/workspace/**/MANIFEST.yaml` 负责**声明与激活**
2. 已安装 Python package 负责**能力实现**
3. `.olav/config/` 只保存**运行态数据**
4. 平台负责**依赖检查、状态展示与优雅降级**

这意味着：

- **不追求**“纯文件级热插拔”
- **接受** skill/domain 需要 Python 依赖与外部二进制
- 用户复制一个 skill 后，平台可以显示 `available` / `unavailable`，但真正安装与激活由 `admin` 通过 workspace CLI 完成

建议控制面命令：

```text
olav workspace install <source>
olav workspace validate <name>
olav workspace status
```

其中：

- `install` / `upgrade` / `remove` / `rollback`：仅 `admin`
- `status`：所有角色可查看，但返回受权限过滤的 skill 可用性视图

---

## 2. 架构图

```
┌─────────────────────────────────────────────────────────┐
│  OLAV Auth Flow                                         │
│                                                         │
│  CLI ──────────────→ TokenAuthProvider ─────────────┐  │
│    └─ OS Identity       (core/auth/token.py)        │  │
│                                                      ↓  │
│  WebUI/API ─────────→ ServerTokenProvider ──→ UserIdentity
│    └─ Bearer header     (core/auth/server.py)   (username,
│                                                   role,   │
│  API Bearer ────────→ UserTokenProvider          expires) │
│    └─ per-user token    (core/auth/token.py)        │  │
│                                                      ↓  │
│                         RBAC Check ─────────────────┘  │
│                   (role -> skill matrix + lifecycle)  │
│                              ↓                         │
│                         AuditEventRecorder             │
│                         (user_id=identity.username)    │
└─────────────────────────────────────────────────────────┘
```

---

## 3. 代码结构

```
src/olav/core/auth/
  __init__.py       — 导出: get_auth_provider, UserIdentity, require_auth
  provider.py       — AuthProvider Protocol + 工厂函数 get_auth_provider(mode)
  identity.py       — UserIdentity(username, role, expires_at, source)
  token.py          — TokenAuthProvider (per-user ~/.olav/token, Tier 1)
  server_token.py   — ServerTokenProvider (WebUI JupyterLab-style, Tier 1)
  os_identity.py    — OSIdentityProvider (Tier 0, fallback)
  authz.py          — RBAC enforcement (role -> skill / lifecycle actions)  [implemented]
  ldap_.py          — LDAPAuthProvider (stub, 激活需 ldap3 包)
  ad.py             — ActiveDirectoryAuthProvider (stub, 激活需 msal 包)
  oidc.py           — OIDCAuthProvider (stub, 激活需 authlib 包)
```

**工厂函数（核心扩展点）：**

```python
# src/olav/core/auth/provider.py
def get_auth_provider(mode: str) -> AuthProvider:
    match mode:
        case "none":        return OSIdentityProvider()      # Tier 0
        case "token":       return TokenAuthProvider()       # Tier 1
        case "server":      return ServerTokenProvider()     # Tier 1 WebUI
        case "ldap":        return LDAPAuthProvider()        # Tier 2 stub
        case "ad":          return ActiveDirectoryAuthProvider()  # Tier 2 stub
        case "oidc":        return OIDCAuthProvider()        # Tier 2 stub
        case _:             return OSIdentityProvider()      # 安全降级
```

---

## 4. api.json auth 节（配置 SSOT）

```json
"auth": {
  "mode": "token",
  "token_file": "~/.olav/token",
  "server_token_file": ".olav/run/server.token",
  "users_db": ".olav/databases/users.duckdb",
  "session_ttl_hours": 24,
  "ldap": {
    "host": "ldap.corp.com",
    "port": 636,
    "base_dn": "OU=Users,DC=corp,DC=com",
    "tls": true
  },
  "ad": {
    "domain": "corp.com",
    "dc_host": "dc01.corp.com"
  },
  "oidc": {
    "issuer_url": "https://sso.corp.com",
    "client_id": "olav"
  }
}
```

`mode` 默认 `"none"`（仅 OS Identity），升级到 `"token"` 无需改代码。

---

## 5. 用户数据库 schema（users.duckdb）

```sql
CREATE TABLE users (
    username       VARCHAR PRIMARY KEY,
    display_name   VARCHAR,
    role           VARCHAR NOT NULL DEFAULT 'user',  -- admin / user / readonly
    token_hash     VARCHAR,                           -- sha256(salt+token), NULL = OS-only
    token_salt     VARCHAR,
    created_at     TIMESTAMPTZ DEFAULT now(),
    expires_at     TIMESTAMPTZ,
    last_login_at  TIMESTAMPTZ,
    is_active      BOOLEAN DEFAULT true,
    source         VARCHAR DEFAULT 'local'            -- local / ldap / ad / oidc
);
```

  ### 5.1 最小 RBAC 扩展（新增）

  当前 `users` 表继续保留单一 `role` 字段；权限矩阵额外落为独立表：

  ```sql
  CREATE TABLE role_skill_permissions (
    role          VARCHAR NOT NULL,      -- admin / user / readonly
    agent_id      VARCHAR NOT NULL,      -- query / ops / config / audit ...
    skill_name    VARCHAR NOT NULL,      -- discovery / creator / sync ...
    action        VARCHAR NOT NULL,      -- use / mutate / install / admin
    is_allowed    BOOLEAN NOT NULL DEFAULT true,
    PRIMARY KEY (role, agent_id, skill_name, action)
  );
  ```

  **设计说明：**

  - `role` 是默认授权基线，不引入 groups 表
  - `agent_id + skill_name` 与 `.olav/workspace/**/MANIFEST.yaml` 对齐
  - `action=install|upgrade|remove|rollback` 只允许 `admin`
  - 未来若确实需要自定义用户组，再新增 `groups` / `user_groups` / `group_skill_permissions`
  - 默认实现提供内置矩阵；是否开放修改工具与用户组能力另行分层

---

## 6. 实现路线图

| 阶段 | 内容 | 工作量 | 触发条件 |
|---|---|---|---|
| **P0 ✅ 今天** | Tier 0：OS `$USER` → `user_id` 填充 | 2 行 | 立即 |
| **P1** | `core/auth/` 骨架 + `OSIdentityProvider` + `TokenAuthProvider` + onboard admin token + users.duckdb schema + CLI 集成 + API Bearer + **GAP-1 audit log redaction** | ~200 行 | 多人团队使用时 |
| **P2** | `olav admin add-user/list-users/revoke-token` CLI 子命令 + admin token rotation（expires_at 90天）+ **GAP-2 audit manifest** + **GAP-3 admin action audit** + **GAP-5 retention policy** | ~150 行 | P1 完成后 |
| **P2.5 ✅** | 最小 RBAC：`role_skill_permissions` + skill 粒度授权 + workspace lifecycle 仅 admin | ~180 行 | P2 稳定后 |
| **P2.6 ✅** | Skill 安装控制面：`workspace install/validate/status` + 依赖预检 + unavailable 状態展示 | ~180 行 | P2.5 後 |
| **P3** | `ServerTokenProvider`（WebUI JupyterLab-style）+ **GAP-4 secure cookie flags + CSRF** | ~100 行 | WebUI 启用时（内网部署） |
| **P4** | LDAP stub 激活 | ~80 行 | 企业 AD/LDAP 要求时 |
| **P5** | AD / OIDC | ~100 行 | SSO 要求时 |

---

## 7. AAA 当前状态（2026-03-15）

| 支柱 | 实现状态 | 说明 |
|---|---|---|
| **Authentication** | ⚠️ Tier 0（P0 后）→ 待 P1 | OS Identity 已填 user_id，无口令验证 |
| **Authorization** | ⚠️ 基线部分完成 | 命令黑名单 ✅；三角色 ✅；`authz.py` + `v0_13_rbac` ✅；workspace lifecycle admin-only ✅；但 runtime 仍以内置默认矩阵为准，skill/control-plane 接线未覆盖完全 |
| **Accounting** | ✅ 核心完整 | audit.duckdb 全事件；P0 后 user_id 有值 |

### 7.1 授权边界（新增）

最小 RBAC 的授权对象不是“任意 Python 函数”，而是平台已知控制面与 skill：

| 对象 | 粒度 | 示例 |
|---|---|---|
| Workspace lifecycle | command/action | `workspace install`, `workspace upgrade`, `workspace rollback` |
| Agent access | agent | `query`, `ops`, `config`, `audit` |
| Skill access | skill | `config.discovery`, `config.creator`, `ops.topology` |
| Skill action | use / mutate / install / admin | 只读分析、变更执行、安装启用、管理操作 |

默认策略（按当前代码真实行为）：

- `admin`：全部允许
- `user`：默认允许 `use` 与 `mutate`，仅对 `workspace/*` 的 `install/admin` 有显式拒绝
- `readonly`：允许 `use`，拒绝 `mutate/install/admin`

当前已接线对象：

- `workspace` 生命周期：已接 `require_permission()`
- `api` 写操作审批：`ApiActionService.stage_request()` / `approve_request()` 已接 `check_permission()`
- 其他 CLI / config 控制面命令：**尚未统一接线**

### 7.2 RBAC 修改路径（新增）

当前推荐路径：

1. **默认阶段**：RBAC 内置，不提供在线修改工具
2. **后续可选**：admin 通过静态 `rbac.yaml` / `security_policies.yaml` 覆盖默认矩阵
3. **企业阶段**：提供 `admin rbac list/grant/revoke`、审批流、版本化、用户组映射

设计原则：

- RBAC 不是普通 skill 的可变业务数据
- RBAC 变更必须是可审计的 admin 控制面动作
- 企业版提供“可编辑 RBAC”，不是“有没有 RBAC”

---

## 7.1 合规差缺分析（Compliance Gap Matrix）

对照 SOC2 CC6/CC7、ISO 27001 A.9、NIST SP 800-53（AU/AC/IA）进行全面逐项评估。

### ✅ 已覆盖（P1 完成后）

| 标准条款 | 内容 | OLAV 实现 |
|---|---|---|
| SOC2 CC6.1 | Logical access controls | Token auth + inline login gate |
| SOC2 CC6.2 | Authorization by role | 3-role baseline + `authz.py`；当前显式 enforcement 在 `workspace` / `ApiActionService` |
| SOC2 CC6.3 | Least privilege | 部分满足：`readonly` 与 `workspace` 控制面最小权限已落地，`user` 的 per-skill 收口仍未完成 |
| SOC2 CC6.6 | Unauthorized access restriction | 登录门 + 黑名单 |
| SOC2 CC7.2 | System monitoring | audit.duckdb 全事件 + route_query |
| ISO 27001 A.9.2.1 | User registration/deregistration | admin CLI add-user/revoke（P2） |
| ISO 27001 A.9.2.4 | Secret authentication info | sha256+salt token hash |
| ISO 27001 A.9.4.2 | Secure logon procedures | inline login gate + 失败记录 |
| NIST AU-2 | Audit events defined | 4-table audit schema |
| NIST AU-3 | Audit record content | username/timestamp/event_type/run_id |
| NIST AC-7 | Unsuccessful logon attempts | rate limiting（P2，≥5 次锁定） |
| NIST AC-3 | Access enforcement | RBAC check → `WorkspaceCommand` / `ApiActionService`（其余入口待补） |

---

### ⚠️ 设计中存在的 5 个真实缺口

#### GAP-1：审计日志中可能泄露凭据（高危）

**问题**：`audit_messages` 表记录 LLM 消息全文。`olav "show running-config"` 的输出包含 BGP 明文密码、SNMP community string 等敏感信息，全部落入 audit.duckdb PLAINTEXT。

**影响**：ISO 27001 A.10（密码学保护）、NIST SC-28（数据静态保护）

**修复方向**：
```python
# audit_recorder.py — record_message() 写入前
REDACT_PATTERNS = [r"password \S+", r"community \S+", r"secret \S+"]
content = redact_sensitive(content, REDACT_PATTERNS)
```
**优先级：P1（和 auth 骨架同步实现）**

---

#### GAP-2：审计日志无防篡改保护（中危）

**问题**：`.olav/databases/audit.duckdb` 是普通文件，`admin` 用户可直接 `rm` 或 `sqlite3`（DuckDB CLI）修改，破坏不可否认性。  

**影响**：NIST AU-9（Audit Record Protection）、SOC2 CC7.3

**修复方向（两选一）**：  
- **轻量**：每日 `sha256sum audit.duckdb >> .olav/databases/audit.duckdb.manifest`，manifest 异地备份  
- **正式**：append-only log 导出到不可删除存储（S3/只读挂载），DuckDB 仅作查询层

**优先级：P2**

---

#### GAP-3：Admin Token 无强制轮换与保护（中危）

**问题**：Admin token 一次性生成后永不过期（`expires_at = NULL`），且为系统最高权限账号，无 MFA 保护。

**影响**：ISO 27001 A.9.2.3（Privileged Access Management）、NIST IA-5(1)

**修复方向**：
1. Admin token 默认 `expires_at = 90天` 后，强制轮换：`olav admin rotate-token`
2. Admin 操作（add-user/revoke）记录含 `admin_username` 的独立 `admin_action` 审计事件
3. P5 方向：admin 操作要求双人确认（Two-Person Integrity）

**优先级：P2**

---

#### GAP-4：WebUI Session Cookie 缺乏安全标志（内网部署时建议启用）

**问题**：D7 中设计了写 session cookie，但未指定 `Secure`、`HttpOnly`、`SameSite=Strict`，且无 CSRF token 保护。

**影响**：OWASP Top10 A01（Broken Access Control）、A03（Injection via CSRF）

**修复方向**：
```python
# FastAPI /login POST 响应
response.set_cookie(
    key="olav_session",
    value=session_token,
    httponly=True,          # 阻止 JS 读取
    secure=True,            # HTTPS only（生产）
    samesite="strict",      # CSRF 防护
    max_age=86400,          # 24h TTL
    path="/",
)
```
**优先级：P3（内网 WebUI 启用时建议配置）**

---

#### GAP-5：审计日志无保留策略（低危，合规必须）

**问题**：audit.duckdb 无限增长，且无文档说明保留期，无定期归档/清理策略。

**影响**：SOC2 CC7.2（retention evidence）、ISO 27001 A.12.4.1（Log management）、多数合规框架要求 1-3 年保留

**修复方向**：
```json
// api.json
"audit": {
  "retention_days": 365,
  "archive_path": ".olav/databases/audit_archive/",
  "rotate_size_mb": 500
}
```
`IngestManager` 每月执行 `EXPORT ... TO PARQUET` + 裁剪旧行。  
**优先级：P2**

---

### 合规达标路线

| 标准 | P1 完成后 | P2 完成后 | P4（LDAP）完成后 |
|---|---|---|---|
| **SOC2 Type I** | ✅ 可达 | ✅ 稳固 | — |
| **SOC2 Type II** | ⚠️ 需 GAP-2 | ✅ 可达 | — |
| **ISO 27001 A.9** | ⚠️ 需 GAP-3 | ✅ 可达 | — |
| **NIST SP 800-53（中等）** | ⚠️ 需 GAP-1,2 | ✅ 基本达标 | — |
| **企业 AD/LDAP 集成** | ❌ | ❌ | ✅ |
| **NERC CIP** | ❌（需 MFA） | ❌ | ⚠️ 需 MFA（P5） |

**MFA 说明**：多数内部运营工具（非公网 SaaS）豁免 MFA 要求，仅 NERC CIP / FedRAMP / 高安全合规场景才强制。OLAV 当前定位无需 MFA。

---

## 8. UX 架构决策（登录入口设计）

### D5: 不采用全屏 Textual TUI

`textual` 是新包（~3MB），对 terminal-native 的网络工程师是负担。已有 `prompt_toolkit` 足够实现内联（inline）登录体验。

**正确做法：`simple_cli()` 启动时的 Inline Login Gate：**
```
$ olav
╔════════════════════════════════╗
║   OLAV v0.11.0                ║
╚════════════════════════════════╝
Username: engineer01
Token: ••••••••••••••••
✓ Authenticated as engineer01 [user]

OLAV> _
```
- 使用 `prompt_toolkit` `PromptSession`（已依赖），密码字段 `is_password=True`
- 通过后进入现有主循环
- OS Identity mode（Tier 0）跳过此提示

### D6: 保留单次查询模式（非交互 = 静默 token 验证）

`olav "query"` 和 `olav log show` 等非交互模式**不弹登录提示**，静默读 `~/.olav/token`：

```
olav "show devices"
  → 文件存在且有效  → 执行
  → 文件不存在/过期 → stderr: "Not authenticated. Run `olav` to log in."  exit 1
```

自动化/CI 场景用环境变量 `OLAV_TOKEN=olav_xxx olav "query"` 覆盖。

### D7: WebUI 登录页（JupyterLab-style + /login fallback）

两种进入方式：
1. `olav service start` 时打印 `http://localhost:8080/?token=olav_srv_xxx`（JWT session cookie 后免 token）
2. 直接访问 `http://localhost:8080/` 无 token → 302 重定向到 `/login`，输入 token 后进入

**FastAPI 路由变化（最小改动）：**
```python
@app.get("/login")      # 返回 login.html（静态）
@app.post("/login")     # 验证 token，设置 session cookie
@app.middleware("http") # 所有非 /login /health 路由检查 cookie 或 Bearer
```

### D8: 登录事件审计

| 事件 | 写入目标 | 字段 |
|---|---|---|
| `login_success` | audit.duckdb + users/{user}.log | username, source_channel, source_ip, timestamp |
| `login_failed` | audit.duckdb + users/{user}.log | attempted_username, source_ip, reason, timestamp |
| `login_expired` | audit.duckdb | username, token_id |

连续失败 ≥ 5 次（P2）：触发 10 分钟速率限制，记录 `auth_rate_limited` 事件。

---

## 9. 三入口认证矩阵（修订）

| 入口 | 认证方式 | 登录 UI | 失败行为 |
|---|---|---|---|
| `olav`（交互） | inline prompt（用户名+token） | `prompt_toolkit` masked input | 重试 3 次后退出 |
| `olav "query"`（单次） | 静默读 `~/.olav/token` 或 `OLAV_TOKEN` env | 无UI，stderr 报错 | exit 1 |
| WebUI | `?token=` 或 `/login` 页面 | HTML login form | HTTP 401 |
| API（程序调用） | `Authorization: Bearer` | 无UI | HTTP 401 JSON |

---

## 11. 开源版 vs 企业版功能边界

> **原则**：安全基线（防止系统被利用的最低保护）属于开源；合规增强（满足企业审计标准的高级能力）属于企业插件。
> 这与 HashiCorp / Teleport / GitLab 的行业惯例一致。

### 切割矩阵

| 功能 | 开源版（BSL free） | 企业插件（BSL commercial） | 原因 |
|---|---|---|---|
| OS Identity（`$USER` → `user_id`） | ✅ | — | 安全基线 |
| Token auth（`~/.olav/token`） | ✅ | — | 安全基线 |
| Onboard admin token（一次性） | ✅ | — | 初始化必须 |
| 三角色模型（admin/user/readonly） | ✅ | — | 自助场景够用 |
| 命令黑名单 | ✅ | — | 安全基线（已实现） |
| GAP-1 凭据脱敏（audit_messages） | ✅ | — | **安全漏洞**，不能是付费修复 |
| GAP-4 安全 Cookie 标志 | ✅ | — | **OWASP 基线**，不能是付费修复 |
| 24h 审计窗口 + `olav log` | ✅ | — | 基础可观测性 |
| inline login gate（TUI） | ✅ | — | 基础认证入口 |
| WebUI `/login` 页面 | ✅ | — | 基础认证入口 |
| LDAP / AD 集成（E-A1） | — | ✅ | 纯企业 SSO |
| OIDC / 企业 SSO（E-A1） | — | ✅ | 纯企业 SSO |
| 审计日志哈希链（E-5） | — | ✅ | 合规增强（SOC2 Type II） |
| 长期保留 + 归档（E-6） | — | ✅ | 合规增强（ISO 27001） |
| 高级脱敏引擎（E-1） | — | ✅ | 合规增强 |
| SFT / Trajectory 导出（E-2,3,4） | — | ✅ | 商业增值 |
| 速率限制 / 暴力破解保护（E-A2） | — | ✅ | 企业安全加固 |
| Admin 强制轮换 + 双人确认（E-A3） | — | ✅ | 企业合规（NIST PAM） |

### 合规达标路线（修订）

| 标准 | 开源版（P1+P2 完成） | 企业插件叠加后 |
|---|---|---|
| **SOC2 Type I** | ✅ | — |
| **SOC2 Type II** | ⚠️ 缺 E-5 哈希链 | ✅ |
| **ISO 27001 A.9** | ⚠️ 缺 E-A3 轮换 | ✅ |
| **NIST SP 800-53（中等）** | ⚠️ 缺 E-5, E-A2 | ✅ |
| **企业 AD/LDAP/OIDC** | ❌ | ✅ E-A1 |
| **NERC CIP / FedRAMP** | ❌（需 MFA） | ⚠️ 需额外 MFA 集成 |

---

## 12. 反模式（CRITICAL）

- ❌ **不在 `.olav/workspace/` 放 auth 代码** — workspace 是 agent 定义
- ❌ **不在 auth 通过前写入 audit.duckdb 以外的表** — audit 记录登录失败本身是合规要求
- ❌ **明文 token 不落盘** — 只存 `sha256(salt + token)`
- ❌ **不跳过 OLAV_AUTH_DISABLE 等环境变量旁路** — 生产环境无旁路
- ❌ **不把 users.duckdb 放 `~/.olav/`** — 用户库是全局共享，必须在 `.olav/databases/`
- ❌ **不为单次模式（`olav "query"`）弹交互登录** — 破坏 CI/脚本自动化
- ❌ **不引入 `textual` 等重 TUI 框架** — `prompt_toolkit` + `rich` 已足够，保持零额外依赖
- ❌ **不把 `show running-config` 等设备输出原文写入 audit_messages** — 必须先过 `redact_sensitive()`（GAP-1）
- ❌ **WebUI session cookie 不加 `HttpOnly + Secure + SameSite=Strict`** — 基本 OWASP 要求（GAP-4）
- ❌ **admin token 不设 expires_at** — 最高权限账号必须有轮换策略（GAP-3，企业层）
- ❌ **把安全漏洞修复（GAP-1、GAP-4）放进企业付费层** — 违反负责任披露原则，损害项目声誉
