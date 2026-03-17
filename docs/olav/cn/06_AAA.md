# OLAV AAA

本文档面向用户和运维人员，说明 OLAV 当前的认证、授权、审计模型。

它刻意区分“已经实现的内容”和“仍处于设计或部分落地状态的内容”，避免再次把规划写成现状。

## 1. 当前状态

以当前 v0.11 代码为准：

1. 认证核心是每用户本地 token，默认存放在 `~/.olav/token`。
2. 用户记录保存在 `.olav/databases/users.duckdb`。
3. 当前已实现的角色是 `admin`、`user`、`readonly`。
4. 管理员创建用户的能力已经通过 admin 用户管理命令提供。
5. 如果没有有效 token 或 users 数据库不存在，token 认证会回退到 OS 身份。

这意味着 OLAV 已经有一个可用的本地多用户模型，但并不是所有规划中的 RBAC 点位都已经强制执行完成。

## 2. 认证

### Token 存储

- 本地 token 文件：`~/.olav/token`
- 共享用户数据库：`.olav/databases/users.duckdb`

token 文件是用户私有的，本地保存。数据库则属于项目共享状态。

推荐权限：

```bash
chmod 600 ~/.olav/token
```

### 管理员用户生命周期

创建管理员：

```bash
uv run olav admin "add-user admin --role admin"
```

列出用户：

```bash
uv run olav admin "list-users"
```

轮换 token：

```bash
uv run olav admin "rotate-token alice"
```

撤销 token：

```bash
uv run olav admin "revoke-token alice"
```

创建或轮换时，token 只显示一次。数据库中保存的是加盐后的哈希，不保存明文 token。

### 当前首用真实流程

旧设计文档里描述过 `olav onboard` 的 bootstrap admin token 流程，但它不是当前代码主路径下已经落地的首用入口。

当前已经实现的路径是：

1. `olav init`
2. `olav admin "add-user admin --role admin"`
3. 把 token 存入 `~/.olav/token`

## 3. 授权

### 基线角色

| 角色 | 目标用途 | 当前含义 |
|---|---|---|
| `admin` | 平台控制面 | 用户管理、平台管理、未来的 workspace 生命周期控制 |
| `user` | 普通工程师/操作员 | 日常 agent 使用 |
| `readonly` | 审计与观察 | 只读访问模型 |

### 当前边界

项目当前已经收敛到一个简单基线：

1. 使用固定角色，而不是任意自定义角色图。
2. 长期方向是 skill 粒度授权。
3. install、upgrade、disable、remove、rollback 这类控制面动作应由 `admin` 独占。

其中有些 enforcement 还在规划或部分落地阶段。角色模型已经稳定，但完整授权面还没有全部收口完毕。

## 4. 审计

项目架构要求对用户动作做集中审计。

当前原则是：

1. CLI 命令必须尽量能归因到具体用户身份。
2. 共享审计状态应落在 `.olav/databases/` 与 `.olav/logs/`。
3. 用户私有密钥和会话状态应放在 `~/.olav/`。

从平台设计角度看，审计不是可选项，而是核心共享控制面的一部分。

## 5. 存储边界

理解 AAA 相关文件时，可以用下面这个边界：

| 位置 | 范围 | 用途 |
|---|---|---|
| `~/.olav/token` | 每用户 | 本地认证 token |
| `~/.olav/sessions/` | 每用户 | 本地会话和 checkpoint |
| `.olav/databases/users.duckdb` | 项目共享 | 用户表与 token 哈希 |
| `.olav/databases/audit.duckdb` | 项目共享 | 审计事件 |
| `.olav/workspace/` | 项目共享 | agent 与 skill 的声明式控制面 |
| `.olav/config/` | 项目共享 | 运行态配置 |

## 6. 还没有完全实现的部分

以下能力目前仍然属于设计驱动或部分完成：

1. workspace 生命周期的完整授权收口。
2. 完整的 skill 级权限矩阵 enforcement。
3. 丰富的策略编辑、用户组、审批流和策略版本化。
4. 更完善的 WebUI 或企业级策略管理界面。

这些可以写进路线图，但不应该被描述成“已经全部完成”。

## 7. 开源基线与企业层

当前架构立场是：

1. 基础 AAA 属于平台基线能力。
2. 固定角色 RBAC 不应被拆成企业专属功能。
3. 可编辑策略管理、用户组、审批与治理界面可以作为企业增强层。

也就是说，平台必须先自带一个可信的默认 AAA 模型；企业版是在管理深度上增强，而不是从零发明 AAA。

## 8. 运维建议

对于小团队，比较实际的做法是：

1. 把 `admin` 用户数量控制到很少。
2. 工程师默认使用 `user`。
3. 审计场景使用 `readonly`。
4. 设备丢失、人员变动时及时轮换 token。
5. 把 workspace 安装和升级视为 admin-only 动作。

## 9. 相关文档

- [docs/cn/02_QUICK_START.md](./02_QUICK_START.md)
- [docs/cn/04_SECURITY_FEATURE.md](./04_SECURITY_FEATURE.md)
- [docs/cn/03_CORE_CONCEPTS.md](./03_CORE_CONCEPTS.md)
- [docs/cn/07_API_OPENAPI.md](./07_API_OPENAPI.md)
- [docs/cn/08_AGENT_SKILL_REGISTRATION.md](./08_AGENT_SKILL_REGISTRATION.md)