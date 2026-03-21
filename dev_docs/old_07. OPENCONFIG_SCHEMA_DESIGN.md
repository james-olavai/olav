# OpenConfig Schema Design, Feasibility, and Current Status

> HISTORICAL DOCUMENT ONLY (do not use as current authority).
>
> Current authoritative chain:
> `dev_docs/07. OPENCONFIG_SCHEMA_DESIGN.md` → `dev_docs/08. LEGACY_CUT_LINE.md` →
> `dev_docs/09. NETWORKX_SANDBOX_DESIGN.md` → `dev_docs/10. CLAB_CAB_AGENT_DESIGN.md` →
> `dev_docs/11. CONTROL_PLANE_SEMANTIC_ENGINE.md` → `dev_docs/12. PLATFORM_NETOPS_OWNERSHIP_MAP.md` →
> `dev_docs/01. tracking.md`

> Archive note: this file is retained only for historical comparison and migration archaeology.

**Status:** Phase-gated implementation. Three phases, each requiring a real E2E test to pass before the next phase begins. This document describes the target design and tracks honest current-state gaps.

**Scope Boundary:** OpenConfig is recommended here as the **NetOps normalization standard** for OLAV. It is not a platform-wide universal schema for every OLAV domain.

## 0. Phase-Gated Implementation Plan

The OpenConfig implementation proceeds in **three strictly ordered phases**. Each phase has a mandatory E2E acceptance test. A phase is only considered complete when its E2E test passes on real devices — not when the code is written.

```
Phase 1: 采集能力验证 (Collection)
   ↓  [Gate: E2E — all devices return raw data]
Phase 2: 数据标准化 (OpenConfig Normalization)
   ↓  [Gate: E2E — all parsed_outputs rows contain OpenConfig JSON]
Phase 3: 拓扑解析 (Topology from OpenConfig)
      [Gate: E2E — topology_links populated from openconfig-lldp data]
```

### Phase 1 — 采集能力验证

**Goal:** Confirm every device in the inventory can deliver raw data through its designated collection protocol.

**Real-Environment Device Mapping (2026-03-19):**

| Device | Platform | Collection Protocol | Status |
|---|---|---|---|
| R1 | juniper_junos | CLI → Scrapli/Netmiko TextFSM | ✅ Validated |
| R2 | cisco_ios | **NETCONF (primary)** → CLI fallback | ✅ NETCONF R2:830 validated (capability + 4 domains) |
| R3 | cisco_ios | CLI → Scrapli/Netmiko TextFSM | ✅ Validated |
| R4 | cisco_ios | CLI → Scrapli/Netmiko TextFSM | ✅ Validated |
| SW1 | cisco_ios | CLI → Scrapli/Netmiko TextFSM | ✅ Validated |
| SW2 | cisco_ios | CLI → Scrapli/Netmiko TextFSM | ✅ Validated |

**Note:** gNMI has not been validated against any real device in the current lab. It remains in the fallback chain code but is not the primary path for any device today.

**E2E Test Gate:** `uv run pytest tests/e2e/test_phase1_collection.py` — must confirm all 6 devices return non-empty raw snapshots.

**Current Gap:** `netops_init.py` has never been run as a full pipeline. R2–R4/SW1–SW2 only have stale snapshots (3+ days old). A full `olav collect --all` run producing fresh data for all 6 devices is required to close Phase 1.

---

### Phase 2 — 数据标准化 (OpenConfig Normalization)

**Goal:** All data collected in Phase 1 — whether from NETCONF, CLI/TextFSM, or gNMI — arrives in DuckDB `parsed_outputs` as a consistent **OpenConfig-standard JSON** structure. No vendor-native field names at storage time.

**This phase is vendor-agnostic and does not depend on whether any device supports gNMI or NETCONF.** The primary path is TextFSM CLI output. NETCONF data is an optional confidence booster, not a prerequisite.

**Correct build order (MUST be sequential):**
```
OC-14: Download OpenConfig YANG repo → pyang compiles flat Golden dict → DuckDB `yang_leaves` table
   ↓
OC-13: LLM-in-sandbox: Schema-to-Schema matching (YANG leaf ↔ TextFSM field) → `mapping_rules` table
           [optional] NETCONF value-confirmation pass upgrades name-similarity → value-confirmed
   ↓
Stage 2 TextFSM loop: load `mapping_rules` for (vendor, command) → transform raw JSON → OC JSON → `parsed_outputs`
```

**E2E Test Gate:** `uv run pytest tests/e2e/test_phase2_normalization.py` — query `parsed_outputs` for all 6 devices; assert every row's `parsed_data` JSON contains correct OpenConfig top-level keys (`openconfig-interfaces:interfaces`, `openconfig-bgp:bgp`, etc.).

**Historical audit note (2026-03-19, superseded by 2026-03-20 fixes):**
- The items below describe the pre-fix gap analysis that led to GATE-BYPASS-1.
- Current runtime status is tracked in `dev_docs/01. tracking.md`; Phase 2–4 gates are now green.
- `OC-6 (schema_cache.py)` has since been migrated to `mapping_rules`.
- `OC-13`/`OC-14` design corrections from this section informed the current implementation, but this paragraph is no longer the live runtime status source.

Phase 2 cannot begin until Phase 1 E2E gate passes.

---

### Phase 3 — 拓扑解析 (Topology from OpenConfig)

**Goal:** With all data in OpenConfig format, the topology engine parses `openconfig-lldp` (and CDP→LLDP bridge) data to automatically populate `topology_links` for L2/L3 full-network topology.

**E2E Test Gate:** `uv run pytest tests/e2e/test_phase3_topology.py` — assert `topology_links` contains correct peer relationships for all 6 devices derived solely from OpenConfig LLDP data.

**Dependencies:** Phase 3 requires Phase 2 to be complete. OC-16 (Topology-on-OpenConfig) is the primary task.

Phase 3 cannot begin until Phase 2 E2E gate passes.

---

## 1. `netops init` 全生命周期时序

### 1.1 命令职责边界

| 命令 | 职责 | 运行频率 |
|---|---|---|
| `olav init` | 平台一次性 bootstrap：下载 YANG 仓库、编译 `yang_leaves`、初始化 DuckDB schema、注册设备表 | **一次性**（或强制重建时） |
| `olav collect` / `sync_all()` | 每次数据采集：从设备抓取数据、Stage 1 原始保存、Stage 2 解析与标准化、重建 `repair_queue` | **每轮采集**（定期或按需） |

---

### 1.2 一次性 Bootstrap（`olav init`）

```
olav init
  │
  ├─ [B-1] 初始化 DuckDB schema
  │       创建 parsed_outputs / devices / topology_links /
  │       sync_metadata / schema_catalog / yang_leaves /
  │       mapping_rules 等表结构
  │
  ├─ [B-2] OC-14: YANG 仓库下载 + 编译 (bootstrap_yang.py)
  │       git clone --depth 1 openconfig/public → .olav/yang_models/
  │       pyang 遍历所有 .yang 文件 → 提取 leaf 元数据
  │       写入 DuckDB: yang_leaves (yang_path, leaf_name, leaf_type, description, module)
  │       ⚠️ 此步骤完成前，OC-13 Schema 匹配无法运行
  │
  └─ [B-3] OC-13: Schema-to-Schema 首次映射编译
          读取 schema_catalog（TextFSM 变量名+类型）
          读取 yang_leaves（YANG leaf 元数据）
          LLM-in-sandbox: 按 (vendor, command) 做 Schema ↔ Schema 对齐
          写入 mapping_rules (vendor, command, src_field, oc_path, confidence="name_similarity")
          ⚠️ 此步骤完成前，Stage 2 OC 变换无法运行
```

**完成标志：** `yang_leaves` 表非空 + `mapping_rules` 包含所有已知 (vendor, command) 对的初始映射。

---

### 1.3 每轮采集生命周期（`olav collect`）

```
olav collect [--devices R1,R2,...] [--categories routing,interfaces,...]
  │
  ├─ [C-0] 设备连通性预检 (parallel_tcp_check)
  │       并发测试所有设备 TCP 22（SSH）或 TCP 830（NETCONF）
  │       不可达设备写入 host.data["tcp_reachable"] = False → 跳过采集
  │
  ├─ [C-1] Nornir 设备表注册 (_populate_devices_table)
  │       从 nornir inventory (hosts.yaml, groups.yaml) 导入设备元数据
  │       写入 DuckDB: devices (hostname, platform, ip, groups, ...)
  │
  ├─ [C-2] Stage 1 — 数据采集 (_sync_device_workflow × 每台设备，并发)
  │       │
  │       ├─ 尝试 gNMI (GnmiCollector)
  │       │     成功 → _write_api_collected_domains() 写 staging JSON
  │       │     失败 → 进入 NETCONF
  │       │
  │       ├─ 尝试 NETCONF (NetconfCollector, 仅 cisco_ios/iosxe)
  │       │     capability 发现 → subtree fetch → xmltodict
  │       │     成功 → _write_api_collected_domains() 写 staging JSON
  │       │     失败 → 进入 CLI
  │       │
  │       └─ CLI 回退 (Scrapli → Netmiko)
  │             逐条执行 show 命令（来自 collect_commands.py 策略表）
  │             原始输出写入: exports/snapshots/{date}/raw/{device}/{cmd_slug}.txt
  │             同时记录 _update_capability_cache() 更新传输协议缓存
  │
  ├─ [C-3] Stage 2 — TextFSM 解析 (_process_sync_stage2)
  │       │
  │       ├─ 遍历 exports/snapshots/{date}/raw/{device}/*.txt
  │       │
  │       ├─ _find_textfsm_template(platform, command)
  │       │     搜索: .olav/templates/ → NTC-templates（优先级降序）
  │       │
  │       ├─ TextFSM 解析 → list[dict]（原始厂商字段）
  │       │
  │       ├─ [目标态 Phase 2] normalize_record() (OC-4) + mapping_rules 变换 → OC JSON
  │       │   [当前现实]     直接存原始厂商 JSON，无 OC 变换
  │       │
  │       ├─ _detect_parse_quality_gap() 质量检测
  │       │     检查: 原始输出非空 但 JSON 为空 → gap
  │       │     过滤: 显式 zero-entry summary 不算 gap
  │       │     分类: HIGH / MEDIUM severity
  │       │
  │       └─ 写入 staging: exports/snapshots/json/{device}.staging.json
  │
  ├─ [C-4] IngestManager.bulk_load() — DuckDB 批量写入
  │       DuckDB read_json_auto("exports/snapshots/json/*.staging.json")
  │       Upsert → parsed_outputs (device_name, command, parsed_data JSON, snapshot_id)
  │       Atomic: 单次批量写入，无逐行 INSERT
  │       staging 文件保留（下次采集覆盖，不删除）
  │
  ├─ [C-5] NETCONF Value-Confirmation Pass（可选，仅有 NETCONF 数据的设备）
  │       对 mapping_rules 中 confidence="name_similarity" 的条目
  │       用同一设备 NETCONF 数据对比 CLI TextFSM 值
  │       匹配率 > 阈值 → 升级 confidence = "value_confirmed"
  │       当前仅 R2 可触发此路径
  │
  ├─ [C-6] 拓扑 ETL (_discover_topology_from_db)
  │       查询 parsed_outputs 中 CDP/LLDP 数据
  │       [目标态 Phase 3] 从 openconfig-lldp JSON 提取对端关系
  │       [当前现实]        从 TextFSM CDP 输出 + cdp_lldp 桥接提取
  │       Upsert → topology_links (local_device, local_port, remote_device, remote_port)
  │
  ├─ [C-7] repair_queue 生成 (_write_repair_queue)
  │       汇总所有 gap → .olav/config/repair_queue.json
  │       每条 gap 含: device, command, severity, raw_file, raw_size, reason
  │       0 gaps = 本轮 Stage 2 完全健康
  │
  └─ [C-8] sync_metadata 落库 (_store_sync_metadata)
          写入: sync_metadata (snapshot_id, device_count, success_count, duration_seconds, ...)
```

---

### 1.4 文件系统布局（每轮采集后）

```
exports/snapshots/
  {date}_{seq}/           ← 每轮采集的快照目录（由 get_sync_dir() 生成）
    raw/
      R1/
        show_version.txt
        show_interfaces.txt
        ...
      R2/
        show_version.txt
        (netconf_interfaces.json 单独写入 staging，不在 raw/)
        ...
  json/
    R1.staging.json       ← Stage 2 输出（供 IngestManager.bulk_load()）
    R2.staging.json
    ...
  latest -> {date}_{seq}  ← 符号链接，指向最新快照

.olav/
  config/
    repair_queue.json     ← 当前快照的解析质量 gap 列表
  databases/
    main.duckdb           ← 所有结构化数据（parsed_outputs, devices, topology_links, ...）
  yang_models/            ← (目标态) OpenConfig YANG 源文件
  templates/              ← 自定义 TextFSM 模板（优先于 NTC）
```

---

### 1.5 关键不变式（Invariants）

1. `exports/snapshots/{date}/raw/` 只写不改：原始 CLI 输出永久保留，用于重跑 Stage 2 或审计。
2. `*.staging.json` 幂等覆盖：每次 `olav collect` 覆盖写，不累加，DuckDB 做 upsert。
3. **DuckDB 只由 IngestManager.bulk_load() 写入**：Agent tool 和 Stage 2 不直接执行 `INSERT`。
4. `mapping_rules` 缓存：相同 `(vendor, command)` 只触发一次 LLM。下次采集直接加载缓存，无 LLM 调用。
5. `repair_queue.json` 是瞬态快照：每次 Stage 2 完整重建，代表当前快照的健康状态，与历史无关。

---

### 1.6 性能模型：平台级复用与批量变换

#### 映射规则平台级共享（最关键的性能特性）

`mapping_rules` 表的主键是 `(vendor, command)`，**不是** `(device, command)`。

这意味着：
- **同一平台的所有设备共享同一套映射规则。**
- `cisco_ios` 平台的 R2 首次触发 OC-13 LLM 映射后，R3/R4/SW1/SW2 的相同命令直接加载缓存，**0 LLM 调用**。
- Juniper `juniper_junos` 平台的 R1 首次完成映射后，所有 Juniper 设备自动受益。
- 新设备加入同一平台 → 立即获得已有映射，无需任何 LLM 介入。

```
首台 cisco_ios 设备（R2）首次采集:
  OC-13 LLM 运行 → 写入 mapping_rules (cisco_ios, show interfaces, ...)
  OC-13 LLM 运行 → 写入 mapping_rules (cisco_ios, show ip bgp summary, ...)
  ...（每条命令一次，约 20-30 次 LLM 调用）

后续 R3/R4/SW1/SW2 采集（同 cisco_ios 平台）:
  → 直接加载 mapping_rules 缓存
  → 0 LLM 调用，仅 DuckDB 读取
  → Stage 2 transform 速度 = 纯 DuckDB 级别
```

**结论：LLM 成本 = O(平台数 × 命令数)，与设备数无关。6 台设备 vs 600 台设备，LLM 调用次数相同。**

#### Stage 2 OC 变换：DuckDB SQL 批量路径（目标架构）

Phase 2 初期可用 Python 循环实现（`for record in parsed_records: apply_rules(record)`），但目标是利用 DuckDB 列式并行做整批变换：

```sql
-- 一次扫描变换本快照所有设备、所有命令的 TextFSM JSON → OC JSON
-- 在 IngestManager.bulk_load() 之前作为 DuckDB SQL 管道执行
SELECT
    p.device_name,
    p.command,
    p.snapshot_id,
    p.platform,
    oc_transform(p.parsed_data, m.rules_json) AS parsed_data
FROM staging_raw p
JOIN mapping_rules m
  ON p.platform = m.vendor
 AND p.command  = m.command
WHERE m.confidence IN ('name_similarity', 'value_confirmed')
```

这是单次 O(n) 列式扫描，代替 Python O(n×m) 双层循环。**Phase 2 后期作为性能优化升级为此路径。**

#### NETCONF Value-Confirmation 批量效果

R2 一台设备的 NETCONF 验证，升级的是**整个 `cisco_ios` 平台**的 `mapping_rules` 条目 confidence。验证粒度是 `(vendor, command)`，不是 `(device, command)`：

- R2 NETCONF 验证了 `show interfaces` 映射 → R3/R4/SW1/SW2 的该条目同时升级为 `value_confirmed`。
- 不需要每台设备分别验证。

---

## 2. Executive Summary

This document evaluates the feasibility of adopting OpenConfig YANG models as the standard JSON schema for OLAV data normalization.

**Conclusion: Feasible and recommended as a NetOps normalization baseline.**

OpenConfig provides a standardized, vendor-neutral structure that improves upon the earlier proprietary "Cisco-as-standard" mapping approach. It is suitable as the primary normalization layer for multi-vendor network collection, but it does not fully cover every vendor-specific feature and should not be described as a full platform-universal schema.

## 2. Current Implementation Snapshot (2026-03-19)

### Phase 1 — Code Implemented (Collection)
- Runtime fallback chain: gNMI → NETCONF → Scrapli → Netmiko (code in `sync_tools.py`).
- `GnmiCollector`: root `/` fetch preference with per-domain grouping fallback.
- `NetconfCollector`: capability discovery + subtree fetch + xmltodict conversion.
- Real-device validated: R2 (cisco_ios) NETCONF at port 830 — capability discovery succeeds, returns `interfaces`, `bgp`, `lldp`, `platform` payloads.
- CLI fallback (Scrapli/Netmiko + TextFSM) validated for R1–R4, SW1–SW2.
- Stage 2 TextFSM parse gap repair closed to 0 for `2026-03-19_2026` snapshot.

### Phase 1 — Not Validated (Missing E2E Gate)
- No full `olav collect --all` run across all 6 devices. `netops_init.py` never executed as a full pipeline.
- gNMI not validated on any real lab device.
- NETCONF not validated on R3, R4, SW1, SW2.

### Phase 2 — Historical pre-fix gap analysis
The following table records the 2026-03-19 pre-fix audit state before the 2026-03-20 OpenConfig pipeline repair:

| Module | Status | Gap |
|---|---|---|
| `normalization.py` (OC-4) | ✅ Unit tested | Never imported by `sync_tools.py`, `gnmi_collector.py`, or `netconf_collector.py` |
| `schema_engine.py` (OC-3) | ✅ Unit tested | Never called from Stage 2 TextFSM loop |
| `schema_cache.py` (OC-6) | ✅ Unit tested | Historical gap closed: runtime now hydrates from `mapping_rules` rather than `schema_mappings` |
| `schema_validation.py` (OC-5) | ✅ Unit tested | Never called from pipeline |
| `OC-13 Golden Map Compiler` | ❌ Design was incorrect + not implemented | Old design: LLM infers structure from raw data (no ground truth). Correct design: LLM does Schema-to-Schema matching against `yang_leaves` table produced by OC-14. Depends on OC-14 first. |

**Historical database snapshot:** This statement described the pre-migration state before `scripts/migrate_oc_pipeline.py` rebuilt OpenConfig-shaped data. See `dev_docs/01. tracking.md` for the accepted current counts/status.

### Phase 3 — Historical pre-fix gap analysis
- These notes described the state before OC-16 was wired into the pipeline.
- Current accepted status is Phase 3 complete; `topology_links` is generated from the repaired OpenConfig-aware flow as tracked in `dev_docs/01. tracking.md`.

## 3. Detailed Architecture per Phase

The following describes the technical implementation target for each pipeline path. Treat the earlier Section 2 audit notes as historical gap records, not as the current runtime truth.

### Phase 1 Technical Paths

#### Primary: Native NETCONF Collection (R2 and future cisco_ios devices)
- **Protocol:** `ncclient` on port 830.
- **Method:** `<get-config>` on `running` datastore → `xmltodict` → Python dict.
- **Real-device status:** R2 validated. R3/R4/SW1/SW2 pending.

#### Default: SSH + TextFSM Fallback (R1 and all non-NETCONF devices)
- **Protocol:** Scrapli (fast) → Netmiko (compat fallback).
- **Result:** Vendor-native TextFSM JSON stored in `parsed_outputs`. This is the current production state.
- **Scope:** All 6 devices have valid CLI snapshots.

#### Future: gNMI (SR Linux, Arista, Junos EOS, IOS-XR)
- **Protocol:** `pygnmi`, root `/` path preferred.
- **Real-device status:** Not validated in current lab.
- **Reservation:** SR Linux ContainerLab nodes only, pending CLAB_API_TOKEN.

### Phase 2 Technical Paths

#### Step A — OC-14: Compile OpenConfig YANG → Golden Dict (prerequisite, run once)

This step is a one-time bootstrap that must complete before OC-13 can run.

1. `bootstrap_yang.py` performs a shallow clone (`--depth 1`) of the [OpenConfig public YANG repo](https://github.com/openconfig/public) into `.olav/yang_models/`.
2. `pyang --format tree` (or equivalent flat-leaf extraction) is run over every `.yang` file.
3. Output is compiled into a flat DuckDB table `yang_leaves (yang_path TEXT, leaf_name TEXT, leaf_type TEXT, description TEXT, module TEXT)` stored in `.olav/databases/main.duckdb`.
4. This table is the **sole ground truth** for all subsequent Schema-to-Schema matching. It is never derived from device data.

#### Step B — OC-13: LLM Schema-to-Schema Mapping → `mapping_rules` (per vendor+command, cached)

This is the core mapping engine. The LLM is used as a **schema alignment tool**, not as a data inference tool.

Inputs to the LLM (both are schemas, not device data):
- **Left side (source):** TextFSM template variable names + their Python types from `schema_catalog` — e.g. `INTF TEXT, IP_ADDR TEXT, STATUS TEXT`.
- **Right side (target):** Relevant rows from `yang_leaves` for the likely OpenConfig domain — e.g. `openconfig-interfaces:interfaces/interface/state/oper-status (enumeration: UP|DOWN|TESTING), /config/name (string)`.

The LLM runs inside a DuckDB sandbox and produces a mapping JSON:
```json
{
  "vendor": "cisco_ios",
  "command": "show interfaces",
  "confidence": "name_similarity",
  "rules": [
    {"src_field": "INTF",    "oc_path": "openconfig-interfaces:interfaces/interface/config/name"},
    {"src_field": "STATUS",  "oc_path": "openconfig-interfaces:interfaces/interface/state/oper-status"}
  ]
}
```

This is written to the `mapping_rules` DuckDB table. Future runs for the same `(vendor, command)` skip the LLM entirely and load from cache.

**Confidence levels in `mapping_rules`:**
- `name_similarity` — names are semantically close, not yet value-verified.
- `value_confirmed` — values from TextFSM field match values from a NETCONF/gNMI source for the same device/command (see Step C).

#### Step C — NETCONF Value-Confirmation Pass (optional, R2 only today)

This pass upgrades `name_similarity` mappings to `value_confirmed` for devices that also have NETCONF data. It is **not required** for the pipeline to produce OpenConfig output — it only increases confidence.

1. For each `(vendor, command)` mapping already in `mapping_rules` at `name_similarity`:
2. Load the NETCONF JSON for the same device + domain from `parsed_outputs` (raw NETCONF column, separate from CLI).
3. For each mapped field, check: does the CLI TextFSM value match the YANG-path value in NETCONF output?
4. If match rate > threshold, upgrade `confidence` to `value_confirmed` in `mapping_rules`.

Today only R2 has NETCONF data. As more devices gain NETCONF support, more mappings get upgraded automatically.

#### Step D — Stage 2 Transform: TextFSM JSON → OpenConfig JSON

This is the only Stage 2 change needed. After `textfsm.parse()` produces the raw list-of-dicts:

1. `normalize_record(record)` — OC-4: interface name / MAC / IP canonicalization.
2. Load `mapping_rules` for `(vendor, command)` from DuckDB.
3. Apply rules: for each `src_field → oc_path` rule, reconstruct a nested OpenConfig dict by splitting `oc_path` on `/`.
4. `schema_validation.validate(oc_json)` — Pydantic OC model validation + LLM self-heal on `ValidationError`.
5. Write final OpenConfig JSON to `parsed_outputs`.

This path **requires no gNMI or NETCONF support from the device**. It works for any vendor that has TextFSM templates.

#### NETCONF → OpenConfig (R2, cisco_ios NETCONF devices)
1. `xmltodict` output (nested dict) from `NetconfCollector`.
2. `NetconfCollector.resolve_master(raw_dict)` — merges multi-subtree XML into OpenConfig domain structure.
3. OC-4 `normalize_record()` pass.
4. Written to `parsed_outputs` (same table, separate rows from CLI).
5. Optionally feeds Step C value-confirmation for CLI mappings of the same device.

#### gNMI → OpenConfig (future, SR Linux / Arista / IOS-XR)
1. Native OpenConfig JSON from device.
2. OC-4 `normalize_record()` pass for interface name / MAC canonicalization.
3. Stored directly to `parsed_outputs`.

### Phase 3 Technical Path: Topology from OpenConfig LLDP

1. Query `parsed_outputs` for rows where `parsed_data` contains `openconfig-lldp:lldp`.
2. Extract `neighbors/neighbor` entries per interface.
3. Upsert into `topology_links` with `(local_device, local_port, remote_device, remote_port, protocol="lldp")`.
4. CDP bridge (`cdp_lldp.py`) maps `openconfig-lldp` with `source: "cdp"` for Cisco devices where only CDP is available.
5. Final `topology_links` table spans all 6 devices.


## 4. Automated Verification vs Human-in-the-Loop (HITL)

Relying solely on an LLM to generate the OpenConfig JSON structure from TextFSM risks schema violations. We can eliminate the need for Human-in-the-Loop (HITL) validation by leveraging existing Python schema validation ecosystems:

### Option A: Pydantic Generation via Datamodel-Code-Generator
1. **Mechanism:** Use `datamodel-code-generator` to compile OpenConfig YANG/JSON Schema specifications into strict Python Pydantic models.
2. **Execution:** The LLM is instructed to map the network data into these Pydantic models.
3. **Verification:** Pydantic will instantly raise `ValidationError` if the LLM output violates the OpenConfig schema (e.g., wrong types, missing required fields, illegal enums like substituting "UP" for "UP_STATE"). 
4. **Retry Loop:** If Pydantic fails validation, the error is fed back to the LLM to self-correct automatically before persisting to DuckDB.

### Option B: Pyangbind
1. **Mechanism:** Use `pyangbind` to generate Python class hierarchies directly from the source `.yang` files.
2. **Execution:** Python code dynamically instantiates these classes and assigns values parsed from TextFSM.
3. **Verification:** `pyangbind` strictly enforces YANG rules (types, leaves, constraints) in standard Python.

**Recommendation:** **Option A (Pydantic)** remains the practical near-term choice. It is already integrated in the current implementation. Dynamic YANG validation should be added later as a stricter second layer rather than replacing the current runtime immediately.

## 5. Impact Assessment on Existing Codebase

| Component | Impact | Changes Required |
| :--- | :--- | :--- |
| `ingest_manager.py` | Low | `parsed_data` JSON structure changes, but DB columns remain the same. |
| `schema_engine.py` | Medium | Migration completed in current runtime: mapping targets are `oc_path`/OpenConfig-aware; keep prompts aligned with OpenConfig schema references. |
| `command_registry.py`| None | TextFSM parsing and registry remain identical. |
| `schema_mutation*` | None | Staging and approval flow remains unaffected. |
| `Query Agent` | Medium | SQL queries generated by the agent must be adapted to extract nested OpenConfig paths rather than vendor-specific paths. |
| `Export Tools` | New | Must create a new tool to push OpenConfig JSON to SR Linux via gNMI. |

## 6. Potential Coverage Gaps
- **CDP:** OpenConfig does not have a native CDP model. **Mitigation:** Map CDP data into the `openconfig-lldp` hierarchy and append a `source: "cdp"` meta-tag.
- **Proprietary Features and Operational-Only Data:** Vendor-specific features and operational commands with no OC YANG module must be carried via the `_olav:` private namespace extension (see §6.1 below). Using a bare `vendor_extensions` dict key is **not acceptable** — data stored there is unqueryable and not persisted by the OC pipeline.

### 6.1 `_olav:` Private Namespace Extension（非 OC 数据扩展规范）

**问题背景**

以下两类数据在运维上同样重要，但没有对应的 OpenConfig YANG 模块：

| 类别 | 代表命令 | 当前状态 |
|---|---|---|
| 诊断类 | `show clock`、`show logging`、`show aliases` | `_unmapped` 内嵌键，不持久化 |
| 系统资源类 | `show users`、`show processes cpu` | 同上 |
| NETCONF 原始信封 | R2 `netconf_bgp`（rpc-reply 未解析） | `skipped_no_oc`，直接丢弃 |
| 厂商私有特性 | IOS-XE 专有 MIB、Junos 私有 RPC | 无任何处理 |

**设计原则**

零 schema 变更。`mapping_rules.oc_path` 是 `TEXT` 列，OpenConfig 路径只是约定前缀。
引入 `_olav:<domain>/` 私有前缀，与 `openconfig-*` 路径在**同一列**中共存。

**Domain 分类**

```
_olav:diagnostic/<concept>/<leaf>   — 运维诊断（clock, logging, users）
_olav:system/<concept>/<leaf>       — 系统资源（cpu, memory, processes）
_olav:raw/netconf/<rpc-type>        — 无法解析模块的 NETCONF rpc-reply 原始数据
_olav:vendor/<vendor>/<feature>     — 厂商私有特性（无任何标准对应）
```

**`parsed_data` JSON 约定**

顶级 key 使用完整 domain path（与 `openconfig-interfaces:interfaces` 对称）：

```json
{
  "_olav:diagnostic/clock": {
    "current-time": "2026-03-20T14:23:01Z",
    "timezone": "UTC",
    "_source": "show clock"
  }
}
```

**`mapping_rules` 条目结构**

```sql
-- 格式与 OC 条目完全相同，只有 oc_path 前缀不同
INSERT INTO mapping_rules (vendor, command, src_field, oc_path, confidence) VALUES
  ('cisco_ios', 'show clock',         'current_time',  '_olav:diagnostic/clock/current-time',    'name_similarity'),
  ('cisco_ios', 'show logging',       'message',       '_olav:diagnostic/logging/message',        'name_similarity'),
  ('cisco_ios', 'show users',         'username',      '_olav:system/users/username',             'name_similarity'),
  ('cisco_ios', 'show processes cpu', 'cpu_five_min',  '_olav:system/process/cpu-utilization-5m', 'name_similarity'),
  ('cisco_ios', 'netconf_bgp',        '_rpc_reply_xml','_olav:raw/netconf/bgp-reply',             'name_similarity');
```

**查询隔离**

```sql
-- 仅 OpenConfig 标准数据
SELECT * FROM parsed_outputs WHERE parsed_data::TEXT LIKE '%"openconfig-%';

-- 仅 OLAV 扩展运维数据
SELECT * FROM parsed_outputs WHERE parsed_data::TEXT LIKE '%"_olav:%';

-- 所有结构化数据（OC + 扩展，全量可查询集合）
SELECT * FROM parsed_outputs WHERE parsed_data IS NOT NULL;
```

**对现有组件的影响**

| 组件 | 变更 | 说明 |
|---|---|---|
| `mapping_rules` 表 | **无** | `oc_path` TEXT 列天然兼容任意前缀 |
| `parsed_outputs` 表 | **无** | JSON 列天然兼容任意顶级 key |
| `apply_oc_mapping()` | **无** | 已支持输出任意顶级 key dict |
| `v_interfaces_auto` 等 OC 视图 | **无** | `json_extract(elem, '$."openconfig-...')` 对 `_olav:` key 天然无感 |
| `schema_engine._COMMAND_MODULE_HINTS` | **补充** | 为诊断/系统类命令添加 `_olav:` 模块提示 |
| `migrate_oc_pipeline.py` `skipped_no_oc` | **修改** | 改为写 `_olav:raw/` 而非跳过 |
| `category_strategy.yaml` | **新建** | domain 分类与 `_olav:` 前缀对齐 |
| `quick/SKILL.md` | **补充** | `_olav:` 路径查询示例 |

> **与 OC-NETCONF-1 的关系**：R2 `netconf_bgp`/`netconf_platform` 两行若无法 unwrap 为真实
> OC 格式，应写入 `_olav:raw/netconf/bgp-reply` 路径保留原始数据，而不是被 `skipped_no_oc` 丢弃。
> `_olav:raw/` 是 OC-NETCONF-1 修复失败时的数据完整性兜底方案。

## 7. Practical Conclusion

OpenConfig is a sound normalization target for OLAV NetOps, especially for multi-vendor collection, unified querying, and SR Linux export. The design is therefore reasonable.

What is not reasonable is treating this document as if every step already exists in runtime. The correct interpretation is:

- The foundational OpenConfig direction is validated.
- A meaningful subset is already implemented.
- Several key pieces are still target-state work, especially NETCONF master-resolution, YANG bootstrap, dynamic schema validation, and topology refactoring.
