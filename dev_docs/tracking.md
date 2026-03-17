# OLAV 开发进度追踪

**Last Updated:** 2026-03-17
**Tests:** 706 passed, 0 failures
**Version:** v0.11.0

---

## 1. 里程碑总览

| 里程碑 | 状态 | 完成日期 | 主要文档 |
|---|---|---|---|
| P1–P4 Agent Trace 系统 | ✅ 完成 | 2026-03-14 | `agent_traces.md` |
| CLI route_query 接线修复 | ✅ 完成 | 2026-03-15 | `agent_traces.md` P2 行 |
| Agentic 闭环文档（doc 09） | ✅ 完成 | 2026-03-15 | `docs/olav/05_AGENTIC_FEATURES.md` |
| Core Concepts §6 自我进化 | ✅ 完成 | 2026-03-15 | `docs/03_CORE_CONCEPTS.md` |
| **AAA 设计方案** | ✅ 设计完成 | 2026-03-15 | `olav_aaa.md` |
| **企业版功能清单** | ✅ 设计完成 | 2026-03-15 | `ent_features.md` |
| **平台/NetOps 剥离评审收口** | ✅ 完成 | 2026-03-16 | `olav_platform.md`, `api_discovery.md` |
| **设计文档一致性守护测试** | ✅ 完成 | 2026-03-16 | `tests/unit/test_tracking_doc_consistency.py`, `tests/unit/test_design_docs_consistency.py` |
| **平台 CLI 骨架（init/workspace/export）** | ✅ 完成 | 2026-03-16 | `src/olav/cli/commands/init.py`, `src/olav/cli/commands/workspace.py`, `src/olav/cli/commands/export.py` |
| **AAA P0：user_id 填充** | ✅ 完成 | 2026-03-16 | `src/olav/cli/main.py`, `src/olav/api/server.py` |
| **AAA P1：Auth 骨架 + GAP-1 脑济笻除** | ✅ 完成 | 2026-03-16 | `src/olav/core/auth/`, `src/olav/core/migrations/v0_12_users.py`, `src/olav/core/audit_recorder.py` |
| **SchemaMutationService apply/approval 流** | ✅ 完成 | 2026-03-16 | `src/olav/core/schema_mutation_service.py` |
| **`olav init` LLM 连通性检查** | ✅ 完成 | 2026-03-16 | `src/olav/cli/commands/init.py` |
| **export claude-plugin frontmatter 富化** | ✅ 完成 | 2026-03-16 | `src/olav/cli/commands/export.py` |
| **workspace upgrade 真实包源集成** | ✅ 完成 | 2026-03-16 | `src/olav/cli/commands/workspace.py` |
| **AAA P2：Admin CLI（add/list/revoke/rotate-token）** | ✅ 完成 | 2026-03-16 | `src/olav/cli/commands/admin_users.py`, `src/olav/cli/admin.py`, `src/olav/core/audit_recorder.py`, `src/olav/core/config.py` |
| **NetOps onboard CLI（snapshot/sync/inspect 命令集）** | ✅ 完成 | 2026-03-16 | 已迁移至 `olav-netops/scripts/netops_init.py`（Phase-1 完成） |
| **schema_engine Phase 1（classify_field + create_unified_view + tool wrappers）** | ✅ 完成 | 2026-03-16 | `src/olav/core/schema_engine.py`, `.olav/workspace/config/discovery/tools/classify_field.py`, `create_unified_view.py` |
| **Platform P2：agent_registry + MANIFEST.yaml stubs + scaffold_domain_agent + get_domain_prompt** | ✅ 完成 | 2026-03-17 | `src/olav/core/agent_registry.py`, `.olav/workspace/*/MANIFEST.yaml`, `.olav/workspace/config/discovery/tools/scaffold_domain_agent.py`, `src/olav/cli/main.py` |
| **Platform P2 続：workspace status MANIFEST-aware + export claude-plugin MANIFEST enrichment** | ✅ 完成 | 2026-03-17 | `src/olav/cli/commands/workspace.py`, `src/olav/cli/commands/export.py` |
| **1.5 热插拔（HP-1/2/3）+ 最小 RBAC 基线（模型/迁移/workspace 接线）+ Skill 安装控制面（SKI-1/2）** | ✅ 完成 | 2026-03-17 | `src/olav/core/auth/authz.py`, `src/olav/core/migrations/v0_13_rbac.py`, `src/olav/core/agent_registry.py`, `src/olav/cli/commands/workspace.py`, `dev_docs/olav_aaa.md` D6.1 |
| **DC-3 + HP-3 + API-RW-1/2/3/4 收口 Sprint** | ✅ 完成 | 2026-03-17 | `src/olav/cli/main.py`（DC-3）, `src/olav/core/agent_registry.py`（HP-3）, `src/olav/cli/commands/workspace.py`（workspace RBAC 接线）, `src/olav/core/api_operation_policy.py`（API-RW-1/2）, `src/olav/core/api_action_service.py`（API-RW-3/4）, `.olav/workspace/config/discovery/tools/register_api_schema.py`（API-RW-1/2） |
| **AAA 实现 P1（auth 骨架）** | ✅ 完成 | 2026-03-16 | `src/olav/core/auth/`, `src/olav/cli/main.py`, `src/olav/api/server.py`, `.olav/config/api.json` |
| **Slash Command 自动注册（SC-1~SC-5）** | ✅ 完成 | 2026-03-16 | `src/olav/cli/commands/registry.py`, `src/olav/cli/commands/shell_runner.py`, `src/olav/cli/commands/builtin.py`, `.olav/workspace/ops/MANIFEST.yaml`, `olav-netops/pyproject.toml` |
| **AAA 实现 P3（WebUI login）** | ✅ 完成 | 2026-03-16 | `src/olav/core/auth/server_token.py`, `src/olav/api/server.py`, `src/olav/api/static/login.html`, `src/olav/cli/commands/services/web.py` |
| **Platform Phase-0：`domain.duckdb` 命名 + `BaseIngestTable.schema_name` 公开 API** | ✅ 完成 | 2026-03-16 | `src/olav/core/config.py`, `src/olav/platform/ingest_base.py` |
| **Platform 阶段零续（完整）：`olav-netops` 骨架 + `pyproject.toml` netops 依赖隔离 + `ingest_manager` TableRegistry 收口 + `admin.py` CommandRegistry 解耦 + `config.py` NETOPS-ONLY 注释** | ✅ 完成 | 2026-03-16 | `olav-netops/` (pyproject, cli.py, core/tables.py, migrations/v0_12_schema_split.py), `pyproject.toml`, `src/olav/core/ingest_manager.py`, `src/olav/cli/admin.py`, `src/olav/core/config.py`, `src/olav/platform/ingest_base.py` (新增 `TableRegistry.get()`) |
| **TD-8/12/14/18 全部清零：MANIFEST 注入接线 + LanceDB 域前缀约定 + 渐进式披露三层固化** | ✅ 完成 | 2026-03-16 | `src/olav/core/agent_registry.py` (新增 `merge_into_config`), `src/olav/agents/agent.py` (`discover_agents + merge_into_config` 接线), `.olav/workspace/quick/MANIFEST.yaml` (`kind: Agent`), `src/olav/core/schema_engine.py` (`get_domain_collection()`), `.olav/workspace/config/discovery/tools/scaffold_domain_agent.py` (`references/` 三层生成) |
| **Platform Phase-1 物理剖离：`olav-netops init` 迁移 + nornir 从主包移除 + NETOPS-ONLY 注释升级** | ✅ 完成 | 2026-03-16 | `olav-netops/src/olav_netops/cli.py`, `pyproject.toml`, `src/olav/core/config.py`, `src/olav/core/defaults.py` |
| **Platform Phase-1 完成：纯 Python 脚本替代 CLI + command_registry 迁移 + onboard 删除** | ✅ 完成 | 2026-03-16 | `olav-netops/scripts/netops_init.py`, `netops_snapshot.py`, `netops_migrate.py`（新建）；`olav-netops/pyproject.toml` 移除 `[project.scripts]`；`src/olav/cli/main.py` 移除 4 处 onboard 引用；`src/olav/core/command_registry.py` 迁移至 `olav-netops/src/olav_netops/command_registry.py`；`admin.py` + workspace 工具 import 路径更新 |
| **Platform/NetOps 解耦 Phase-0 骨架** | ✅ 完成 | 2026-03-16 | `pyproject.toml` netops optional dep 清空; `src/olav/core/ingest_manager.py` staging_dir 显式注入; `.olav/workspace/{ops,ops/simulator,quick,config}/tools/execute_cli.py` 导入防护 |
| **NetOps onboard E2E 验证完成：ingest 管道修复 + 真实 E2E 测试落地** | ✅ 完成 | 2026-03-16 | 修复 `ensure_schema()` 缺失 UNIQUE 约束（`ingest_base.py`）；修复 migration `CREATE TABLE AS SELECT` 无约束（`v0_12_schema_split.py`）；修复 `sync_tools.py` topology INSERT 目标为不可写 compat view（改为 `netops.topology_links`）；修复 `TopologyLinksTable` schema 与运行时不匹配；重建 compat views；新增 12 项真实 E2E 测试 `tests/integration/test_netops_onboard_e2e.py`（DB 隔离、ingest 成功、幂等性、约束验证、migrate 验证）；测试基线 291 → 303 passed |
| **E2E Bug Fix Sprint：3 个运行时 Bug + 工具全覆盖验证** | ✅ 完成 | 2026-03-16 | **Bug 1**：`audit_recorder.py` `__init__` 并发锁 → try/except 优雅降级（`_conn=None`），所有 `record_*` 方法添加 None guard；**Bug 2**：`ping_device.py` 主机名 → `mgmt_ip` 解析（查 `devices` 表）；**Bug 3**：`web_search` `ddgs` 包安装（`uv add ddgs==9.11.4`）；**traceroute**：Linux 优先 `traceroute`，回退 `tracepath`，双格式 hop 解析器；验证通过：traceroute ✅ port_scan ✅ diff_topology_drift ✅ diff_routing_drift ✅ search_commands ✅ web_search ✅ ping_device(hostname) ✅；pytest 303 passed ✅ |
| **SC-1~SC-5 Slash Command 自动注册** | ✅ 完成 | 2026-03-16 | `src/olav/cli/commands/registry.py`（新建，`SlashCommandSpec` + 三层加载器）；`src/olav/cli/commands/shell_runner.py`（新建，安全 shell 执行 + 审批门）；`src/olav/cli/commands/builtin.py` 接入三层合并注册；`.olav/workspace/ops/MANIFEST.yaml` 新增 `slash_commands:` 块；`olav-netops/pyproject.toml` 新增 `[project.entry-points."olav.slash_commands"]`；`olav-netops/src/olav_netops/cli/builtin.py` 新增 `netops_init_main()`；pytest 303 passed ✅ |
| **api_discovery.md Phase 4+5 完成：`register_api_schema` + `trigger_schema_evolve` + `propose_standard` + SKILL.md 平台化** | ✅ 完成 | 2026-03-16 | `schema_mutation_service.py` 新增 `propose_standard` 分支；`schema_engine.py` `evolve_trigger()` + `_llm_propose_standard_name()` 已落地（Phase 5）；`.olav/workspace/config/discovery/tools/trigger_schema_evolve.py`（新建）；`.olav/workspace/config/discovery/tools/register_api_schema.py`（新建，stdlib-only OpenAPI 3.x 解析器）；`discovery/SKILL.md` 升级至 v3.0.0，去除 NetOps 语言，声明全部 4 个新工具；测试 303 passed ✅ |
| **api_discovery.md Phase 6 设计：OpenAPI 读写分流 + 写操作 HMITL** | ✅ 设计完成 | 2026-03-17 | `dev_docs/api_discovery.md` v0.4 |
| **`olav config evolve` CLI（--list / --approve）** | ✅ 完成 | 2026-03-16 | `src/olav/cli/commands/config_evolve.py`（新建 340 行：`cmd_evolve_list`、`cmd_evolve_approve`、`_write_to_lancedb`、`run_evolve_command`）；`src/olav/cli/main.py` config handler 新增 `evolve` 分发 + 解析器 help 更新；测试 303 passed ✅ |
| **agentic_rector.md PERF-1/PERF-2 收口** | ✅ 完成 | 2026-03-17 | PERF-1：`get_embedder()` 单例复用（`knowledge/__init__.py` + `llm.py` 共享单例避免 ~90MB 重复加载）；PERF-2：`SemanticCache.invalidate_all()` 测试验证 OK；531 passed ✅ |
| **audit_dataset_export.md Phase 1：SFT Chat JSONL 导出** | ✅ 完成 | 2026-03-17 | `src/olav/enterprise/audit_dataset_export.py`（新建 ~620 行：`rebuild_run_timeline`、`NetworkObjectAnonymizer`、`redact_audit_run` 3 层管道、`gate_check`、`audit_to_sft_jsonl`）；`src/olav/enterprise/__init__.py`；`src/olav/cli/main.py`（`log export sft` 子命令）；25 个 TDD 测试全通过；556 passed ✅ |
| **audit_dataset_export.md Phase 2：Tool Trajectory 导出** | ✅ 完成 | 2026-03-17 | `audit_dataset_export.py` 新增 ~350 行：`_compute_dedup_fingerprint`（SHA-256 归一化指纹）、`_build_trajectory_steps`（timeline→trajectory 重建）、`_has_hitl_reject`（HITL 拒绝检测）、`audit_to_tool_trajectory`（完整导出管道含 dedup）；`__init__.py` 新增导出；`main.py` 新增 `log export trajectory` 子命令；20 个 TDD 测试全通过；576 passed ✅ |
| **audit_dataset_export.md Phase 3：Advanced Redaction + ATIF 导出** | ✅ 完成 | 2026-03-17 | `audit_dataset_export.py` 新增 ~200 行：`save_mapping`/`load_mapping`（跨导出映射持久化）、Layer 3 config-block 扩展计数（tool_calls+events）、`_apply_presidio_hook` 接入 `_redact_text`、`_build_atif_spans`+`audit_to_atif`（ATIF trace 导出）；`__init__.py` 新增 `audit_to_atif`+`register_presidio_hook`；`main.py` 新增 `log export atif` 子命令；23 个 TDD 测试全通过；599 passed ✅ |
| **audit_dataset_export.md Phase 4：Quality Scoring + Gate** | ✅ 完成 | 2026-03-17 | `audit_dataset_export.py` 新增 Section 9（~280 行）：`compute_rule_score`（4 维规则评分：completeness/query_specificity/analysis_value/tool_consistency）、`compute_quality_score`（规则+可插拔 LLM 评分）、`quality_gate`（阈值过滤+hard reject）、`register_llm_scorer`（回调注册）、`HARD_REJECT_LABELS`；SFT/Trajectory 导出管道接入评分+过滤+stats；CLI `--min-score` flag；`__init__.py` 新增 5 个公开 API；28 个 TDD 测试全通过；627 passed ✅ |
| **encrypted_dataset_control.md Phase 1-2：Tink AEAD + 加密集成** | ✅ 完成 | 2026-03-17 | `src/olav/enterprise/dataset_encryption.py`（新建 112 行：`EncryptionMode`、`TempFilePolicy`、`build_associated_data()`、`atomic_write()`、`DatasetEncryptor`、`check_encryption_mode()`）；`pyproject.toml` 新增 `tink>=1.14.1`；`src/olav/core/config.py` 新增 `DatasetExportConfig`（7 属性）；`src/olav/cli/main.py` 3 个 export 子命令增加 `--encrypt/--no-encrypt/--key-ref`；33+11 个加密单元+集成测试全通过 |
| **encrypted_dataset_control.md Phase 3：KMS Key Ref 检测** | ✅ 完成 | 2026-03-17 | `dataset_encryption.py` 新增 `is_kms_key_ref()`（4 种 KMS URI 前缀检测：gcp-kms/aws-kms/hcvault/azure-kms）；`load_keyset()` KMS URI 检测→`NotImplementedError`；9 个 TDD 测试全通过 |
| **encrypted_dataset_control.md Phase 4：一次性 Token 控制 + CLI** | ✅ 完成 | 2026-03-17 | `dataset_encryption.py` 新增 `OneTimeTokenManager`（JWT 签发+DuckDB denylist+单次使用+审计日志）；`pyproject.toml` 新增 `PyJWT>=2.8.0`；`src/olav/cli/main.py` 新增 `log export grant-local-train` 子命令（`--export-id`、`--ttl-minutes`）；`__init__.py` 新增 8 个加密/token 公开 API；13 个 TDD 测试全通过；175 passed（audit_dataset_export 全文件）✅ |
#NR|| **Platform §11.2 公开合约：`DomainAgent` Protocol + `BaseDomainAgent` 基类** | ✅ 完成 | 2026-03-16 | `src/olav/platform/extensions.py`（74 行，`@runtime_checkable` Protocol）；`src/olav/platform/agent_base.py`（119 行，默认实现 + `__init_subclass__` 警告）；`src/olav/platform/__init__.py` 更新导出 5 符号；测试 303 passed ✅ |
#QB|| **api_discovery.md §6：`bootstrap_field_classifications.py` LanceDB 种子脚本** | ✅ 完成 | 2026-03-16 | `scripts/bootstrap_field_classifications.py`（26 个标准字段，6 类别：interface/bgp/ospf/routing/device/topology；幂等写入；`--dry-run`/`--verbose`/`--domain`/`--lancedb-path`/`--list-domains` CLI flags；依赖 `get_embedder()` 单例）；测试 303 passed ✅ |

---

## 2. 当前活跃 Backlog

已确认 AAA 基础层、Platform Phase-0 骨架、MANIFEST 发现、workspace 生命周期、
Claude 导出兼容层以及 slash command 自动注册已落地。当前代码状态已经达到：

- **平台可独立运行**：没有 netops 包时，平台主流程可以降级运行。
- **工作区可声明激活**：`.olav/workspace/**/MANIFEST.yaml` 可激活 skill 与 slash command。
- **域能力仍依赖已安装包**：`domain_prompt`、`reload_hook`、`config_commands`、`ingest_tables` 仍走 entry point。
- **RBAC 已有基线模型，但运行时接线仍有限**：当前显式接线覆盖 `workspace` 生命周期和 `ApiActionService` 的 submit/approve，尚未统一覆盖 `config evolve`、`log export grant-local-train` 等控制面命令。
- **OpenAPI 写操作已支持 stage/approve 基线**：`ApiActionService` 已落地，但 `API-RW-5` 所要求的独立 `read / submit-write / approve-write` 权限层尚未完成。

因此，当前状态不是"文件级热插拔"，而是**工作区声明 + 包级扩展**。新的目标定义为：
**1.5 级热插拔 = 声明级即插即用 + 依赖可校验 + 能力可降级**。

### 当前活跃事项（2026-03-17）

| 编号 | 内容 | 优先级 | 说明 |
|---|---|---|---|
| split_rbac_runtime_alignment | 校正文档与实现：RBAC 运行时 SSOT 仍是 `DEFAULT_PERMISSIONS`，`role_skill_permissions` 仅完成 migration/seed | 🔴 P0 | 需避免继续把 DB 持久化和 skill 粒度接线写成“已完整落地” |
| split_config_control_authz | 为 `olav config evolve` 等控制面命令补统一 `require_permission()` 接口 | 🔴 P0 | 当前 `config evolve --approve` 仍未接入 admin 鉴权 |
| split_api_rw_5 | 完成 API-RW-5：引入独立 `read / submit-write / approve-write` 权限语义 | 🟡 P1 | 当前仅通过 `mutate` / `admin` 映射 write submit/approve |
| split_core_ent_detangle | 为三仓库拆分做前置收口：移除 core 对 enterprise 的硬依赖 | 🔴 P0 | 包括 `src/olav/cli/main.py` 直接 import 与 `pyproject.toml` 中 `tink` / `PyJWT` |
| split_netops_workspace_extract | 规划并迁出 netops workspace 资产 | 🔴 P0 | `.olav/workspace/ops`、`config/sync`、`config/learner` 仍在 monorepo 根内 |
| split_gitea_publish_plan | 按目标远端准备三仓库首发顺序与目录归属 | 🟡 P1 | `olav-core` → `olav-netops` → `olav-ent` |

---

## 3. 企业功能待办（Enterprise Backlog）

> 完整功能列表见 `ent_features.md`。以下为路线图视图。

| 编号 | 内容 | 触发条件 |
|---|---|---|
| ent_sso_providers | LDAP / AD / OIDC SSO | 企业客户要求 AD 集成 |
| ent_auth_rate_limit | 速率限制 + 暴力破解保护 | 多团队 / 互联网暴露场景 |
| ent_admin_dual_control | Admin 强制轮换 + 双人确认 | ISO 27001 A.9 合规审计 |
| ent_field_redaction | 高级脱敏引擎（字段级+哈希映射） | 合规要求去标识化 |
| ent_sft_export / ent_trajectory_export / ent_atif_export | SFT / Trajectory / Harbor 导出 | 企业内部模型微调需求 |
| ent_audit_hash_chain | 审计哈希链（防篡改） | SOC2 Type II / NIST AU-9 |
| ent_audit_archive | 长期保留 + S3/GCS 归档 | ISO 27001 A.12.4.1 |

---

## 4. 已知技术债务

| 编号 | 描述 | 严重程度 | 文档引用 |
|---|---|---|---|
| TD-27 | RBAC 文档与运行时 source-of-truth 不一致：代码仍以 `DEFAULT_PERMISSIONS` 为准，`role_skill_permissions` 未参与运行时判权 | 🔴 高 | `olav_aaa.md` D6.1 |
| TD-28 | `config evolve --approve` 是控制面写路径，但尚未接入 admin 鉴权 | 🔴 高 | `api_discovery.md` §4.7 |
| TD-29 | enterprise 仍嵌入 core：`src/olav/cli/main.py` 直接 import `olav.enterprise.*`，无法独立发 `olav-ent` | 🔴 高 | `olav_platform.md` §10.1 |
| TD-30 | `pyproject.toml` 仍把 `tink` / `PyJWT` 放在主包依赖中，core 不能独立发布 | 🔴 高 | `olav_platform.md` §10.1 |
| TD-31 | netops workspace 资产仍位于 monorepo 根 `.olav/workspace/`，尚未形成 `olav-netops` 自有源码分发边界 | 🟡 中 | `olav_platform.md` §10.1 |
| TD-32 | 文档索引仍引用不存在的 `docs/cn/09_AGENTIC_FEATURES.md`，中英文文档树尚未完全收口 | 🟡 中 | `docs/` |

补充：`api_discovery.md` 已在 2026-03-17 升级到 v0.4，新增 OpenAPI 读写分流、写操作 HMITL、`ApiActionService` 与 Phase 6 任务定义。其中 API-RW-1/2/3/4 已实现；`API-RW-5`（独立 read / submit-write / approve-write 权限层）仍未完成，不能再按“RBAC 三层收口已完成”表述。

---

## 5. Platform 解耦 Sprint

当前进入 **Repo 目录迁移 Sprint**，目标是把 monorepo 拆为三个可独立发布的仓库，并先完成 core/ent 解耦前置条件。

### 5.1 目标仓库

| 仓库 | 目标远端 |
|---|---|
| `olav-core` | `http://192.168.100.50:3000/admin/olav-core.git` |
| `olav-netops` | `http://192.168.100.50:3000/admin/olav-netops.git` |
| `olav-ent` | `http://192.168.100.50:3000/admin/olav-ent.git` |

### 5.2 当前 Sprint 任务

| 编号 | 任务 | 优先级 |
|---|---|---|
| CORE-1 | 从 `olav-core` 剥离 enterprise 直接 import，改为 optional bridge / entry-point 发现 | 🔴 P0 |
| CORE-2 | 将主包中的 enterprise 依赖移出 `pyproject.toml`，改为 optional extra 或 `olav-ent` 自带依赖 | 🔴 P0 |
| NETOPS-1 | 明确 `olav-netops` 应托管的 workspace 资产：`.olav/workspace/ops`、`config/sync`、`config/learner` | 🔴 P0 |
| ENT-1 | 为 `olav-ent` 建立独立包边界：`src/olav/enterprise/` + 企业设计文档 + 发布元数据 | 🟡 P1 |
| DOCS-1 | `docs/olav/**` 归属 `olav-core` 仓库；`docs/netops/**` 归属 `olav-netops` 仓库；根 `docs/{01_README.md,cn/}` 作为总索引 | 🟡 P1 |
| REL-1 | 完成三仓库首发顺序、目录映射、远端初始化与 tag 规则 | 🟡 P1 |

---

## 6. 设计文档索引

| 文档 | 内容 | 状态 |
|---|---|---|
| `dev_docs/olav_aaa.md` | AAA 全套设计（Auth/Authz/Accounting 分层、切割矩阵、GAP 分析） | ✅ 完成 |
| `dev_docs/ent_features.md` | 企业版功能清单（AAA 企业层 + 审计企业层） | ✅ 完成 |
| `dev_docs/log_rector.md` | 审计事件系统改造方案 | ✅ 完成 |
| `dev_docs/agent_traces.md` | Agent Trace 系统（融合进 audit.duckdb） | ✅ 完成 |
| `dev_docs/plugin_rector.md` | 插件框架设计（开源/企业 entry points 分离） | ✅ 完成 |
| `dev_docs/olav_platform.md` | 平台/域拆分方案（三包架构、域 CLI 独立二进制、声明式注册、Claude skill 兼容层、Domain Extension Contract、数据库 Schema 隔离、生命周期闭环、三仓库发布计划） | ✅ v0.7 |
| `dev_docs/api_discovery.md` | 语义字段分类引擎与 OpenAPI 控制面设计（含 TextFSM 离线路径、schema mutation service、OpenAPI 读写分流、写操作 HMITL） | ✅ v0.4 |
| `dev_docs/slash_command_auto_registration.md` | Slash command 自动注册设计（MANIFEST + entry point + python/sh 执行边界） | ✅ v0.1 |
| `dev_docs/agentic_rector.md` | Agentic 自进化系统 Bug 修复 + 性能优化（7 项全部完成） | ✅ 完成 |
| `dev_docs/audit_dataset_export.md` | 审计数据训练导出管道（SFT/Trajectory/ATIF，4 个 Phase） | ✅ 完成 |
| `dev_docs/encrypted_dataset_control.md` | Tink AEAD 加密层（数据集导出加密控制） | ✅ 完成 |
| `docs/olav/05_AGENTIC_FEATURES.md` | Agentic 自进化特性（EN） | ✅ 完成 |
| `docs/cn/09_AGENTIC_FEATURES.md` | Agentic 自进化特性（CN） | ⚠️ 待迁移（原路径不存在） |
