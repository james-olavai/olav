---
name: containerlab-e2e
description: >
  Use when: running ContainerLab E2E pipeline, deploying virtual network labs,
  configuring Nokia SR Linux nodes, collecting BGP/topology state from containers,
  debugging CLAB API failures, fixing E2E test failures, self-healing pipeline bugs.
  Covers: deploy_lab, configure_device, wait_readiness, collect_exec, run_assertions,
  destroy_lab, ContainerLab REST API, NodeFilter workaround, SRL BGP config, JWT auth.
---

# ContainerLab E2E Skill

> **Progressive Disclosure**: This file is the entry point. Load sub-references
> **only** when the task requires that specific detail.

## Quick Start

```bash
# 1. Get a fresh JWT token
export CLAB_API_TOKEN=$(curl -s -X POST http://192.168.100.12:8080/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"yhvh","password":"jAmes92323"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")

# 2. Run the full pipeline
cd /home/yhvh/Olav
uv run python .agent/skills/containerlab-e2e/scripts/run_e2e.py \
    --scenario .agent/skills/containerlab-e2e/topologies/bgp_2node.clab.yaml \
    [--dry-run-only] \
    [--skip-destroy]
```

**Expected result (passing run)**:
```
[9/9] track_coverage
E2E result: PASSED
  sql_count_0 ✓  (2 rows in parsed_outputs WHERE command LIKE '%bgp%')
  sql_count_1 ✓  (1 row in topology_links)
  file_exists_2 ✓ (exports/snapshots exists)
```

---

## Pipeline Steps (9-step orchestrator in `run_e2e.py`)

| Step | Module | Purpose | Output artifact |
|------|--------|---------|----------------|
| 1 | `compile_scenario` | Parse YAML → `ExecutionPlan` | `evidence/<run_id>/execution-plan.json` |
| 2 | `deploy_lab` | POST topology → ContainerLab API | `evidence/<run_id>/deploy.json` |
| 3 | `configure_device --dry-run` | Render templates, preview only | `evidence/<run_id>/config-preview/` |
| 4 | `configure_device --apply` | Write files + hostname-conditional exec | `evidence/<run_id>/configure.json` |
| 5 | `wait_readiness` | SSH poll + exec fallback health check | `evidence/<run_id>/readiness.json` |
| 6 | `prepare_netops` | Create isolated test DuckDB + nornir inv | `evidence/<run_id>/nornir_inventory.yaml` |
| 7 | `collect_exec` | BGP state via exec API → DuckDB | `exports/snapshots/json/*.staging.json` |
| 8 | `run_assertions` + `collect_artifacts` | Evaluate SQL/file assertions | `evidence/<run_id>/assertions.json` |
| 9 | `destroy_lab` + `track_coverage` | DELETE lab + update coverage matrix | `evidence/<run_id>/destroy.json` |

---

## Critical API Behaviors (Know Before You Debug)

> **Full details** → [references/api-behaviors.md](references/api-behaviors.md)

### The 3 Rules That Always Bite

1. **NodeFilter is silently ignored** — every exec command runs on ALL nodes.
   Workaround: hostname-conditional bash (already in `configure_device.py`):
   ```bash
   bash -c 'H=$(hostname); cfg=/tmp/olav_<rid>_${H}.cfg; [ -f "$cfg" ] && sr_cli < "$cfg" 2>&1 || echo SKIP_$H'
   ```

2. **Management IPs unreachable from CI host** — `192.168.100.110/111` are only
   reachable from the clab server's Docker bridge. Use exec API for all collection.

3. **Deploy format** — `topologyContent` must be a **JSON dict** (output of
   `yaml.safe_load()`), not a YAML string. Lab name = `next(iter(response_body))`.

## Collection Architecture — Why Exec API, Not Nornir

管理 IP（192.168.100.110/111）只在 clab 服务器的 Docker bridge 可达，**CI 主机（192.168.100.50）无法 SSH 连接**。
因此 nornir 的 SSH collect 路径被 exec API 替代，但 **其余管道完全走生产路径**：

```
ContainerLab exec API          # 替代 nornir SSH（唯一的差别）
    ↓ raw CLI stdout
staging.json                   # IngestManager 格式（device_name/command/parsed_data/snapshot_id）
    ↓
IngestManager.bulk_load()      # 同生产代码路径（schema 校验、ON CONFLICT upsert）
    ↓
test DuckDB → netops.parsed_outputs    # 与生产 DDL 完全相同
test DuckDB → netops.topology_links    # 直接 INSERT（IngestManager 无 topology 路径）
```

**不可跳过的规则（AGENTS.md §3）**：`collect_exec.py` 不得直接 `INSERT INTO`，
必须写 staging.json → `IngestManager.bulk_load()`。staging 目录用 `evidence/<run_id>/staging/`，
与生产 `exports/snapshots/json/` 完全隔离。

---

> **Full signatures + argument docs** → [references/module-interfaces.md](references/module-interfaces.md)

```python
compile_scenario(scenario_path: Path, evidence_base: Path | None) -> ExecutionPlan
async deploy_lab(plan: ExecutionPlan, api_server: str, evidence_dir: Path) -> DeployResult
async configure_device(deploy: DeployResult, config_dir: Path, dry_run: bool, ...) -> ConfigureResult
async wait_readiness(deploy: DeployResult, ...) -> ReadinessResult
prepare_netops(deploy: DeployResult, evidence_dir: Path) -> PrepareNetopsResult
async collect_exec(deploy: DeployResult, plan: ExecutionPlan, db_path: str, ...) -> bool
run_assertions(test_run_id: str, assertions: list, db_path: str, ...) -> AssertionsResult
collect_artifacts(test_run_id: str, evidence_dir: Path, base_dir: Path | None) -> ArtifactsResult
async destroy_lab(deploy: DeployResult, output_dir: Path) -> DestroyResult
track_coverage(test_run_id: str, scenario_name: str, ...) -> CoverageMatrix
```

---

## File Layout

```
.agent/skills/containerlab-e2e/
├── SKILL.md                        ← This file (entry point)
├── scripts/                        ← All Python executables
│   ├── models.py                   ← All Pydantic models + get_auth_headers()
│   ├── run_e2e.py                  ← 9-step orchestrator
│   ├── compile_scenario.py         ← Step 1
│   ├── deploy_lab.py               ← Step 2
│   ├── configure_device.py         ← Steps 3 + 4
│   ├── wait_readiness.py           ← Step 5
│   ├── collect_artifacts.py        ← Step 6
│   ├── run_assertions.py           ← Step 7a
│   ├── run_query_assertions.py     ← Step 7b
│   ├── destroy_lab.py              ← Step 8
│   ├── track_coverage.py           ← Step 9
│   ├── hosts_inject.py             ← Nornir inventory injection
│   ├── run_session.py              ← Long-lived lab session orchestrator
│   ├── olav_invoke.py              ← OLAV query bridge
│   └── manage_lab.py              ← enterprise-dual-site lab manager (API-only)
├── lab_sessions/
│   └── enterprise_dual_site/
│       ├── topology.clab.yaml      ← ContainerLab topology (12 nodes)
│       ├── SESSION.yaml            ← Node registry + test suite refs
│       └── config/                 ← Jinja2 config templates per platform
├── topologies/
│   └── bgp_2node.clab.yaml         ← Minimal SRL eBGP topology
├── test_suites/
│   ├── L2_access/
│   ├── L3_routing/
│   └── fault_injection/
└── references/
    ├── api-behaviors.md            ← CLAB REST API quirks
    └── module-interfaces.md        ← Full function signatures
```
