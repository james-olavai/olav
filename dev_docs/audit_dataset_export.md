# OLAV 审计日志到训练集导出设计

更新日期: 2026-03-18  
状态: ⚠️ 部分实施（导出器已完成，运行态审计源仍不完整）  
实现: `src/olav/enterprise/audit_dataset_export.py`  
测试: `tests/unit/test_audit_dataset_export.py`  
范围: `audit.duckdb` → 脱敏 → `sft.jsonl` / `trajectory.jsonl` / `atif.jsonl` 导出

> 2026-03-18 实库复核：导出器本身已可工作，但真实 `.olav/databases/audit.duckdb` 当前仅有 `12 runs / 35 events / 1 tool_call / 2 messages / 0 reasoning_block`。因此本文档描述的是“目标导出模型 + 已实现导出器”，而不是“主链路日志采集已完全达标”。

---

## 1. 目标

本设计解决以下问题：

1. 如何从统一审计事实层 `audit.duckdb` 派生训练样本
2. 如何在导出前执行**强制脱敏**，避免敏感网络数据泄露
3. 如何把单次 run 重建为 SFT chat、tool-use trajectory、ATIF / Harbor 风格数据
4. 如何用 `netutils` 等成熟工具做网络对象级规范化与去标识化，而不是继续堆积脆弱正则

本设计**不**解决以下问题：

1. 模型训练流程本身
2. 数据标注平台建设
3. 审计事件采集逻辑改造
4. ContainerLab 测试技能实现

---

## 2. 设计原则

### 2.1 只从审计事实层导出

训练集导出只能从以下结构化表派生：

- `audit_runs`
- `audit_events`
- `audit_tool_calls`
- `audit_messages`

不能从以下来源直接导出：

- Web UI 渲染文本
- 终端屏幕回显
- `.olav/logs/*.log` 运行日志
- 任意临时缓存文件

原因：

- UI 文本无法保证顺序和完整性
- 运行日志不是结构化事实层
- 训练集必须可复现、可过滤、可重放

### 2.2 导出前强制脱敏

任何导出动作都必须先经过脱敏门控。  
原则是：

- **先脱敏，再过滤，再导出**
- 未通过脱敏检查的 run 不得进入训练集
- 脱敏结果必须带元数据，不能只改文本不留痕

### 2.3 不自造网络对象识别轮子

涉及网络对象识别与规范化时，优先使用成熟工具：

- `netutils`：网络对象和厂商配置语义辅助
- `ipaddress`：IP / prefix / network 标准化
- `hashlib` / `hmac`：稳定不可逆映射
- `re`：只用于有限、显式、高风险字段兜底

设计原则是：

- 网络对象识别尽量用 network-aware 工具
- 只有凭据类和值类字段才用规则替换
- 不把整个脱敏系统建立在一堆不可维护的正则上

### 2.4 先去重，再打分，最后导出

训练集治理顺序建议固定为：

1. 先重建 run timeline
2. 再脱敏与 gate 检查
3. 再做数据库级候选去重
4. 再做质量打分
5. 最后按阈值导出

原因：

- 不先去重，质量打分会浪费在重复样本上
- 不先脱敏，去重指纹可能把真实敏感值带入治理链路
- 不先做数据库级硬去重，后续 LLM 打分成本会被重复样本放大

---

## 3. 数据源

### 3.1 表级职责

#### `audit_runs`

提供 run 级元数据：

- `run_id`
- `start_time`
- `end_time`
- `status`
- `agent_id`
- `session_id`
- `thread_id`
- `user_id`
- `source_channel`

#### `audit_messages`

提供按 `sequence_no` 排序的用户 / assistant / tool 消息。  
它是 SFT Chat JSONL 的主数据源。

**当前风险（2026-03-18）**: 主代码路径尚未系统性调用 `record_message()`，`audit_messages` 在真实库中仍极稀疏。导出器依赖本表，因此真实运行样本仍会被大量拒绝。

#### `audit_tool_calls`

提供工具调用、参数、结果、失败信息。  
它是 tool-use trajectory 的主数据源。

**当前风险（2026-03-18）**: callback 已补写 `record_tool_call()`，但真实库覆盖率仍低，需进一步确认 callback 子 run 与顶层 run 的归并逻辑。

#### `audit_events`

提供更广泛的事件，如：

- routing decision
- HITL request / decision
- cancellation / error
- reasoning summary

它主要用于 trajectory 重建和样本过滤。

### 3.2 可选补充源

如果某些训练样本需要验证型 metadata，可选择性读取：

- `.agent/skills/containerlab-e2e/evidence/<test_run_id>/artifacts.json`
- `exports/snapshots/json/*.staging.json`
- `parsed_outputs`

但这些不是审计训练集的主真相源，只能作为增强元数据。

---

## 4. 导出对象

### 4.1 SFT Chat JSONL

用于标准多轮对话监督微调。

#### 单条样本结构

```json
{
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": null, "tool_calls": [{"id": "call_abc123", "type": "function", "function": {"name": "query_db", "arguments": "{\"sql\": \"SELECT ...\"}"}}]},
    {"role": "tool", "tool_call_id": "call_abc123", "content": "..."},
    {"role": "assistant", "content": "..."}
  ],
  "metadata": {
    "run_id": "uuid",
    "agent_id": "quick",
    "source_channel": "cli",
    "status": "completed",
    "task_type": "query_generation",
    "domain_tags": ["query", "schema", "interfaces"],
    "schema_snapshot": "network.v1",
    "tool_schema_snapshot": "tools.v1",
    "quality_score": 0.94,
    "requires_tool": false,
    "redaction_policy": "audit-redaction-v1"
  }
}
```

#### 构造规则

1. 按 `run_id` 聚合
2. 从 `audit_messages` 按 `sequence_no` 排序
3. 保留 `system/user/assistant/tool` 四类消息
4. `assistant` 消息保留 `tool_calls` 字段（如有）；`tool` 消息保留 `tool_call_id` 字段
5. 默认只导出 `status = completed`

### 4.2 Tool-use Trajectory JSONL

用于多步工具调用训练。

#### 单条样本结构

```json
{
  "instruction": "Show recent failed audit runs",
  "trajectory": [
    {"type": "assistant_reasoning", "content": "..."},
    {"type": "tool_call", "tool": "query_audit_log", "args": {"hours": 24}},
    {"type": "tool_result", "content": "..."},
    {"type": "assistant_final", "content": "..."}
  ],
  "metadata": {
    "run_id": "uuid",
    "agent_id": "audit",
    "task_type": "tool_selection",
    "domain_tags": ["audit", "tool_use"],
    "schema_snapshot": "network.v1",
    "tool_schema_snapshot": "tools.v1",
    "quality_score": 0.91,
    "requires_tool": true,
    "risk_flags": [],
    "redaction_policy": "audit-redaction-v1"
  }
}
```

#### 构造规则

1. 优先从 `audit_messages` 提取用户首条输入作为 `instruction`
2. 从 `audit_events` + `audit_tool_calls` 重建中间轨迹
3. 最终 assistant 输出来自最后一条 `assistant` 消息
4. 若存在 `hitl_decision = reject`，默认不导出
5. 若 tool call 缺失结果或顺序不闭合，标记为 `invalid_trajectory`

### 4.3 ATIF / Harbor 风格导出

用于对接内部分析平台或 LangSmith 风格回放。

#### 单条样本结构

```json
{
  "trace_id": "uuid",
  "spans": [
    {"name": "user_input", "type": "message", "content": "..."},
    {"name": "tool_call", "type": "tool", "tool": "execute_sql", "input": {}},
    {"name": "tool_result", "type": "tool_result", "output": "..."}
  ],
  "metadata": {
    "run_id": "uuid",
    "agent_id": "ops",
    "task_type": "trace_analysis",
    "domain_tags": ["ops", "trace", "debug"]
  }
}
```

这类导出与 SFT 不同，重点是保留 trace 结构，而不是压平成 chat 消息。

### 4.4 长期保留格式 vs 训练派生格式

本设计要求明确区分两类格式：

#### A. 长期保留格式

长期保留格式用于：

- 数据治理
- 数据回放
- 重新切分样本
- 适配不同训练框架

建议长期保留的主格式只有两种：

1. `sft.jsonl`
2. `trajectory.jsonl`

`atif.jsonl` 可保留用于分析和回放，但不是首选训练主格式。

#### B. 训练派生格式

训练派生格式用于：

- 适配 Unsloth
- 适配 Hugging Face Trainer
- 适配特定 chat template

训练派生格式不应作为长期真相源保存。  
原因：

- 它们通常绑定某个训练框架或模板约定
- 容易随模型家族变化
- 一旦主格式设计稳定，派生格式可以重复生成

因此：

- `sft.jsonl` / `trajectory.jsonl` 是长期保留格式
- `unsloth_chat.jsonl` / `unsloth_toolcall.jsonl` 是派生格式

### 4.4.1 规范文件命名

为避免实现阶段命名漂移，统一采用以下文件名：

- 主格式：
  - `sft.jsonl`
  - `trajectory.jsonl`
  - `atif.jsonl`

- 训练派生格式：
  - `unsloth_chat.jsonl`
  - `unsloth_toolcall.jsonl`

- 辅助文件：
  - `manifest.json`
  - `rejected_runs.json`
  - `stats.json`

若启用企业版加密控制，文件名在原名后追加 `.enc`，例如：

- `sft.jsonl.enc`
- `trajectory.jsonl.enc`
- `atif.jsonl.enc`

### 4.5 面向训练目标的样本类型

本项目训练目标不是泛用聊天，而是让 LLM 更擅长 OLAV 工作流。  
因此建议把样本分成以下三类任务：

#### A. `query_generation`

目标：

- 熟悉 OLAV 的查询 schema
- 把自然语言需求快速转成 query / SQL / audit query

推荐来源：

- 高质量 `user -> assistant` 查询生成对话
- 最终答案明确包含查询语句或结构化查询意图的 run

推荐主格式：

- `sft.jsonl`

#### B. `tool_selection`

目标：

- 知道什么时候调用哪个 OLAV 工具
- 学会构造正确工具参数
- 学会根据工具结果继续下一步

推荐来源：

- `audit_messages` + `audit_tool_calls` + `audit_events`

推荐主格式：

- `trajectory.jsonl`

#### C. `network_analysis`

目标：

- 提升对网络状态、拓扑、协议、日志的解释能力
- 学会给出有依据的分析结论

推荐来源：

- 高质量 final answer
- 配套的工具结果摘要
- 已脱敏的网络状态证据

推荐主格式：

- `sft.jsonl`

### 4.6 Unsloth 兼容导出

#### 结论

可以用于 Unsloth，但推荐按“两步法”处理：

1. 先生成框架无关的主格式：`sft.jsonl` / `trajectory.jsonl`
2. 再派生成 Unsloth 兼容格式

这样做的好处是：

- 训练框架变化时不需要重做脱敏和主导出
- 便于同时支持 Qwen、Llama、Mistral 等不同 chat template
- 语义结构和训练表达分离，便于质量治理

#### A. `unsloth_chat.jsonl`

适用目标：

- query generation
- schema 熟悉
- network analysis

建议结构：

```json
{
  "messages": [
    {"role": "system", "content": "You are OLAV assistant..."},
    {"role": "user", "content": "Find interfaces down on leaf switches"},
    {"role": "assistant", "content": "SELECT device_name, interface_name ..."}
  ],
  "metadata": {
    "task_type": "query_generation",
    "schema_snapshot": "network.v1",
    "redaction_policy": "audit-redaction-v1"
  }
}
```

这是最容易直接喂给 Unsloth 的格式。  
如有需要，也可在导出阶段进一步展开为单字段 `text`。

#### B. `unsloth_toolcall.jsonl`

适用目标：

- 工具调用
- 多步推理
- 根据工具结果继续分析

建议结构：

```json
{
  "text": "<|system|>You are OLAV assistant.<|user|>Analyze why BGP is flapping on R1<|assistant|><tool_call>{\"tool\":\"query_db\",\"args\":{\"sql\":\"SELECT ...\"}}</tool_call><tool_result>...</tool_result><final>R1 is flapping because ...</final>",
  "metadata": {
    "task_type": "tool_selection",
    "tool_schema_snapshot": "tools.v1",
    "redaction_policy": "audit-redaction-v1"
  }
}
```

这里不建议把 `trajectory.jsonl` 原样直接送入 Unsloth。  
更稳妥的做法是先序列化为模型能学习的单轮文本或 chat 文本。

#### C. 与 Unsloth 的适配原则

为了兼容 Unsloth，派生导出需要满足：

1. 每条样本是单个 JSON object
2. 至少有 `messages` 或 `text` 之一
3. 不依赖训练时再去重建 run 轨迹
4. 工具调用标记采用稳定、可模板化的文本标签

建议固定以下派生文件名：

- `unsloth_chat.jsonl`
- `unsloth_toolcall.jsonl`

### 4.7 推荐 metadata 字段

为了让训练目标真正对准 OLAV，建议主格式和派生格式都保留以下 metadata：

- `task_type`
  可选值：`query_generation` / `tool_selection` / `network_analysis` / `trace_analysis`

- `domain_tags`
  例如：`bgp`, `ospf`, `topology`, `audit`, `interfaces`, `schema`

- `schema_snapshot`
  表示该样本对应的数据 schema 版本

- `tool_schema_snapshot`
  表示工具参数 schema 版本

- `quality_score`
  用于过滤低质量 run 或错误样本

- `dedup_fingerprint`
  用于标记该样本在导出窗口内的规范化去重指纹

- `dedup_strategy`
  标记该样本采用的去重策略，例如 `exact_v1` / `trajectory_v1`

- `scoring_policy`
  标记质量打分策略版本，例如 `dataset-score-v1`

- `requires_tool`
  标记该任务是否本质上依赖工具调用

- `redaction_policy`
  标记脱敏策略版本

- `risk_flags`
  标记是否涉及高风险操作或敏感域

### 4.8 规范 manifest 字段

为与加密控制文档保持一致，`manifest.json` 中与加密相关的字段统一为：

```json
{
  "encryption": {
    "applied": true,
    "mode": "required",
    "provider": "tink",
    "primitive": "aead",
    "key_ref": "dataset-export-key-v1"
  }
}
```

不再使用平铺字段名如：

- `encryption_applied`
- `encrypt_enabled`
- `dataset_key_name`

相关生产控制见 `encrypted_dataset_control.md`。

---

## 5. 脱敏总体设计

### 5.1 脱敏分层

脱敏必须分三层执行：

1. **字段级脱敏**：已知高风险字段和值
2. **网络对象级脱敏**：IP、prefix、hostname、interface、AS number 等网络语义对象
3. **配置块级脱敏**：整段设备配置、ACL、policy、neighbor 段落

### 5.2 脱敏输出要求

脱敏后的每条样本和每次导出任务都必须记录元数据：

```json
{
  "applied": true,
  "policy_version": "audit-redaction-v1",
  "fields_redacted": ["password", "snmp_community"],
  "network_objects_hashed": ["ip_address", "hostname"],
  "config_blocks_masked": 2
}
```

### 5.3 脱敏门控

导出程序必须在写 JSONL 之前执行以下检查：

1. 是否应用了 redaction policy
2. 是否发现未处理的高风险字段
3. 是否存在疑似明文凭据
4. 是否存在未匿名化的网络对象

若任一检查失败：

- 该 run 标记为 `redaction_failed`
- 不进入导出文件
- 写入 `rejected_runs.json`

---

## 6. 使用 `netutils` 等成熟工具的策略

### 6.1 为什么要用 `netutils`

审计日志里不只有普通文本，还有大量网络领域对象：

- 主机名
- 接口名
- IP / prefix
- 邻居地址
- 厂商配置片段
- VRF / VLAN / ASN / 路由策略标识

这些对象如果只靠通用正则脱敏，问题会很明显：

- 容易误伤普通文本
- 不能稳定归一化同一对象
- 不便于跨 run 做一致映射
- 无法区分合法网络对象和普通字符串

因此本设计规定：

- `netutils` 负责网络对象识别与标准化辅助
- `ipaddress` 负责 IP / network 的严格解析
- 正则只做凭据类高风险兜底

### 6.2 推荐使用范围

#### A. 接口名规范化

很多日志里同一个接口会以不同形式出现：

- `Gi0/1`
- `GigabitEthernet0/1`
- `ge-0/0/0`

这里应优先使用 `netutils` 做接口规范化，再决定是否匿名化。  
脱敏后保留结构但隐藏真实标识，例如：

```text
GigabitEthernet0/1 -> if_cisco_001
ge-0/0/0 -> if_junos_001
```

#### B. IP / prefix 识别

对所有疑似 IP 或 CIDR：

1. 先用 `ipaddress` 校验
2. 校验通过后再进入稳定哈希映射

脱敏后建议保留“类型与网段层级信息”，例如：

- `10.1.2.3` → `ip_priv_v4_001`
- `192.0.2.0/30` → `pfx_doc_v4_001`

#### C. 主机名与设备名

主机名通常和网络拓扑强关联，不适合原样保留。  
建议先用网络对象识别规则过滤，再做稳定映射：

- `edge-r1-shanghai` → `host_001`
- `sw-core-02` → `host_002`

#### D. 厂商配置块

对设备配置类输出，不建议逐字段硬切，而应该：

1. 先识别配置块类型
2. 对块内的 IP / hostname / community / key-string / password 等对象分层替换
3. 保留语法骨架，移除真实值

示例：

```text
neighbor 10.0.0.1 password Sekr3t!
```

脱敏后：

```text
neighbor ip_priv_v4_001 password [REDACTED]
```

### 6.3 工具选型建议

本阶段建议分两层：

#### 核心层

- `netutils`
- `ipaddress`
- `hashlib` / `hmac`
- `re`

原因：

- 已在项目依赖中存在 `netutils`，见 `pyproject.toml`
- 核心层可控、稳定、可离线运行
- 足够覆盖网络审计日志的主体对象

#### 增强层（可选）

如果后续需要通用 PII 脱敏，可评估引入：

- Microsoft Presidio
- scrubadub

但增强层不是本设计首阶段的必需项。  
首阶段优先保证“网络对象 + 凭据”两类高风险数据的确定性脱敏。

---

## 7. 稳定映射策略

### 7.1 原则

训练集不能保留真实网络对象，但又需要保留跨样本一致性。  
因此需要**稳定不可逆映射**。

### 7.2 方案

对敏感网络对象使用：

```text
token = HMAC_SHA256(secret_key, normalized_value)
```

再映射到短标签：

- 主机名：`host_<n>`
- IP：`ip_<class>_<n>`
- prefix：`pfx_<class>_<n>`
- 接口：`if_<platform>_<n>`
- ASN：`asn_<n>`

### 7.3 分类保留建议

为保留一定语义，可在映射标签中保留低风险分类信息：

- IP 类型：`priv_v4`, `pub_v4`, `v6`, `doc_v4`
- 接口平台：`cisco`, `junos`, `eos`
- 对象角色：`peer`, `loopback`, `mgmt`

不能保留的内容：

- 原始数值
- 原始 hostname 前缀
- 原始站点编码
- 原始 ASN

---

## 8. 样本过滤规则

### 8.1 默认允许导出的 run

只导出满足以下条件的 run：

1. `status = completed`
2. 脱敏成功
3. 未命中高风险拒绝规则
4. 轨迹完整

### 8.2 默认拒绝导出的 run

以下情况默认拒绝导出：

1. `status in ('error', 'cancelled')`
2. 存在 HITL `reject`
3. 命中敏感动作标签，如：
   - token rotation
   - password reset
   - raw config secret display
4. 发现未脱敏字段
5. 轨迹缺失 tool result 或 final answer

### 8.3 可配置放宽项

企业内部调试场景允许按 profile 放宽：

- 是否保留失败 run
- 是否保留 tool role message
- 是否导出 reasoning summary

但默认值必须是保守的。

### 8.4 数据库级去重

结论：**应该先做 DuckDB 级别的硬去重**。  
这一步的目标不是理解语义优劣，而是低成本去掉明显重复、模板化、批量重放的样本。

#### 为什么放在数据库层

原因：

1. 成本最低，适合大批量窗口扫描
2. 结果稳定，可重复执行，可审计
3. 可以先把候选量压下来，再进入较贵的 LLM 打分阶段
4. DuckDB 很适合对规范化字段做 `GROUP BY`、`ROW_NUMBER()`、`QUALIFY`

#### 去重对象

建议对不同主格式分别计算指纹：

- `sft.jsonl`
  以 `task_type + canonical_user_text + canonical_assistant_text` 为主

- `trajectory.jsonl`
  以 `task_type + canonical_instruction + tool_sequence + canonical_final_answer` 为主

#### 指纹构造原则

指纹必须基于**脱敏后、规范化后**的数据生成，而不是原始文本。  
建议规范化步骤：

1. 去除时间戳、UUID、run_id、随机 token 等波动字段
2. 对 SQL / query 做空白折叠和大小写规范化
3. 对工具参数做 key 排序后再序列化
4. 对 assistant final answer 做空白折叠、脱敏 token 替换、常见模板句裁剪

示例：

```text
dedup_fingerprint = SHA256(
  task_type
  + canonical_instruction
  + canonical_tool_sequence
  + canonical_final_answer
)
```

#### 数据库层推荐策略

第一版建议只做两类：

1. **exact duplicate**
   完全相同的规范化指纹只保留一条
2. **high-frequency template collapse**
   同一指纹在窗口内出现过多次时，只保留质量最高或最近的一条

DuckDB 实现思路：

```sql
WITH ranked AS (
  SELECT
    *,
    ROW_NUMBER() OVER (
      PARTITION BY dedup_fingerprint
      ORDER BY end_time DESC, run_id DESC
    ) AS rn,
    COUNT(*) OVER (
      PARTITION BY dedup_fingerprint
    ) AS dup_count
  FROM export_candidates
)
SELECT *
FROM ranked
WHERE rn = 1;
```

#### 保留哪一条

第一版建议优先级：

1. 已完成且轨迹完整
2. 脱敏结果更干净、risk_flags 更少
3. 质量分更高
4. 若仍相同，则保留最近一条

#### 不建议第一版在数据库层解决的事情

以下不建议放在第一版 DuckDB 硬去重中：

1. 语义近似去重
2. embedding 聚类去重
3. LLM 判断“这两条是不是差不多”

这些都可以作为第二阶段增强，因为：

- 成本更高
- 可解释性更弱
- 容易误删少量但有价值的变体样本

### 8.5 样本质量打分

数据库级去重之后，建议再进入质量打分阶段。  
这一步的目标是把“可导出”进一步收敛为“值得训练”。

#### 设计结论

建议采用两阶段评分：

1. **规则分**：默认必做，离线、稳定、低成本
2. **LLM 分**：可选增强，只对去重后的候选样本执行

最终：

```text
quality_score = weighted(rule_score, llm_score)
```

#### A. 规则分

规则分适合先覆盖这些维度：

- 轨迹完整性
- 用户问题是否明确
- assistant 最终回答是否具体、非空、非占位
- 是否包含可学习的 query / tool 参数 / 网络分析结论
- tool result 与 final answer 是否基本一致
- 是否存在明显失败模式：空结果、跑偏、拒答、重复模板回答

建议规则分输出多个子项，而不是只给总分：

```json
{
  "score_components": {
    "completeness": 1.0,
    "tool_consistency": 0.9,
    "query_specificity": 0.8,
    "analysis_value": 0.7
  },
  "rule_score": 0.84
}
```

#### B. LLM 分

LLM 不建议直接替代规则，而应只做“高层语义质量判断”。

建议让 LLM 只评估这些问题：

1. 这条样本是否真的教会模型更好地使用 OLAV
2. assistant 输出是否忠于工具结果和上下文事实
3. 对 query generation / tool_selection / network_analysis 是否有训练价值
4. 是否存在明显幻觉、空泛总结、无依据推断

建议输出：

- `llm_score`
- `llm_reason`
- `quality_labels`

例如：

```json
{
  "llm_score": 0.88,
  "quality_labels": ["good_query_pattern", "grounded_analysis"],
  "llm_reason": "Answer is grounded in tool output and teaches a reusable OLAV query pattern."
}
```

#### C. 门控策略

建议默认导出门槛：

1. `rule_score >= min_rule_score`
2. 若启用 LLM 评分，则 `quality_score >= min_quality_score`
3. 命中硬拒绝标签时直接丢弃，例如：
   - hallucination
   - unresolved_failure
   - low_signal_template
   - unsafe_sensitive_pattern

#### D. 为什么不要只靠 LLM 打分

原因：

1. 成本高
2. 稳定性不如规则分
3. 对明显垃圾样本没有必要浪费模型调用
4. 企业环境中需要更强的可解释性和可复现性

因此建议：

- 规则分负责大规模筛选
- LLM 分负责高价值精排

### 8.6 导出统计要求

`stats.json` 和 `manifest.json` 建议显式记录去重和打分结果：

- `runs_scanned`
- `runs_after_filter`
- `samples_before_dedup`
- `samples_after_dedup`
- `samples_scored`
- `samples_exported`
- `dedup_strategy`
- `scoring_policy`
- `avg_rule_score`
- `avg_quality_score`
- `rejected_by_reason`

---

## 9. 导出流程

```text
audit.duckdb
   ↓
load runs / messages / events / tool_calls
   ↓
rebuild run timeline
   ↓
redaction pipeline
   ↓
gate checks
   ↓
database-level dedup
  ↓
sample scoring
  ↓
sample builder
   ↓
jsonl writer
   ↓
manifest + rejected_runs.json + stats.json
```

### 9.1 导出目录

建议输出到：

```text
exports/audit_datasets/<export_id>/
```

目录结构：

```text
exports/audit_datasets/<export_id>/
├── sft.jsonl
├── trajectory.jsonl
├── atif.jsonl
├── rejected_runs.json
├── stats.json
└── manifest.json
```

### 9.2 `manifest.json`

必须包含：

```json
{
  "export_id": "audit-export-20260316-180000",
  "source_db": ".olav/databases/audit.duckdb",
  "window": {"start": "...", "end": "..."},
  "redaction_policy": "audit-redaction-v1",
  "dedup_strategy": "exact_v1",
  "scoring_policy": "dataset-score-v1",
  "encryption": {
    "applied": false,
    "mode": "disabled",
    "provider": null,
    "primitive": null,
    "key_ref": null
  },
  "formats": ["sft", "trajectory"],
  "runs_scanned": 120,
  "runs_after_filter": 96,
  "samples_before_dedup": 140,
  "samples_after_dedup": 101,
  "samples_scored": 101,
  "runs_exported": 84,
  "runs_rejected": 36
}
```

---

## 10. 推荐接口

### 10.1 Python API

建议新增模块：

```text
src/olav/enterprise/audit_dataset_export.py
```

导出 API：

```python
def audit_to_sft_jsonl(...):
    ...


def audit_to_tool_trajectory(...):
    ...


def audit_to_atif(...):
    ...


def redact_audit_run(...):
    ...
```

### 10.2 CLI

建议命令：

```text
olav log export sft --hours 24 --output exports/audit_datasets/...
olav log export trajectory --hours 24 --output exports/audit_datasets/...
olav log export all --hours 24 --redaction-policy audit-redaction-v1
```

默认行为：

- 只导出最近窗口
- 默认启用脱敏门控
- 默认只导出 completed run

---

## 11. 最低完成标准

以下条件全部满足，才算“日志到训练集导出”设计闭环：

1. 能从 `audit.duckdb` 重建单次 run 的消息顺序
2. 能从 `audit_tool_calls` + `audit_events` 重建至少一种 tool trajectory
3. `audit_messages`、`audit_events`、`audit_tool_calls` 都有统一脱敏入口
4. `netutils` + `ipaddress` 已接入网络对象识别与规范化
5. 导出前 gate 能阻止未脱敏 run
6. 至少定义一种 SFT JSONL 和一种 trajectory JSONL 的稳定 schema
7. DuckDB 层支持基于规范化指纹的稳定硬去重
8. 质量打分至少包含 `rule_score`，并可选叠加 `llm_score`
9. 导出目录含 `manifest.json`、`rejected_runs.json`、`stats.json`

---

## 12. 分阶段实施建议

### Phase 1: 基础脱敏与 SFT 导出

目标：先把最基础、最确定的链路跑通。

任务：

1. 统一 run 重建逻辑
2. 对 `audit_messages`、`audit_events`、`audit_tool_calls` 建立统一 redaction pipeline
3. 引入 `netutils` + `ipaddress` 做网络对象规范化
4. 实现 `audit_to_sft_jsonl`
5. 输出 `manifest.json` / `stats.json`

### Phase 2: Tool trajectory 导出

目标：把工具调用轨迹变成稳定训练样本。

任务：

1. 关联 `audit_messages` 与 `audit_tool_calls`
2. 重建 `instruction → tool_call → result → final`
3. 处理 HITL reject / cancelled / invalid trajectory
4. 实现 `audit_to_tool_trajectory`
5. 增加 `dedup_fingerprint` 生成与窗口内硬去重

### Phase 3: 高级脱敏与 Harbor / ATIF

目标：支持企业内部更复杂的导出场景。

任务：

1. 配置块级脱敏
2. 稳定对象映射缓存
3. Harbor / ATIF schema 对接
4. 可选接入 Presidio / scrubadub

### Phase 4: 质量评分与精排

目标：让训练集从“可导出”提升到“值得训练”。

任务：

1. 实现规则分 `rule_score`
2. 增加可解释的 `score_components`
3. 可选接入 LLM 评分 `llm_score`
4. 输出 `quality_score`、`quality_labels`、`llm_reason`
5. 允许按 profile 调整导出阈值

---

## 13. 当前明确不做的事情

本阶段明确不做：

1. 直接从 UI 或 SSE 流写训练集
2. 保留真实网络对象用于“内部可见”训练
3. 无脱敏导出调试开关
4. 自动上传外部训练平台

这些都不应成为第一版能力的一部分。