# 安全模型

OLAV 从设计之初就考虑了多用户、团队协作场景下的安全需求。本页介绍认证、授权和数据隔离的工作方式。

!!! abstract "功能声明"
    | ID | 声明 | 状态 |
    |----|------|------|
    | C-L2-23 | `olav admin "add-user/list-users/revoke-token"` 用户管理 | ✅ v0.10.0 |
    | C-L2-28 | 支持 none/token/ldap/ad/oidc 认证模式 | ✅ v0.10.0 |
    | C-L2-12 | 多用户并发 Audit 无写冲突 | ✅ v0.10.0 |

---

## 认证：确认你是谁

每个用户有一个唯一的令牌（Token），存储在 `~/.olav/token`。OLAV 在每次请求时验证此令牌。

### 添加新用户

管理员创建用户并分配角色：

```bash
olav admin "add-user alice --role user"
```

命令执行后会打印一次性令牌——请立即分享给用户，之后无法再次查看。

### 用户配置令牌

用户收到令牌后，保存到本地：

```bash
mkdir -p ~/.olav
echo "TOKEN_HERE" > ~/.olav/token
chmod 600 ~/.olav/token
```

令牌以 SHA256 哈希（加盐）形式存储在 `.olav/databases/users.duckdb` 中，明文令牌不会被保存。

---

## 授权：你能做什么

OLAV 使用固定的三级角色模型（RBAC），简单直观：

| 角色 | 能做什么 | 不能做什么 |
|------|---------|-----------|
| `admin` | 一切——管理用户、查看所有日志、修改配置、安装技能 | — |
| `user` | 运行查询、调用工具、查看自己的审计日志 | 安装/卸载技能、管理用户 |
| `readonly` | 只读查询 | 任何写入操作（修改数据、执行命令） |

权限系统基于 `(agent_id, skill_name, action)` 三元组匹配，支持精细到特定 Agent 和技能的访问控制。四种操作类型：

- **use**：运行查询、调用工具
- **mutate**：修改数据、执行写入操作
- **install**：安装/卸载技能
- **admin**：用户管理、配置修改

---

## 多用户并发安全

OLAV 支持多人同时使用同一个项目目录，每个资源都有明确的安全边界：

| 资源 | 存储位置 | 并发安全 | 说明 |
|------|---------|---------|------|
| 审计日志 | `.olav/databases/audit.duckdb` | ✅ | DuckDB 原子写入，每条记录标记 user_id |
| LLM 缓存 | `~/.olav/cache/` | ✅ | 用户隔离，互不影响 |
| 会话记录 | `~/.olav/sessions/` | ✅ | 用户隔离，24h 后自动过期 |
| 认证令牌 | `~/.olav/token` | ✅ | 仅当前用户可读（chmod 600） |

---

## 认证模式

根据团队规模和安全需求，选择合适的认证方式。在 `.olav/config/api.json` 的 `auth.mode` 中配置：

| 模式 | 适用场景 | 说明 |
|------|---------|------|
| `none` | 个人使用、本地开发 | 默认模式，使用 OS 用户名识别身份，无需令牌 |
| `token` | 小团队 | OLAV 内置令牌认证，最简单的多用户方案 |
| `ldap` | 企业环境 | 对接 LDAP 目录服务 |
| `ad` | 企业环境 | 对接 Active Directory |
| `oidc` | SSO 场景 | 对接 OpenID Connect 单点登录 |

---

## 凭证安全：什么该提交，什么不该

| 内容 | 是否提交 Git | 原因 |
|------|------------|------|
| `.olav/workspace/` | ✅ 提交 | Agent 和 Skill 定义，无敏感信息 |
| `.olav/config/` | ❌ 加入 .gitignore | 包含 API 密钥和认证配置 |
| `.olav/databases/` | ❌ 加入 .gitignore | 包含审计日志和业务数据 |

!!! tip "审计日志的防篡改保护"
    OLAV 的审计系统会为每条日志生成 SHA256 摘要并写入审计清单文件（Audit Manifest），满足 NIST AU-9 防篡改要求。你可以通过内置的完整性验证功能检测日志是否被修改。

详见 [用户与角色参考 →](../reference/users-and-roles.md)

---

!!! info "沙箱与执行安全"
    认证/授权只是防护的第一层。OLAV 还提供三层代码执行沙箱、Prompt 注入扫描、危险命令 HITL 审批等机制，详见 [Agent Harness →](agent-harness.md)。
