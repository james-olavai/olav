# olav-config Agent 重构迁移方案

**版本**: v1.0  
**日期**: 2026-02-20  
**状态**: 📋 方案确认中

---

## 一、核心原则

```
src/olav/
  agents/     ← 框架代码（AgentFactory, SubAgent 基类）
  cli/        ← CLI 入口（typer app, 命令路由）
  core/       ← 最小框架工具（LLM factory, tool_discovery, query_cache）
              ← 不再包含业务逻辑、不再包含数据库操作、不再包含 Nornir

.olav/skills/olav-config/tools/    ← 所有"基础设施"业务逻辑
  sync_schemas.py     ← DB 初始化 + schema 管理   (从 core/database.py 提取)
  sync_inventory.py   ← Nornir → DuckDB 设备同步  (从 core/devices_import.py 提取)
  snapshot.py         ← SSH 数据采集 Map phase     (从 olav-audit 迁移)
  sync_tools.py       ← ACE 引擎 + Stage 2 解析   (从 olav-audit 迁移)
  manage_cron.py      ← Snapshot 调度             (inspection_scheduler.py 重命名/简化)
  sync_commands.py    ← CommandRegistry 刷新      (从 core/command_registry.py 提取)
  command_executor.py ← 已存在，保留
  read_file.py        ← 已存在，保留
  write_file.py       ← 已存在，保留
  web_search.py       ← 已存在，保留
  kb_manager.py       ← 已存在，保留（依赖 LLMFactory，LLMFactory 留在 core/）
```

**禁止模式**:
- ❌ `olav_executor.py` — 包装 `uv run olav xxx` 的子进程工具（删除）
- ❌ `src/olav/core/database.py` 里的业务逻辑被 skill tools 通过框架 import 调用
- ❌ skill tools 里 `from olav.core.database import get_database` 散落各处

---

## 二、现状盘点

### 2.1 `src/olav/core/` 各文件的归宿

| 文件 | 当前用途 | 迁移方向 |
|------|---------|---------|
| `database.py` | DB 连接 + schema 初始化 | `_db_client()` 辅助函数留 core（纯连接），schema 定义迁移到 `olav-config/tools/sync_schemas.py` |
| `devices_import.py` | Nornir hosts.yaml → DuckDB | 合并到 `olav-config/tools/sync_inventory.py` 作为 `@tool` |
| `command_registry.py` | TextFSM 模板扫描 + hot-reload | 重构为 `olav-config/tools/sync_commands.py`；`_resolve_commands_for_categories()` 调用它 |
| `registry.py` | v2.0 兼容存根 | **删除**（stub，无实际用途） |
| `tool_discovery.py` | `@tool` 自动发现 | ✅ 留 core（框架核心） |
| `llm.py` | LLM 工厂 | ✅ 留 core（框架核心） |
| `query_cache.py` | SQL 语义缓存 | ✅ 留 core（olav-ops 使用，框架工具） |
| `knowledge/` | 知识库工具 | ✅ 留 core（olav-ops/kb 使用） |

### 2.2 `olav-config/tools/` 现有文件问题

| 文件 | 问题 | 处理 |
|------|------|------|
| `olav_executor.py` | 包装 `uv run olav` 子进程 ❌ | **删除** |
| `inspection_scheduler.py` | 功能用 cron 调度，但名字耦合 inspection | 重命名为 `manage_cron.py`，泛化为任意 job 调度 |
| `kb_manager.py` | 依赖 `LLMFactory`（留 core） | ✅ 保留 |
| `command_executor.py` | execute shell | ✅ 保留 |

### 2.3 skills 中 `from olav.core.database import get_database` 分布

```
olav-audit/tools/sync_tools.py        ×6 处
olav-audit/tools/audit_runner.py      ×1 处
olav-audit/tools/schema_inspector.py  ×1 处
network-inspection/tools/sync_tools.py ×5 处（待删除）
network-inspection/tools/_run_inspection.py ×3 处（待删除）
```

**解决方案**: 在 `sync_tools.py` / `audit_runner.py` 内部封装 `_get_db()` 辅助函数，
不对外散落 import。`core/database.py` 保留 `get_database()` 接口（连接入口），
但 schema 定义和业务初始化移出。

---

## 三、目标架构

```
执行流程（正确的职责分离）
═══════════════════════════════════════════════════════════

olav-config agent（基础设施层 / Infrastructure）
─────────────────────────────────────────────
                    Cron A: 每天 02:00
  sync_schemas()    └─ 建/确认所有表 schema（6 张表）
  sync_inventory()  └─ 从 hosts.yaml → devices 表
  sync_commands()   └─ 扫描 .olav/templates/ + NTC
                        → commands 表（持久化注册表）
                        → schema_catalog 表（JSON 字段索引）
  take_snapshot()   └─ SSH 采集，读 commands 表确定执行命令
                        → parsed_outputs 表（JSON blob）
                        → exports/snapshots/{date}/raw/（原始文本）
                        → topology_links 表（CDP/LLDP 链路）
                        → sync_metadata 表（采集元数据）
  manage_cron()     └─ 管理 Cron A 本身的调度

                             │
                             ▼ 共享 DuckDB（只读）

olav-audit agent（治理层 / Governance — 只读 DB）
─────────────────────────────────────────────
                    Cron B: 每小时 / 每天按类型
  run_audit()       └─ 加载 AUDIT_*.yaml 规则
  rule evaluation   └─ structured: 查 parsed_outputs (JSON blob)
                    └─ raw_contains: 读 exports/snapshots/ 文件
  LLM 分析          └─ 根因分析 + 报告生成
  manage_cron()     └─ 管理 Cron B 本身的调度

  写入 → exports/reports/audit_*.md（全量报告）
  写入 → .olav/knowledge/alerts/（仅 CRITICAL 结果入 KB）
  ❌ 不写 audit_results 表（噪音太多，按需入 KB）
  ❌ 不调用 take_snapshot（audit 不拥有采集能力）

─────────────────────────────────────────────
olav-ops agent（查询层 / Query）
─────────────────────────────────────────────
  启动时: SELECT * FROM schema_catalog → 加载到内存
  查询时: LLM 基于 schema_catalog 知道 JSON 字段名
          → 生成 data->>'field' 形式的 DuckDB JSON 查询

─────────────────────────────────────────────
src/olav/（框架层 / Framework — 不含业务逻辑）
  agents/agent.py        轻量 AgentFactory
  cli/cli_app.py         typer 入口，路由到 agent 或 admin
  core/llm.py            LLMFactory
  core/tool_discovery.py @tool 自动发现
  core/database.py       纯连接封装（get_database()，无 schema 业务逻辑）
  core/query_cache.py    语义缓存
```

### 3.1 DuckDB 表一览

| 表名 | 写入者 | 读取者 | 保留策略 |
|------|--------|--------|----------|
| `devices` | sync_inventory | 所有 agent | 永久，随 hosts.yaml 更新 |
| `commands` | sync_commands | snapshot, olav-ops | 永久，随模板更新 |
| `schema_catalog` | sync_commands | olav-ops（启动加载） | 永久，随模板更新 |
| `parsed_outputs` | take_snapshot | olav-audit, olav-ops | 时序，可按日期滚动清理 |
| `topology_links` | take_snapshot | olav-ops | 永久 + 历史变更追踪 |
| `sync_metadata` | sync_tools | olav-config, olav-ops | 时序 |
| ~~`audit_results`~~ | ~~olav-audit~~ | ~~-~~ | **删除 — 改写 KB** |

---

## 四、迁移步骤（分 Phase）

### Phase B1 — 删除 `olav_executor.py`

**任务**: 删除 `olav-config/tools/olav_executor.py`

**原因**:
- 它通过 `subprocess` 调用 `uv run olav ask/admin/...`
- 这违反了"工具直接调用 Python 函数"的原则
- config agent 有 `command_executor.py` 可以执行任意 shell（必要时用）
- config agent 的 `@tool` 函数应该直接调用 Python，不通过 olav CLI

**影响检查**:
```bash
grep -r "execute_olav" .olav/skills/ --include="*.py"
```

---

### Phase B2 — 新建 `olav-config/tools/sync_schemas.py`

从 `src/olav/core/database.py` 提取 schema 初始化逻辑：

```python
@tool
def sync_schemas(force_recreate: bool = False) -> dict:
    """Create or migrate all OLAV DuckDB table schemas.
    
    Creates tables: devices, parsed_outputs, topology_links, audit_results.
    Safe to call repeatedly — uses CREATE TABLE IF NOT EXISTS.
    Call this after OLAV installation or schema updates.
    """
    from olav.core.database import get_database
    db = get_database()
    # db.__init__ 已经调用 _init_schema() — 直接调用即可触发
    # 但要新增 audit_results 表（目前不在 database.py 中）
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_results (
            id INTEGER PRIMARY KEY DEFAULT nextval('audit_results_id_seq'),
            audit_name VARCHAR NOT NULL,
            audit_type VARCHAR,
            device_name VARCHAR,
            rule_name VARCHAR,
            status VARCHAR NOT NULL,
            severity VARCHAR,
            detail JSON,
            snapshot_date DATE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.conn.commit()
    return {"status": "success", "message": "DB schema initialized"}
```

---

### Phase B3 — 新建 `olav-config/tools/sync_inventory.py`

将 `src/olav/core/devices_import.py` 包装为 `@tool`：

```python
@tool
def sync_inventory() -> dict:
    """Sync device inventory from Nornir hosts.yaml into DuckDB devices table.
    
    Call this when:
    - First time setting up OLAV
    - After adding/removing devices from hosts.yaml
    - Before take_snapshot() to ensure device list is current
    
    Returns: { "imported": int, "errors": int }
    """
    from olav.core.devices_import import import_devices_from_nornir
    # ...
```

---

### Phase B4 — 迁移 `snapshot.py` + `sync_tools.py` 最终落地

`olav-audit/tools/snapshot.py` + `sync_tools.py` 已经在上一阶段迁移过来。  
在 `olav-config/tools/` 中也放一份（或让 audit 直接从 config 调用）。

**最终状态**:
- `olav-config/tools/snapshot.py` — 主版本，olav-config 负责运行
- `olav-audit/tools/snapshot.py` — **删除**，audit 不收集数据
- `olav-audit/tools/sync_tools.py` — **删除**，audit 只读 DB

---

### Phase B5 — 更新 SKILL.md 和 OLAV.md

`olav-config/SKILL.md` tools 列表更新：
```yaml
tools:
  - sync_schemas           # NEW
  - sync_inventory         # NEW（从 devices_import 提取）
  - take_snapshot          # NEW（从 audit 迁移）
  - sync_commands          # NEW（从 command_registry 提取）
  - manage_cron            # 已有（inspection_scheduler 重命名）
  - read_file              # 已有
  - write_file             # 已有
  - execute_shell          # 已有（command_executor）
  - web_search             # 已有
  - kb_manager             # 已有
```

---

### Phase C — 清理 `src/olav/core/`

完成 B 系列后，`src/olav/core/` 最终状态：

```
core/
  __init__.py          ← 保留（最小化）
  database.py          ← 保留，但仅作连接封装（OlavDatabase + get_database()）
                          schema 业务逻辑已移到 sync_schemas.py
  llm.py               ← 保留
  tool_discovery.py    ← 保留
  query_cache.py       ← 保留
  devices_import.py    ← 保留（被 sync_inventory.py 调用，或内联进去后删除）
  command_registry.py  ← 保留（被 sync_commands.py 调用）
  registry.py          ← 删除（v2.0 stub，无用）
  knowledge/           ← 保留（ollama-ops 使用）
```

---

## 五、当前 `olav_executor.py` 问题详解

**现状**:
```python
@tool
def execute_olav(command: str, timeout: int = 60) -> dict:
    """Execute OLAV CLI command (convenience wrapper for testing)."""
    full_cmd = ["uv", "run", "olav"] + command.split()
    result = subprocess.run(full_cmd, ...)
```

**问题**:
1. 启动子进程 = 启动新的 Python 解释器 + 新的 DeepAgents session，性能差
2. 结果只有 stdout/stderr 字符串，没有结构化数据
3. 循环依赖风险：olav-config agent 调用 `olav ask`，后者再调用 config agent
4. 违反"tools 直接调用 Python 函数"原则

**替代方案**:
- 测试 OLAV 功能 → 直接调用对应函数：`execute_sql("SELECT ...")`, `sync_inventory()`
- 需要 shell 命令 → `command_executor.py: execute_shell("cmd")`
- 不需要 `execute_olav` 存在

---

## 六、影响矩阵

| skill | 变更前 | 变更后 |
|-------|--------|--------|
| olav-config | execute_olav（子进程） | 直接 @tool 函数 |
| olav-audit | owns snapshot.py + sync_tools.py | 只读 DB，不收集数据 |
| olav-ops | 依赖 core/llm.py, core/query_cache.py | 不变 |
| command_learner | 依赖 core/command_registry.py | 改为调用 config 的 sync_commands |
| network-inspection | 全部工具 | **整体删除** |

---

## 七、优先级排序

```
✅ 已完成（2026-02-20）：
  1. ✅ 删除 olav_executor.py（子进程包装器）
  2. ✅ 更新 SKILL.md / system.md / OLAV.md — 清除 execute_olav 引用
  3. ✅ 新建 sync_schemas.py（@tool，DB schema 管理）
  4. ✅ 新建 sync_inventory.py（@tool，包装 devices_import）
  5. ✅ 新建 sync_commands.py（@tool，包装 CommandRegistry.reload()）
  6. ✅ 复制 snapshot.py + sync_tools.py + get_current_datetime.py 到 olav-config/tools/
  7. ✅ 更新 OLAV.md SubAgents 表 + Skills 表，移除 network-inspection 行

🔧 DB Schema 修正（最高优先级）：
  8. 修改 sync_schemas.py — 删除 audit_results 表，新增 commands + schema_catalog + sync_metadata
  9. 修改 sync_commands.py — 新增写 commands 表 + schema_catalog 表（TextFSM Value 解析）
  10. 修改 snapshot.py/_resolve_commands_for_categories — 从 commands 表读命令（DB as source of truth）
  11. 修改 olav-ops/tools/database.py/SchemaContext — schema_context 加入 schema_catalog 的 JSON 字段信息

🔧 olav-audit 只读化：
  12. 修改 audit_runner.py — 删除 Step 2（snapshot 调用），无数据时返回说明而非报错
  13. 修改 audit_runner.py — CRITICAL 结果调用 kb_manager.add_entry() 入 KB
  14. 删除 olav-audit/tools/snapshot.py（audit 不采集）
  15. 删除 olav-audit/tools/sync_tools.py（audit 不写 DB）

后续清理：
  16. 删除 src/core/registry.py（stub，无用）
  17. 内联 devices_import.py 进 sync_inventory.py 后删除原文件
  18. 删除 network-inspection/ 整个 skill
  19. 重命名 inspection_scheduler.py → manage_cron.py

✅ 额外完成（2026-02-20）：
  20. ✅ 删除 olav-ops SKILL.md 中的 take_snapshot（属于 olav-config，ops 不拥有采集能力）
  21. ✅ 更新 olav-ops system.md — 删除 network-inspection SubAgent 引用
  22. ✅ 修改 olav-ops/tools/network.py → 重命名为 execute_cli.py，新增 _validate_command()
        → 读 commands 表，blacklisted=true 时拒绝执行
        → 命令含 | 但 pipe_allowed=false 时拒绝执行
        → commands 表不存在时 graceful degradation（只报 warning，不阻断）
  23. ✅ 重命名 olav-ops/tools/ 4 个文件，文件名与 @tool 函数名统一
        database.py → execute_sql.py
        network.py  → execute_cli.py
        export.py   → format_and_export.py
        knowledge_search.py → search_knowledge.py
  24. ✅ 新建 olav-ops/tools/search_commands.py
        → 按 device/platform + keyword 查 commands 表
        → 替代"一次性读取整个命令列表"，实现按需搜索
        → 确立 LLM 工作流：search_commands → 挑选 → execute_cli
  25. ✅ 新建 olav-ops/tools/take_snapshot.py（独立实现，非 bridge）
        → 针对排错场景：指定设备 + 指定命令，并行采集
        → 结果写入 parsed_outputs + raw 文件，供 execute_sql 后续查询
        → 与 olav-config 的 take_snapshot 职责区分：
          olav-config = Cron A 全量快照
          olav-ops = 排错时按需靶向快照
```


---

## 八、DuckDB Schema 完整设计

### 8.1 最终表一览

| 表名 | 写入者 | 读取者 | 保留策略 |
|------|--------|--------|----------|
| `devices` | sync_inventory | 所有 agent | 永久，随 hosts.yaml 更新 |
| `commands` | sync_commands | snapshot, olav-ops | 永久，随模板更新 |
| `schema_catalog` | sync_commands | olav-ops（启动加载） | 永久，随模板更新 |
| `parsed_outputs` | take_snapshot | olav-audit, olav-ops | 时序，可按日期滚动清理 |
| `topology_links` | take_snapshot | olav-ops | 永久 + 历史变更追踪 |
| `sync_metadata` | sync_tools | olav-config, olav-ops | 时序 |
| ~~`audit_results`~~ | ~~olav-audit~~ | — | **删除 — 改写 KB** |

### 8.2 `commands` 与 `schema_catalog` 的关系

两张表是**平行兄弟表**，由 `sync_commands()` 同时写入，共享逻辑键 `(command_name, platform)`，但无 FK 约束：

```
commands                             schema_catalog
─────────────────────────────────────────────────────────
command_name ←── 逻辑关联 ──── source_name   (source_type='textfsm')
platform     ←── 逻辑关联 ──── platform
category           │                 fields       ← schema_catalog 独有
template_path      │                 source_type  ← schema_catalog 独有
allowed            │
blacklisted        │
pipe_allowed       │               ← commands 独有（CLI 灰度命令控制）
                   └─ 两张表各自独立，无 FK
```

**职责划分**：
- `commands` 回答 **"该不该跑、能不能跑、能不能加管道过滤"** — snapshot 和 CLI 直接读这张表
- `schema_catalog` 回答 **"输出解析出了哪些字段"** — 只有 olav-ops LLM SQL 生成读这张表

**snapshot 的查询**（`_resolve_commands_for_categories`）:
```sql
-- snapshot 只执行精确命令：allowed=true, blacklisted=false
-- 注意 snapshot 不关心 pipe_allowed（只执行原始命令，不加管道）
SELECT command_name, template_path, has_template
FROM commands
WHERE platform IN ('cisco_ios', '*')
  AND category IN ('routing', 'bgp')
  AND allowed = true
  AND blacklisted = false
ORDER BY command_name;
```

**CLI 命令白名单建议**（olav-ops）:
```sql
-- 查出允许的命令及是否支持管道过滤
SELECT command_name, category, has_template, pipe_allowed
FROM commands
WHERE platform = 'cisco_ios'
  AND allowed = true
  AND blacklisted = false
ORDER BY category, command_name;
-- pipe_allowed=true  → LLM 可生成: "show run | include neighbor"
-- pipe_allowed=false → LLM 只能原样执行: "show version"
```

以上两个场景均**不需要 `schema_catalog`**，直接读 `commands` 表即可。
`schema_catalog` 仅在 LLM 需要组装 `parsed_data->>'field'` 查询时才使用。

### 8.3 `commands` 表 — 命令注册表（持久化）

```sql
CREATE TABLE IF NOT EXISTS commands (
    command_name   VARCHAR NOT NULL,
    platform       VARCHAR NOT NULL,    -- 'cisco_ios' | 'juniper_junos' | '*'
    category       VARCHAR,             -- 'system' | 'routing' | 'interfaces' ...
    template_path  VARCHAR,             -- 模板文件完整路径，NULL = raw only
    has_template   BOOL DEFAULT FALSE,
    allowed        BOOL DEFAULT TRUE,   -- 来自 .olav/templates/config/allowed_commands.yaml
    blacklisted    BOOL DEFAULT FALSE,  -- 来自 .olav/templates/config/blacklisted_commands.yaml
    pipe_allowed   BOOL DEFAULT FALSE,  -- 来自 allowed_commands.yaml 的 pipe 字段
    updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (command_name, platform)
)
```

**配置文件布局**（黑名单 / 白名单统一放 templates 目录，和模板并列）:
```
.olav/templates/
├── cisco_ios/              ← TextFSM 模板（ntc-templates 或自定义）
├── juniper_junos/
└── config/                 ← 命令控制配置（与模板同根，sync_commands 一起扫）
    ├── allowed_commands.yaml
    └── blacklisted_commands.yaml
```

`allowed_commands.yaml` 示例：
```yaml
- command: show ip ospf neighbor
  platforms: [cisco_ios, cisco_xe]
  pipe_allowed: false      # 精确命令，snapshot 和 CLI 都不加管道

- command: show running-config
  platforms: [cisco_ios, cisco_xe]
  pipe_allowed: true       # CLI/LLM 可追加 "| include ..." 等过滤

- command: show interfaces
  platforms: ['*']
  pipe_allowed: false
```

**三态语义**（`allowed` × `blacklisted` × `pipe_allowed`）：

| allowed | blacklisted | pipe_allowed | 含义 |
|---------|-------------|--------------|------|
| true    | false       | false        | ✅ 精确执行（snapshot + CLI，原样执行，不加管道） |
| true    | false       | true         | ✅ 灰度命令（CLI/LLM 可追加 `\| filter`，snapshot 仍只执行原始命令） |
| false   | false       | -            | ⚠️ 未分类（扫到模板但未在 allowed 列表，olav-ops 不建议） |
| *       | true        | -            | ❌ 永久禁止（blacklisted 优先于 allowed，CLI 和 snapshot 均拒绝） |

**写入时机**: `sync_commands()` 扫模板 + 读 `config/*.yaml` → upsert  
**读取者**:
- `snapshot.py` — 按 `(platform, category, allowed=true, blacklisted=false)` 查询，只执行原始命令（忽略 pipe_allowed）
- olav-ops — 同上查询，`pipe_allowed` 字段传给 LLM system prompt，告知哪些命令可追加管道过滤

### 8.4 `schema_catalog` 表 — JSON 字段结构索引（永久）

```sql
CREATE TABLE IF NOT EXISTS schema_catalog (
    source_type    VARCHAR NOT NULL,   -- 'textfsm' | 'openapi' | 'custom'
    source_name    VARCHAR NOT NULL,   -- 命令名 e.g. 'show ip ospf neighbor'
                                       -- 或 API path e.g. '/api/v1/devices'
    platform       VARCHAR NOT NULL,   -- 'cisco_ios' | 'juniper_junos' | '*'
    fields         JSON NOT NULL,      -- [{"name":"neighbor_id","type":"str"}, ...]
    description    VARCHAR,
    updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (source_name, platform, source_type)
)
```

**为什么重要**: `parsed_outputs.parsed_data` 是 JSON blob，LLM 看 `DESCRIBE parsed_outputs`
只能看到一列 `parsed_data JSON`，不知道里面有 `neighbor_id`、`state` 等字段，无法生成
正确 SQL。`schema_catalog` 解决这个问题，让 ops agent 的 SQL 生成从猜字段名变成查表。  
**唯一读取者**: olav-ops `SchemaContext`（启动时全量加载到内存）。

**DuckDB JSON 查询方式**（olav-ops 生成的 SQL 目标形式）:

```sql
SELECT
    device_name,
    parsed_data->>'neighbor_id'  AS neighbor_id,
    parsed_data->>'state'        AS state,
    parsed_data->>'dead_time'    AS dead_time
FROM parsed_outputs
WHERE command = 'show ip ospf neighbor'
  AND snapshot_date = CURRENT_DATE
ORDER BY device_name, neighbor_id;
```

**未来 OpenAPI 支持**: 将 `openapi.yaml` 的 paths/responses 解析后写入 `schema_catalog`
（`source_type='openapi'`），ops agent 同一套机制即可支持 API 数据查询。

### 8.5 `topology_links` — 保留独立表

保留独立表的理由：链路是**结构性数据**，带 `first_seen`/`last_seen`/`status_changes`
历史追踪，不适合混入时序 blob。现有 schema 定义良好，保留不变。

### 8.6 `sync_metadata` — 移入 sync_schemas 统一管理

当前由 `sync_tools.py` 在运行时 `CREATE TABLE IF NOT EXISTS`（临时创建）。
需要移入 `sync_schemas.py` 统一定义，确保表在首次 sync 之前已存在。

---

## 九、工具对齐检查

### 9.1 `sync_schemas.py` ← 需要修改

| 变更 | 方向 |
|------|------|
| 删除 `audit_results` 表及其 sequence | audit 不写 DB |
| 新增 `commands` 表 DDL | 命令注册表持久化 |
| 新增 `schema_catalog` 表 DDL | JSON 字段索引 |
| 新增 `sync_metadata` 表 DDL | 从 sync_tools 运行时创建移到这里 |
| 返回值 tables 列表更新 | 同步 |

### 9.2 `sync_commands.py` ← 需要修改

**当前行为**: 只调用 `CommandRegistry.reload()`（内存刷新），不写 DB  
**目标行为**: 额外 upsert `commands` 表 + `schema_catalog` 表

写入逻辑分两步：
1. 扫 TextFSM 模板目录 → upsert `commands`（has_template=true）+ upsert `schema_catalog`
2. 读 `.olav/templates/config/allowed_commands.yaml` → 更新 `allowed` / `pipe_allowed`
3. 读 `.olav/templates/config/blacklisted_commands.yaml` → 更新 `blacklisted=true`

需新增 TextFSM Value 解析逻辑:

```python
def _parse_textfsm_fields(template_path: str) -> list[dict]:
    import re
    fields = []
    with open(template_path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            m = re.match(r'^Value\s+(?:List\s+|Filldown\s+|Required\s+)*(\w+)', line)
            if m:
                fields.append({"name": m.group(1).lower(), "type": "str"})
    return fields
```

然后在 `CommandRegistry.reload()` 之后，遍历所有模板 upsert `commands` 和 `schema_catalog`。

### 9.3 `snapshot.py` ← 需要修改（优先级较低）

**函数**: `_resolve_commands_for_categories(platform, categories)`  
**当前行为**: 扫描文件系统 + NTC 包 → 内存 CommandRegistry  
**目标行为**: 优先查 `commands` 表（DB as source of truth）；DB 为空时回退到文件扫描

```python
# 修改逻辑:
# 1. SELECT command_name FROM commands
#    WHERE platform IN (?, '*') AND blacklisted=false AND category IN (?, ...)
# 2. 若结果为空（首次启动，sync_commands 未运行）→ 回退到现有文件扫描逻辑
```

### 9.4 `olav-ops/tools/database.py` ← 需要修改

**类 `SchemaContext._refresh_schema()`**  
**当前行为**: `INFORMATION_SCHEMA` + `DESCRIBE table` → 只能看到 `parsed_data JSON` 列名  
**目标行为**: 额外查 `schema_catalog` → 将每个 command 的 fields 加入 schema_context

```python
# 在 _refresh_schema() 末尾追加:
try:
    catalog_rows = db_query(
        "SELECT source_name, platform, fields FROM schema_catalog "
        "WHERE source_type = 'textfsm' ORDER BY source_name"
    )
    if catalog_rows:
        schema_catalog_info = []
        for row in catalog_rows:
            fields = row.get('fields', [])
            if isinstance(fields, str):
                import json as _json
                fields = _json.loads(fields)
            field_names = [f['name'] for f in (fields or [])]
            schema_catalog_info.append(
                f"  {row['source_name']} ({row['platform']}): {', '.join(field_names)}"
            )
        self._schema_cache['schema_catalog'] = schema_catalog_info
except Exception:
    pass  # schema_catalog 尚未填充，跳过
```

`get_schema_context()` 需要追加 schema_catalog 块，让 LLM 看到：

```
**parsed_outputs JSON fields (via schema_catalog):**
  show ip ospf neighbor (cisco_ios): neighbor_id, priority, state, dead_time, address, interface
  show interfaces (cisco_ios): interface, link_status, protocol_status, hardware_type, ...
  Query pattern: SELECT parsed_data->>'field_name' FROM parsed_outputs WHERE command='...'
```

**影响**: LLM 能正确生成 `parsed_data->>'field'` 形式的 JSON 查询，不再猜列名。

### 9.5 `olav-audit/tools/audit_runner.py` ← 需要修改

**变更 1 — 删除 Step 2（snapshot 调用）**

```python
# 删除（约 15 行）:
# categories = _intents_to_categories(config.collect.intents)
# snapshot_result = _take_snapshot.func(devices=devices, categories=categories, wait=True)

# 改为: 直接读 DB
sql_rows = _query_parsed_outputs(devices=devices)
if not sql_rows:
    return {
        "status": "no_data",
        "message": (
            "No parsed_outputs found for today. "
            "Run take_snapshot() first via olav-config agent, "
            "or check if Cron A is scheduled (daily 02:00)."
        ),
    }
```

**变更 2 — CRITICAL 结果写 KB**（Step 6 写 markdown 之后）:

```python
if result.get('critical_count', 0) > 0:
    try:
        _config_tools = str(_PROJECT_ROOT / ".olav" / "skills" / "olav-config" / "tools")
        if _config_tools not in sys.path:
            sys.path.insert(0, _config_tools)
        from kb_manager import add_knowledge_entry
        _title = f"[{audit_name}] Critical findings {datetime.now().strftime('%Y-%m-%d')}"
        _content = _format_critical_section(result, config)  # 需新增辅助函数
        add_knowledge_entry(title=_title, content=_content,
                           tags=["audit", "critical", audit_name.lower()])
    except Exception as exc:
        logger.warning("KB write failed (non-fatal): %s", exc)
```

### 9.6 `olav-audit/tools/snapshot.py` ← 删除

audit 遗留文件。audit 是只读层，数据由 olav-config 的 Cron A 或手动 `take_snapshot()` 提供。

### 9.7 `olav-audit/tools/sync_tools.py` ← 删除

audit 遗留文件（ACE + TextFSM 解析 + DB 写入）。采集和解析只在 olav-config 层发生。

### 9.8 `olav-audit/tools/schema_inspector.py` ← 可简化（非紧急）

当前 957 行，运行时动态扫描 `parsed_outputs` JSON keys 发现字段名。  
`schema_catalog` 建成后，`discover_field()` 可优先查 `schema_catalog` 再 fallback。  
优先级低，现有逻辑可继续工作，等 schema_catalog 稳定后再简化。
