# 安全功能和治理

OLAV 实现了一个**多层安全架构**，设计用来防止高风险操作、确保访问控制以及维护全面的审计跟踪。该框架集成了意图识别、基于角色的访问控制、凭证管理和实时监控。

## 🎯 安全架构概览

```
┌─────────────────────────────────────────────────┐
│ 用户查询 / CLI 命令                              │
├─────────────────────────────────────────────────┤
│ 第1层：身份和认证                               │
│ • 用户识别、API密钥验证                         │
├─────────────────────────────────────────────────┤
│ 第2层：基于角色的访问控制(RBAC)                 │
│ • 用户角色验证、代理权限检查                    │
├─────────────────────────────────────────────────┤
│ 第3层：语义防火墙(风险检测)                     │
│ • 意图分析、风险分类                            │
├─────────────────────────────────────────────────┤
│ 第4层：命令黑名单(确定性)                       │
│ • 硬编码禁用命令阻止                            │
├─────────────────────────────────────────────────┤
│ 第5层：审计和日志                               │
│ • 请求日志、结果跟踪、合规性                    │
└─────────────────────────────────────────────────┘
```

## 🔐 核心安全组件

### 第1层：身份和认证
- API密钥 / SSH密钥验证
- 多用户隔离 (USER_ID跟踪)
- 令牌过期和续期策略

### 第2层：基于角色的访问控制 (RBAC)
- 用户角色：`admin`（管理员）、`user`（普通用户）、`readonly`（只读用户）
- 代理级权限 (用户可以调用哪些代理)
- 数据访问范围 (用户可以查询哪些设备/网络)

### 第3层：语义防火墙 (主动保护)
使用AI嵌入识别用户查询的*意图*。即使用户改述危险命令(例如"清空箱子"而不是"删除配置")，语义层也可以检测到风险。

### 第4层：命令黑名单 (反应式保护)
禁用命令的硬编码列表。此层阻止特定的预定义命令被发送到任何网络设备，提供确定性保护。

### 第5层：审计和日志
所有操作、用户操作和系统事件的完整审计跟踪，用于合规性和取证。

---

## 1️⃣ 身份和认证

确保只有授权用户可以访问 OLAV 系统。

### 用户识别
```bash
# 用户通过以下方式识别:
# - 用户名 + API密钥 (HTTP API)
# - 用户名 (交互式CLI)
# - SSH密钥 + 用户名 (SSH访问)

# 查看当前用户
olav config "显示当前用户和他们的角色"

# 列出所有授权用户
olav --agent config "显示所有用户和他们的角色"
```

### API密钥管理
```bash
# 为用户创建 API 密钥
olav --agent config "为用户 john.doe 生成 API 密钥，有效期 90 天"

# 撤销 API 密钥
olav --agent config "撤销用户 john.doe 的 API 密钥"

# 检查 API 密钥过期日期
olav --agent config "显示所有用户的 API 密钥过期日期"

# 自动轮换过期密钥
olav --agent config "自动轮换超过 90 天的 API 密钥"
```

### SSH密钥管理
```bash
# 更新设备凭证的 SSH 密钥
olav --agent config "更新设备 R1 的 SSH 私钥"

# 验证密钥访问权限
olav --agent config "测试所有设备的 SSH 连通性并使用当前密钥"
```

---

## 2️⃣ 基于角色的访问控制 (RBAC)

定义 OLAV 中每个用户可以做什么。

### 用户角色

| 角色 | 描述 | 权限 |
|------|------|------|
| **admin** | 完全控制面访问 | 用户管理、平台管理、未来的 workspace 生命周期动作 |
| **user** | 标准运维访问 | 日常 agent 使用 |
| **readonly** | 只读访问 | 只读查询与审计观察 |

### 代理级权限

```bash
# 检查用户可以访问哪些代理
olav --agent config "显示用户 alice 的权限矩阵"

# 为用户授予代理访问权限
olav --agent config "允许用户 bob 访问 Ops 代理"

# 撤销代理访问权限
olav --agent config "撤销 Bob 对 Config 代理的访问权限"

# 范围数据访问(哪些设备/网络)
olav --agent config "用户 alice 只能查询标签为 tag=production 的设备"
```

### 命令级权限

```bash
# 受限命令需要 admin 控制面权限
olav --agent config "启用命令过滤：破坏性控制面操作需要 admin 角色"

# 用户范围过滤
olav --agent config "用户 john.doe 只能访问区域为 region=US 的设备"
```

### 权限验证

```bash
# 执行前，OLAV 检查:
olav "显示设备 R1 的配置"  # ✅ readonly 可以执行只读查询
olav --agent config "修改管理 IP"  # ❌ readonly 不能执行控制面动作
```

---

## 3️⃣ 语义防火墙 (保护装置)

语义防火墙将用户查询分类为风险级别，并根据与定义的策略模式的相似性匹配采取行动(BLOCK、CONFIRM 或 WARN)。

### 配置
管理地址: `.olav/config/security_policies.yaml` 和 **Config 代理**

```bash
# 查看当前安全策略
olav --agent config "显示所有语义防火墙规则"

# 调整风险阈值
olav --agent config "降低语义防火墙阈值至 0.7(更敏感)"
```

### 关键策略级别：
- **破坏性**: 永久删除或修改数据的操作 (例如 `rm -rf`, `drop database`)。 
  - **操作**: `BLOCK` (立即终止请求)。
- **高风险**: 显著影响系统或网络状态的操作 (例如 `reboot`, `modify ospf`)。
  - **操作**: `CONFIRM` (需要显式用户确认)。
- **中等风险**: 需要谨慎的操作 (例如 `execute command`, `export data`)。
  - **操作**: `WARN` (允许执行但记录警告)。
- **低风险**: 安全查询 (例如 `show config`, `ping`)。
  - **操作**: `ALLOW` (立即执行，日志记录)。

### 示例

```bash
# 破坏性操作 → 被阻止
olav "删除所有快照"
# 输出: ❌ 已阻止 - 检测到破坏性操作

# 高风险操作 → 需要确认
olav "重启路由器 R1"
# 输出: ⚠️ 需要确认 - 此操作将导致服务中断
# 是否继续? [yes/no]

# 中等风险操作 → 警告已日志记录
olav "导出所有网络快照数据"
# 输出: ✓ 已允许(已记录警告) - 大数据导出
```

---

## 4️⃣ 命令黑名单

命令黑名单为特定命令字符串提供了不可变的防护。它特别有用，可以防止 CPU 密集型调试命令或未经授权的配置保存。

### 配置
管理地址: `.olav/config/blacklisted_commands.yaml` 和 **Config 代理**

```bash
# 查看黑名单命令
olav --agent config "显示所有黑名单命令和它们的原因"

# 将命令添加到黑名单
olav --agent config "将命令 'debug ip ospf' 加入黑名单 - 原因: CPU 密集"

# 从黑名单删除命令
olav --agent config "从黑名单删除 'debug ip ospf'(紧急覆盖)"

# 测试命令是否被阻止
olav --agent config "'write memory' 是否在黑名单中?"
```

### 黑名单命令示例：
- `debug ip ospf` (防止设备 CPU 峰值)
- `write memory` (防止未经批准的意外保存)
- `copy running-config startup-config` (强化操作需要显式请求)
- `reload <interface>` (接口重启应通过变更管理进行)

---

## 5️⃣ 审计日志和合规性

OLAV 维护所有用户操作的全面审计日志，用于合规性、取证和安全监控。

### 审计日志位置

```
~/.olav/logs/
  ├── users/
  │   ├── {user}.log          # 此用户的所有操作
  │   └── {user}-failed.log   # 失败的操作(访问被拒、等)
  ├── security/
  │   ├── auth.log            # 认证事件(登录/登出)
  │   ├── blocked.log         # 被阻止/拒绝的操作
  │   └── sensitive.log       # 高风险操作(更改、删除)
  └── audit/
      ├── config-changes.log  # 配置修改
      ├── device-access.log   # 设备 SSH 访问日志
      └── data-exports.log    # 数据导出事件
```

### 查询审计日志

```bash
# 查看过去 24 小时内用户的所有操作
olav --agent config "显示过去 24 小时内用户 alice 的审计日志"

# 查看所有失败的访问尝试
olav --agent config "显示所有失败的认证尝试"

# 查看所有配置变更
olav --agent config "谁修改了管理 IP? 何时修改的? 改了什么?"

# 查看高风险操作
olav --agent config "显示过去 7 天内的所有高风险操作"

# 为合规性导出审计日志
olav --agent config "将 2026 年 3 月的所有审计日志导出为 CSV"

# 实时审计监控
olav --agent config "对所有 'BLOCK' 或 'CONFIRM' 操作实时告警"
```

### 审计日志示例条目
```
2026-03-06 14:23:15 | 用户: john.doe | 角色: user | 操作: query
代理: ops | 查询: "显示 R1 的 BGP 邻居"
风险级别: 低 | 状态: 被允许 | 结果: 成功 | 耗时: 250ms
日志文件: /home/john/.olav/logs/users/john.doe.log
```

### 合规性和保留

```bash
# 设置审计日志保留策略
olav --agent config "保留审计日志 2 年，在此之前归档旧日志"

# 生成合规性报告
olav --agent config "生成 SOC2 / ISO 27001 合规性报告(2026 年一季度)"

# 检查日志是否不可变
olav --agent config "验证审计日志是写保护和不可变的"
```

---

## 6️⃣ 凭证生命周期管理

使用自动轮换和过期管理 API 密钥、SSH 密钥、设备凭证。

### API密钥生命周期

```bash
# 生成 API 密钥
olav --agent config "为用户 alice 创建 API 密钥，有效期 90 天，范围: production 设备"

# 跟踪密钥过期
olav --agent config "显示：哪些 API 密钥在接下来的 30 天内过期"

# 自动轮换密钥
olav --agent config "启用自动轮换：每 90 天刷新 API 密钥"

# 立即撤销密钥
olav --agent config "立即撤销 API 密钥 {key_id} - 已被泄露"

# 为用户轮换所有密钥
olav --agent config "强制轮换用户 bob 的所有 API 密钥"
```

### SSH密钥生命周期

```bash
# 更新设备 SSH 密钥
olav --agent config "更新设备组 'production-routers' 的 SSH 私钥"

# 验证密钥访问
olav --agent config "使用当前密钥测试所有设备的 SSH 连通性"

# 检查密钥年龄
olav --agent config "显示超过 180 天的 SSH 密钥，标记为轮换"

# 紧急密钥撤销
olav --agent config "由于泄露，撤销设备 R1 的 SSH 密钥"
```

### 密码策略

```bash
# 设置密码要求
olav --agent config "强制执行：最少 12 个字符，必须包括数字+特殊字符"

# 强制用户更改密码
olav --agent config "要求所有用户在 7 天内更改密码"

# 检查凭证强度
olav --agent config "审计所有设备凭证 - 显示弱点"
```

---

## 7️⃣ 与 Config 代理的集成

**Config 代理**是管理所有安全策略和凭证的集中方式。

### 通过 Config 代理进行安全管理

```bash
# 查看所有安全设置
olav --agent config "显示所有安全策略和设置"

# 修改安全策略
olav --agent config "更新语义防火墙阈值至 0.8"
olav --agent config "添加新规则：在所有设备上阻止 'debug all'"

# 管理用户
olav --agent config "创建用户 john.doe，角色=operator"
olav --agent config "将 alice 的角色从 viewer 改为 engineer"
olav --agent config "删除用户 bob(撤销所有访问权限)"

# 管理凭证
olav --agent config "按 90 天政策轮换所有 API 密钥"
olav --agent config "验证所有 SSH 密钥是否可访问"

# 生成安全报告
olav --agent config "生成安全审计报告 - 活跃用户、最近变更、失败登录"
```

### Config 代理安全工作流

**工作流 1：载入新用户**
```bash
olav --agent config "载入新用户 sarah.chen
- 创建账户，角色=engineer
- 生成 API 密钥(90 天有效期)
- 分配到设备范围：region=APAC
- 在 Config 代理审计跟踪中记录"
```

**工作流 2：紧急访问撤销**
```bash
olav --agent config "紧急：撤销用户 david 的所有访问权限
- 立即撤销 API 密钥
- 撤销 SSH 凭证
- 终止所有活跃会话
- 存档此用户的审计日志"
```

**工作流 3：安全合规性审计**
```bash
olav --agent config "每月安全审计
- 列出所有活跃用户及其角色
- 检查已过期/即将过期的凭证
- 回顾上个月的高风险操作
- 生成合规性报告(SOC2)"
```

---

## 8️⃣ 最佳实践和安全建议

### 🛡️ 操作安全

1. **最小权限原则**
   - 为用户分配完成其工作所需的最小角色
   - 使用设备/网络范围限制数据访问
   - 定期审计权限过度授予

2. **密钥轮换**
   - 每 90 天自动轮换 API 密钥
   - 每 180 天轮换 SSH 密钥
   - 如果密钥疑似被泄露，立即进行紧急轮换

3. **多用户隔离**
   - 每个用户在 `~/.olav/` 中有隔离的会话/缓存
   - 全局审计日志集中在 `.olav/logs/` 中
   - 无跨用户数据泄漏

4. **语义防火墙调优**
   - 降低阈值 (0.7) = 更安全但可能阻止合法请求
   - 提高阈值 (0.9) = 减少假正例但可能遗漏风险
   - 定期审查被阻止的请求以寻找假正例

5. **审计日志监控**
   - 每日审查高风险操作
   - 为 BLOCK/CONFIRM 事件设置实时告警
   - 定期存档日志以供合规性使用

### ⚠️ 安全反模式

- ❌ **永远不要在脚本中硬编码凭证** - 使用 Config 代理进行管理
- ❌ **永远不要记录敏感数据** (密码、API 密钥、SSH 密钥)
- ❌ **永远不要跳过确认** CONFIRM 级别的操作
- ❌ **永远不要完全禁用语义防火墙**，即使对于"受信任"用户
- ❌ **永远不要共享 API 密钥** - 每个用户一个密钥
- ❌ **永远不要在没有审计跟踪和批准的情况下覆盖黑名单**

### 🔍 监控和告警

```bash
# 设置实时安全告警
olav --agent config "我们推荐在以下情况下告警：
  - 任何 BLOCK 操作(可能表示攻击尝试)
  - 所有 CONFIRM 操作(高风险变更)
  - 失败的认证(错误的 API 密钥)
  - 异常数据导出(大规模访问模式)
  - 非工作时间访问(工作时间外)"
```

---

## 9️⃣ 配置和管理

### 通过 Config 代理编辑安全策略 (推荐)
```bash
# 所有安全变更应通过 Config 代理进行
olav --agent config "修改安全策略：..."
olav --agent config "将新命令加入黑名单：..."
olav --agent config "更新用户权限：..."
```

### 手动配置 (高级)
```bash
# 直接文件编辑(需要系统管理员访问)
vi .olav/config/security_policies.yaml
vi .olav/config/blacklisted_commands.yaml
vi .olav/config/rbac_matrix.yaml

# 手动编辑后同步更改
uv run python -m olav.tools.sync_security_rules
```

### 验证配置
```bash
# 测试安全规则
olav --agent config "这个操作被允许吗? [操作描述]"

# 验证配置语法
uv run python -m olav.tools.validate_security_config

# 直接测试安全检查逻辑
uv run python -m olav.core.security "delete all configs"
```

---

## 🔟 事件响应

### 安全事件程序

**如果 API 密钥被泄露：**
```bash
olav --agent config "紧急：立即撤销 API 密钥 {key_id}"
olav --agent config "审计：显示所有使用被泄露密钥的操作"
# 终止现有会话，重新生成新密钥
```

**如果账户被泄露：**
```bash
olav --agent config "为用户 john.doe 紧急撤销：
- 撤销所有 API 密钥
- 撤销所有 SSH 凭证
- 终止所有活跃会话
- 标记账户为锁定(待密码重置)"
```

**如果黑名单被更新(紧急)：**
```bash
olav --agent config "这次覆盖黑名单命令 'write memory'：
- 原因：紧急配置必须保存
- 批准人：管理员用户
- 日志记录到 sensitive.log"
```

---

## 📋 安全检查清单

在将 OLAV 部署到生产环境之前：

- [ ] 配置 RBAC 角色和用户矩阵 (admin、user、readonly)
- [ ] 为所有用户生成初始 API 密钥 (启用 90 天轮换)
- [ ] 配置语义防火墙策略 (必要时调整阈值)
- [ ] 填充命令黑名单 (添加设备特定的危险命令)
- [ ] 启用审计日志并设置日志保留策略 (最少 1 年)
- [ ] 为高风险操作设置实时监控告警
- [ ] 测试事件响应程序 (密钥撤销、账户锁定)
- [ ] 记录安全策略并与所有用户共享
- [ ] 计划定期安全审计 (至少每月一次)
