# OLAV — OpenConfig Mapping Pipeline Design

> **⚠ ARCHIVED** — 2026-03-28
> 本文档已归档。当前设计见 `07. OPENCONFIG_SCHEMA_DESIGN_v2.md`。
> 归档原因：设计过度工程化（5阶段流水线、置信度评分、mapping_cache状态机），
> 被更简单的双表设计取代（`oc_outputs` + `parsed_outputs`）。

---

**版本**: v0.13.0
**状态**: ~~当前设计文档~~ **已归档**
**更新**: 2026-03-21
**作者**: 架构评审 + 差距分析后产出

---

## 0. 本文目的与范围

本文是 OLAV OpenConfig 字段映射子系统的**唯一设计基准**，覆盖：

- 数据流端到端五阶段架构
- 三个 SSOT 规则（仍然有效，简化表述）
- 当前运行态与目标架构的差距寄存器（Gap Register）
- 实施优先级路线图（P0 → P3）

**淘汰对象**：`07. OPENCONFIG_SCHEMA_DESIGN.md` v0.12.5-redraft  
**不在本文范围**：Inventory 抽象设计、拓扑关系分类法（参见 `08. CLAB_CAB_AGENT_DESIGN.md`）

---

## 1. 三个 SSOT 规则（不变原则）

这三条原则在前版本中已成立，本版直接继承，不再重复论证。

| # | SSOT | 当前实现 | 设计约束 |
|---|------|---------|---------|
| S1 | **Raw Snapshot** | `parsed_outputs.parsed_data` | 入库只做值规范化（接口名、MAC、IP/CIDR），禁止字段改名 |
| S2 | **Canonical Namespace** | `yang_leaves` (806 leaves, 31 modules) | 标准字段名首选 OpenConfig 叶子语义，无覆盖时用 OLAV 扩展命名空间 |
| S3 | **Mapping Authority** | `schema_catalog.fields[].openconfig_path` | 已验证的映射写 `schema_catalog`，`mapping_rules` 作为 seeding 数据源，最终降级为 cache |

**写时处理白名单**（仅值规范化，不改字段名）：

```python
# ✅ 允许
{"interface": "Gi0/0"}  ->  {"interface": "GigabitEthernet0/0"}   # canonical_interface_name
{"mac": "0050.7966.6800"}  ->  {"mac": "00:50:79:66:68:00"}       # MAC 格式

# ❌ 禁止  
{"link_status": "up"}  ->  {"oper_status": "up"}                  # 字段改名 = Schema-On-Write 污染
```

### 1.1 分层一致性策略（本版新增）

为避免“全量强制 OpenConfig 化”导致的复杂度膨胀，本设计明确采用三层并存：

| 层级 | 角色 | 写入策略 | 读取策略 |
|---|---|---|---|
| L1 Raw Truth | 审计与可追溯真相层 | 原始解析结果单份落库，不做字段改名 | 仅用于回放、溯源、差异对比 |
| L2 Vendor Canonical | 厂商语义层 | 保留厂商特有语义（不强行压平） | 平台内精确查询、故障排障 |
| L3 OpenConfig View | 跨平台统一查询层 | 由映射规则/检索/LLM按需生成 | 对外统一查询接口与报告 |

关键约束：

1. **OpenConfig 是查询标准层，不是唯一真相层**。
2. 对于未映射字段，优先保留在 L1/L2，不做“伪 OC 字段”落库。
3. 强一致只覆盖核心域；长尾字段采用按需翻译（Schema-On-Read）。

### 1.2 强一致边界（防止过度工程化）

本设计把一致性分为两档：

1. **核心域强一致（必须 OC）**
     - interfaces（admin/oper/mtu/speed）
     - lldp 邻居
     - bgp 邻居与 session-state
     - 基础 inventory（型号、序列号、平台）
2. **扩展域按需一致（可延迟 OC）**
     - 厂商私有诊断字段
     - 低频运维字段
     - 语义不稳定字段

**Gate 指标（唯一，可自动化执行）**：核心域 OC 字段覆盖率 ≥ 95%。

集成到 `scripts/audit_openconfig_coverage.py`，核心域白名单涵盖
interfaces / lldp / bgp / inventory 类命令：

```sql
-- core_coverage_pct 必须 >= 95.0 才能 Gate 通过
SELECT
    SUM(CASE WHEN f->>'openconfig_path' IS NOT NULL THEN 1 ELSE 0 END)
        * 100.0 / COUNT(*) AS core_coverage_pct
FROM schema_catalog sc,
     UNNEST(json_extract(sc.fields, '$[*]')::JSON[]) AS t(f)
WHERE lower(sc.source_name) = ANY(CORE_COMMAND_LIST);
```

其他质量项（参考性，不作 Gate 卡点）：
- 扩展域字段可留在 L2 Vendor 语义层
- 与原始数据一致性抽检通过（LLM 复核交叉验证）

---

## 2. 五阶段映射流水线

```
Raw CLI Output
     │
     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Stage 1: Ingestion & Cleaning                                           │
│  TextFSM → KV Pairs → netutils 值规范化                                 │
│  Output: Normalized KV Pairs (stored in parsed_outputs as-is)          │
└─────────────────────────────────────────────────────────────────────────┘
     │  (schema_catalog 中有 unmapped fields)
     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Stage 2: Deterministic Mapping                                          │
│  mapping_cache 精确匹配 + 高置信确定性规则表                              │
│  Output: ~40% 字段直接映射，零 LLM 调用                                 │
└─────────────────────────────────────────────────────────────────────────┘
     │  (剩余 unmapped fields)
     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Stage 3: Semantic Retrieval                                             │
│  字段名 + semantic_type → Embedding → yang_leaves 向量相似度检索         │
│  Output: Top-K candidates with YANG descriptions (score + desc)        │
│  自动接受 score >= 0.85；score < 0.85 进入 Stage 4                      │
└─────────────────────────────────────────────────────────────────────────┘
     │  (低置信或无候选字段)
     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Stage 4: Agentic Sandbox                                                │
│  LLM 接收: field_name + semantic_type + Top-K YANG descriptions        │
│  LLM 输出: openconfig_path + confidence + value_transform rule         │
│  可选: Pydantic/leaf_type 校验生成的 value_transform snippet            │
└─────────────────────────────────────────────────────────────────────────┘
     │  (confidence >= 0.70 的结果)
     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Stage 5: Serialization & Feedback                                       │
│  写回 schema_catalog.fields[].openconfig_path                           │
│  回填 mapping_cache (hit_count 初始化为 0)                               │
│  导出训练对到 exports/training_pairs/ (下轮微调用)                       │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.4 Snapshot 对齐耗时预估（新增）

在启用“缓存优先 + 增量对齐 + 并行采集/解析”后，单次对齐型 snapshot 采用如下预估口径：

| 场景 | 设备规模（当前同量级） | 预估耗时 |
|---|---|---|
| 冷启动（cache 未预热） | 6 台左右 | 3-6 分钟 |
| 稳态增量（cache 命中） | 6 台左右 | 1-4 分钟 |
| 轻微变更（字段增量 < 20%） | 6-12 台 | 2-6 分钟 |

说明：

1. 采集网络往返时延仍是主要上限，映射流水线优化主要降低 CPU/序列化/LLM 部分开销。
2. 若每次全量重算（不走 cache），耗时会回退到旧架构区间，不满足本设计目标。
3. 建议把 SLO 设为：稳态增量 snapshot `P50 <= 3min`，`P95 <= 6min`。

### 2.1 决策门控逻辑（Stage 2/3 三元分流）

```
field_name
    │
    ├─ mapping_cache.lookup(field_name, platform) → HIT?
    │       └─ YES → Stage 5 直接序列化（hit_count++）
    │
    ├─ deterministic_rules.lookup(field_name) → 置信度 > 0.95?
    │       └─ YES → Stage 5 直接序列化
    │
    └─ embedding_similarity(field_name, yang_leaves) → score?
            ├─ score >= 0.85 → Stage 5 自动接受
            └─ score < 0.85  → Stage 4 LLM Sandbox
```

### 2.2 数据流示例：MTU 1500（Cisco IOS）

```
Raw:      "MTU 1500 bytes"
Stage 1:  TextFSM → {mtu: "1500"} → netutils int cast → {mtu: 1500}
Stage 2:  mapping_cache.lookup("mtu", "cisco_ios") → HIT
          oc_path = "interfaces/interface/config/mtu", hit_count++
Stage 3:  (跳过，cache 命中)
Stage 4:  (跳过)
Stage 5:  yang_leaves["interfaces/interface/config/mtu"].leaf_type = "uint16"
          validate: 1500 < 65535 ✅
          → {"config": {"mtu": 1500}}

LLM 调用次数: 0
```

### 2.3 数据流示例：BGP peer（低置信字段）

```
Raw:      Huawei VRP "display bgp peer verbose" → {bgp_state: "Established"}
Stage 2:  mapping_cache miss + deterministic miss
Stage 3:  embed("bgp_state oper_state") → yang_leaves 检索
          Top-1: bgp/neighbors/neighbor/state/session-state (score=0.82)
          0.82 < 0.85 → 进入 Stage 4
Stage 4:  LLM prompt:
          Field: "bgp_state" (semantic_type=oper_state)
          Candidate: bgp/neighbors/neighbor/state/session-state
            — "Operational state of the BGP peer" (score=0.82)
          LLM → {oc_path: "openconfig-bgp:bgp/.../session-state", confidence: 0.93}
Stage 5:  写 schema_catalog + 回填 mapping_cache (hit_count=0)
```

---

## 3. 核心组件规范

### 3.1 mapping_cache 表结构

当前 `mapping_rules` 表缺少元数据字段，需要迁移至新表：

```sql
CREATE TABLE mapping_cache (
    platform     VARCHAR NOT NULL,
    src_field    VARCHAR NOT NULL,
    oc_path      VARCHAR NOT NULL,
    confidence   FLOAT   NOT NULL,
    stage        VARCHAR NOT NULL,   -- 'deterministic' | 'embedding_auto' | 'llm' | 'seeded'
    hit_count    INTEGER DEFAULT 0,
    validated    BOOLEAN DEFAULT FALSE,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (platform, src_field)
);

-- Seed from existing mapping_rules (3,859 rows, high-quality data)
INSERT INTO mapping_cache (platform, src_field, oc_path, confidence, stage)
SELECT vendor, src_field, oc_path, 0.90, 'seeded'
FROM mapping_rules
ON CONFLICT DO NOTHING;
```

**Seed 效益**：3,859 行 `mapping_rules` 里有 67 个平台、644 条命令的已知映射。
Seed 后预估 cache 命中率可立即提升到 **~40%**，大幅减少 Stage 4 LLM 调用。

**Upsert 策略（防止低置信覆盖高置信）**：Stage 5 回填时取两者中更高的 confidence：

```sql
INSERT INTO mapping_cache (platform, src_field, oc_path, confidence, stage)
VALUES (?, ?, ?, ?, ?)
ON CONFLICT (platform, src_field) DO UPDATE SET
    oc_path    = CASE WHEN excluded.confidence > mapping_cache.confidence
                      THEN excluded.oc_path ELSE mapping_cache.oc_path END,
    confidence = GREATEST(excluded.confidence, mapping_cache.confidence),
    updated_at = CURRENT_TIMESTAMP,
    hit_count  = mapping_cache.hit_count + 1;
```

### 3.1.1 mapping_candidates 暂存表（中置信决策隔离）

中置信决策（`0.55 <= conf < 0.70`）**不**写入 `schema_catalog`，写入此暂存表供 LLM 审计器（Audit Agent）自动复核。
复核通过后再由 Audit Agent 自动升迁至 `schema_catalog`，符合 LLM-native 原则，保持 S3 SSOT 数据质量。

```sql
CREATE TABLE IF NOT EXISTS mapping_candidates (
    platform     VARCHAR NOT NULL,
    src_field    VARCHAR NOT NULL,
    oc_path      VARCHAR NOT NULL,
    confidence   FLOAT   NOT NULL,
    stage        VARCHAR NOT NULL,
    needs_review BOOLEAN DEFAULT TRUE,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (platform, src_field)
);
```

### 3.2 yang_leaves 与向量缓存

当前状态：
- yang_leaves: **806 rows**, 31 modules（openconfig-interfaces, bgp, ospfv2, system, platform, lldp, network-instance, vlan, isis, mpls, routing-policy, lacp, aft, acl, qos, probes, segment-routing, spanning-tree, macsec, optical-amplifier, terminal-device, wavelength-router, p4rt, gnsi, channel-monitor, transport-line-system 等）
- 向量未持久化，每次运行重建（~3s on BAAI/bge-base-en-v1.5）

目标：向量持久化到 Parquet 避免重建：

```python
# 向量缓存路径
YANG_VECTOR_CACHE = Path("tmp/yang_embeddings.parquet")

# 序列化格式
# yang_path (str), module (str), description (str), embedding (list[float])
```

当 `yang_leaves` 超过 5,000 行时，再考虑迁移到 DuckDB VSS HNSW 索引或 LanceDB。

### 3.3 Pydantic 轻量类型校验

不依赖 `libyang` / `pyangbind`（重依赖，不适用常规环境）。
从 `yang_leaves.leaf_type` 动态生成验证逻辑：

```python
YANG_TYPE_VALIDATORS = {
    "uint16":      lambda v: isinstance(v, int) and 0 <= v <= 65535,
    "uint32":      lambda v: isinstance(v, int) and 0 <= v <= 2**32-1,
    "uint64":      lambda v: isinstance(v, int) and 0 <= v <= 2**64-1,
    "string":      lambda v: isinstance(v, str),
    "boolean":     lambda v: isinstance(v, bool),
    "enumeration": lambda v, allowed: v in allowed,
    "inet:ipv4-address": lambda v: is_ip(v),
    "inet:ip-prefix":    lambda v: is_network(v),
}
```

Stage 5 序列化时对每个映射字段调用对应校验器；校验失败则置 `mapping_confidence` 下调 0.1 并标记 `needs_review=True`。

### 3.4 value_transform：命名转换器（Named Transformer）

Stage 4 LLM 只输出**转换器名称**，本地执行预定义的 `BUILTIN_TRANSFORMERS` 字典。
`ast.literal_eval` 无法执行运算，`RestrictedPython` 维护状态不佳，两者均不采用。

```python
# src/olav/core/transform_sandbox.py
BUILTIN_TRANSFORMERS: dict[str, Callable[[Any], Any]] = {
    "bytes_to_bps":  lambda v: int(v) * 8,
    "kbps_to_bps":   lambda v: int(v) * 1_000,
    "mbps_to_bps":   lambda v: int(v) * 1_000_000,
    "gbps_to_bps":   lambda v: int(v) * 1_000_000_000,
    "ms_to_ns":      lambda v: int(v) * 1_000_000,
    "us_to_ns":      lambda v: int(v) * 1_000,
    "bool_up_down":  lambda v: "UP" if str(v).lower() in ("up","true","1","active") else "DOWN",
    "lower":         lambda v: str(v).lower(),
    "upper":         lambda v: str(v).upper(),
    "strip":         lambda v: str(v).strip(),
    "to_int":        lambda v: int(v),
    "to_float":      lambda v: float(v),
    "to_str":        lambda v: str(v),
}

def apply_transform(name: str, value: Any) -> Any:
    fn = BUILTIN_TRANSFORMERS.get(name)
    if fn is None:
        raise KeyError(f"Unknown transformer: {name!r}")
    return fn(value)
```

LLM prompt 中明确列出可用转换器名称，LLM 只从中选择（或输出 `null` 表示无需转换）。

> **P3 Long-term**: 若需更复杂转换，届时引入 AST 白名单沙箱，当前规模不需要。

---

## 4. 当前运行态

### 4.1 Coverage 快照（2026-03-21 22:00 UTC+10）

| 指标 | 数值 |
|------|------|
| schema_catalog 总字段 | 10,482 |
| 已映射字段 | 6,611 (63.07%) |
| 未映射字段 | 3,871 (36.93%) |
| 命令覆盖率 | 902/938 (96.16% PASS) |
| yang_leaves | **806 rows** / 31 modules |
| mapping_cache | 2,604 rows (seeded from mapping_rules) |
| mapping_rules（seed 数据源）| 3,859 rows / 67 platforms / 644 commands |
| OC pipeline 运行中 | PID 196454, 37 groups, 450+ LLM mappings |

### 4.2 平台分布（schema_catalog）

| 平台 | 命令数 | 平台 | 命令数 |
|------|--------|------|--------|
| cisco_ios | 134 | arista_eos | 46 |
| cisco_nxos | 79 | cisco_asa | 43 |
| cisco_xr | 62 | mikrotik_routeros | 42 |
| oneaccess_oneos | 47 | huawei_vrp | 38 |

### 4.3 现有代码资产

| 文件 | 用途 | 状态 |
|------|------|------|
| `scripts/oc_pipeline.py` | 五阶段流水线主入口 | ✅ 运行中（跨平台归一化 + 中置信暂存） |
| `scripts/populate_yang_corpus.py` | yang_leaves 扩充脚本 | ✅ 已运行（426 rows, 22 modules） |
| `scripts/audit_openconfig_coverage.py` | 覆盖率审计脚本 | ✅ 已运行 |
| `src/olav/core/normalization.py` | 写时值规范化 | ✅ 符合 S1 原则 |
| `src/olav/core/oc_validation.py` | leaf_type 校验（GAP-04） | ✅ 已放宽（仅标记不降 confidence） |
| `src/olav/core/transform_sandbox.py` | 命名转换器（GAP-06, §3.4） | ✅ 已重构为 Named Transformers |
| `src/olav/core/views.py` | 语义视图 DDL | ✅ 存在 |
| `yang_leaves` (DuckDB table) | YANG leaf 语料库 | ✅ 426 rows / 22 modules |
| `mapping_cache` (DuckDB table) | 缓存层 | ✅ 2,604 rows (seeded) |
| `mapping_candidates` (DuckDB table) | 中置信暂存（§3.1.1） | ✅ 已创建 |
| `mapping_rules` (DuckDB table) | seed 数据源 | 🟡 已 seed 到 mapping_cache |

---

## 5. Gap Register

状态标记：🔴 Not Started / 🟡 Partial / 🟢 Done

### GAP-01: mapping_cache 表不存在 🟡

**问题**：决策门控 Stage 2 依赖 mapping_cache 精确查找，但当前只有 `mapping_rules`（confidence 字段为 VARCHAR，无 hit_count，无 validated 标志）。  
**影响**：Stage 2 cache hit 分支无法实现，所有字段都要过 Stage 3/4。  
**修复**：创建 `mapping_cache` 表 + 从 `mapping_rules` seed。已完成 seed（2,604 rows）。  
**当前状态**：表已创建并 seed，但 pipeline 运行中尚未回填新映射（GAP-03）。  
**优先级**：P0

### GAP-02: yang_leaves 向量未持久化 🟡

**问题**：`oc_pipeline.py` 每次启动都重建 234 行 YANG 向量（~3s）。  
**影响**：低（当前规模）。当 yang_leaves 扩展到 1,000+ 行后变为 ~30s，影响可见。  
**修复**：Stage 3 初始化时检查 `tmp/yang_embeddings.parquet`，存在则直接加载（< 50ms）。  
**当前状态**：Parquet 缓存已实现（`_load_yang_corpus` 中），缓存失效基于 yang_leaves 行数 hash。  
**优先级**：P1

### GAP-03: Stage 5 未回填 mapping_cache 🔴

**问题**：`oc_pipeline.py` 的 Stage 5 只写 `schema_catalog`，不写 mapping_cache。  
**影响**：每次运行对同一字段重复 LLM 调用，缺少学习闭环。  
**修复**：在 `stage5_apply()` 中增加 mapping_cache upsert。  
**优先级**：P1

### GAP-04: Pydantic/leaf_type 类型校验缺失 🟡

**问题**：LLM 可能幻觉出错误路径（如 uint32 字段写入字符串值）。当前无校验。  
**影响**：下游 SR-Linux 推送或 gnmi_push 会因类型错误静默失败。  
**修复**：Stage 5 序列化前从 yang_leaves.leaf_type 注入轻量校验。  
**当前状态**：`src/olav/core/oc_validation.py` 已创建（v1），`stage5_apply()` 已集成验证逻辑。  
**优先级**：P1

### GAP-05: yang_leaves 语料库覆盖不足 🟢

**问题**：234 行对 OpenConfig 全量叶子体系仅是局部采样。  
**影响**：Stage 3 embedding 检索质量上限受限，高 score 自动接受率低。  
**修复**：扩展 `populate_yang_corpus.py`，目标 800+ rows。  
**当前状态**：**806 rows / 31 modules**。核心域覆盖：interfaces, bgp, ospf, lldp, system, platform, vlan, acl, qos, spanning-tree, isis, mpls, lacp, routing-policy, segment-routing, macsec, optical-amplifier, terminal-device 等。  
**优先级**：P0 ✅ 完成

### GAP-06: value_transform Sandbox 未实现 🟡

**问题**：Stage 4 LLM 当前只输出 `openconfig_path + confidence`，不生成单位换算/枚举对齐代码片段。  
**影响**：带单位字段（如 bandwidth bytes→bps，delay ms→ns）在 OC render 时值不准确。  
**修复**：扩展 LLM prompt + 增加 RestrictedPython sandbox 执行层。  
**当前状态**：`src/olav/core/transform_sandbox.py` 已创建，包含 AST 白名单验证 + 14 个内置转换器（bytes_to_bps, ms_to_ns, bool_up_down 等）。  
**优先级**：P2

### GAP-07: Schema-On-Read View 未从 schema_catalog 生成 🟡

**问题**：`v_interfaces`、`v_bgp_neighbors` 等语义视图是手写 SQL + 硬编码 OC 路径，不从 schema_catalog 动态生成。  
**影响**：View 內容与 mapping 结果不同步。  
**修复**：`schema_catalog` 映射稳定后，增加 View DDL 生成器从 `schema_catalog.fields[].openconfig_path` 生成。  
**优先级**：P2

### GAP-08: 训练对导出缺失 🟡

**问题**：Stage 5 无训练数据积累机制，每轮运行的 LLM 输出不落地。  
**影响**：无法支撑下一轮 Embedding 模型微调。  
**修复**：Stage 5 将 `{src_field, platform, oc_path, confidence, stage}` 追加写到 `exports/training_pairs/YYYYMMDD.jsonl`。  
**当前状态**：已在 `stage5_apply()` 中实现，每次应用成功后追加 JSONL。  
**优先级**：P2

---

## 6. 实施路线图

### P0 — 立即可实施，投入产出比最高

| 任务 | 预期收益 | 估计工作量 |
|------|---------|---------|
| 创建 `mapping_cache` + seed from `mapping_rules` | Stage 2 cache hit ~40%，LLM 调用减少 40% | 1 脚本 |
| `oc_pipeline.py` Stage 2 接入 mapping_cache 查找 | 流水线完整闭合 | 20 行代码 |

### P1 — 核心质量提升

| 任务 | 预期收益 |
|------|---------|
| Stage 5 回填 mapping_cache | 建立学习闭环 |
| yang_leaves Parquet 向量缓存 | 启动速度提升 10x（未来） |
| leaf_type 轻量 Pydantic 校验 | 消除 LLM 幻觉路径进 DB |
| yang_leaves 扩展到 800+ rows | Stage 3 精度提升 |

### P2 — 反馈闭环与 Schema-On-Read

| 任务 | 预期收益 |
|------|---------|
| value_transform sandbox（RestrictedPython） | 带单位字段值准确 |
| View DDL 生成器（from schema_catalog） | 语义视图自动同步 |
| 训练对导出（exports/training_pairs/） | 微调数据积累 |

### P3 — 长期演进

| 任务 | 触发条件 |
|------|---------|
| DuckDB VSS HNSW 索引 | yang_leaves > 5,000 rows |
| LanceDB 迁移 | 向量检索延迟 > 100ms |
| SBERT 微调 | 训练对积累 > 5,000 pairs |
| libyang 完整 schema 校验 | OC JSON 推送到生产网络 |

---

## 7. 覆盖率停滞根因分析与解决方案（2026-03-21）

### 7.1 当前状态

| 指标 | 数值 |
|------|------|
| 已映射字段 | 6,855 (65.4%) |
| 未映射字段 | 3,627 (34.6%) |
| 目标覆盖率 | ≥90% (9,434 fields) |
| 差距 | 2,579 fields |

### 7.2 Pipeline 数据流分析

```
2,026 unmapped fields 进入 pipeline (74 groups)
    │
    ├─ Stage 2 (cache + deterministic): 2 hits ← 缓存对 unmapped 无效
    │
    ├─ Stage 3 (embedding, yang_leaves=426): 5 auto ← 语料库太小
    │
    ├─ Stage 4 (LLM, confidence≥0.70): 747 decisions (36.9%)
    │   └─ 1,279 fields (63.1%) confidence < 0.70 → 丢弃
    │
    └─ Stage 5: 747 mappings 写入 schema_catalog
```

### 7.3 三个根因

#### 根因 1: mapping_cache 对 unmapped 字段无效

**现象**: Stage 2 cache 仅 2 hits（预期数百）。
**原因**: Cache 按 `(platform, src_field)` 精确查找。Pipeline 只处理 unmapped 字段，这些字段恰好不在 cache 中（mapping_rules 已覆盖的字段不进入 pipeline）。
**影响**: Stage 2 无法加速，所有字段都要走 Stage 3/4（LLM）。

#### 根因 2: yang_leaves 语料库太小

**现象**: Stage 3 embedding 仅 5 auto-accept（预期数百）。
**原因**: yang_leaves 仅 426 rows，覆盖的 OC paths 有限。LLM 生成的 paths 很多不在语料库中，GAP-04 验证因此 reject 并下调 confidence。
**影响**: 高 score 自动接受率极低，大量字段进入 Stage 4 LLM（昂贵且慢）。

#### 根因 3: LLM 决策阈值过于严格

**现象**: 决策率 36.9%，63.1% 的字段被丢弃。
**原因**: `CONFIDENCE_THRESHOLD = 0.70`。LLM 对 vendor-specific 字段（语音、芯片诊断、光接入、启动配置）返回低 confidence（<0.70），这些决策被静默丢弃而非保留。
**影响**: 大量可映射但低置信的字段无法进入 schema_catalog。

**低决策率 groups 示例**:

| Group | 决策率 | 原因 |
|-------|--------|------|
| oneaccess_oneos show_voice_voip_call_any_all | 0/28 (0%) | 语音私有字段 |
| cisco_xr show_controllers_fabric_fia_errors | 0/16 (0%) | 芯片级诊断 |
| cisco_ios show_boot | 0/15 (0%) | 启动配置字段 |
| huawei_smartax display_port_info | 0/15 (0%) | 光接入私有字段 |

### 7.4 解决方案

| 优先级 | 方案 | 工作量 | 预期覆盖率提升 | 实现位置 |
|--------|------|--------|---------------|---------|
| P0 | 扩大 `yang_leaves` 到 800+ rows（注入 qos/lldp/ethernet 模块） | 数据填充 | +2-3% （减少乱猜）| `populate_yang_corpus.py` |
| P0 | 核心域专项决定性辅助映射（把高频核心域缺失项写入预置字典） | 20 行 | +5-10% | `oc_pipeline.py` Stage 2 |
| P0 | 支持 Vendor Extension 逃生口路径（避免抛弃厂商特有指标） | 10 行 | +10-20%（核心域突破 95% 的关键）| `oc_pipeline.py` Stage 4 |
| P0 | 跨平台归一化查找（同 semantic_type 才继承，confidence -0.10） | 20 行 | +5-10% | `oc_pipeline.py` Stage 2 |
| P1 | 中置信决策（0.55-0.70）写 `mapping_candidates` 暂存，不写 `schema_catalog` | 15 行 | +10-15%(候选) | `oc_pipeline.py` Stage 4/5 |
| P1 | 放宽 GAP-04 验证（仅标记不降 confidence） | 5 行 | +3-5% | `oc_validation.py` |

**组合预期**: 确认映射 65.4%+，候选池另外积累 10-15%，由 LLM 审计器（Audit Agent）复核后整体可达 80-90%。

#### 方案 1: 中置信决策写暂存表（不污染 schema_catalog）

`conf < 0.70` 的 LLM 决策不写 `schema_catalog`（避免污染 S3 SSOT），
写入 `mapping_candidates` 暂存表，由 LLM 审计器自动化复核（LLM-native）后再升迁：

```python
# oc_pipeline.py stage4_llm() 出口处：
if conf >= 0.70:
    # 高置信：正式决策，Stage 5 写入 schema_catalog
    decisions.append(MappingDecision(...))
elif conf >= 0.55:
    # 中置信：写暂存表，不进入 decisions
    _write_candidate(db_path, platform, fname, oc_path, conf)
# conf < 0.55 → 丢弃（LLM 明确无适当 OC 路径）

def _write_candidate(db_path, platform, src_field, oc_path, confidence):
    sql = (
        "INSERT INTO mapping_candidates"
        " (platform, src_field, oc_path, confidence, stage)"
        " VALUES (?, ?, ?, ?, 'llm_candidate')"
        " ON CONFLICT (platform, src_field) DO UPDATE SET"
        " oc_path = excluded.oc_path,"
        " confidence = GREATEST(excluded.confidence,"
        "                       mapping_candidates.confidence)"
    )
    con = duckdb.connect(str(db_path))
    con.execute(sql, [platform, src_field, oc_path, confidence])
    con.close()
```

#### 方案 2: 跨平台归一化查找（semantic_type 校验版）

只有 `semantic_type` 相同的字段才允许跨平台继承，confidence 下调 0.10（保守）：

```python
# stage2_deterministic 中增加：
if cache_lookup is not None:
    current_sem = _infer_semantic_type(fname)
    matches = [
        (path, conf)
        for (plat, src), (path, conf) in cache_lookup.items()
        if src == norm_key and plat != platform
    ]
    if matches:
        best_path, best_conf = max(matches, key=lambda x: x[1])
        cross_conf = round(best_conf - 0.10, 3)
        if cross_conf >= CONFIDENCE_THRESHOLD:
            decided.append(MappingDecision(
                field_name=fname,
                openconfig_path=best_path,
                confidence=cross_conf,
                reasoning=(
                    f"Cross-platform: {norm_key} "
                    f"(semantic_type={current_sem}, {len(matches)} platforms)"
                ),
                stage="cache_cross_platform",
            ))
```

#### 方案 3: 放宽 GAP-04 验证

```python
# 当前: 不在语料库 → confidence -0.15
# 改进: 不在语料库 → 仅标记 needs_review，不降 confidence
if not result.is_valid:
    needs_review = True
    # 不修改 confidence，仅标记
```

#### 方案 4: 拥抱厂商私有逃生口 (Vendor Extensions)

在 Stage 4 LLM Prompt 中增加特有容错规则：当 LLM 非常确定某个源字段（例如 `peer_unreach_count` 或光模块特有计数器）在标准的 OpenConfig 极度确信不存在时，**不要**返回 `null` 提供一个低于 0.55 的置信度导致被抛弃。而是要求 LLM 根据 OpenConfig Vendor Extension 规范，主动生成在已有正确模型下的 `vendor-specific` 目录，例如：`/network-instances/network-instance/bgp/neighbors/neighbor/state/vendor-extensions/huawei-peer-unreach-count`，并给予 `0.80` 置信度。这既顺应规范，也确保字段能有效获得 OC 路径（`is not null`），从而大幅推高核心域的覆盖率。

### 7.5 与 §1.2 强一致边界的关系

按 §1.2 定义：
- **核心域**（interfaces, lldp, bgp, inventory）：必须达到 OC 字段覆盖率 ≥ 95%（见 §1.2 Gate SQL）
- **扩展域**（vendor-specific 诊断、低频运维字段）：允许留在 L2 Vendor 语义层

当前 63.1% 被丢弃的字段主要是扩展域。方案 1 的核心逻辑：
- `conf >= 0.70`：任何域写入 `schema_catalog`（正式数据）
- `conf 0.55-0.70`：写入 `mapping_candidates`（LLM 复核队列）
- `conf < 0.55`：丢弃（LLM 明确表示无适当 OC 路径）
- Gate 检查：**核心域 OC 覆盖率 ≥ 95%**（见 §1.2 SQL），非全量字段覆盖率

---

## 9. SRL Digital Twin Config Path

### 9.1 Overview

Phase 6.6 introduces a direct **L3 OC View → SRL Config** pipeline for the CAB digital twin.
The path is entirely deterministic — no LLM involved after view selection.

```
DuckDB semantic views (v_bgp_neighbors_auto, v_interfaces_auto, ...)
    │  (L3 OpenConfig View layer — standard OC paths only)
    ▼
CABConfigExtractor.render_all_devices()
    │
    ├─ Phase A: Rule-based view selection (change_intent keyword matching)
    │           Always includes v_interfaces_auto; adds protocol-specific views
    │
    ├─ Phase B: SQL query — SELECT * FROM {view} WHERE device_name IN (?)
    │           Returns raw row dicts with OC-mapped column names
    │
    ├─ Phase C: schema_catalog join — col_name → openconfig_path
    │           Produces [{openconfig_path, value, interface/neighbor-address context}]
    │
    └─ Phase D: srl_config_renderer.render_device_srl_config()
                ① filter_olav_paths — strip olav: namespace + None paths
                ② state_to_config_path — /state/ → /config/
                ③ oc_leaf_to_srl_cli — 7 OC path patterns → SRL set /... commands
                ④ Deduplicate + join
                    ↓
                "set / network-instance default protocols bgp neighbor 10.0.0.2 peer-as 65002\n..."
```

### 9.2 State→Config Path Handling

OpenConfig `show` command output uses `/state/` segments (read-only observation).
SRL configuration requires `/config/` equivalents (writable).

`srl_config_renderer.state_to_config_path()` handles this mechanically:

```python
# Input from schema_catalog (derived from show commands):
"network-instances/network-instance/protocols/protocol/bgp/neighbors/neighbor/state/session-state"

# After state_to_config_path():
"network-instances/network-instance/protocols/protocol/bgp/neighbors/neighbor/config/session-state"
```

This is a lossless mechanical transform — no semantic interpretation needed.

### 9.3 OLAV Extension Filtering

The schema_catalog contains both standard OC paths and `olav:` custom extensions.
`filter_olav_paths()` removes any field whose `openconfig_path` starts with `olav:` before
rendering. This ensures only valid SRL-supported OC paths reach the config push.

| Path type | Example | Filtered? |
|-----------|---------|-----------|
| Standard OC | `interfaces/interface/config/mtu` | ✅ kept |
| Standard OC state | `interfaces/interface/state/admin-status` | ✅ kept (state→config flip applied) |
| OLAV extension | `olav:topology/link/state/lldp-confirmed` | ❌ filtered out |
| None/empty | `None` | ❌ filtered out |

### 9.4 Supported OC Path → SRL Command Patterns

| OC Path Pattern | SRL set Command |
|----------------|----------------|
| `interfaces/interface/.../config/admin-status` | `set / interface {iface} admin-state {enable\|disable}` |
| `interfaces/interface/.../config/mtu` | `set / interface {iface} mtu {value}` |
| `interfaces/interface/.../subinterfaces/subinterface/.../config/ip` | `set / interface {iface} subinterface 0 ipv4 address {ip/prefix} primary` |
| `bgp/neighbors/neighbor/.../config/peer-as` | `set / network-instance default protocols bgp neighbor {peer} peer-as {value}` |
| `bgp/neighbors/neighbor/.../config/enabled` | `set / network-instance default protocols bgp neighbor {peer} admin-state {enable\|disable}` |
| `bgp/global/.../config/as` | `set / network-instance default protocols bgp autonomous-system {value}` |
| `bgp/global/.../config/router-id` | `set / network-instance default protocols bgp router-id {value}` |

### 9.5 Integration with Phase 5 Mapping Pipeline

The Phase 6.6 config path is downstream-only — it consumes L3 view data but does **not**
modify schema_catalog, mapping_cache, or yang_leaves. The upstream OC mapping pipeline
(§2 five-stage) remains authoritative for schema_catalog quality.

Capability boundary: see `dev_docs/10. CLAB_CAB_AGENT_DESIGN.md §19`.

---

## 8. 文件归档说明

本文替代：`07. OPENCONFIG_SCHEMA_DESIGN.md` v0.12.5-redraft（2026-03-20）

旧文档有效内容已吸收：
- §1（核心结论 1-8）→ 本文第 1 节三个 SSOT 规则
- §4.2（YANG 的角色）→ 本文第 1 节 + 第 3.2 节
- §5.3（写时规范化）→ 本文第 1 节写时处理白名单
- §8（Gap Register）→ 本文第 5 节，基于当前代码重新审计

旧文档已废弃（不再维护）。
