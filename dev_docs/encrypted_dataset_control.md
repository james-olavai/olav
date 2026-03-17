# OLAV 训练集导出加密控制设计（Tink 最小方案）

更新日期: 2026-03-16  
状态: 方案设计，未实施  
范围: 企业版训练集导出加密、开发测试阶段明文绕过、生产阶段强制加密、可选本地训练一次性 token 模式

---

## 1. 目标

本设计只解决一个非常具体的问题：

1. 企业版训练集导出默认必须加密
2. 直接使用成熟库 `Google Tink`
3. 开发测试阶段允许不加密，降低联调成本
4. 生产阶段强制加密，避免误导出明文训练集
5. 尽量少引入自定义密码学协议
6. 明确去重、打分、导出、加密四个阶段的边界

本设计**不**解决以下问题：

1. 完整 DRM 或“绝对防止用户训练”
2. 托管训练平台架构
3. 复杂双接收者恢复密钥体系
4. 客户端环境中的反调试或反内存抓取

必须明确：

- 一次性 token 只能提高本地训练的访问门槛
- 不能从根本上防止用户在本地环境提取明文样本
- 去重和质量打分属于**加密前的数据治理阶段**，不是加密阶段的一部分

---

## 2. 设计结论

本方案不自研加密格式，直接使用：

- `Google Tink`
- `AEAD` 原语
- 可选 KMS 包装主密钥

原则上分三种环境：

1. **dev**：允许明文导出
2. **test/staging**：默认允许明文，但可切换到加密模式做联调
3. **prod**：强制加密，不允许明文导出

这意味着：

- 开发测试阶段不为“先跑通”增加过重负担
- 生产阶段不依赖开发者自觉，直接由配置和代码门控强制执行
- 去重与质量打分可以独立演进，不应被绑死在具体加密实现里

如果企业客户有“允许本地训练，但要有访问控制”的诉求，可再启用：

- `dataset_export.local_train_access_mode`

可选值：

- `none`
- `one_time_token`
- `managed_only`

---

## 3. 为什么直接选 Tink

选择 `Google Tink` 的原因：

1. 高层 API，误用空间比底层 `cryptography` 小
2. 适合企业产品使用，语义清晰
3. 支持 AEAD，能同时保证机密性和完整性
4. 容易和 KMS 思路对接
5. 不需要自己设计 nonce、tag、文件头格式

本设计明确不建议第一版使用：

- 手写 `AES-GCM` 分块协议
- 自定义密钥封装格式
- 自定义二进制 header

---

## 4. 环境分级策略

### 4.1 配置目标

建议增加统一配置项：

```text
dataset_export.encryption_mode
```

以及可选配置项：

```text
dataset_export.local_train_access_mode
```

可选值：

- `disabled`
- `optional`
- `required`

推荐环境映射：

| 环境 | encryption_mode | 含义 |
|---|---|---|
| `dev` | `disabled` | 明文导出，便于调试 |
| `test` | `optional` | 默认可明文，可切加密验证 |
| `staging` | `optional` | 上线前联调，推荐开启加密 |
| `prod` | `required` | 强制加密，不允许明文导出 |

### 4.2 行为约束

#### `disabled`

- 直接输出 `sft.jsonl` / `trajectory.jsonl`
- 不生成密文文件
- `manifest.json` 必须显式标注 `encryption.applied = false`
- 只能用于 `dev` / `test`

#### `optional`

- 允许通过参数切换：
  - `--encrypt`
  - `--no-encrypt`
- 默认值由环境配置决定
- 用于联调和回归测试

#### `required`

- 任何导出都必须加密
- 禁止 `--no-encrypt`
- 若未加载 Tink keyset 或 KMS 配置，导出直接失败

### 4.3 本地训练访问模式

#### `none`

- 不支持本地训练解密
- 用户只能下载密文或发起托管训练

#### `one_time_token`

- 允许本地训练时申请一次性解密 token
- token 必须短时有效、单次使用、绑定 `export_id`
- token 的作用是“增加访问控制”，不是“阻止明文被提取”

#### `managed_only`

- 只允许托管训练
- 不提供本地训练解密能力
- 对“防止用户自己训练”最有效

### 4.5 推荐配置结构

建议不要把训练集导出控制拆散到多个无关配置块。  
第一版可统一收敛到 `dataset_export` 下：

```json
{
  "dataset_export": {
    "encryption_mode": "required",
    "local_train_access_mode": "managed_only",
    "key_ref": "dataset-export-key-v1",
    "temp_file_policy": "delete_on_success",
    "allow_plaintext_stats": true,
    "allow_plaintext_rejected_runs": true,
    "associated_data_version": "v1"
  }
}
```

字段建议：

- `encryption_mode`
  `disabled | optional | required`

- `local_train_access_mode`
  `none | one_time_token | managed_only`

- `key_ref`
  当前环境默认使用的密钥引用

- `temp_file_policy`
  控制导出过程中明文临时文件如何处理

- `allow_plaintext_stats`
  是否允许 `stats.json` 明文保留

- `allow_plaintext_rejected_runs`
  是否允许 `rejected_runs.json` 明文保留

- `associated_data_version`
  用于 future-proof AEAD associated data 拼接格式

其中 `temp_file_policy` 第一版建议支持：

- `memory_preferred`
  优先在内存中构造样本，只有必要时才落临时文件

- `delete_on_success`
  允许临时明文文件，但导出成功后立即删除

- `keep_for_debug`
  仅限 `dev/test`，允许保留中间明文用于排查

### 4.4 与导出治理的边界

本设计需要和 `audit_dataset_export.md` 的治理流程保持一致。  
职责边界应明确如下：

#### 导出治理层负责

- run timeline 重建
- 脱敏
- gate checks
- 数据库级去重
- 规则分 / LLM 分质量打分
- 构造 `sft.jsonl` / `trajectory.jsonl` / 派生格式

#### 加密控制层负责

- 判断当前环境是否允许明文导出
- 对最终导出文件执行 AEAD 加密
- 记录加密元数据和密钥引用
- 控制本地训练解密访问模式

因此顺序必须固定为：

```text
redact -> gate -> dedup -> score -> build dataset -> encrypt
```

而不是：

```text
encrypt -> dedup -> score
```

原因：

1. 去重和打分需要读取样本内容，天然发生在加密前
2. 加密后的 `.enc` 文件不应再被拿来做数据治理
3. 把治理和加密解耦，才能独立替换打分策略或加密实现

---

## 5. 最小数据流

### 5.1 开发测试阶段

```text
audit.duckdb
  -> redact
  -> dedup
  -> score
  -> build dataset
  -> write sft.jsonl / trajectory.jsonl
```

### 5.2 生产阶段

```text
audit.duckdb
  -> redact
  -> dedup
  -> score
  -> build dataset bytes
  -> Tink AEAD encrypt
  -> write *.enc + manifest.json
```

### 5.3 中间产物约束

为了避免“虽然最终导出了密文，但中间过程到处是明文”的问题，建议增加明确约束。

#### `dev` / `test`

- 允许落盘明文 JSONL
- 允许输出可人工检查的 `stats.json`
- 允许保留调试期中间文件，但应限制在工作目录内

#### `staging`

- 默认不建议长期保留中间明文文件
- 若为了联调保留，应在任务结束后自动清理
- 推荐把中间样本构造保持在内存或临时目录中

#### `prod`

- 最终训练样本文件必须只以 `.enc` 形式落盘
- 不应长期保留去重后、打分后的明文 JSONL 成品
- 如需临时明文中间文件，应使用临时目录并在导出成功后立即删除
- 日志中不得打印样本正文、LLM 打分原文、解密后的样本内容

### 5.4 导出状态机

建议把一次导出任务明确建模为有限状态机，避免实现时散落布尔标记。

推荐状态：

```text
created
  -> building
  -> encrypting
  -> finalized
  -> failed
```

状态语义：

- `created`
  已分配 `export_id`，目录和 manifest 骨架已建立

- `building`
  正在做脱敏、去重、打分、样本构造

- `encrypting`
  明文样本已经生成，正在写 `.enc` 文件

- `finalized`
  所有目标文件、统计文件、manifest 均已完成并落盘

- `failed`
  导出任务失败，manifest 中应保留失败原因和失败阶段

建议 `manifest.json` 增加：

```json
{
  "status": "finalized",
  "failed_stage": null,
  "failure_reason": null
}
```

### 5.4 不追求的事情

本方案第一版不要求：

- 全程流式 secretstream
- 内存零拷贝
- 客户端不可提取明文

尤其需要强调：

- 若训练发生在用户控制的本地机器上，明文最终仍可能被提取
- 一次性 token 不能被当作 DRM 或防复制机制宣传

第一版目标很务实：

- dev/test 易用
- prod 默认安全
- 代码简单

---

## 6. 导出文件格式

### 6.1 明文模式

开发测试阶段输出：

```text
exports/audit_datasets/<export_id>/
├── sft.jsonl
├── trajectory.jsonl
├── atif.jsonl
├── unsloth_chat.jsonl
├── unsloth_toolcall.jsonl
├── rejected_runs.json
├── stats.json
└── manifest.json
```

说明：

- `sft.jsonl` / `trajectory.jsonl` 是长期保留主格式
- `atif.jsonl` 是可选分析格式
- `unsloth_chat.jsonl` / `unsloth_toolcall.jsonl` 是训练派生格式
- 默认至少产出主格式，派生格式按导出选项生成

### 6.2 加密模式

生产阶段输出：

```text
exports/audit_datasets/<export_id>/
├── sft.jsonl.enc
├── trajectory.jsonl.enc
├── atif.jsonl.enc
├── unsloth_chat.jsonl.enc
├── unsloth_toolcall.jsonl.enc
├── rejected_runs.json
├── stats.json
└── manifest.json
```

注意：

- `rejected_runs.json` 和 `stats.json` 可以明文保留，因为它们不应包含训练样本正文
- 如果后续发现统计元数据也敏感，可再整体加密
- 若某次导出未生成 `atif` 或 `unsloth` 派生格式，则对应 `.enc` 文件也不会存在

补充约束：

- `stats.json` 可以记录去重和评分统计，但不应包含样本正文
- `rejected_runs.json` 默认只保留 `run_id`、拒绝原因、策略版本，不保留完整消息正文
- 若企业客户要求更严格，可追加 `stats.json.enc` / `rejected_runs.json.enc` 模式，但不作为第一版默认要求

### 6.3 文件生命周期与原子写入

为了避免导出半成品暴露给用户或下游训练任务，建议所有目标文件都走“临时名 -> fsync -> rename”流程。

#### 推荐文件生命周期

以 `sft.jsonl.enc` 为例：

```text
sft.jsonl.enc.tmp
  -> fsync
  -> rename to sft.jsonl.enc
```

明文模式下同理：

```text
sft.jsonl.tmp
  -> fsync
  -> rename to sft.jsonl
```

推荐规则：

1. `manifest.json` 最后写
2. 只有当所有目标文件成功 rename 后，`status` 才能从 `encrypting` 进入 `finalized`
3. 若中途失败，保留 `manifest.json` 说明失败阶段，但不应留下伪装成成品的正式文件名

#### 临时目录建议

建议使用：

```text
exports/audit_datasets/<export_id>/.tmp/
```

优点：

- 与最终成品同分区，rename 原子化更容易成立
- 失败时清理范围明确
- 不污染其他导出任务目录

### 6.3 `manifest.json`

建议结构：

```json
{
  "export_id": "audit-export-20260316-180000",
  "formats": ["sft", "trajectory"],
  "redaction_policy": "audit-redaction-v1",
  "dedup_strategy": "exact_v1",
  "scoring_policy": "dataset-score-v1",
  "encryption": {
    "applied": true,
    "mode": "required",
    "provider": "tink",
    "primitive": "aead",
    "key_ref": "dataset-export-key-v1"
  }
}
```

开发测试阶段示例：

```json
{
  "export_id": "audit-export-20260316-180000",
  "formats": ["sft", "trajectory"],
  "redaction_policy": "audit-redaction-v1",
  "dedup_strategy": "exact_v1",
  "scoring_policy": "dataset-score-v1",
  "encryption": {
    "applied": false,
    "mode": "disabled",
    "provider": null,
    "primitive": null,
    "key_ref": null
  }
}
```

字段命名约束：

- 一律使用嵌套对象 `encryption.applied`
- 不再使用 `encryption_applied` 这类平铺字段
- `key_ref` 是统一字段名，不再使用 `key_name` / `kms_key` 等别名
- `dedup_strategy` / `scoring_policy` 应作为顶层治理字段保留，不塞进 `encryption` 对象

### 6.4 `stats.json` 最低字段建议

为与导出治理设计保持一致，建议 `stats.json` 至少包含：

```json
{
  "runs_scanned": 120,
  "runs_after_filter": 96,
  "samples_before_dedup": 140,
  "samples_after_dedup": 101,
  "samples_scored": 101,
  "samples_exported": 84,
  "dedup_strategy": "exact_v1",
  "scoring_policy": "dataset-score-v1",
  "avg_rule_score": 0.82,
  "avg_quality_score": 0.79
}
```

要求：

- 只保留统计信息，不保留样本正文
- 不记录可直接还原训练样本的明文片段
- 若包含 `llm_reason` 一类文本解释，默认写入内部临时报告，不进入 `stats.json`

### 6.5 `rejected_runs.json` 最低字段建议

建议第一版结构：

```json
[
  {
    "run_id": "uuid",
    "reason": "redaction_failed",
    "stage": "gate",
    "policy_version": "audit-redaction-v1"
  }
]
```

不要默认放入：

- 原始 user prompt
- assistant 全量输出
- tool result 正文
- LLM 打分解释全文

---

## 7. Tink 实现方式

### 7.1 原语选择

第一版直接使用 Tink 的 `AEAD`。

原因：

- 适合文件或字节块加密
- 简单稳定
- 自带认证标签
- 足够满足训练集文件加密需求

第一版不需要引入更复杂的：

- Streaming AEAD
- Hybrid Encryption
- MAC-only

### 7.2 最小实现模型

伪代码：

```python
import tink
from tink import aead

aead.register()

handle = tink.read_keyset_handle(...)
primitive = handle.primitive(aead.Aead)

ciphertext = primitive.encrypt(dataset_bytes, associated_data)
plaintext = primitive.decrypt(ciphertext, associated_data)
```

其中：

- `dataset_bytes` 是整个 JSONL 文件内容
- `associated_data` 建议绑定 `export_id`、格式名、版本号、治理策略版本

例如：

```python
associated_data = b"audit-export-20260316-180000:sft:v1:exact_v1:dataset-score-v1"
```

这样可以防止文件被替换到错误上下文中解密。

建议最少绑定这些字段：

- `export_id`
- `format`
- `dataset_schema_version`
- `dedup_strategy`
- `scoring_policy`

这样做的意义是：

- 防止不同治理策略下的文件被错误混用
- 防止同名格式文件在错误上下文里被解密
- 让解密侧能验证“这份密文对应的是哪套样本治理规则”

### 7.3 keyset 管理

第一版建议两种模式：

#### A. 开发模式

- 本地 keyset 文件
- 路径示例：`~/.olav/keys/dataset_export_tink.json`
- 仅用于开发测试

#### B. 生产模式

- 由 KMS/Vault 保护的 keyset
- 应避免把可直接解密的 keyset 明文放在仓库或容器镜像里

本设计不强制第一版立刻上 KMS，但生产配置必须预留 `key_ref` 概念。

### 7.4 密文文件格式约束

为了保持最小复杂度，第一版不自定义额外文件头。  
`.enc` 文件内容就是 Tink 返回的密文字节序列。

这意味着：

- 文件外部元数据全部放在 `manifest.json`
- 不在 `.enc` 文件中重复嵌入 JSON header
- 解密时必须同时依赖 `manifest.json` 和调用侧传入的 associated data 规则

好处：

1. 实现简单
2. 不需要维护自定义封装格式
3. 后续若更换 provider，迁移点更清晰

代价：

- `.enc` 文件本身不自描述
- 调用方必须保留同目录 `manifest.json`

因此建议：

- 把 `manifest.json` 视为导出对象的一部分
- 不支持只拷贝单个 `.enc` 文件而丢失 manifest 的工作流

---

## 8. CLI 与接口约束

### 8.1 CLI

建议接口：

```text
olav log export sft --hours 24 --output exports/audit_datasets/...
olav log export trajectory --hours 24 --output exports/audit_datasets/...
```

加密相关参数：

```text
--encrypt
--no-encrypt
--key-ref <name>
```

治理相关参数建议继续保留在导出层，而不是混进加密层，例如：

```text
--dedup-strategy <name>
--min-rule-score <float>
--enable-llm-score
--min-quality-score <float>
```

这些参数控制候选样本治理，最终结果再由加密层决定是否输出 `.enc`。

### 8.2 内部接口分层

建议内部实现至少拆成三层接口：

#### A. 导出治理层

负责返回内存中的样本对象或明文字节：

```python
build_dataset_artifacts(...) -> DatasetArtifacts
```

#### B. 加密层

负责把单个格式文件字节加密并写出：

```python
encrypt_dataset_bytes(bytes, associated_data, key_ref) -> bytes
```

#### C. 编排层

负责根据环境和配置决定：

- 是否允许明文
- 是否要写 `.enc`
- 是否删除临时文件
- 是否允许本地训练 token

这样实现时可以避免把业务判断塞进 Tink 调用函数里。

### 8.3 参数行为

#### 当 `encryption_mode = disabled`

- `--encrypt` 可选支持
- `--no-encrypt` 默认成立

#### 当 `encryption_mode = optional`

- `--encrypt` 和 `--no-encrypt` 都允许
- 未显式指定时走环境默认值

#### 当 `encryption_mode = required`

- `--encrypt` 可省略，因为默认强制加密
- `--no-encrypt` 必须报错

### 8.4 本地训练一次性 token 模式

建议接口：

```text
olav log export grant-local-train --export-id <id> --ttl-minutes 10
```

返回结构建议：

```json
{
  "export_id": "audit-export-20260316-180000",
  "access_mode": "one_time_token",
  "token": "opaque-single-use-token",
  "expires_at": "2026-03-16T18:10:00Z"
}
```

#### token 约束

一次性 token 至少要满足：

1. 绑定单个 `export_id`
2. 单次使用
3. 短 TTL，例如 5 到 15 分钟
4. 审计所有签发和使用事件
5. 最好绑定调用用户和训练任务 ID

#### 最小交互模型

```text
client requests one-time token
  -> server validates entitlement
  -> server issues token
  -> local trainer presents token once
  -> server allows one decrypt / one download / one stream session
  -> token invalidated
```

#### 风险说明

这个模式只能做到：

- 限制谁能解密
- 限制何时能解密
- 限制解密次数
- 提高未授权复制成本

不能做到：

- 防止已授权用户提取本地明文
- 防止用户修改本地 trainer 代码保存样本

因此：

- 若企业诉求是“默认受控本地训练”，可用 `one_time_token`
- 若企业诉求是“尽量不让客户自己训练”，应使用 `managed_only`

补充边界：

- token 只控制“谁可以解密最终样本文件”
- token 不参与数据库级去重
- token 不参与质量打分
- token 不改变样本治理结果，只控制成品访问

---

## 9. 开发测试阶段为什么允许不加密

原因非常现实：

1. 先验证脱敏和样本构造正确性
2. 先验证去重和打分结果是否合理
2. 方便人工查看 JSONL 内容
3. 方便调试 Unsloth / 训练前处理链路
4. 避免一开始就把问题复杂化成“数据问题还是加密问题”

但必须加两个边界：

1. 明文导出只能在 `dev/test` 环境启用
2. manifest 必须明确记录未加密状态

还建议再加一个实现边界：

3. `keep_for_debug` 只允许在 `dev/test`

---

## 10. 推荐实施顺序

### Phase 1: 不加密打通主流程

目标：

- 先把 `sft.jsonl` / `trajectory.jsonl` 跑通
- 验证脱敏、去重、打分、manifest 正确

任务：

1. 完成样本构建
2. 完成脱敏门控
3. 完成数据库级去重
4. 完成规则分，必要时预留 LLM 分接口
5. 完成明文导出
6. 在 manifest 中记录 `encryption.applied = false`

### Phase 2: 引入 Tink AEAD

目标：

- 在不改变样本治理逻辑的情况下增加加密层

任务：

1. 增加 Tink 依赖
2. 增加 keyset 加载逻辑
3. 对 `sft.jsonl` / `trajectory.jsonl` 输出 `.enc`
4. 把 `dedup_strategy` / `scoring_policy` 绑定进 associated data
5. 增加 decrypt 验证测试
6. 增加临时文件 rename 与清理逻辑

### Phase 3: 接 KMS / Vault

目标：

- 让生产环境密钥管理不再依赖本地 keyset 文件

任务：

1. 引入 `key_ref`
2. 对接 KMS 或 Vault
3. 在 prod 中强制 `encryption_mode = required`
4. 增加失败恢复与重试边界

### Phase 4: 可选本地训练 token 控制

目标：

- 允许企业客户在本地训练场景下使用一次性访问控制

任务：

1. 增加 `local_train_access_mode`
2. 增加一次性 token 签发与校验
3. 增加 token 使用审计
4. 明确 `one_time_token` 与 `managed_only` 的产品边界

---

## 11. 最低完成标准

以下条件全部满足，才算这份最小方案闭环：

1. `dev` 环境可成功导出明文 `sft.jsonl` / `trajectory.jsonl`
2. `prod` 环境默认输出 `.enc` 文件而不是明文文件
3. `manifest.json` 能明确记录去重策略、打分策略、是否加密、使用哪个 `key_ref`
4. `required` 模式下，`--no-encrypt` 会直接失败
5. `prod` 成功导出后，不长期保留明文成品 JSONL
6. 有至少一条自动化测试覆盖 `encrypt -> decrypt -> 内容一致`
7. 若启用 `one_time_token`，至少有一条自动化测试覆盖 `token single-use`
8. 导出失败时不会留下伪装成正式成品的半成品文件

### 11.1 最低测试矩阵

建议至少覆盖以下测试：

1. `disabled` 模式导出明文成功
2. `required` 模式下 `--no-encrypt` 失败
3. `.enc` 文件可正常解密且内容与明文一致
4. associated data 不匹配时解密失败
5. 导出过程中异常中断后，正式文件名不存在或 manifest 标记为 failed
6. `stats.json` / `rejected_runs.json` 不包含样本正文
7. `one_time_token` 单次使用成功，二次使用失败

---

## 12. 当前明确不做的事情

本阶段明确不做：

1. 用加密本身防止客户环境提取明文
2. 自定义复杂信封加密协议
3. 自定义二进制文件格式
4. 强制所有开发测试阶段也必须加密

本方案的目标是“简单、直接、先落地”，不是一次性做完所有安全控制。