# Module Interfaces — Full Signatures

All modules live in `.agent/skills/containerlab-e2e/`.
All Pydantic models are in `models.py`.

---

## `models.py` — Shared Data Models

### Key Constants
```python
DEFAULT_API_SERVER = "http://192.168.100.12:8080/api/v1"
DEFAULT_SSH_TIMEOUT = 180
DEFAULT_PROTOCOL_TIMEOUT = 240
MGMT_CLOUD_BASE = "192.168.100"
MGMT_CLOUD_START_OFFSET = 110   # r1→.110, r2→.111, ...
```

### Key Models

```python
class NodeInfo(BaseModel):
    name: str
    container_name: str
    platform: str
    mgmt_cloud_ip: str
    mgmt_cloud_port: int
    username: str
    password: str

class DeployResult(BaseModel):
    test_run_id: str
    lab_name: str
    api_server: str
    nodes: dict[str, NodeInfo]
    timestamp: str
    status: Literal["success", "failed"]

class ExecutionPlan(BaseModel):
    test_run_id: str
    scenario_name: str
    nodes: list[PlannedNode]
    links: list[PlannedLink]     # ← used by collect_exec for topology_links
    assertions: list[ScenarioAssertion]
    topology_file: str

class ScenarioAssertion(BaseModel):
    type: Literal["sql_count", "file_exists"]
    query: str | None           # for sql_count
    path: str | None            # for file_exists
    operator: str               # "eq", "gte", "gt", etc.
    expected: int | str
```

---

## `compile_scenario.py`

```python
def compile_scenario(
    scenario_path: Path,
    evidence_base: Path | None = None,
) -> ExecutionPlan
```
Reads a YAML scenario file and returns a fully resolved `ExecutionPlan`.
Allocates mgmt IPs (192.168.100.110+), P2P addresses from pool, loopbacks.

```python
def compile_scenario_from_dict(data: dict) -> ExecutionPlan
```
Same but accepts a pre-parsed dict (useful in tests).

---

## `deploy_lab.py`

```python
async def deploy_lab(
    plan: ExecutionPlan,
    api_server: str = DEFAULT_API_SERVER,
    evidence_dir: Path | None = None,
) -> DeployResult
```
POSTs topology to ContainerLab API. Writes `deploy.json` to `evidence_dir`.

**Internal**: `_resolve_topology_content(topology_ref: str) -> dict`  
Reads the `.clab.yaml` file and returns `yaml.safe_load()` result (JSON dict).

---

## `configure_device.py`

```python
async def configure_device(
    deploy: DeployResult,
    config_dir: Path,
    dry_run: bool = True,
    api_server: str | None = None,
    evidence_dir: Path | None = None,
) -> ConfigureResult
```

**`dry_run=True`** (Step 3): Renders templates and writes previews to
`evidence_dir/config-preview/<node>/step_NNN.txt`. No API calls.

**`dry_run=False`** (Step 4): Two-phase exec:
1. Write all node cfg files to all containers (hostname-keyed temp paths)
2. Hostname-conditional apply via `sr_cli`

Config files looked up at: `config_dir/<platform>/<node_name>/*.cfg`
Fallback: `config_dir/<node_name>/*.cfg`

---

## `wait_readiness.py`

```python
async def wait_readiness(
    deploy: DeployResult,
    ssh_timeout: float = DEFAULT_SSH_TIMEOUT,
    protocol_timeout: float = DEFAULT_PROTOCOL_TIMEOUT,
    poll_interval: float = 10.0,
    api_server: str | None = None,
    evidence_dir: Path | None = None,
) -> ReadinessResult
```

**Behavior**:
1. Polls each node's mgmt_cloud_ip:mgmt_cloud_port via TCP (SSH port check)
2. If SSH poll times out → falls back to exec API health check (`hostname` command)
3. If exec health check passes → node marked `ready` via `exec_fallback`

`ReadinessResult.status` = `"success"` if all nodes ready by either method.

---

## `prepare_netops.py`

```python
def prepare_netops(
    deploy: DeployResult,
    evidence_dir: Path | None = None,
) -> PrepareNetopsResult
```

Creates an isolated test DuckDB file (at `evidence_dir/<test_run_id>.duckdb`)
and a nornir YAML inventory file. The DuckDB contains empty `parsed_outputs`
and `topology_links` tables, ready for `collect_exec` to populate.

`PrepareNetopsResult.db_path` → absolute path to the created DuckDB file.

---

## `collect_exec.py`

```python
async def collect_exec(
    deploy: DeployResult,
    plan: ExecutionPlan,
    db_path: str,
    evidence_dir: Path | None = None,
    base_dir: Path | None = None,
) -> bool
```

**BGP collection**: Runs `show network-instance default protocols bgp neighbor`
via exec API on each node. Inserts one row per node into `parsed_outputs`.

**Topology links**: Derived from `plan.links` (topology file as ground truth,
since NodeFilter prevents per-node LLDP discovery). Inserts into `topology_links`.

**JSON snapshots**: Written to `{base_dir}/exports/snapshots/json/*.staging.json`.

Returns `True` on success.

---

## `run_assertions.py`

```python
def run_assertions(
    test_run_id: str,
    assertions: list[ScenarioAssertion],
    db_path: str,
    evidence_dir: Path | None = None,
) -> AssertionsResult
```

Evaluates assertions from the scenario YAML:
- `sql_count`: runs SQL against the test DuckDB, compares row count
- `file_exists`: checks if a path exists on disk

`AssertionsResult.passed` = True if ALL assertions pass.

---

## `collect_artifacts.py`

```python
def collect_artifacts(
    test_run_id: str,
    evidence_dir: Path,
    base_dir: Path | None = None,
) -> ArtifactsResult
```

Scans `evidence_dir` and `exports/snapshots/` for all artifacts produced during
the run. Returns a manifest with file types and sizes.

---

## `destroy_lab.py`

```python
async def destroy_lab(
    deploy: DeployResult,
    output_dir: Path | None = None,
) -> DestroyResult
```

Sends `DELETE /labs/{lab_name}`. Verifies removal via `GET /labs/{lab_name}` (expects 404).
Also checks for residual Docker containers, networks, and volumes.

---

## `track_coverage.py`

```python
def track_coverage(
    test_run_id: str,
    scenario_name: str,
    assertions_result: AssertionsResult,
    coverage_file: Path | None = None,
) -> CoverageMatrix
```

Appends a `CoverageEntry` to the coverage matrix JSON file
(default: `.agent/skills/containerlab-e2e/evidence/coverage.json`).
Upserts by `(scenario_name, test_run_id)`.
