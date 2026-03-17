# 企业版功能清单（BSL Commercial Tier）

**Updated:** 2026-03-16  
**对应设计文档：** `olav_aaa.md`、`log_rector.md`、`plugin_rector.md`、`audit_dataset_export.md`、`encrypted_dataset_control.md`

> **分界原则**：安全基线（基础认证、凭据脱敏、安全 Cookie）属于**开源版，必须实现**；  
> 合规增强（SSO、审计哈希链、长期保留、训练数据导出、高级速率限制）属于**企业插件**。  
> 企业插件通过 Python entry points 发现，不在开源目录中（见 `plugin_rector.md`）。  
> 参照：HashiCorp Vault / Teleport / GitLab 同一切割模式。

> **RBAC 分界补充**：
> - **默认内置 / 开源基线**：固定三角色（admin/user/readonly）+ 默认 skill 权限矩阵 + admin-only workspace lifecycle
> - **企业增强**：可编辑 RBAC 策略、用户组、审批流、策略版本化、UI/CLI 管理工具
> - 因此，企业版卖点不是“有没有 RBAC”，而是“能否灵活管理和审计 RBAC”

> **命名规则**：从本版开始，所有企业功能统一使用 `ent_` 前缀作为功能标识；旧的 `E-A1`、`E-4.5` 等编号仅作为历史别名保留在注释中，不再作为新设计主标识。

---

### AAA 企业层（auth_rector.md 对应项）

#### ent_sso_providers（原 E-A1） 企业 SSO 集成（olav_aaa.md §3 Tier 2）

- [ ] `LDAPAuthProvider`：ldap3 包激活，group → role 映射
- [ ] `ActiveDirectoryAuthProvider`：msal 包，AD group 到 OLAV 角色映射
- [ ] `OIDCAuthProvider`：authlib 包，JWT 验证 + claims 映射
- [ ] `api.json` auth.mode = "ldap" / "ad" / "oidc" 切换，无需改代码

#### ent_auth_rate_limit（原 E-A2） 高级速率限制与暴力破解保护（olav_aaa.md GAP-2/3）

- [ ] 连续失败 ≥ 5 次 → 10 分钟 IP 锁定（内存 + DuckDB 持久化）
- [ ] `auth_rate_limited` 事件写入 audit.duckdb
- [ ] `olav admin list-blocked-ips` + `olav admin unblock <ip>`

#### ent_admin_dual_control（原 E-A3） Admin 强制轮换与双人确认（olav_aaa.md GAP-3）

- [ ] Admin token 默认 90 天 `expires_at`，到期前 7 天 CLI 警告
- [ ] `olav admin rotate-token`
- [ ] Admin 操作（add-user/revoke）记录独立 `admin_action` 事件，含操作者身份
- [ ] 两人确认（Two-Person Integrity）标志位，高危操作可选启用

#### ent_rbac_policy_management（新增） 企业 RBAC 策略管理（olav_aaa.md D6 / §7.2）

- [ ] `admin rbac list/grant/revoke` CLI
- [ ] 用户组 / 组成员 / 组到 skill 权限映射
- [ ] RBAC 策略版本化与回滚
- [ ] 高危授权变更审批流 / 双人确认
- [ ] WebUI 权限矩阵管理页
- [ ] 所有 RBAC 变更写入独立 `admin_action` / `rbac_change` 审计事件

---

### 审计与日志企业层（log_rector.md 对应项）

#### ent_field_redaction（原 E-1） 字段级脱敏引擎（log_rector.md §7.2–7.5）

- [ ] 高风险字段名规则（password / token / api_key / community 等）
- [ ] IP/hostname/username 稳定哈希映射
- [ ] 设备配置块级替换规则
- [ ] 可配置白名单与保留策略
- [ ] `redaction` 字段元数据写入（`applied`, `policy_version`, `fields_redacted`）
- [ ] 脱敏后再导出门控

#### ent_sft_export（原 E-2） SFT Chat JSONL 导出（log_rector.md §9.2）

- [ ] `audit_to_sft_jsonl()` 函数
- [ ] 从 `audit_runs` + `audit_messages` 派生规范主格式 `sft.jsonl`
- [ ] 过滤失败 run / 高风险操作

#### ent_trajectory_export（原 E-3） Tool-use Trajectory JSONL 导出（log_rector.md §9.2）

- [ ] `audit_to_tool_trajectory()` 函数
- [ ] 从 `audit_events` 重建 `instruction → reasoning → tool_call → tool_result → final` 轨迹，产出规范主格式 `trajectory.jsonl`
- [ ] 脱敏后再导出

#### ent_atif_export（原 E-4） ATIF / Harbor 风格轨迹导出（log_rector.md §9.2）

- [ ] 产出可选分析格式 `atif.jsonl`
- [ ] 对接 LangSmith 或内部分析工具
- [ ] `_legacy_archived/memory-lancedb-pro/` 中已存参考实现，待整合

#### ent_dataset_export_encryption（原 E-4.5） 训练集导出加密控制（encrypted_dataset_control.md）

- [ ] 使用 `Google Tink` 作为企业版训练集导出加密库
- [ ] 增加 `dataset_export.encryption_mode = disabled | optional | required`
- [ ] `dev/test` 允许明文导出，`prod` 强制加密
- [ ] 对规范主格式和训练派生格式统一产出 `.enc` 文件
- [ ] 统一使用带 `encryption` 对象的 `manifest.json`
- [ ] `required` 模式下禁止 `--no-encrypt`
- [ ] 预留 `key_ref` 以对接 KMS / Vault

#### ent_local_train_one_time_token（原 E-4.6） 可选本地训练一次性 token 控制（encrypted_dataset_control.md）

- [ ] 增加 `dataset_export.local_train_access_mode = none | one_time_token | managed_only`
- [ ] 支持一次性 token 签发、短 TTL、单次使用、绑定 `export_id`
- [ ] 记录 token 签发和使用审计
- [ ] 明确 `one_time_token` 仅提高访问门槛，不作为 DRM 能力宣传
- [ ] 对“尽量不让客户自己训练”的场景，优先提供 `managed_only`

#### ent_audit_hash_chain（原 E-5） 防篡改哈希链（log_rector.md §8.5）

- [ ] `audit_events` 表增加 `prev_event_hash` + `event_hash` 列
- [ ] 写入时计算 SHA-256 链式签名
- [ ] 验证工具 `olav log verify --run <run_id>`

#### ent_audit_archive（原 E-6） 长期保留与归档（log_rector.md §8.4，olav_aaa.md GAP-5）

- [ ] 可配置保留策略（`api.json` `audit.retention_days`，推荐 365 天）
- [ ] 归档到外部存储（S3 / GCS），导出格式 Parquet
- [ ] `olav log archive --before <date>`
- [ ] 开源版默认 24h 查询窗口，超出部分自动压缩不删除

---

## 开源版 vs 企业版快速参照

| 功能 | 开源 | 企业 |
|---|---|---|
| OS Identity / Token auth | ✅ | — |
| 三角色（admin/user/readonly） | ✅ | — |
| 默认 skill 粒度 RBAC 矩阵 | ✅ | — |
| admin-only workspace lifecycle | ✅ | — |
| 命令黑名单 | ✅ | — |
| GAP-1 凭据脱敏（audit_messages） | ✅ 必须 | — |
| GAP-4 安全 Cookie 标志 | ✅ 必须 | — |
| 24h 审计窗口 + `olav log` | ✅ | — |
| RBAC 策略编辑 / 用户组 / 审批（ent_rbac_policy_management） | — | ✅ |
| LDAP / AD / OIDC（ent_sso_providers） | — | ✅ |
| 速率限制 / 暴力破解锁定（ent_auth_rate_limit） | — | ✅ |
| Admin 轮换 + 双人确认（ent_admin_dual_control） | — | ✅ |
| 审计哈希链（ent_audit_hash_chain） | — | ✅ |
| 长期保留 + 归档（ent_audit_archive） | — | ✅ |
| 高级脱敏引擎（ent_field_redaction） | — | ✅ |
| SFT / Trajectory / ATIF 导出（ent_sft_export / ent_trajectory_export / ent_atif_export） | — | ✅ |
| 训练集导出加密控制（ent_dataset_export_encryption） | — | ✅ |
| 本地训练一次性 token 控制（ent_local_train_one_time_token） | — | ✅ |
