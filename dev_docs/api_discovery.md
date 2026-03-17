# 语义感知型动态数据集成引擎 — 设计文档

**状态**: 设计草案 v0.4（补充 OpenAPI 读写分流、写操作 HMITL 与控制面审批模型）  
**日期**: 2026-03-17  
**归属**: config agent → discovery 子 Agent

---

## 1. 背景与定位

### 1.1 解决的问题

OLAV 接入新系统（新厂商设备 / NMS / SDN 控制器）时，存在以下痛点：

| 痛点 | 当前状态 | 目标状态 |
|:--|:--|:--|
| 新厂商字段映射 | 工程师手工维护 `normalization_strategy.yaml` | 向量相似度自动分类，仅边界情况调 LLM |
| OpenAPI 系统接入 | 无机制 | 解析 openapi.yaml 自动生成 schema 映射与域 agent 脚手架 |
| 跨厂商归一化视图 | 无动态 VIEW | DuckDB VIEW 自动生成和维护 |
| Schema 演进 | 完全手动 | 聚类发现新模式，人工门控审核 |

### 1.2 与现有 discovery 子 Agent 的关系

本设计是对 **config → discovery 子 Agent** 的能力升级，不是新建系统：

```
config-orchestrator (AGENT.md)
└── discovery / SKILL.md          ← 当前：fuzzy_map_schema (LLM-only)
    └── [本设计升级后]
        ├── classify_field         ← 新增：向量优先分类（替代纯 LLM 路径）
        ├── register_api_schema    ← 新增：OpenAPI 接入
        ├── create_unified_view    ← 新增：自动生成 DuckDB VIEW
        └── trigger_schema_evolve  ← 新增：演进层触发（人工门控）
```

### 1.3 TextFSM 字段与语义分类引擎的边界

> **核心结论**：TextFSM 字段**不应**走「在线实时分类」路径，而应走**离线批量扫描**路径。

#### 为什么不在采集热路径里分类

TextFSM 模板的 header 在模板编写时就已确定，字段名由模板作者主导，不是"未知的外部 API"。在
`_process_sync_stage2` 中实时跑向量分类会引入：

- 延迟（单次采集需额外 N×embed 调用）
- 不确定性（相同字段名每次可能得不同 `standard_name`）
- 错误放大（分类错误直接污染 `parsed_data` 写入）

#### 真正需要解决的问题：NTC legacy 模板命名不一致

NTC templates 跨厂商命名存在大量语义重复但名称不同的字段：

```
cisco_ios  show ip bgp neighbors  → BGP_NEIGHBOR   (字段名)
juniper    show bgp neighbor      → PEER_ADDRESS
arista     show ip bgp neighbors  → PEER
```

**解法**：一次性离线扫描，将结果固化为 `schema_mappings`，查询时通过 `v_unified_*` VIEW 做映射，
完全绕开热路径。

#### 两条路径对比

| 路径 | 触发时机 | 写入目标 | 错误影响 |
|:--|:--|:--|:--|
| **在线分类**（本文档主路径）| 接入新 OpenAPI 系统时 | `schema_mappings` | 仅映射层，可回滚 |
| **离线批量扫描**（TextFSM 专用）| `olav-netops init` / `olav workspace upgrade` | `schema_mappings` | 预生产验证，可回滚 |

#### TextFSM 字段与 LanceDB 的反向关系

TextFSM 标准字段库（`STANDARD_FIELDS`）是 `<domain>_field_mappings` 集合的**初始 bootstrap 来源**，
而不是分类的待分类目标：

```
olav-netops init
  ├─ 扫描所有 *.textfsm 模板 header（离线）
  ├─ 对每个 header 字段构建语义摘要
  ├─ 调用 schema_engine.classify_field()（批量、静默）
  │    confidence > 0.85 → 写 schema_mappings（vendor/command/raw_key → standard_name）
  │    confidence < 0.85 → 写 pending（人工确认）
  └─ 生成初始 v_unified_* VIEW（供跨厂商查询）
```

新模板编写时，`classify_field()` 还可作为 **DX 辅助工具**（非强制）：在 `olav learn_cmd` 流程
中建议与已有标准字段对齐的命名，降低未来跨厂商 VIEW 的维护负担。

---

## 2. 系统架构

```
                    ┌─────────────────────────────────────┐
                    │  输入源 (Ingestion Sources)          │
                    │  - 设备 CLI (现有 TextFSM 路径)      │
                    │  - openapi.yaml (新增 REST API 路径)  │
                    └──────────────┬──────────────────────┘
                                   │ 字段元数据
                                   ▼
┌──────────────────────────────────────────────────────────────────┐
│  解析层  (Metadata Extractor)                                     │
│  - CLI:  TextFSM → parsed_data JSON (现有流程，不变)             │
│  - API:  prance/openapi-spec-validator → field_metadata JSON      │
└──────────────────────────────────────────────────────────────────┘
                                   │ 字段语义摘要
                                   ▼
┌──────────────────────────────────────────────────────────────────┐
│  语义索引层  (LanceDB — <domain>_field_mappings 集合)            │
│                                                                  │
│   ① 向量化: bge-small-en-v1.5 (复用 get_embedder() 单例)         │
│                                                                  │
│   ② 分级分流:                                                    │
│      confidence > 0.85 ──────→ 自动匹配标准字段   (Tier 0)       │
│      0.60 ≤ confidence ≤ 0.85 → LLM 二轮确认     (Tier 1)       │
│      confidence < 0.60 ─────→ unclassified 暂存  (Tier 2 待演进) │
│                                                                  │
│   ③ 生成变更请求 → schema mutation staging / service            │
└──────────────────────────────────────────────────────────────────┘
                                   │ 映射关系
                                   ▼
┌──────────────────────────────────────────────────────────────────┐
│  执行层  (DuckDB — 统一视图 + 原始存储)                           │
│                                                                  │
│  parsed_outputs (现有宽表)                                       │
│  ├── parsed_data::JSON   ← 所有字段，含特殊字段                  │
│  └── schema_mappings     ← 字段映射缓存 (vendor/command/raw_key) │
│                                                                  │
│  v_unified_{command} (动态 VIEW，由 create_unified_view 生成)    │
│  └── CAST(parsed_data->>'raw_field' AS TYPE) AS standard_name   │
└──────────────────────────────────────────────────────────────────┘
                                   │ 定时触发
                                   ▼
┌──────────────────────────────────────────────────────────────────┐
│  演进层  (Self-Evolving Engine — 人工门控)                        │
│                                                                  │
│  1. 聚类分析: HDBSCAN 对 unclassified 字段向量做密度聚类          │
│  2. LLM 命名: 为高密度簇提议新的标准字段名（Tier 2 ReAct）        │
│  3. 人工门控: 写入 pending_schema_evolutions 表，等待审核         │
│  4. 审核命令: olav config evolve --list / --approve <id>         │
│  5. 执行迁移: IngestManager 原子提交新 VIEW 定义                  │
└──────────────────────────────────────────────────────────────────┘
```

---

## 3. 核心组件设计

### 3.1 字段语义摘要格式

将字段元数据拼接为统一的语义摘要字符串，用于向量化：

```python
# 语义摘要 = 字段所有语义信息的拼接
def build_semantic_summary(field: dict) -> str:
    parts = [
        field.get("name", ""),           # 字段名
        field.get("description", ""),    # 描述
        field.get("type", ""),           # 数据类型
        str(field.get("example", "")),   # 示例值
        field.get("command", ""),        # 来源命令（CLI 场景）
    ]
    return " | ".join(p for p in parts if p)

# 示例输出
# "ip_address | IPv4 management address of the interface | string | 192.168.1.1 | show interfaces"
```

### 3.2 字段分类工具 (classify_field)

**核心逻辑**：向量相似度分级分流，避免每个字段都调用 LLM。

```python
def classify_field(field_metadata: dict) -> dict:
    """
    分级分流:
      confidence > 0.85  → 自动匹配，不调 LLM
      0.60 ~ 0.85       → LLM 二轮确认 (Tier 1, max_iterations=1)
      < 0.60            → 标记为 unclassified，进入演进池

    系统级函数，负责产出 schema mutation request；实际写入由平台服务执行。
    """
    domain = field_metadata.get("domain", "platform")
    summary = build_semantic_summary(field_metadata)
    vector = get_embedder().encode(summary, normalize_embeddings=True).tolist()

    # 在 LanceDB <domain>_field_mappings 集合中检索
    db = lancedb.connect(LANCEDB_PATH)
    table = db.open_table(f"{domain}_field_mappings")
    results = table.search(vector).limit(1).to_list()

    if not results:
        return {"status": "unclassified", "confidence": 0.0}

    # 注意：LanceDB cosine metric 返回 _distance ∈ [0, 2]（越小越相似）
    # 正确转换：confidence = 1 - (distance / 2)，值域 [0, 1]
    # ⚠️ 错误写法 1.0 - distance 在 distance > 1 时产生负数，绕过所有阈值判断
    distance = results[0].get("_distance", 2.0)
    confidence = 1.0 - (distance / 2.0)   # ← 统一转换为相似度，值域 [0, 1]

    if confidence > 0.85:
        # Tier 0: 直接命中，写缓存
        mapping = results[0]["standard_name"]
        _save_mapping(field_metadata, mapping, method="vector")
        return {"status": "matched", "standard_name": mapping, "confidence": confidence}

    elif confidence >= 0.60:
        # Tier 1: LLM 确认 (Zero-Shot, 1次调用)
        mapping = _llm_confirm(field_metadata, results[0], confidence)
        _save_mapping(field_metadata, mapping, method="llm_confirm")
        return {"status": "llm_confirmed", "standard_name": mapping, "confidence": confidence}

    else:
        # Tier 2: 进入演进池
        _add_to_evolution_pool(field_metadata, vector)
        return {"status": "unclassified", "confidence": confidence}
```

### 3.3 LanceDB 表结构 (`<domain>_field_mappings`)

存储标准字段的向量索引，作为分类的"标准库"：

```python
# Bootstrap 脚本从 TextFSM 模板自动生成
schema = pa.schema([
    ("standard_name", pa.string()),    # 标准字段名，如 "management_ip"
    ("description",   pa.string()),    # 语义描述
    ("data_type",     pa.string()),    # DuckDB 类型，如 "INET", "VARCHAR"
    ("category",      pa.string()),    # 分类：interface / bgp / ospf / routing
    ("vector",        pa.list_(pa.float32(), 384)),  # bge-small-en-v1.5 维度
    ("source",        pa.string()),    # "textfsm" | "llm_evolved" | "manual"
    ("created_at",    pa.timestamp("us")),
])
```

### 3.4 DuckDB 统一视图生成 (create_unified_view)

**规则**：VIEW 的生成在 IngestManager 流程中执行，不允许工具层直接 DDL。

```python
def create_unified_view(command: str, mappings: list[dict]) -> str:
    """生成归一化 SQL VIEW，在 IngestManager.bulk_load() 之后调用。"""
    cols = []
    for m in mappings:
        raw_key = m["raw_key"]
        std_name = m["standard_name"]
        data_type = m.get("data_type", "VARCHAR")
        cols.append(
            f"  TRY_CAST(parsed_data->>'{raw_key}' AS {data_type}) AS {std_name}"
        )
    cols_sql = ",\n".join(cols)

    view_name = f"v_unified_{command.replace(' ', '_').replace('-', '_')}"
    sql = f"""
CREATE OR REPLACE VIEW {view_name} AS
SELECT
  device_name,
  snapshot_id,
{cols_sql},
  parsed_data AS raw_attributes  -- 保留原始 JSON 作为 fallback
FROM parsed_outputs
WHERE command = '{command}'
"""
    return sql
```

### 3.5 演进层流程

> **D3**：`evolution_pool`、`schema_mappings`、`pending_schema_evolutions` 均写入
> `.olav/databases/domain.duckdb` 的平台/域 schema，**不得混入** `audit.duckdb`（审计专用）。

> **D2**：演进层用 `sklearn.cluster.OPTICS` 替代 `hdbscan` 包，避免额外依赖；
> `scikit-learn` 已在项目依赖中，对少量 unclassified 字段 OPTICS 足够。

```
[定时任务 / 手动触发]
    ↓
从 domain.duckdb.<domain>.evolution_pool 取出 unclassified 向量
    ↓
sklearn.cluster.OPTICS (min_samples=3)   # 替代 hdbscan，无额外依赖
    ↓
[有高置信度簇?]
    ├─ 否 → 继续累积，下次再试
    └─ 是 → Tier 2 LLM ReAct Agent 定义新标准字段名
                ↓
         写入 pending_schema_evolutions 表
         (status='pending', proposed_name, cluster_id, sample_fields)
                ↓
         工程师: olav config evolve --list  # 查看待审核
                olav config evolve --approve <id>
                ↓
         执行: 新标准写入 <domain>_field_mappings LanceDB 集合
               + 触发受影响 VIEW 的重建
```

---

## 4. 注册为 config agent 的合理性分析

### 4.1 为什么应该归属于 config agent ✅

**关键论据**：

1. **职责连续性**：`config → discovery` 子 Agent 的已有描述就是 *"Schema Alignment"*，本设计是其能力的自然延伸（从纯 LLM 分类 → LanceDB 加速分类）。

2. **控制面定位**：discovery 不属于业务 Agent，它是平台控制面的 schema 发现入口，负责提出变更请求、展示 diff、组织审核。

3. **不再主张 direct DB write 例外**：为保持与 AGENTS.md 一致，config agent 不直接写共享 DuckDB/LanceDB；它只把变更提交给 `SchemaMutationService` / staging pipeline。

4. **权限边界清晰**：
   ```
   业务 Agent (olav/ops/audit)  → 只读 DB（query）
    config Agent (control plane) → 提交 schema mutation request + 审核上下文
    platform services            → 执行共享存储写入
   ```

### 4.2 需要的约束条件（设计护栏）

| 约束 | 说明 |
|:--|:--|
| **写入限制**：agent 不直接写共享表 | 仅生成 schema mutation request / staging 文件 |
| **演进层必须人工门控** | 直接 `ALTER TABLE` 禁止；新标准必须经 `--approve` 命令确认 |
| **落库幂等** | 平台服务落库使用 UPSERT / replace 语义；VIEW 使用 `CREATE OR REPLACE` |
| **嵌入模型统一** | 复用 `get_embedder()` 单例（BAAI/bge-small-en-v1.5），不允许额外加载模型 |
| **覆盖范围** | 不管理 `parsed_outputs` 的数据内容，只管理 schema 请求、视图定义和映射关系 |

### 4.3 渐进式披露约束（新增）

discovery 相关 skill 必须拆成三层：

1. `SKILL.md` 只保留摘要、调用条件、执行骨架，控制在可审阅长度内。
2. OpenAPI 参考、字段样例、认证说明放 supporting files，按需读取。
3. 脚本与模板不注入主上下文，只在执行时调用。

这与 Claude Code skill 的组织方式保持一致，也防止 discovery skill 变成巨型 prompt。

### 4.3.1 生成物目录边界（新增）

`scaffold_domain_agent` / `register_api_schema` 生成 OpenAPI 域脚手架时，必须遵守以下边界：

1. `.olav/workspace/<domain>/` 只放**静态控制面**内容：
    `MANIFEST.yaml`、`AGENT.md`、`SKILL.md`、`tools/`、`references/`。
2. `.olav/config/domains/<domain>/` 放**项目运行态**配置：
    endpoint、auth mode、凭据引用、用户本地覆盖项。
3. `.olav/databases/`、`.olav/logs/`、`.olav/run/` 不属于 scaffold 生成目录，
    它们是平台共享运行态，不绑定某个 skill 包。

这条约束用于避免把“可升级的 skill 定义”与“不可静默覆盖的项目配置”混在一起。

### 4.4 组件归属总结（D4：工具层轻薄化）

> **D4 原则**：workspace 工具只做参数准备 + 调用，核心分类逻辑下沉到
> `src/olav/core/schema_engine.py`，防止 LLM agent 直接触发写 DB 路径。

```
src/olav/core/
└── schema_engine.py             # ← 新增（核心）：classify, save_mapping,
                                 #   create_unified_view, evolve_trigger,
                                 #   build_mutation_request

.olav/workspace/config/
├── AGENT.md                     # 已有：config-orchestrator
└── discovery/
    ├── SKILL.md                 # 升级：声明 4 个新工具
    └── tools/
        ├── fuzzy_map_schema.py  # 现有：内部委托 schema_engine
        ├── classify_field.py    # 新增：薄包装 → schema_engine.classify_field()
        ├── register_api_schema.py  # 新增：OpenAPI 解析 → schema_engine.register()
        ├── create_unified_view.py  # 新增：薄包装 → schema_engine.create_view()
        └── trigger_schema_evolve.py # 新增：薄包装 → schema_engine.evolve_trigger()

.olav/config/
└── domains/
    └── <domain>/
        ├── api.json              # endpoint / auth mode / credential refs
        ├── policies.yaml         # 域级策略与只读/写入门控
        └── local_overrides.yaml  # 项目私有覆盖，禁止由 scaffold 静默覆盖
```

### 4.5 OpenAPI 读写分流与 HMITL 控制面（新增）

> 目标不是让 LLM 在运行时“猜这个 API 是否危险”，而是在 OpenAPI 注册阶段就把
> operation 分类为 read / write，并把 write 默认纳入 Human-in-the-Loop 审批。

#### 为什么必须原生区分 read / write

如果 API 仍以“统一工具调用”暴露给 agent，会出现三个问题：

1. **安全边界不清晰**：LLM 可能把查询类接口与变更类接口等价对待。
2. **当前 RBAC 接线还不够细**：现有模型可表达 `agent / skill / action`，但运行时尚未形成独立的“可读 / 可提写 / 可批准写”三层权限。
3. **审计不可解释**：审计事件只能看到“调了某个 API 工具”，看不到它是只读查询还是有副作用的写操作。

因此，OpenAPI 接入后的最小原生模型应是：

- **read operation**：默认允许直通执行，但仍受 RBAC 控制。
- **write operation**：默认禁止 agent 直写，必须生成 action request，进入 HMITL 审批流。
- **unknown / ambiguous operation**：按 write 处理，宁可保守降级，不做乐观放行。

#### Operation 意图判定规则

注册阶段从 OpenAPI `paths` 中抽取 operation 时，平台应为每个 operation 固化一份元数据：

| 输入信号 | 默认解释 | 备注 |
|:--|:--|:--|
| `GET` / `HEAD` / `OPTIONS` | `intent=read` | 无副作用方法默认视为只读 |
| `POST` / `PUT` / `PATCH` / `DELETE` | `intent=write` | 默认视为有副作用 |
| 未识别 method / 缺少 method 语义 | `intent=unknown` | 按 write 收口 |
| `x-olav-intent: read|write` | 覆盖默认 method 推断 | 用于修正“POST 查询”“副作用 GET”等遗留 API |
| `x-olav-approval: required|none` | 覆盖默认审批策略 | 允许 vendor 明确声明高风险写操作 |

> 结论：HTTP method 负责第一轮原生分类，OpenAPI vendor extension 负责纠偏；
> **没有显式声明时一律保守**。

#### 建议的 operation 元数据结构

```python
ApiOperationPolicy = {
    "domain": "itsm",
    "operation_id": "createTicket",
    "path": "/api/tickets",
    "method": "POST",
    "intent": "write",            # read | write | unknown
    "approval_policy": "required", # none | required
    "idempotent": False,
    "side_effect_risk": "high",  # low | medium | high
    "source_of_truth": "method_default",  # method_default | openapi_extension | manual_override
}
```

该结构应作为 `register_api_schema` 的副产物落到控制面元数据中，而不是只在运行时临时计算。

### 4.6 写操作为什么必须强制 HMITL（新增）

当前 `SchemaMutationService` 已经证明：共享控制面写入最稳妥的模式不是“agent 直写”，而是：

```text
request -> pending -> approve -> apply -> audit
```

同样原则应推广到 OpenAPI 写操作：

1. agent 只负责生成 **action request**，不能直接执行远端变更。
2. action request 写入平台 staging 区，包含 operation policy、请求参数摘要、风险等级。
3. 工程师审批后，平台 service 才真正调用远端 API。
4. 审批与执行结果都写入审计。

这条原则有三个收益：

- **把 LLM 从“执行者”降级为“提案者”**，显著降低误操作面。
- **把写权限从 agent 级收口到 control-plane 级**，便于统一治理。
- **让审计记录可解释**：不仅知道“谁调了 API”，还知道“谁提出、谁批准、谁执行”。

> 对于高风险写操作，`--auto-approve` 不应绕过 HMITL；否则全局开关会直接削弱写路径安全边界。

### 4.7 与 RBAC 的组合边界（新增）

OpenAPI 读写分流不能单独存在，必须与最小 RBAC 组合：

| 能力 | `readonly` | `user` | `admin` |
|:--|:--|:--|:--|
| 调用 read operation | 可按域授权开放 | 可按域授权开放 | 可开放 |
| 发起 write action request | 默认拒绝 | 可按策略允许“提案” | 可允许 |
| 批准 write action request | 拒绝 | 拒绝 | 允许 |
| 直接执行 write operation | 禁止 | 禁止 | 仅平台审批执行器可执行 |

**当前实现 reality check：**

- 上表是**目标边界**，不是当前全部已落地的运行时状态。
- 当前代码只在 `ApiActionService` 中把 write submit / approve 映射到 `mutate` / `admin`。
- read operation 仍未引入独立授权动作，仍主要依赖现有 agent/tool 入口控制。
- `config evolve --approve` 这类 schema 审批命令也尚未统一纳入 RBAC。

这里要强调一个边界：

- **RBAC 决定“谁可以发起 / 批准”**。
- **HMITL 决定“写操作是否必须经过人工门控”**。

两者不是替代关系，而是叠加关系。

### 4.8 建议新增的平台服务抽象（新增）

现有 `SchemaMutationService` 已覆盖 schema 变更写路径。若要让 OpenAPI 写操作也原生受控，
平台应补一个并行抽象，例如：

```text
ApiActionService
  - stage_action(request)
  - list_pending_actions()
  - approve_action(action_id)
  - execute_approved_actions()
```

建议的最小 request 结构：

```python
ApiActionRequest = {
    "request_id": "uuid",
    "domain": "itsm",
    "operation_id": "createTicket",
    "method": "POST",
    "path": "/api/tickets",
    "intent": "write",
    "approval_policy": "required",
    "params_summary": {"title": "router down", "priority": "high"},
    "requested_by": "alice",
    "requested_at": "2026-03-17T12:00:00Z",
    "status": "pending",
}
```

它与 `SchemaMutationService` 的关系应是并列而非混用：

- `SchemaMutationService`: 管 schema / mapping / view 变更
- `ApiActionService`: 管远端 API 写操作

补充现实边界：`SchemaMutationService` 的审批 CLI（`olav config evolve --approve`）当前仍是独立路径，
尚未像 `ApiActionService` 一样接入 admin 鉴权，这也是当前 control-plane 的一个未收口点。

这样可以保持审计语义和 apply 阶段的职责清晰。

---

## 5. 数据流全景

```
步骤  动作                         技术栈                   说明
─────────────────────────────────────────────────────────────────────
 1   注入 CLI 或 openapi.yaml      TextFSM / prance         提取字段定义
 2   向量化字段语义摘要             bge-small-en-v1.5 单例   <10ms/字段
 3   LanceDB 向量检索              <domain>_field_mappings   <5ms 毫秒级匹配
 4   分流判断                      Python (无 IO)            0 延迟
     ├─ >0.85: 生成映射请求       schema mutation request   待平台应用
     ├─ 0.6~0.85: LLM 零样本确认  Tier 1 (Zero-Shot, 1次)  ~3s
     └─ <0.60: 写演进请求         domain.duckdb evolution   待平台应用
 5   平台应用变更                  SchemaMutationService     原子提交
 6   生成统一视图                  CREATE OR REPLACE VIEW    平台服务流程中
 7   演进：OPTICS 聚类             scikit-learn (已依赖)     定时/按需触发
 8   演进：LLM 命名新标准          Tier 2 ReAct              人工审核门控
 9   演进：审核通过                olav config evolve --approve  工程师确认
10   演进：更新标准库              <domain>_field_mappings   追加新向量
```

> **补充约束**：第 1 步如果来源是 OpenAPI，生成的认证说明与 endpoint 配置只写入
> `.olav/config/domains/<domain>/` 模板，不直接内嵌到 `SKILL.md` / `AGENT.md`。

### 5.1 OpenAPI operation 控制流（新增）

```text
register_api_schema
    ↓
解析 paths + methods + vendor extensions
    ↓
为每个 operation 生成 ApiOperationPolicy
    ↓
[intent == read]
    ├─ 生成只读工具元数据
    └─ 运行时按 RBAC 直接调用

[intent == write or unknown]
    ├─ 生成写操作工具元数据（approval_policy=required）
    ├─ 运行时 agent 只能 stage_action()
    ├─ 工程师审批
    └─ 平台执行器 execute_approved_actions()
```

> 这里的关键不是“把 write tool 隐藏掉”，而是**让 write tool 的默认行为变成生成请求，而不是执行变更**。

---

## 6. Bootstrap 脚本（初始化标准库）

```python
# scripts/bootstrap_field_classifications.py
# 从 TextFSM 模板自动生成 LanceDB 初始标准向量库

import lancedb
from olav.core.embedder import get_embedder
from olav.core.config import DATABASES_DIR

# TextFSM 模板定义的标准字段（手工维护一次）
STANDARD_FIELDS = [
    {"standard_name": "management_ip",   "description": "IPv4 management address", "data_type": "VARCHAR", "category": "interface"},
    {"standard_name": "interface_name",  "description": "Interface name or identifier", "data_type": "VARCHAR", "category": "interface"},
    {"standard_name": "bgp_peer_ip",     "description": "BGP neighbor IP address", "data_type": "VARCHAR", "category": "bgp"},
    {"standard_name": "bgp_as_number",   "description": "BGP autonomous system number", "data_type": "BIGINT", "category": "bgp"},
    {"standard_name": "ospf_router_id",  "description": "OSPF router ID", "data_type": "VARCHAR", "category": "ospf"},
    {"standard_name": "ospf_area",       "description": "OSPF area ID", "data_type": "VARCHAR", "category": "ospf"},
    # ... 从 normalization_strategy.yaml 自动生成其余字段
]

def bootstrap():
    embedder = get_embedder()
    db = lancedb.connect(str(DATABASES_DIR / "memory.lancedb"))
    # ... 向量化并写入 netops_field_mappings 集合
```

---

## 7. 实施路线图

| 阶段 | 目标 | 关键交付物 | 估时 |
|:--|:--|:--|:--|
| **Phase 1** | Bootstrap + 向量分类 | `schema_engine.py`（核心）+ `classify_field.py`（薄包装）+ LanceDB 初始化脚本 | 1 周 |
| **Phase 2** | Schema mutation service | `SchemaMutationService` + staging/审批流 | 1 周 |
| **Phase 3** | DuckDB 统一 VIEW | `create_unified_view.py` + 平台服务集成 | 1 周 |
| **Phase 4** | OpenAPI 接入 | `register_api_schema.py` + prance 解析 + domain scaffold | 1 周 |
| **Phase 5** | 演进层 | `trigger_schema_evolve.py` + `olav config evolve` CLI | 2 周 |
| **Phase 6** | OpenAPI 读写分流 + 写操作 HMITL | `ApiOperationPolicy` 元数据、`ApiActionService`、审批/执行 CLI 或 service 接口 | 1~2 周 |

### 7.1 Phase 6 具体开发计划（新增）

| 编号 | 任务 | 实现落点 | 目标 |
|:--|:--|:--|:--|
| API-RW-1 | 在 `register_api_schema` 中抽取 operation policy | `.olav/workspace/config/discovery/tools/register_api_schema.py` | 注册时固化 method、intent、approval_policy |
| API-RW-2 | 支持 `x-olav-intent` / `x-olav-approval` vendor extensions | `register_api_schema.py` | 允许覆盖默认 method 推断 |
| API-RW-3 | 定义 `ApiActionRequest` / `ApiActionService` | `src/olav/core/` | 写操作统一走 stage / approve / execute 控制面 |
| API-RW-4 | 为 write operation 接入 HMITL + 审计 | `src/olav/api/`, `src/olav/core/audit_recorder.py`, CLI/service 层 | 写操作默认需人工批准且可追溯 |
| API-RW-5 | 与最小 RBAC 收口（未完成） | `src/olav/core/auth/authz.py`, config agent / API 执行入口 | 引入独立 read、submit-write、approve-write 三类权限 |

### 7.2 当前实现对照（2026-03-17）

- **已完成**：API-RW-1 / API-RW-2 / API-RW-3 / API-RW-4
- **未完成**：API-RW-5

准确表述应为：

- `ApiOperationPolicy` 与 vendor extension 支持已落地
- `ApiActionService` 的 stage / approve / execute 基线已落地
- 写操作 submit / approve 已映射到现有 `mutate` / `admin`
- **独立 read / submit-write / approve-write 权限层仍未实现**

> [!TIP]
> **最快验证路径**：使用 ContainerLab 环境（`dev_docs/ContainerLab.md`）对 Cisco `show interfaces` 和 Huawei `display interface` 的解析输出运行 Phase 1 分类器，验证同一字段（如 IP 地址）是否能被正确归一化到 `management_ip`。
