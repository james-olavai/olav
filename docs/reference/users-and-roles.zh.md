# 用户与角色

OLAV 支持多用户协作，通过角色控制每个人能做什么。

!!! abstract "功能声明"
    | ID | 声明 | 状态 |
    |----|------|------|
    | C-L2-23 | `olav admin "add-user/list-users/revoke-token/rotate-token"` | ✅ v0.10.0 |
    | C-L2-28 | 支持 none/token/ldap/ad/oidc 认证模式 | ✅ v0.10.0 |
    | C-L2-44 | `rotate-token` 与 `add-user --expires` | ✅ v0.10.0 |

---

## 角色权限

| 角色 | 能做什么 | 典型人员 |
|------|---------|---------|
| `admin` | 一切：管理用户、查看所有人的日志、修改配置、安装技能 | 平台管理员 |
| `user` | 运行查询、调用工具、查看自己的审计日志 | 日常使用者（默认角色） |
| `readonly` | 只读查询，不能执行任何写入操作 | 审计人员、观察者 |

---

## 用户管理（管理员操作）

### 添加用户

```bash
olav admin "add-user alice --role user"
olav admin "add-user bob --role admin"
```

执行后会打印一次性令牌——请**立即**分享给用户，之后无法再次查看。

你也可以设置令牌过期时间：

```bash
olav admin "add-user contractor --role user --expires 2026-06-01"
```

### 查看所有用户

```bash
olav admin "list-users"
```

### 令牌管理

```bash
olav admin "revoke-token alice"    # 立即撤销（用户无法再登录）
olav admin "rotate-token alice"    # 生成新令牌，旧令牌失效
```

---

## 用户初始设置

收到管理员分配的令牌后，保存到本地：

```bash
mkdir -p ~/.olav
echo "TOKEN_HERE" > ~/.olav/token
chmod 600 ~/.olav/token
```

`chmod 600` 确保只有你自己能读取令牌文件。

---

## 会话管理

交互模式中的对话会自动保存为会话：

```bash
olav --session <id> "继续之前的对话"
```

会话默认 24 小时后过期，可在配置中调整：`auth.session_ttl_hours`。

---

## 数据隔离

| 资源 | 作用范围 | 存储位置 |
|------|---------|---------|
| 工作空间（Agent 定义） | 项目共享 | `.olav/workspace/` |
| 审计日志 | 项目共享（标记 user_id） | `.olav/databases/audit.duckdb` |
| 认证令牌 | 个人私有 | `~/.olav/token` |
| 会话记录 | 个人私有 | `~/.olav/sessions/` |
| LLM 缓存 | 个人私有 | `~/.olav/cache/` |

---

## 管理员：查看全部活动

管理员可以直接查询审计数据库，查看所有用户的操作记录：

```bash
# 通过 OLAV 查询
olav log list

# 或直接用 DuckDB 查询（更灵活）
duckdb .olav/databases/audit.duckdb \
  "SELECT user_id, agent_id, status, started_at
   FROM audit_runs
   ORDER BY started_at DESC
   LIMIT 20"
```

---

## 认证模式配置

在 `.olav/config/api.json` 中配置，详见 [配置参考 → 认证模式](configuration.md#认证模式)。
