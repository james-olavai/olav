# 语义感知型动态数据集成引擎 — 设计文档

**状态**: 设计草案 v0.2（修正 D1-D4）  
**日期**: 2026-03-15  
**归属**: config agent → discovery 子 Agent

---

## 1. 背景与定位

### 1.1 解决的问题

OLAV 接入新系统（新厂商设备 / NMS / SDN 控制器）时，存在以下痛点：

| 痛点 | 当前状态 | 目标状态 |
|:--|:--|:--|
| 新厂商字段映射 | 工程师手工维护 `normalization_strategy.yaml` | 向量相似度自动分类，仅边界情况调 LLM |
| OpenAPI 系统接入 | 无机制 | 解析 openapi.yaml 自动生成 schema 映射 |
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

TextFSM 标准字段库（`STANDARD_FIELDS`）是 `field_classifications` 表的**初始 bootstrap 来源**，
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
│  语义索引层  (LanceDB — field_classifications 表)                 │
│                                                                  │
│   ① 向量化: bge-small-en-v1.5 (复用 get_embedder() 单例)         │
│                                                                  │
│   ② 分级分流:                                                    │
│      confidence > 0.85 ──────→ 自动匹配标准字段   (Tier 0)       │
│      0.60 ≤ confidence ≤ 0.85 → LLM 二轮确认     (Tier 1)       │
│      confidence < 0.60 ─────→ unclassified 暂存  (Tier 2 待演进) │
│                                                                  │
│   ③ 映射持久化 → schema_mappings 表 (DuckDB, 系统级写入)         │
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

    系统级函数，负责写入 schema_mappings 表。
    """
    summary = build_semantic_summary(field_metadata)
    vector = get_embedder().encode(summary, normalize_embeddings=True).tolist()

    # 在 LanceDB field_classifications 表中检索
    db = lancedb.connect(LANCEDB_PATH)
    table = db.open_table("field_classifications")
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

### 3.3 LanceDB 表结构 (field_classifications)

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
> `.olav/databases/main.duckdb`，**不得混入** `audit.duckdb`（审计专用）。

> **D2**：演进层用 `sklearn.cluster.OPTICS` 替代 `hdbscan` 包，避免额外依赖；
> `scikit-learn` 已在项目依赖中，对少量 unclassified 字段 OPTICS 足够。

```
[定时任务 / 手动触发]
    ↓
从 main.duckdb.evolution_pool 取出 unclassified 向量
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
         执行: 新标准写入 field_classifications LanceDB 表
               + 触发受影响 VIEW 的重建
```

---

## 4. 注册为 config agent 的合理性分析

### 4.1 为什么应该归属于 config agent ✅

**关键论据**：

1. **现有先例**：`fuzzy_map_schema.py` 已经直接写入 `schema_mappings` 表（DuckDB），config agent 本身就是 OLAV 中**系统级别的写 DB 角色**，这是架构设计意图，非异常。

2. **职责连续性**：`config → discovery` 子 Agent 的已有描述就是 *"Schema Alignment"*，本设计是其能力的自然延伸（从纯 LLM 分类 → LanceDB 加速分类）。

3. **Staging-First 例外的合理性**：OLAV v0.11 的 Anti-Pattern `❌ NO Direct DB Writes` 针对的是**业务 Agent（olav/ops/audit）**，防止它们污染共享状态。config agent 作为**基础设施层**，其写 DB 行为是受控的、幂等的（`INSERT OR REPLACE`），等同于 `IngestManager` 的身份。

4. **权限边界清晰**：
   ```
   业务 Agent (olav/ops/audit)  → 只读 DB（query）
   config Agent (system-level)  → 读写 DB（schema_mappings, field_classifications, pending_schema_evolutions）
   ```

### 4.2 需要的约束条件（设计护栏）

| 约束 | 说明 |
|:--|:--|
| **写入限制**：只写 schema 相关表 | `schema_mappings` / `field_classifications` LanceDB / `pending_schema_evolutions`，不写 `parsed_outputs` |
| **演进层必须人工门控** | 直接 `ALTER TABLE` 禁止；新标准必须经 `--approve` 命令确认 |
| **映射幂等** | 所有写操作使用 `INSERT OR REPLACE`；VIEW 使用 `CREATE OR REPLACE` |
| **嵌入模型统一** | 复用 `get_embedder()` 单例（BAAI/bge-small-en-v1.5），不允许额外加载模型 |
| **覆盖范围** | 不管理 `parsed_outputs` 的数据内容，只管理视图定义和映射关系 |

### 4.3 组件归属总结（D4：工具层轻薄化）

> **D4 原则**：workspace 工具只做参数准备 + 调用，核心分类逻辑下沉到
> `src/olav/core/schema_engine.py`，防止 LLM agent 直接触发写 DB 路径。

```
src/olav/core/
└── schema_engine.py             # ← 新增（核心）：classify, save_mapping,
                                 #   create_unified_view, evolve_trigger

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
```

---

## 5. 数据流全景

```
步骤  动作                         技术栈                   说明
─────────────────────────────────────────────────────────────────────
 1   注入 CLI 或 openapi.yaml      TextFSM / prance         提取字段定义
 2   向量化字段语义摘要             bge-small-en-v1.5 单例   <10ms/字段
 3   LanceDB 向量检索              field_classifications 表  <5ms 毫秒级匹配
 4   分流判断                      Python (无 IO)            0 延迟
     ├─ >0.85: 直接写映射缓存     schema_mappings (DuckDB)  系统级写入 ✅
     ├─ 0.6~0.85: LLM 零样本确认  Tier 1 (Zero-Shot, 1次)  ~3s
     └─ <0.60: 写演进池           main.duckdb.evolution_pool  系统级写入 ✅
 5   生成统一视图                  CREATE OR REPLACE VIEW    IngestManager 流程中
 6   演进：OPTICS 聚类             scikit-learn (已依赖)     定时/按需触发
 7   演进：LLM 命名新标准          Tier 2 ReAct              人工审核门控
 8   演进：审核通过                olav config evolve --approve  工程师确认
 9   演进：更新 LanceDB 标准库     field_classifications      追加新向量
```

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
    # ... 向量化并写入 field_classifications 表
```

---

## 7. 实施路线图

| 阶段 | 目标 | 关键交付物 | 估时 |
|:--|:--|:--|:--|
| **Phase 1** | Bootstrap + 向量分类 | `schema_engine.py`（核心）+ `classify_field.py`（薄包装）+ LanceDB 初始化脚本 | 1 周 |
| **Phase 2** | DuckDB 统一 VIEW | `create_unified_view.py` + IngestManager 集成 | 1 周 |
| **Phase 3** | OpenAPI 接入 | `register_api_schema.py` + prance 解析 | 1 周 |
| **Phase 4** | 演进层 | `trigger_schema_evolve.py` + `olav config evolve` CLI | 2 周 |

> [!TIP]
> **最快验证路径**：使用 ContainerLab 环境（`dev_docs/ContainerLab.md`）对 Cisco `show interfaces` 和 Huawei `display interface` 的解析输出运行 Phase 1 分类器，验证同一字段（如 IP 地址）是否能被正确归一化到 `management_ip`。
