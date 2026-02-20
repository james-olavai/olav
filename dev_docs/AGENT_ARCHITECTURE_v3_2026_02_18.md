# OLAV Agent 架构 v3 设计方案
**Date**: 2026-02-18  
**Status**: 设计阶段，待实施  
**Version**: v3.2（2026-02-19 Inspection 归属修正）

> **v3.2 变更**：inspection 执行动作（运行/解读/指定设备检查）从 ConfigAgent 移入 OLAVAgent。
> 判断依据：用户触发的运维动作 → OLAVAgent；系统写/调度动作 → ConfigAgent。
> `manage_inspection_schedule`（cron 写操作）仍在 ConfigAgent 的 `olav-config` skill 中。

---

## 背景：v2 架构问题

v2 的 OLAVAgent 承担了所有网络操作（查询 + 巡检 + 快照 + 分析），导致：
- 工具集过大（22个工具），LLM 选择混乱
- snapshot/inspection 是**被动定期任务**，被混在交互式查询 agent 中不合理
- shared/tools/ 成了垃圾堆：13个文件，多数没有 `@tool` 装饰器
- `devices_queries.py` 8个工具全是硬编码 SQL 包装器，`execute_sql` 完全可以替代
- `smart_sql_query` 是 `execute_sql` 的重复子集（120行冗余）
- `network-expert` 和 `network-analysis`、`network-cli` 工具集高度重叠，仅 SKILL.md 文字不同

---

## v3 架构：职责重新分配

### 核心原则

> **运行/读/解读 → OLAVAgent**：所有用户发起的运维动作（执行检查、读报告、解读异常、指定设备检查）  
> **写/调度/配置 → ConfigAgent**：所有系统管理写操作（cron 调度、修改配置、文件写入）  
> **工具去重**：消除所有 SQL 包装器工具，用 `execute_sql` + SKILL.md 策略替代  
> **Skill 合并**：无独特工具的 skill 合并，减少 prompt 噪音  
> **工具独立化**：消除 shared/，每个工具放到使用它的 skill 下

**动词判断表**：

| 用户请求 | 动词 | 归属 |
|---|---|---|
| "帮我检查一下网络" | 运行 inspection | OLAVAgent |
| "R1 的 CPU 高，帮我查" | 运行 + 解读 | OLAVAgent |
| "解读上次的巡检报告" | 读 + 分析 | OLAVAgent |
| "每天凌晨2点自动巡检" | 写 cron | ConfigAgent |
| "修改 inspection 阈值" | 写配置文件 | ConfigAgent |
| "把巡检结果导出 CSV" | 读 + 导出 | OLAVAgent |

---

## 三个 Agent 的职责边界

### 1. OLAVAgent — 查询、运维执行与分析（交互式）

**触发方式**：用户实时提问  
**框架**：LangGraph（需要动态 system prompt 注入 skill 策略）

#### v3.1 工具精简分析

| 工具 | v2 状态 | v3.1 决策 | 理由 |
|------|---------|-----------|------|
| `execute_sql` | ✅ 保留 | ✅ 保留 | 核心工具，替代所有 SQL 包装器 |
| `execute_cli` | ✅ 保留 | ✅ 保留 | 核心工具，实时 CLI 执行 |
| `list_devices_inventory` | ✅ 保留 | ❌ **删除** | DuckDB 已有 hostname/platform/device_role 字段，`execute_sql('SELECT * FROM devices')` 完全替代；2026-02-18 修复 DB 数据后删除 |
| `search_knowledge` | ✅ 保留 | ✅ 保留 | 唯一有独特能力的 expert 工具 |
| `web_search` | ✅ 保留 | ✅ 保留 | 实时信息，无法 SQL 替代 |
| `format_and_export` | ✅ 保留 | ✅ 保留（移至根目录） | 汇总输出是主 Agent 的最后一步 |
| `smart_sql_query` | 保留 | ❌ **删除** | `execute_sql` 的功能子集，120行冗余 |
| `list_devices` | 保留 | ❌ **删除** | `execute_sql("SELECT * FROM devices")` 可替代 |
| `get_device` | 保留 | ❌ **删除** | 硬编码 SQL 包装器 |
| `get_device_interfaces` | 保留 | ❌ **删除** | 硬编码 SQL 包装器 |
| `get_device_capabilities` | 保留 | ❌ **删除** | 硬编码 SQL 包装器 |
| `query_subnet_devices` | 保留 | ❌ **删除** | 硬编码 SQL 包装器 |
| `filter_devices` | 保留 | ❌ **删除** | 硬编码 SQL 包装器 |
| `get_device_status` | 保留 | ❌ **删除** | 硬编码 SQL 包装器 |
| `index_knowledge_files` | 保留 | ❌ **移至 ConfigAgent** | 索引是管理操作，不是查询操作 |
| `get_knowledge_status` | 保留 | ❌ **移至 ConfigAgent** | 同上 |
| `manage_inspection_schedule` | 保留 | ❌ **移至 ConfigAgent** | cron 写操作，系统调度 |
| `take_snapshot` | 新建 | ✅ **属于 OLAVAgent** | 用户触发的运维动作 |
| `aggregate_inspection_results` | 新建 | ✅ **属于 OLAVAgent** | 用户触发的运维动作 |

**精简结果：原 14+ 个工具 → 5 个工具**

#### v3.1 最终工具集（5个）

```
execute_sql                  ← DuckDB 查询 + schema 自动发现（含设备清单查询）
execute_cli                  ← Nornir CLI 执行
take_snapshot                ← 按需巡检（SSH 采集 + 写入 DuckDB）
aggregate_inspection_results ← 聚合 DuckDB 快照数据 + 异常检测
search_knowledge             ← 向量知识库检索
web_search                   ← 实时网络搜索
format_and_export            ← 文件导出（CSV/JSON/Markdown）
```

> **Inspection 完整生命周期在 OLAVAgent 内**：用户说"检查一下网络" → LLM 调 `take_snapshot`（SSH采集）→ 调 `aggregate_inspection_results`（异常分析）→ 直接解读输出。无需跨 Agent 传递。

> **设备清单查询**：`execute_sql("SELECT name, hostname, platform, device_role, site FROM devices")` 替代原 `list_devices_inventory`。DuckDB 已于 2026-02-18 修复，使用 `src/olav/lib/devices_import.py` 从 `hosts.yaml` 导入 6 台真实设备（全字段：hostname, platform, device_role, site）。

#### v3.1 Skill 合并方案

`network-query`、`network-analysis`、`network-cli` 三个 skill **工具集完全相同**（均为 execute_sql + execute_cli + list_devices），区别仅在 SKILL.md 中的 instructions 文字。合并为单一 skill，将策略写在同一份 SKILL.md 内：

```
删除：network-query/, network-analysis/, network-cli/, knowledge-management/, olav-core/, shared/
保留：olav-ops/   ← 合并后的统一运维 skill（含查询策略 + 分析策略 + CLI 策略）
保留：network-expert/  ← search_knowledge 是唯一有独特能力的工具，值得独立 skill
```

**负责的 Skills（精简后）**：
| Skill | 职责 | 工具 |
|-------|------|------|
| `olav-ops` | 网络运维：查询、CLI、分析、导出 | `execute_sql`, `execute_cli`, `format_and_export` |
| `network-inspection` | 巡检执行与报告解读 | `take_snapshot`, `aggregate_inspection_results`（+ execute_sql 读历史） |
| `network-expert` | CCIE 级根因分析 + 知识检索 | `search_knowledge`, `web_search`（+ 共享 execute_sql, execute_cli） |

**注**：`network-expert` 不只查 KB，它本身也有 `execute_sql` + `execute_cli`，可以自己查数据，无需「频繁请求 ops 给数据」。

**工具数量**：7 个（从 v2 的 22 个精简至 7 个）

---

### 2. ConfigAgent — 系统运维（被动 + 主动管理）

**触发方式**：定时任务、用户管理操作  
**框架**：DeepAgents（`create_deep_agent`）

**负责的 Skills**：
| Skill | 职责 | 核心工具 |
|-------|------|---------|
| `olav-config` | 文件/Shell/系统管理 + **调度写操作** | `read_file`, `write_file`, `execute_shell`, `execute_olav`, `web_search`, `manage_inspection_schedule` |

**v3.2 变更（从 v3.1 更新）**：
- `network-inspection` skill **移入 OLAVAgent**（执行是用户触发的运维动作）
- `network-snapshot` skill **移入 OLAVAgent**（`take_snapshot` 是用户触发的运维动作）
- `manage_inspection_schedule` **留在 ConfigAgent**，注册到 `olav-config` skill 下

**ConfigAgent 职责边界（v3.2）**：
- ✅ 设置/修改/删除 cron 调度（`manage_inspection_schedule`）
- ✅ 修改 `inspection_config.yaml`（阈值、平台命令）
- ✅ `olav-config` 文件系统和 Shell 操作（`read_file`, `write_file`, `execute_shell`）
- ✅ `execute_olav` 可以调用任何 olav 子命令
- ❌ **不持有** `take_snapshot` / `aggregate_inspection_results`（归 OLAVAgent）

**工具数量**：约 6 个

---

### 3. CommandLearnerAgent — TextFSM 学习（独立工作流）

**触发方式**：用户手动触发学习流程  
**框架**：DeepAgents（固定 6 步工作流，Human-in-the-Loop）  
**完全独立**：7 个专属工具，不与其他 Agent 共享

工具：`execute_command`, `analyze_output`, `generate_template`, `read_template_file`, `save_template`, `search_ntc_templates`, `browse_ntc_directory`

---

## 关于消除 shared/ 目录

### 现状：shared/tools/ 实际工具盘点

```
.olav/skills/shared/tools/
├── aggregation.py      — 无 @tool，纯内部函数（inspection 用）
├── batch_executor.py   — 无 @tool，内部并行执行器（inspection 用）
├── data_export.py      — ✅ @tool: format_and_export
├── inspection_views.py — 无 @tool，DuckDB view 初始化
├── kb_ops.py           — 无 @tool，空文件
├── kb_tools.py         — ✅ @tool: index_knowledge_files, search_knowledge, get_knowledge_status
├── network_executor.py — 无 @tool，Nornir 单例工厂
├── network_parser.py   — 无 @tool，TextFSM 解析器
├── network.py          — ✅ @tool: nornir_execute, list_devices（但无法加载，相对导入）
├── report_formatter.py — 无 @tool，报告生成函数
├── sync_tools.py       — ✅ @tool: sync_all, get_sync_age（但无法加载，nornir_scrapli 未安装）
```

**注**：`api_client.py` 已于 v3.0 阶段删除（Netbox token 为占位符，无实际使用）。

**结论**：shared/ 里真正被 agent 使用的 `@tool` 只剩 `data_export.py`（`kb_tools.py` 的 `index_knowledge_files`/`get_knowledge_status` 移至 ConfigAgent 后，OLAVAgent 无需再加载）

### 工具归属：消除 shared/ 后的最终目录结构

```
.olav/tools/                         ← root-level（全局通用，所有 Agent 可用）
  database.py                        ← execute_sql
  network.py                         ← execute_cli
  export.py                          ← format_and_export（从 shared/data_export.py 移入）

.olav/skills/
  olav-ops/                          ← 新建，合并 network-query + network-analysis + network-cli
    SKILL.md                         ← 统一策略：查询 + CLI + 分析 + 导出
    [无独有工具，全用 root-level 工具]

  network-expert/tools/
    knowledge_search.py              ← search_knowledge
    [web_search 使用 olav-config 的工具，或复制]

  network-inspection/tools/          ← inspection 专属（归 ConfigAgent）
    aggregation.py                   ← 从 shared 移入
    batch_executor.py                ← 从 shared 移入
    report_formatter.py              ← 从 shared 移入

  network-snapshot/tools/            ← snapshot 专属（归 ConfigAgent）
    sync_tools.py                    ← 从 shared 移入

  olav-config/tools/
    kb_manager.py                    ← index_knowledge_files, get_knowledge_status（从 shared/kb_tools.py 移入）
    [其余工具保持不变]

  ~~删除~~: network-query/, network-analysis/, network-cli/,
            knowledge-management/, olav-core/, shared/
```

### 删除 devices_queries.py 和 smart_sql_query.py 的理由

`devices_queries.py`（425行）和 `smart_sql_query.py`（120行）共 **545行代码全部冗余**：

```python
# get_device 的实际内容——就是一条固定 SQL（代表所有 8 个工具的模式）：
sql = """SELECT device_id, hostname, vendor, device_type, is_active, created_at
         FROM devices WHERE device_id = ? OR hostname = ? LIMIT 1"""
# LLM 完全可以自己写这条 SQL，无需包装器工具
```

`execute_sql` 内置 `explain_only` 模式（自动返回 schema 上下文），`smart_sql_query` 「先查 schema 再生成 SQL」的两步骤已被其完全替代。

**删除列表**：
- `.olav/skills/network-query/tools/devices_queries.py` — 545行，全部冗余
- `.olav/skills/network-query/tools/smart_sql_query.py` — 与 execute_sql 重复
- `.olav/skills/shared/tools/kb_ops.py` — 空文件
- `.olav/skills/shared/tools/network_executor.py` — 无 @tool，内部模块
- `.olav/skills/shared/tools/network_parser.py` — 无 @tool，内部模块
- `.olav/skills/shared/tools/inspection_views.py` — 无 @tool，内部模块

---

## 实施优先级

### Phase 1（无风险，立即可做）：删除冗余工具代码

删除以下文件（工具功能全部由 `execute_sql` 覆盖）：
- `devices_queries.py`（425行）——全部硬编码 SQL 包装器
- `smart_sql_query.py`（120行）——`execute_sql` 的重复子集
- `shared/kb_ops.py`——空文件
- `shared/network_executor.py`、`shared/network_parser.py`、`shared/inspection_views.py`——无 `@tool`，内部模块

### Phase 2（无风险，立即可做）：创建 olav-ops skill

新建 `.olav/skills/olav-ops/SKILL.md`，内容合并自：
- `network-query/SKILL.md` 的查询策略
- `network-analysis/SKILL.md` 的分析策略  
- `network-cli/SKILL.md` 的 CLI 执行策略

合并后删除：`network-query/`、`network-analysis/`、`network-cli/`、`knowledge-management/`、`olav-core/`

### Phase 3（需谨慎）：snapshot/inspection 归 Admin

1. 在 `admin_agent_v3.py` 的 `_load_admin_tools()` 中添加对 `network-inspection/` 和 `network-snapshot/` tools 的扫描
2. 在 `agent.py` 的 `_load_tools()` 中排除这两个 skill 的工具
3. 将 `index_knowledge_files`、`get_knowledge_status` 从 OLAVAgent 工具集移至 ConfigAgent

### Phase 4（需谨慎）：工具文件迁移 + 消除 shared/

- 将 `shared/data_export.py` → `.olav/tools/export.py`
- 将 `shared/aggregation.py`、`batch_executor.py`、`report_formatter.py` → `network-inspection/tools/`
- 将 `shared/sync_tools.py` → `network-snapshot/tools/`
- 将 `shared/kb_tools.py`（保留 `index_knowledge_files`、`get_knowledge_status`）→ `olav-config/tools/kb_manager.py`
- 删除 `shared/` 目录

最终 `.olav/tools/` 状态：
```
.olav/tools/
  database.py   → execute_sql
  network.py    → execute_cli
  inspection.py → manage_inspection_schedule（由 ConfigAgent 加载）
  export.py     → format_and_export（从 shared 移入）
```

---

## SubAgent 扩展性分析（2026-02-18）

### Query Fallback 到 Expert 的机制

SubAgent 是 **stateless + ephemeral**，SubAgent 内部无法调用其他 SubAgent。
Fallback 只能由 **Main Agent 在 system_prompt 中声明策略**，Main Agent 发起第二次 `task` 调用：

```
Main Agent 判断 → task(network-ops) → 结果不足？
                                          ↓ Yes
                                   task(network-expert) → 综合结果
```

**当前 OLAVAgent（7个工具）不需要 SubAgent**——LLM 可以直接在同一个 Agent 中先调 `execute_sql`，结果不足时再调 `search_knowledge`，无需跨 SubAgent 传递。

### Netbox 集成后的数据同步模式

SubAgent 间通过 Main Agent 传递数据（Main Agent 充当「数据变换桥」）：

```
用户："把 DuckDB 的设备数据同步到 Netbox"

Main Agent:
  1. task("查询所有设备，返回完整信息", subagent_type="network-ops")
        └─ execute_sql("SELECT * FROM devices") → 返回数据
  2. [接收数据，构造同步指令]
  3. task("将以下数据写入 Netbox：{...}", subagent_type="netbox")
        └─ query_netbox() + create_device() + update_device() → 完成
```

SubAgent 之间的消息完全隔离（`_EXCLUDED_STATE_KEYS = ("messages", "todos")`），Main Agent 是唯一的数据中转点。

### SubAgent 引入时机

| 场景 | 当前方案 | SubAgent 方案 |
|------|---------|-------------|
| 简单 SQL 查询 | ✅ 直接工具调用，无开销 | ❌ task 调用有额外 LLM 轮次 |
| Query 不足 fallback expert | ✅ 同 Agent 内直接调下一个工具 | ✅ Main 发起第二次 task（过度复杂） |
| 6台设备并行巡检 | ⚠️ 顺序执行 | ✅ 6个 task 并行，线性加速 |
| DuckDB → Netbox 同步 | ✅ ops + netbox 工具顺序调用 | ✅ 两个 SubAgent 独立（Netbox 工具隔离） |
| 100台设备大规模检查 | ❌ 顺序执行太慢 | ✅ SubAgent 并行是必需的 |

**引入时机**：Netbox 接入或设备规模超过 20 台批量操作时，再考虑 SubAgent 架构。

---

## 未来扩展模式（以 Netbox 为例）

**原则**：新功能默认扩展 OLAVAgent，不新建 Agent

```
新增 Netbox 集成：
  .olav/skills/netbox/SKILL.md          ← 描述工作流和使用策略
  .olav/skills/netbox/tools/
    netbox_api.py                        ← query_netbox, sync_netbox_to_duckdb 等

OLAVAgent 的 discover_tools() 自动发现新工具
OLAVAgent 的 _load_skills() 自动加载 SKILL.md 策略
无需修改任何 Python 框架代码
```

**只在以下情况新建 Agent**：
1. 完全不同的工作域（不与网络查询交互）
2. 需要专属的 Human-in-the-Loop 工作流
3. 工具集与现有 Agent 零重叠

---

## 当前状态 vs 目标对比

| 维度 | v2 现状 | v3.2 目标 |
|------|---------|----------|
| OLAVAgent 工具数 | 22 | **7**（+take_snapshot, +aggregate） |
| OLAVAgent Skills 数 | 8（含空 skill） | **3**（olav-ops + network-inspection + network-expert） |
| DB 设备数据 | 80条 mock 数据（旧 schema） | **6台真实设备**（hosts.yaml 同步，新 schema）|
| ConfigAgent 工具数 | 5 | ~6（精简；inspection 执行工具移出） |
| Inspection 执行归属 | 混在 OLAVAgent（v2）→ ConfigAgent（v3.1错误判断） | **OLAVAgent**（用户触发的运维动作）|
| Inspection 调度归属 | 混在 OLAVAgent | **ConfigAgent** olav-config skill（cron 写操作）|
| 冗余 SQL 包装器 | 8 个（425行） | **0**（全部删除） |
| shared/ 文件数 | 11 | **0**（完全消除） |
| 工具位置确定性 | 模糊（shared 是垃圾桶） | 明确（每工具有归属） |
| format_and_export 位置 | shared/tools/ | `.olav/tools/export.py`（根目录）|

---

## v3.3 更新：OLAVAgent 纯调度器 + SubAgents
**Date**: 2026-02-20  
**Status**: ✅ 已实施

### 变更动机

v3.2 的 OLAVAgent 直接持有 10 个工具，LLM 需要在所有工具中选择，增加了推理负担。
v3.3 将 OLAVAgent 改为**纯调度器**：自身只持有 `format_and_export`，通过 DeepAgents 
`SubAgentMiddleware` 将任务分派给专用 SubAgent。

LangChain SQLiteCache 缓存相同查询的 LLM 响应，加速路由。

### v3.3 工具分布

```
OLAVAgent（纯调度器，1 工具）
├── format_and_export          ← 格式化和保存结果

├── SubAgent: network-ops（7 工具）
│   ├── execute_sql            ← DuckDB 查询
│   ├── execute_cli            ← 设备 CLI 命令
│   ├── search_knowledge       ← 知识库检索
│   ├── sync_all               ← 同步设备数据
│   ├── get_sync_age           ← 查询同步时间
│   ├── search_sync            ← 搜索同步数据
│   └── diff_configs           ← 配置对比

└── SubAgent: network-inspection（2 工具）
    ├── take_snapshot          ← SSH 采集 → DuckDB
    └── aggregate_inspection_results  ← 健康评分 + 异常检测

ConfigAgent（独立，写/调度，6 工具）
├── manage_inspection_schedule ← cron 调度
├── write_file, read_file
├── execute_olav, execute_shell
└── web_search
```

### 实施细节

**DeepAgents API**:  
`create_deep_agent(model, tools, system_prompt, checkpointer, store, subagents=[...])`  
`SubAgent(name, description, system_prompt, tools)` — TypedDict，直接传入 subagents 参数

**SubAgent 系统提示位置**:
- network-ops: `.olav/skills/olav-ops/prompts/network_ops_subagent.md`（原 system.md 内容）
- network-inspection: `.olav/skills/network-inspection/prompts/system.md`（已有）
- Orchestrator: `.olav/skills/olav-ops/prompts/system.md`（新写，专注调度）

**LangChain 缓存**:
```python
from langchain_community.cache import SQLiteCache
langchain.llm_cache = SQLiteCache(database_path=".olav/databases/llm_cache.db")
```

**删除的文件**:
- `.olav/skills/olav-ops/tools/snapshot_bridge.py` — take_snapshot 现在由 network-inspection SubAgent 直接加载，桥接文件已不需要

### 数据流

```
用户查询
    │
    ▼
OLAVAgent（调度器）
    │  task() 分派
    ├──────────────► network-ops SubAgent
    │                 → DB/CLI/知识库查询
    │                 → 返回结构化数据
    │
    └──────────────► network-inspection SubAgent
                      → SSH 采集 → DuckDB
                      → 健康评分
                      → 返回报告
    │
    ▼（SubAgent 结果回到调度器）
format_and_export（如需要）
    │
    ▼
用户
```
