# 10. CLAB CAB Agent Design

**Status:** Design
**Version:** v0.2 (2026-03-27) — Digital Twin + OC Conversion Pipeline Added
**Depends on:** `07. OPENCONFIG_SCHEMA_DESIGN.md`, `08. LEGACY_CUT_LINE.md`, `09. NETWORKX_SANDBOX_DESIGN.md`, `11. CONTROL_PLANE_SEMANTIC_ENGINE.md`

---

## 0.1 Package Ownership Boundary

本文件定义的是 **NetOps domain validation capability**，不属于 `olav-platform` 的通用核心能力。

归属划分如下：

- **属于 `olav-platform` 的底座**：agent runtime、audit pipeline、workspace control plane、isolated validation environment 的通用编排机制
- **属于 `olav-netops` 的能力**：CLAB schema import、lab topology render、network change replay、protocol assertions、prediction-versus-observation comparison
- **当前仓库中的混合现实**：文档中提到的 CLAB API schema、拓扑裁剪和网络断言属于 netops 域实现，最终不应沉淀为 platform 默认能力

详细归属总表见 `12. PLATFORM_NETOPS_OWNERSHIP_MAP.md`。

---

## 1. Positioning

This document defines the **strict CAB validation path** for OLAV.

The design assumes the following division of labor:

1. the Ops NetworkX sandbox investigates the real network and proposes a candidate plan
2. the CLAB CAB agent validates that plan in an isolated lab before approval

So the CLAB CAB path is not a general troubleshooting assistant.

Its purpose is narrower and stricter:

- reproduce the relevant part of the network
- apply the proposed change
- collect post-change evidence
- compare predicted impact with observed results
- issue a CAB verdict based on evidence

This validation happens in an **isolated lab only**.

OLAV must not write configuration to production devices. Even after successful validation, final execution remains the responsibility of a human network engineer.

---

## 2. Design Principle

The CLAB CAB agent exists because graph-assisted reasoning is not enough for final approval.

Therefore the rule is:

```text
Ops sandbox may propose a plan
CLAB CAB must validate the plan
```

The final approval path must be based on observed lab evidence, not only on LLM reasoning or graph heuristics.

Approval does not mean autonomous execution. It means the system can recommend that a human engineer execute the change.

---

## 3. Inputs

The CLAB CAB agent consumes four classes of input.

### 3.1 Change Intent

- operator request
- candidate action plan from Ops sandbox
- expected success conditions
- explicit safety assertions

### 3.2 Canonical State

Default state reads come from semantic views and other canonical contracts:

- `v_interfaces`
- `v_bgp_neighbors`
- `ospf_neighbors` or future `v_ospf_*`
- future `v_routes`, `v_policy_*`
- `topology_links`
- inventory sources

### 3.3 Render Metadata

Render-time translation comes from:

- `schema_catalog`
- canonical projections
- raw snapshot fallback only where strictly needed

### 3.4 Validation Context

- target protocols involved
- blast radius estimated by the sandbox
- invariants that must hold after the change

---

## 4. Relationship to the Ops Sandbox

The CLAB CAB agent must not duplicate the sandbox role.

### 4.1 Sandbox Responsibilities

The sandbox is responsible for:

1. identifying likely root cause
2. generating candidate fixes or change plans
3. estimating likely impact
4. deciding whether validation is required

### 4.2 CLAB CAB Responsibilities

The CLAB CAB path is responsible for:

1. lab deployment
2. change replay
3. post-change collection
4. assertion execution
5. verdict generation

The CAB agent is therefore an **evidence engine**, not a hypothesis engine.
It is also not a production change executor.

---

## 5. Architecture

```text
User or Ops workflow
        ↓
Ops NetworkX sandbox
        ├─ grounded investigation
        ├─ candidate plan
        ├─ predicted risk
        └─ requires_clab_validation = true
        ↓
CLAB CAB agent
        ├─ read semantic views + topology_links + schema_catalog
        ├─ render lab topology
        ├─ render device change payloads
        ├─ deploy lab
        ├─ apply change in isolated lab only
        ├─ collect observed state
        ├─ run assertions
        ├─ compare prediction vs observation
        └─ emit CAB recommendation artifact
```

---

## 6. CLAB CAB Flow

```text
1. Receive CandidatePlan from Ops sandbox
        ↓
2. Query semantic views for current canonical state
   (v_interfaces, v_bgp_neighbors, v_routes, topology_links)
        ↓
3. Build reduced topology for blast radius
   → LabTopologySpec (nodes + links, platform preserved)
        ↓
4. Render .clab.yaml
   → all nodes mapped to srl kind + image (SRL as universal digital twin target)
   → links from LabTopologySpec.links
        ↓
5. Reconstruct baseline state as OpenConfig payloads
   → semantic views → OC JSON per node
   → via OC Conversion Sandbox (see §15)
        ↓
6. Deploy lab via CLAB API (CLabClient.build + deploy)
        ↓
7. Push baseline OC config to SRL nodes via gNMI Set
   → SrlExporter.export_interfaces() + export_bgp_neighbors()
        ↓
8. Apply proposed change delta (also as OC gNMI Set)
        ↓
9. Wait for convergence (wait_readiness)
        ↓
10. Collect post-change state into isolated validation DuckDB
    → collect_exec() → netops.parsed_outputs
        ↓
11. Run protocol + topology + invariant assertions
    → evaluate_assertions() against isolated DB snapshot
        ↓
12. Compare sandbox predictions vs observed results
    → compare_predictions() → PredictionMatch
        ↓
13. Destroy lab (CLabClient.destroy)
        ↓
14. Return CABEvidenceArtifact with verdict + evidence
```

---

## 7. Why CLAB Is Mandatory for CAB

The CLAB path compensates for the exact limits of the sandbox.

The sandbox and semantic engine may still be wrong because of:

- incomplete protocol semantics
- incomplete policy modeling
- vendor-specific behavior
- convergence edge cases
- hidden dependencies in the collected state

CLAB reduces this residual risk by using a stricter validation mode:

- isolated replay
- observed post-change state
- explicit assertions
- auditable evidence

This is the correct place to be strict.

---

## 8. Data Contracts

### 8.1 Query Contract

The CAB path must use semantic views as the default source of truth for current state.

It must not assume that `parsed_outputs.parsed_data` is already OpenConfig-shaped truth.

### 8.2 Graph Contract

`topology_links` is the shared downstream topology contract used to construct the lab topology.

The CLAB CAB path should consume edge-typed topology, not flatten everything into simple neighbor pairs unless the test scenario explicitly permits that simplification.

### 8.3 Render Contract

The render pipeline has two stages:

**Stage A — Topology Render** (`.clab.yaml` generation):
- Source: `LabTopologySpec` (nodes + links from `topology_links`)
- Target: valid CLAB topology YAML consumable by `CLabClient.deploy()`
- Node kind: always `srl` (SR Linux as universal digital twin target — see §14)
- Node image: configurable per deployment context (default: `ghcr.io/nokia/srlinux`)
- Links: directly from `LabTopologySpec.links` (source/target interface preserved)

**Stage B — State Reconstruction** (OC payload generation):
- Source: semantic views (`v_interfaces`, `v_bgp_neighbors`, `v_routes`, `topology_links`)
- Target: OC JSON payloads consumable by `SrlExporter`
- Conversion: vendor-specific field values → OC-normalized values via OC Conversion Sandbox (see §15)
- Coverage: semantic views are primary; `parsed_outputs.raw_output` fallback for fields not in views
- Output format: `openconfig-interfaces:interfaces/interface[name=...]/config` etc.

### 8.4 Isolation Contract

All validation collection must land in an isolated DB or isolated schema so that validation results never pollute production truth.

### 8.5 Execution Boundary

The CLAB CAB path may write only to the isolated validation environment.

It must not:

1. push configuration to production devices
2. trigger production rollback actions automatically
3. commit production network changes on behalf of the operator

The output of the CAB path is a recommendation and evidence package for human decision-making.

---

## 9. Assertions

The CAB path must evaluate explicit assertions, not vague success text.

Examples:

1. BGP sessions that must remain established
2. prefixes that must remain reachable
3. next-hop choice that must or must not change
4. interfaces or links that must remain unaffected
5. policy behaviors that must hold after the change
6. blast-radius boundaries that must not expand

Assertions should be defined before lab execution whenever possible.

---

## 10. Prediction vs Observation

The strongest part of this design is not lab replay by itself.

It is the comparison between:

1. what the Ops sandbox predicted
2. what the CLAB lab actually observed

This comparison gives OLAV a much stronger operating model:

- sandbox for fast guided reasoning
- CLAB for strict replay and evidence
- mismatch detection to expose weak hypotheses or missing semantics

If prediction and observation diverge, the CAB verdict must degrade accordingly.

---

## 11. Verdict Model

Recommended verdict classes:

1. `RECOMMEND_HUMAN_EXECUTION`
2. `RECOMMEND_HUMAN_EXECUTION_WITH_CONDITIONS`
3. `NEEDS_REVIEW`
4. `REJECT_CHANGE`

The verdict must be based on:

- assertion results
- protocol observations
- blast radius comparison
- prediction vs observation match quality

---

## 12. Evidence Artifact

```json
{
  "lab_id": "cab-R1-bgp-policy-20260320T123000",
  "timestamp": "2026-03-20T12:30:00+11:00",
  "candidate_plan_source": "ops_networkx_sandbox",
  "query_contract": "semantic_views",
  "graph_contract": "topology_links",
  "render_contract": "schema_catalog+canonical_projection",
  "predicted_risk": "high",
  "observed_risk": "medium",
  "prediction_match": "partial",
  "assertions": {
    "passed": 8,
    "failed": 1
  },
  "verdict": "NEEDS_REVIEW",
  "audit_run_id": "3a1a02da-..."
}
```

The artifact must say explicitly whether the result came from lab observation, not only from sandbox reasoning.
It must also state explicitly that production execution remains a human responsibility.

---

## 13. Required Codebase Changes

### 13.1 CLAB API Schema Import

✅ **Done** (`api_registry.py` + `clab_client.py` schema-aware migration, 2026-03-27).

The codebase keeps schema-import: `CLabClient.build()` bootstraps `~/.olav/olav_registry.duckdb` via subprocess, verifies 7 required operations, builds URLs from schema paths.

### 13.2 Reduced Topology Render

✅ **Done** (`CLABCABAgent.build_reduced_topology()`, `clab_cab.py`, 2026-03-27).

Blast-radius reduction implemented. Returns `LabTopologySpec` with filtered nodes + links.

**Still needed**: `LabTopologySpec → .clab.yaml` renderer (see §14).

### 13.3 Isolated Validation Collection

✅ **Partially done** (`collect_exec.py` uses per-run DuckDB, 2026-03-27).

`collect_exec()` accepts `db_path` argument, writes to isolated file per `test_run_id`.

**Still needed**: wire CAB `run_validation(dry_run=False)` to pass isolated `db_path` through the full pipeline.

### 13.4 Prediction Comparison

✅ **Done** (`compare_predictions()`, `clab_cab.py`, 2026-03-27).

`PredictionMatch.FULL / PARTIAL / MISMATCH / UNKNOWN` — currently `UNKNOWN` in dry-run. Live comparison activates once lab observation is available.

### 13.5 Topology-to-CLAB Renderer

**Not done.** Needed for `dry_run=False`.

Render `LabTopologySpec` → `.clab.yaml` dict consumable by `CLabClient.deploy()`.
See §14 for full design.

### 13.6 OC Conversion Sandbox

**Not done.** Needed for digital twin baseline reconstruction.

Converts semantic view rows → SRL-compatible OC JSON payloads.
See §15 for full design.

### 13.7 dry_run=False Live Pipeline

**Not done.** `CLABCABAgent.run_validation(dry_run=False)` currently raises `NotImplementedError`.

Full live pipeline: render → deploy → push OC → converge → collect → assert → destroy.
See §16 for full design.

---

## 14. Topology Render — LabTopologySpec → .clab.yaml

### 14.1 Design Principle

SR Linux is the universal digital twin target regardless of production vendor.

Rationale:
- SRL natively supports OpenConfig via gNMI Set (no vendor-specific config push path required)
- SRL ContainerLab images are freely available and well-maintained
- The digital twin validates routing logic and policy intent, not vendor-specific CLI syntax
- Vendor-specific behavior differences (timer defaults, etc.) are acceptable for change-impact validation

### 14.2 Renderer Contract

Input: `LabTopologySpec` (from `CLABCABAgent.build_reduced_topology()`)

Output: dict suitable for `CLabClient.deploy(topology_content=...)`

```python
def render_clab_topology(
    spec: LabTopologySpec,
    lab_name: str,
    srl_image: str = "ghcr.io/nokia/srlinux",
) -> dict:
    """Render LabTopologySpec as CLAB topology dict.

    All nodes use kind=srl regardless of production platform.
    Lab name is prefixed with 'cab-' to distinguish from production labs.
    """
```

Output structure:
```yaml
name: cab-{lab_name}-{run_id[:8]}
prefix: ""          # always — ensures short node names in exec API response
topology:
  defaults:
    kind: srl
    image: {srl_image}
  nodes:
    {node.name}: {}    # one entry per LabNode
  links:
    - endpoints: ["{link.source}:{link.source_iface}", "{link.target}:{link.target_iface}"]
```

`prefix: ""` is mandatory — without it exec API returns `clab-{lab}-{node}` names, breaking node lookup in `collect_exec`.

### 14.3 Interface Name Mapping

SRL uses `ethernet-1/1`, `ethernet-1/2`, etc. Production interfaces may be `eth1`, `Gi0/0`, `et-0/0/0`.

The renderer must map production interface names to SRL format:
- `eth1`, `e1`, `Ethernet1` → `ethernet-1/1`
- `eth2`, `e2`, `Ethernet2` → `ethernet-1/2`
- Fallback: `ethernet-1/{index}` where index is derived from the link order

### 14.4 Location

`src/olav/core/clab_topology_render.py` — belongs to `olav-netops` (network-domain rendering logic).

---

## 15. OC Conversion Sandbox — Vendor State → SRL Config

### 15.1 Problem Statement

Production devices collect data as vendor CLI text stored in `parsed_outputs.raw_output`.
Semantic views (`v_interfaces`, `v_bgp_neighbors`) already normalize this into OC-like structure.
SRL accepts configuration via gNMI Set using standard OpenConfig paths.

The gap: semantic view rows must be projected into SRL-consumable OC JSON payloads, with field values normalized to OC conventions.

### 15.2 Conversion Pipeline

```
parsed_outputs.raw_output (vendor CLI text)
        ↓  [already done — Phase 3 pipeline]
semantic views (v_interfaces, v_bgp_neighbors, v_routes)
        ↓  [new — OC Conversion Sandbox]
OC JSON payloads per SRL OC path
        ↓  [already exists]
SrlExporter.export_interfaces() / export_bgp_neighbors()
        ↓  [already exists]
SRL gNMI Set
```

### 15.3 Semantic View → OC Payload Mapping

**Interfaces** (`v_interfaces` → `openconfig-interfaces:interfaces`):

| View field | OC path |
|---|---|
| `interface_name` | `interface[name=...]/config/name` |
| `admin_status` | `interface[name=...]/config/enabled` (UP→true) |
| `ip_address` | `interface[name=...]/subinterfaces/subinterface[index=0]/ipv4/addresses/address[ip=...]/config/prefix-length` |
| `mtu` | `interface[name=...]/config/mtu` |
| `description` | `interface[name=...]/config/description` |

**BGP neighbors** (`v_bgp_neighbors` → `openconfig-bgp:bgp/neighbors`):

| View field | OC path |
|---|---|
| `peer_ip` | `neighbor[neighbor-address=...]/config/neighbor-address` |
| `remote_as` | `neighbor[neighbor-address=...]/config/peer-as` |
| `local_as` | `neighbor[neighbor-address=...]/config/local-as/config/as-number` |
| `state` | read-only — not pushed to lab |

**Note on routes**: Static routes may be pushed for connectivity; dynamic routes (BGP/OSPF) are allowed to reconverge in the lab after baseline config is applied.

### 15.4 Non-Standard OC → Standard OC Conversion

Some vendor-collected data uses non-standard field names or value formats that differ from OC conventions. The conversion sandbox handles this in two layers:

**Layer 1 — Value normalization** (existing `transform_sandbox.py`):
- `bool_up_down`: `"up"/"Up"/"UP"` → `True` (OC `enabled`)
- `to_int`: string MTU values → integer
- `upper`: state enum normalization

**Layer 2 — Structural normalization** (new, in `clab_topology_render.py`):
- Interface name: `Gi0/0`, `et-0/0/0`, `eth1` → SRL `ethernet-1/N`
- IP/prefix: `10.0.0.1/24` → split into `ip` + `prefix-length`
- BGP peer state: vendor-specific state strings → ignored for config push (state is not pushed)

**Layer 3 — Coverage gap fallback** (new):
- If a field required for digital twin reconstruction is absent from semantic views, fall back to regex extraction from `parsed_outputs.raw_output`
- Log gap — these are signals for Phase 3 OC coverage improvement

### 15.5 Location

`src/olav/core/oc_payload_builder.py` — belongs to `olav-netops`.

Depends on: `views.py` (semantic views), `transform_sandbox.py` (value normalization), `srl_exporter.py` (gNMI push).

---

## 16. dry_run=False — Live Pipeline Design

### 16.1 Pipeline

`CLABCABAgent.run_validation(plan, dry_run=False)` executes:

```python
async def run_validation_live(self, plan: CandidatePlan, run_id: str) -> CABEvidenceArtifact:
    # 1. Build reduced topology
    spec = self.build_reduced_topology(plan.blast_radius_estimate)

    # 2. Render .clab.yaml
    topology_content = render_clab_topology(spec, lab_name=run_id)

    # 3. Build OC baseline payloads
    payloads = build_oc_payloads(spec.node_names(), self.snapshot)

    # 4. Deploy lab
    client = await CLabClient.build(api_server, token)
    deploy_result = await client.deploy(topology_content)
    lab_name = deploy_result.lab_name

    # 5. Wait for nodes ready
    await wait_readiness(deploy_result)

    # 6. Push baseline OC config via gNMI
    for node_name, oc_payload in payloads.items():
        exporter = SrlExporter(target=(node_name, 57400), ...)
        exporter.export_interfaces(oc_payload["interfaces"])
        exporter.export_bgp_neighbors(oc_payload["bgp_neighbors"])

    # 7. Apply proposed change delta
    await apply_change_delta(client, lab_name, plan.actions)

    # 8. Wait for convergence
    await wait_readiness(deploy_result, protocol_check=True)

    # 9. Collect post-change state into isolated DB
    isolated_db = f".olav/databases/cab_{run_id}.duckdb"
    await collect_exec(deploy_result, plan_as_execution_plan, db_path=isolated_db)

    # 10. Evaluate assertions against isolated DB
    post_snapshot = ControlPlaneIR(isolated_db).build()
    agent_post = CLABCABAgent(post_snapshot)
    assertion_results = agent_post.evaluate_assertions(plan.assertions, spec.blast_radius_devices)

    # 11. Compare predictions
    prediction_match = self.compare_predictions(plan, assertion_results, lab_deployed=True)

    # 12. Destroy lab
    await client.destroy(lab_name)

    # 13. Return artifact
    return self._build_artifact(plan, assertion_results, prediction_match, run_id, lab_deployed=True)
```

### 16.2 Change Delta Application

`plan.actions` is a list of strings (proposed config commands). For SRL:
- Commands are translated to gNMI Set operations via a simple action parser
- OR applied via `clab_client.exec_command()` using SRL CLI syntax
- The simpler path for Phase 6: exec_command with SRL CLI; gNMI path for Phase 7+

### 16.3 Isolated DB Contract

Each CAB live run uses a dedicated DuckDB file: `.olav/databases/cab_{run_id}.duckdb`.

This file:
- Is created fresh per run (never reused)
- Is destroyed after artifact emission (or retained for audit if configured)
- Must never be the production `.olav/databases/main.duckdb`
- Is passed as `db_path` to `collect_exec()` and `ControlPlaneIR()`

### 16.4 gNMI Connectivity

SRL ContainerLab nodes expose gNMI on port 57400 by default.

From the CAB runner (CI host or OLAV backend):
- gNMI target: `{clab_mgmt_ip}:57400` (management IP from `deploy_result.nodes`)
- Credentials: `admin` / `NokiaSrl1!` (default SRL credentials)
- TLS: insecure for lab use (`insecure=True`)

**Note**: Management IPs are on the Docker bridge network of the CLAB server (192.168.100.x). gNMI calls must originate from the CLAB server itself or a host on the same bridge, not from the CI host (192.168.100.50).

---

## 17. Final Position

The CLAB CAB agent should be treated as:

1. the strict validation layer for change approval
2. the evidence-producing stage of the workflow
3. the place where candidate plans are challenged by observed behavior
4. an advisory system for human change execution

It should not be treated as:

1. the primary troubleshooting interface
2. a free-form reasoning sandbox
3. a replacement for the Ops NetworkX sandbox
4. a production change writer

The correct OLAV workflow is therefore:

1. investigate and propose in the NetworkX sandbox
2. validate in CLAB CAB
3. hand the evidence and recommendation to a human network engineer for execution

That separation gives OLAV a stronger operational model than forcing one engine to serve both exploratory reasoning and formal approval.
---

## §17 Agent-Driven OC Config Extraction

**版本:** v0.3 (2026-03-27)  
**替代:** §15 `oc_payload_builder.py` 中的硬编码提取路径

### 设计动机

原有 `build_oc_payloads()` 只提取两个维度（topology_links 中的接口 + bgp_neighbors），且接口 IP 靠 /30 子网启发式反推，无法覆盖多协议变更场景。

新架构让 `CABConfigExtractor` 通过 `schema_catalog` + `yang_leaves` 内省 DB schema，根据 `change_intent` 决定查询哪些 semantic view，再由确定性转换层生成 SRL 配置。

### Phase A — 协议检测与 view 选择（规则驱动）

```
change_intent
    ↓  关键词匹配（bgp/ospf/isis/evpn/vxlan/mpls/stp）
    ↓  _PROTOCOL_VIEW_MAP
selected_views + v_interfaces_auto（始终包含）
```

`CABConfigExtractor.select_views_for_change(change_intent, available_views)` 返回需要查询的 view 名列表。无匹配时回退到 BGP + interfaces 默认集。

### Phase B — SQL 查询

`query_views_for_devices(view_names, devices)` 对每个 view 执行：

```sql
SELECT * FROM {view} WHERE device_name IN (?)
```

返回 `{view_name: [row_dicts]}`，查询失败时静默返回空列表。

### Phase C — OC 字段提取

`extract_oc_fields(view_data, devices)` 将每行 view 数据与 `schema_catalog` join：

1. 读取每个 view 对应的 CLI 命令 hint（`_VIEW_COMMAND_HINTS`）
2. 从 schema_catalog 拿到该命令下 `{col_name: openconfig_path}` 映射
3. 每个有 OC 路径的列生成一个 field dict：`{openconfig_path, value, ...context_keys}`
4. context keys：`neighbor-address`（来自 neighbor_ip）、`interface` 等

### Phase D — 确定性 SRL 渲染

见 §18。`render_all_devices()` 是完整 A→D 管道入口。

### 模块 API

```python
# src/olav/core/cab_config_extractor.py
class CABConfigExtractor:
    def __init__(self, db_path: str): ...
    def get_schema_catalog(self) -> dict[str, list[str]]: ...
    def select_views_for_change(self, change_intent, available_views) -> list[str]: ...
    def query_views_for_devices(self, view_names, devices) -> dict[str, list[dict]]: ...
    def extract_oc_fields(self, view_data, devices) -> dict[str, list[dict]]: ...
    def render_all_devices_from_views(self, view_data, devices, iface_map) -> dict[str, str]: ...
    def render_all_devices(self, change_intent, blast_radius_devices, iface_map) -> dict[str, str]: ...
```

### 与 run_validation_live() 的集成

`CLABCABAgent.from_db()` 现在将 `db_path` 存储为 `self._db_path`。  
`run_validation_live()` 的 Step 2 优先使用 `CABConfigExtractor`，无 `_db_path` 时回退到 `build_oc_payloads()`（兼容不通过 `from_db()` 构造的测试场景）。

---

## §18 确定性 SRL 翻译层

**模块:** `src/olav/core/srl_config_renderer.py`

### 四条翻译规则（顺序执行）

| 规则 | 函数 | 说明 |
|------|------|------|
| ① 过滤 olav: 扩展 | `filter_olav_paths()` | 移除 `olav:` 命名空间和无 OC 路径的字段 |
| ② state→config path | `state_to_config_path()` | `/state/` 节段替换为 `/config/` |
| ③ 接口名规范化 | `map_iface_to_srl()` (已有) | GigabitEthernet0/1 → ethernet-1/1 |
| ④ OC leaf → SRL CLI | `oc_leaf_to_srl_cli()` | 模式匹配生成 `set /...` 命令 |

### oc_leaf_to_srl_cli 支持的模式

| OC 路径模式（后缀匹配） | 上下文键 | SRL 命令 |
|------------------------|---------|---------|
| `interfaces/interface/config/admin-status` | interface | `set / interface {iface} admin-state enable\|disable` |
| `interfaces/interface/config/mtu` | interface | `set / interface {iface} mtu {value}` |
| `interfaces/.../subinterface/.../config/ip` | interface | `set / interface {iface} subinterface 0 ipv4 address {cidr} primary` |
| `.../bgp/neighbors/neighbor/config/peer-as` | neighbor-address | `set / network-instance default protocols bgp neighbor {ip} peer-as {as}` |
| `.../bgp/neighbors/neighbor/config/enabled` | neighbor-address | `set / network-instance default protocols bgp neighbor {ip} admin-state enable` |
| `.../bgp/global/config/as` | — | `set / network-instance default protocols bgp autonomous-system {as}` |
| `.../bgp/global/config/router-id` | — | `set / network-instance default protocols bgp router-id {ip}` |

### 说明

- IP 地址必须包含前缀长度（CIDR 格式），否则跳过（无法配置 SRL 接口地址）
- 未知路径静默返回 None（不中断渲染流程）
- `db_path` 参数可选：提供时用 `yang_leaves` 验证路径合法性

---

## §19 能力边界寄存器（Capability Boundary Register）

记录 SRL 数字孪生可仿真与不可仿真的范围。E2E 测试覆盖状态随测试推进更新。

| 协议/特性 | OC View 可用 | SRL 可配置 | E2E 测试覆盖 | 备注 |
|----------|------------|-----------|------------|------|
| BGP eBGP 邻居 | ✅ v_bgp_neighbors_auto | ✅ | 🟡 P0 – 待 e2e | 核心测试场景 |
| BGP iBGP + RR | ✅ | ✅ | ❌ | P1 待补充 |
| 接口 IP（含前缀的 CIDR） | ✅ v_interfaces_auto | ✅ | 🟡 P0 | 必须是 x.x.x.x/n 格式 |
| 接口 admin-state | ✅ v_interfaces_auto | ✅ | 🟡 P0 | |
| 接口 MTU | ✅ v_interfaces_auto（如采集） | ✅ | ❌ P2 | |
| OSPF 邻接 | ✅ v_ospf_neighbors | ✅ | ❌ P1 | SRL 支持 OC OSPF |
| IS-IS 邻接 | 🟡 skeleton | ✅ | ❌ P2 | View 存在，数据稀少 |
| EVPN 实例 | 🟡 skeleton | ✅ | ❌ P2 | |
| VXLAN 隧道 | 🟡 skeleton | ✅ | ❌ P2 | |
| MPLS LDP peers | 🟡 skeleton | ✅ | ❌ P2 | |
| STP 端口状态 | ✅ v_stp_ports | ❌ 仿真无意义 | ❌ | SRL 无 STP 兼容模式 |
| 路由策略/route-map | ❌ 无 OC view | ❌ | ❌ | 不在 CAB 范围内 |
| 防火墙策略 | ❌ 厂商私有 | ❌ | ❌ | SRL 无防火墙模式 |
| ACL | ❌ | ❌ | ❌ | 超出范围 |

**更新规则：** 每次 e2e 测试通过后将对应行的 E2E 列改为 ✅，并记录日期。

