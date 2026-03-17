# OLAV 全流程审计日志改造方案

更新日期: 2026-03-15
状态: 方案设计，未实施
范围: CLI, Web API, LangGraph/DeepAgents 执行链, 审计存储, `olav log` 查询面, 企业版脱敏与数据集导出

## 1. 背景

OLAV 作为生产级网络运维工具，审计不是附属功能，而是核心能力。当前实现只有“命令级日志”，无法满足以下要求：

1. 所有用户输入必须可审计。
2. LLM 串流输出必须可审计。
3. 工具调用参数、结果、失败信息必须可审计。
4. Human-in-the-loop 审批请求与决策必须可审计。
5. 模型对外暴露的 reasoning 或 reasoning summary 必须可审计。
6. 最终输出必须可审计。
7. 开源版日志默认不应以“好用的源文件形式”直接暴露给用户。
8. 架构必须支持后续企业版脱敏与标准 LLM 训练数据集导出。

## 2. 当前实现问题

### 2.1 只有命令级日志，没有轨迹级日志

当前 `src/olav/core/audit_logger.py` 只记录一行文本，格式类似：

```text
[timestamp] USER=<user> SESSION=<session> CMD=<command>
```

这只能回答“用户输入过什么命令”，不能回答：

- 模型输出了什么流式内容
- 调用了哪些工具
- 工具参数和结果是什么
- 是否触发了审批
- 用户批准还是拒绝
- 最终答复是什么
- 某次运行为什么失败

### 2.2 审计主存储与运行日志目录职责未统一

当前审计输出存在三条互相矛盾的路径：

| 来源 | 路径 |
|---|---|
| `audit_logger.py` 实际写入 | `~/.olav/history/{user}.log` |
| AGENTS.md 文档要求 | `.olav/logs/users/{user}.log` |
| `config.py` / `defaults.py` 默认值 | `.olav/logs/` |

这三条路径分别指向不同位置，导致文档、代码、运行行为三者不一致，审计源不唯一，多用户项目级审计无法统一查询。

新设计对职责做明确拆分：

- `.olav/logs/` 保留为**运行日志目录**（olav.log、web.log、query.log、syslog_receiver.log 等），不再作为审计真相源
- `.olav/databases/audit.duckdb` 成为审计 SSOT，所有审计事件统一写入此数据库
- `~/.olav/history/` 不再使用，`USER_HISTORY_DIR` 配置项可在后续清理

AGENTS.md 中 `Centralized Audit Logs (.olav/logs/users/*.log)` 的表述也需要在后续同步更新为指向 `audit.duckdb`。

### 2.3 Web 路径没有服务端审计闭环

当前 Web SSE 接口只是把 LangGraph 事件透传给前端，前端仅在浏览器内存里维护消息数组。也就是说：

- Web 用户输入没有可靠服务端轨迹存储
- Web 流式输出没有服务端镜像审计
- 前端显示过的 tool-call 标签没有审计价值

### 2.4 HITL 审批流程未纳入统一审计

deepagents-cli 的执行循环已经可以拿到：

- interrupt 请求
- 审批动作列表
- 用户 approve/reject 决策
- auto-approve 切换
- resume payload

但当前这些信息只用于交互执行，不落审计日志。

### 2.5 reasoning 当前被识别但未沉淀

执行层可识别 `reasoning` block，但目前基本只影响终端显示，不写入结构化日志。

注意：

“思考可审计”应定义为“记录模型对外暴露的 reasoning artifact”，不能假设所有模型都能暴露完整隐藏 chain-of-thought。

### 2.6 当前日志产品形态不利于开源版与企业版分层

当前实现的问题不只是“没有脱敏”，还包括“日志暴露方式过于原始”。如果未来继续以源文件为主承载日志，即使做了更多事件覆盖，也会带来以下问题：

- 开源版很容易变成“原始轨迹文件分发器”
- `olav log` 命令的产品价值被削弱
- 企业版的高级能力难以建立清晰边界
- 日志格式和存储方式对最终用户过于透明

此外，当前主链路中也没有日志专用的 redaction pipeline。若直接扩大日志覆盖范围，会泄露：

- IP 地址
- hostname
- 用户名
- token
- API key
- 密码或 secret 字段
- SNMP community
- 设备配置中的敏感段

### 2.7 现有日志格式既不适合查询，也不适合训练集派生

当前按行拼接文本的日志，不适合直接做以下两类事情：

1. 作为 `olav log` 的统一查询后端
2. 作为企业版训练集派生基础

具体表现为：

- SFT chat JSONL
- tool-use trajectory dataset
- preference 或 critique dataset
- LangSmith / Harbor / ATIF 风格轨迹

## 3. 改造目标

本次改造的目标不是“多写几行日志”，而是建立统一的可审计事件系统。

### 3.1 核心目标

1. 审计覆盖 CLI, Web, API 三条入口。
2. 审计覆盖输入、流、工具、审批、输出、异常全链路。
3. 所有审计事件都使用统一 schema。
4. 开源版日志统一收敛到数据库，不再以易用源文件作为主接口。
5. 用户主要通过 `olav log` 命令查看最近窗口期日志，体验类似网络设备 logging。
6. 审计事件可以回放单次 run。
7. 架构支持企业版脱敏与训练数据集派生。
8. 审计记录 append-only，不允许静默篡改。

### 3.2 非目标

1. 不尝试获取模型供应商未暴露的隐藏内部 CoT。
2. 不在第一阶段引入复杂外部观测平台作为唯一依赖。
3. 不将审计和业务日志混写。
4. 不把“底层文件不容易找到”当作真正的安全边界。

## 4. 总体设计

建议把当前的 `audit_logger` 升级为统一的 `audit trace recorder`。

### 4.1 分层结构

建议拆成三层：

1. Event Capture Layer
2. Storage and Query Layer
3. Enterprise Extension Layer

#### Event Capture Layer

负责从不同执行入口捕获标准事件：

- CLI 交互执行链
- Web SSE 服务端执行链
- LangChain / LangGraph callback/tracer
- HITL interrupt 审批链

#### Storage and Query Layer

负责：

- 将审计事件统一写入项目级 DuckDB
- 建立 `audit_runs` / `audit_events` / `audit_tool_calls` / `audit_messages` 等查询表
- 为 `olav log` 命令提供统一查询后端
- 控制开源版默认可见窗口，例如最近 24 小时

#### Enterprise Extension Layer

负责：

- 可配置脱敏策略
- 标准训练集导出
- 长期保留与归档
- 合规审计与回放

### 4.2 产品分层决策

本方案采用如下产品分层：

1. 开源版: 统一写入 `.olav/databases/audit.duckdb`
2. 开源版: 默认只通过 `olav log` 查看日志
3. 开源版: 默认只暴露最近 24 小时窗口，行为类似网络设备 `show logging`
4. 开源版: 不提供方便的原始数据集导出能力
5. 企业版: 在相同事件模型上增加脱敏、数据集生成、长周期留存、导出和回放

需要明确的一点是：

“熟悉本地环境的用户可以直接打开 DuckDB 文件”是事实，但这并不构成架构问题。任何有能力直接打开 DuckDB 的用户，也同样有能力修改代码自行保存全量日志。因此，本设计不以“隐藏底层文件”作为安全边界，而以“默认产品能力边界”作为开源版与企业版的分层方式。

## 5. 审计事件模型

### 5.1 基本原则

所有审计记录必须是结构化 JSON，每行一条事件。

建议内部事件以结构化记录为核心语义，主落盘载体在开源版中为 DuckDB 表。

逻辑事件格式仍建议保持 JSON 语义，便于后续企业版导出和 schema 演进。例如：

```json
{
	"schema_version": "audit.v1",
	"event_id": "uuid",
	"event_type": "tool_call_started",
	"timestamp": "2026-03-15T12:34:56.123456Z",
	"sequence_no": 17,
	"run_id": "uuid",
	"session_id": "...",
	"thread_id": "...",
	"user_id": "yhvh",
	"agent_id": "quick",
	"subagent_id": "ops",
	"source_channel": "cli",
	"payload": {},
	"redaction": null
}
```

### 5.2 必备标识字段

每条事件至少要包含以下字段：

- `schema_version`
- `event_id`
- `event_type`
- `timestamp`
- `sequence_no`
- `run_id`
- `session_id`
- `thread_id`
- `user_id`
- `agent_id`
- `subagent_id`
- `source_channel`
- `tool_call_id`
- `parent_run_id`
- `payload`
- `redaction`

其中：

- `run_id` 用于串联一次完整请求
- `session_id` 用于跨多轮会话
- `thread_id` 用于 Web/API 线程恢复
- `tool_call_id` 用于串联工具开始/结束/失败
- `sequence_no` 用于严格回放顺序

说明：

- 开源版中 `redaction` 可以为空，表示未启用企业版脱敏策略
- 企业版中 `redaction` 字段应记录实际应用的脱敏策略信息

### 5.3 事件类型

第一阶段必须覆盖以下事件：

- `user_input_received`
- `user_input_normalized`
- `llm_request_started`
- `model_stream_delta`
- `reasoning_block`
- `tool_call_started`
- `tool_call_completed`
- `tool_call_failed`
- `hitl_requested`
- `hitl_decision`
- `assistant_output_final`
- `run_cancelled`
- `run_error`

第二阶段可补充：

- `context_file_injected`
- `prompt_template_resolved`
- `checkpoint_written`
- `checkpoint_restored`
- `dataset_exported`

## 6. 各入口的采集点

### 6.1 CLI 入口

当前 CLI 中只在输入阶段调用 `log_command()`，应改为：

1. 用户输入后记录 `user_input_received`
2. 文件注入和 prompt 归一化后记录 `user_input_normalized`
3. 模型流开始时记录 `llm_request_started`
4. 流式 token 记录 `model_stream_delta`
5. reasoning block 记录 `reasoning_block`
6. tool call chunk 聚合完成后记录 `tool_call_started`
7. ToolMessage 回来后记录 `tool_call_completed` 或 `tool_call_failed`
8. interrupt 出现时记录 `hitl_requested`
9. 用户 approve/reject 时记录 `hitl_decision`
10. 最终输出完成后记录 `assistant_output_final`
11. Ctrl+C 或异常时记录 `run_cancelled` 或 `run_error`

### 6.2 Web / API 入口

Web 不能依赖前端内存作为审计来源，必须在服务端落盘。

建议在 API 层做到：

1. 接收到 HTTP 请求时记录 `user_input_received`
2. `agent.graph.astream_events(...)` 的每个事件都先镜像写入审计，再决定是否向前端透传
3. `on_chat_model_stream` 转换为 `model_stream_delta`
4. `on_tool_start` / `on_tool_end` 转换为工具事件
5. `on_chat_model_end` 或结束消息聚合为 `assistant_output_final`
6. 错误异常转换为 `run_error`

### 6.3 LangChain / LangGraph 回调层

应增加统一 callback handler 或 tracer，优先作为核心采集点，而不是把采集逻辑散在 UI 层。

建议接入以下生命周期事件：

- model start
- model stream
- model end
- tool start
- tool end
- tool error
- chain start/end

这样可以保证：

- CLI 和 Web 共享同一套审计语义
- 后续新增入口不需要重写审计逻辑

### 6.4 HITL 审批链

审批应作为一等事件建模，而不是一个布尔字段。

#### `hitl_requested` payload 建议

```json
{
	"interrupt_id": "...",
	"action_requests": [
		{
			"name": "write_file",
			"description": "Write config file",
			"args": {"file_path": "..."}
		}
	]
}
```

#### `hitl_decision` payload 建议

```json
{
	"interrupt_id": "...",
	"decision": "approve",
	"auto_approve_enabled": false,
	"action_name": "write_file"
}
```

必须明确记录：

- 请求了什么动作
- 展示给用户的摘要是什么
- 用户是否批准
- 是否切换 auto-approve
- 最终 resume 内容是否继续执行

## 7. 脱敏设计与版本边界

### 7.1 当前产品决策

脱敏不再作为开源版第一阶段的强制阻塞项，而是作为企业高级能力设计。

这意味着：

1. 开源版第一阶段优先解决统一事件采集、数据库收敛和 `olav log` 查询问题
2. 企业版再引入字段级脱敏、脱敏数据集导出、可配置策略控制

但需要明确：

这不是安全边界，只是产品边界。不能宣称 DuckDB 本身能阻止高级用户读取底层数据。

### 7.2 企业版脱敏处理策略

建议按字段类型和语义分类处理：

1. 文本字段脱敏
2. 结构化参数脱敏
3. 设备配置块脱敏
4. 网络标识匿名化

### 7.3 企业版建议脱敏范围

#### 强制替换类

- `password`
- `secret`
- `token`
- `api_key`
- `authorization`
- `cookie`
- `private_key`
- `community`

输出形式：

```text
[REDACTED]
```

#### 可逆性禁止，保留关联能力

对以下字段建议使用稳定哈希映射，而不是明文保存：

- IP 地址
- hostname
- username
- device name

输出形式示例：

```text
host_4f1c2a
ip_9b72f0
```

### 7.4 netutils 的角色

`netutils` 可以用于网络对象标准化和部分格式识别，但不能单独承担完整脱敏职责。

必须额外增加：

- 高风险字段名规则
- 凭证正则规则
- 配置片段块级替换规则
- 可配置白名单和保留策略

### 7.5 企业版脱敏元数据

每条事件都应带：

```json
"redaction": {
	"applied": true,
	"policy_version": "redact.v1",
	"fields_redacted": [
		"payload.tool_args.password",
		"payload.output.running_config"
	]
}
```

这样后续才能审计“导出的企业数据是否已经脱敏”。

## 8. 存储设计

### 8.1 开源版主存储

开源版建议使用 DuckDB 作为统一审计主存储，而不是原始 JSONL 文件树。

建议路径：

```text
.olav/databases/audit.duckdb
```

说明：

- 与 OLAV 现有 DuckDB 技术栈保持一致
- 用户默认不直接面向源文件操作日志
- `olav log` 可以直接基于数据库提供“show logging”式体验
- 便于实现窗口期查询、过滤、分页、截断和摘要输出

### 8.2 建议表结构

建议至少包含以下表：

1. `audit_runs`
2. `audit_events`
3. `audit_tool_calls`
4. `audit_messages`

#### `audit_runs`

用于存储一次请求级别的元数据：

- `run_id`
- `session_id`
- `thread_id`
- `user_id`
- `agent_id`
- `source_channel`
- `started_at`
- `ended_at`
- `status`

#### `audit_events`

用于存储完整事件流：

- `event_id`
- `run_id`
- `sequence_no`
- `event_type`
- `timestamp`
- `tool_call_id`
- `payload_json`

#### `audit_tool_calls`

用于工具调用的查询索引：

- `tool_call_id`
- `run_id`
- `tool_name`
- `status`
- `started_at`
- `ended_at`
- `duration_ms`
- `requires_hitl`

#### `audit_messages`

用于文本内容查询：

- `message_id`
- `run_id`
- `message_type`
- `content`
- `content_summary`
- `token_count`

### 8.3 查询面

开源版的主要使用方式不是直接打开数据库，而是通过 `olav log` 命令查询。

用途：

- 查看最近 24 小时日志
- 按用户、agent、tool、run_id 过滤
- 查看某次运行的摘要轨迹
- 查看错误和工具失败
- 模拟网络设备 `show logging` 的操作体验

建议命令形态：

- `olav log`
- `olav log tail`
- `olav log show --run <run_id>`
- `olav log search --tool execute_cli`
- `olav log errors --since 24h`

### 8.4 窗口期与保留策略

开源版建议默认只保留最近 24 小时查询窗口，或者至少默认只通过 `olav log` 暴露最近 24 小时信息。

这层限制的目的不是“绝对防止高级用户访问底层数据”，而是定义产品默认行为：

- 开源版可用
- 开源版不以舒适的数据导出为目标
- 企业版再提供长期保留、导出和脱敏数据集功能

### 8.5 防篡改增强

生产级建议增加：

- `sequence_no`
- `prev_event_hash`
- `event_hash`

从而形成简单哈希链，提高审计可信度。

## 9. 企业版训练集导出设计

### 9.1 原则

训练集导出不属于开源版默认能力，而属于企业高级功能。

企业版导出仍应从统一审计事件事实层派生，而不是从 UI 渲染文本导出。

### 9.2 企业版建议支持的导出类型

#### SFT Chat JSONL

用于标准问答训练：

```json
{
	"messages": [
		{"role": "user", "content": "..."},
		{"role": "assistant", "content": "..."}
	],
	"metadata": {
		"agent_id": "quick",
		"source": "olav_audit"
	}
}
```

#### Tool-use Trajectory JSONL

用于多步工具调用训练：

```json
{
	"instruction": "...",
	"trajectory": [
		{"type": "assistant_reasoning", "content": "..."},
		{"type": "tool_call", "tool": "execute_cli", "args": {}},
		{"type": "tool_result", "content": "..."},
		{"type": "assistant_final", "content": "..."}
	]
}
```

#### ATIF / Harbor 风格轨迹

仓库归档中已有参考实现，后续可直接对接 LangSmith 或内部分析工具。

### 9.3 导出前过滤

企业版导出应支持：

- 脱敏后再导出
- 过滤失败 run
- 过滤被人工拒绝的危险操作
- 过滤包含高风险敏感字段的事件

## 10. 需要修改的代码位置

以下是当前最关键的改造点。

### 10.1 `src/olav/core/audit_logger.py`

当前问题：

- 只支持文本行格式
- 只记录命令
- 无 schema
- 无数据库写入能力
- 无 run 级轨迹

需要改为：

- 统一 `AuditEventRecorder`
- 支持 DuckDB 事件写入
- 支持按 run_id 写入
- 支持多种 event_type
- 为后续企业版 redaction/export 预留扩展点

### 10.2 `src/olav/core/config.py`

当前问题：

- 审计日志主路径指向 `~/.olav/history`
- 与 AGENTS 文档和项目级审计路径不一致

需要改为：

- 项目级审计数据库路径作为唯一主路径
- 建议新增 `AUDIT_DB_PATH = .olav/databases/audit.duckdb`
- 保持 `.olav/logs/` 作为运行日志目录，而不是主审计真相源

### 10.3 `src/olav/cli/main.py`

当前问题：

- 只在输入处调用 `log_command()`

需要改为：

- 输入事件记录
- 单次 run 初始化 `run_id`
- 把 recorder 注入执行链

### 10.4 CLI 执行循环

当前 deepagents-cli 执行循环已经能拿到大量有价值事件，但未写审计。

需要改为：

- 记录 reasoning block
- 记录 tool call start/end/fail
- 记录 interrupt request
- 记录 approval decision
- 记录 final output
- 记录 cancellation/error

### 10.5 `src/olav/api/server.py`

当前问题：

- 只做 SSE 透传
- 未做服务端镜像审计

需要改为：

- 请求开始先初始化 run context
- 每个 LangGraph 事件先写审计再转 SSE
- 请求异常写 `run_error`
- 请求完成写 `assistant_output_final`

### 10.6 `src/olav/api/static/index.html`

当前问题：

- 前端持有临时对话状态，但不应承担审计职责

需要改为：

- 前端仅负责展示
- 不把浏览器状态当作审计真相源

### 10.7 `olav log` 命令与企业导出模块

当前缺失：

- 缺少统一的 `olav log` 查询入口
- 缺少从审计事件导出标准数据集的企业模块

需要新增：

- `olav log` 子命令族
- `olav log tail`
- `olav log show`
- `olav log search`
- `audit_to_sft_jsonl`
- `audit_to_tool_trajectory`
- `audit_to_atif`

## 11. 分阶段实施建议

### Phase 1: 统一基础设施

目标：建立统一事件 schema 和 recorder。

任务：

1. 统一日志与审计路径职责
2. 新增 `AuditEventRecorder`
3. 新增 `audit.duckdb`
4. 补 run_id / sequence_no / source_channel
5. 建立基础表结构

### Phase 2: 覆盖 CLI 执行链

目标：让 CLI 具备全链路审计。

任务：

1. 记录输入
2. 记录 reasoning
3. 记录 tool start/end/error
4. 记录 HITL request/decision
5. 记录 final output
6. 记录取消与异常

### Phase 3: 覆盖 Web/API

目标：让 Web 审计能力与 CLI 对齐。

任务：

1. 服务端请求初始化 run context
2. SSE 事件服务端镜像落盘
3. 输出聚合和收尾事件

### Phase 4: 开源版查询面与企业扩展预留

目标：完成 `olav log` 产品化查询面，并为企业功能预留扩展点。

任务：

1. 实现 `olav log` 基础命令
2. 增加最近 24 小时窗口查询
3. 增加 run/tool/error 过滤
4. 预留 redaction/export extension points

### Phase 5: 企业版脱敏与训练集导出

目标：在同一审计模型上叠加企业高级能力。

任务：

1. 引入脱敏策略引擎
2. 增加脱敏元数据
3. 导出 SFT JSONL
4. 导出 tool trajectory
5. 导出 ATIF
6. 增加长期保留和归档

## 12. 最低验收标准

当以下条件全部满足，才可认为“全流程可审计”初步达标：

1. 同一条 CLI 请求可从审计数据库回放完整执行顺序。
2. 同一条 Web 请求可从审计数据库回放完整执行顺序。
3. 每次 run 都能看到：输入、流、工具、审批、输出、异常。
4. `olav log` 可以查看最近 24 小时日志，并支持基本过滤。
5. 任何工具失败都能在审计中定位参数、错误和上下文。
6. 企业版可以在同一事件模型上导出至少一种标准训练集格式。

## 13. 推荐结论

当前 OLAV 最需要的不是“增强当前行文本日志”，而是建立统一的审计事件系统，并把它产品化为数据库后端加 `olav log` 查询面。

建议路线：

1. 废弃“命令行文本日志作为主审计源”的思路。
2. 建立项目级 `audit.duckdb` 作为开源版统一审计存储。
3. 使用统一 callback/tracer 和执行层 hook 采集全链路事件。
4. 用 `olav log` 作为开源版默认日志访问入口，默认只暴露最近 24 小时窗口。
5. 将脱敏、训练集生成、长期留存定义为企业高级能力。

需要再次明确：

即使把日志统一存入 DuckDB，也不能把“用户不容易直接看到源文件”当作安全边界。任何有能力直接打开 DuckDB 的用户，也有能力修改代码存储更完整日志。因此，本设计的重点不是“阻止高级用户”，而是定义开源版默认能力边界，并为企业版高级审计能力保留清晰扩展面。

按这个方向演进，OLAV 可以在开源版提供统一、可查询、类设备 logging 的日志体验，同时把脱敏数据集生成、长期留存和高级导出保留为企业能力。
