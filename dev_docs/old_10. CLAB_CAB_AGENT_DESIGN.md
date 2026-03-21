# 08. CAB Sub-Agent: ContainerLab Digital Twin

> HISTORICAL DOCUMENT ONLY (do not use as current authority).
>
> Current authoritative CLAB/CAB design is in `dev_docs/10. CLAB_CAB_AGENT_DESIGN.md`.
> Related current chain: `dev_docs/09. NETWORKX_SANDBOX_DESIGN.md`, `dev_docs/11. CONTROL_PLANE_SEMANTIC_ENGINE.md`,
> `dev_docs/12. PLATFORM_NETOPS_OWNERSHIP_MAP.md`, `dev_docs/01. tracking.md`.

> Archive note: this file is retained for draft-history traceability only.

**Status:** Design  
**Version:** v0.2 (2026-03-19) — Schema-Aware + Sandbox approach  
**Depends on:** `07. OPENCONFIG_SCHEMA_DESIGN.md` (OC-9)

---

## 1. Overview

The **ContainerLab (CLAB) CAB Sub-Agent** provisions a digital twin of the production network, pushes a proposed OpenConfig configuration change, runs assertions, and returns signed evidence to the Ops Agent for Change Advisory Board (CAB) approval.

**Design philosophy (OLAV-native):**  
Instead of writing custom scripts per CLAB API operation, OLAV imports the CLAB OpenAPI spec into DuckDB once. The Ops Agent sandbox then discovers endpoints via schema query and generates `requests` calls dynamically — zero hand-written API adapters.

**Key assumptions:**
- ContainerLab is installed and managed by the operator on a **remote host**.
- OLAV connects exclusively via the **ContainerLab HTTP REST API**.
- The API address and token are user-supplied in `.olav/config/skills/clab.yaml`.
- OLAV's DuckDB stores device state as **standard OpenConfig JSON** (post OC-sprint).

---

## 2. Configuration

Operator configures the remote CLAB server once:

**`.olav/config/skills/clab.yaml`**
```yaml
clab:
  api_url: "https://192.168.100.12:8080"  # Remote CLAB host
  api_token: "${CLAB_API_TOKEN}"          # Env var — never hardcode
  tls_verify: false
  default_timeout_s: 300
```

> Export `CLAB_API_TOKEN` as an environment variable. Never commit it.

---

## 3. Architecture

```
User: "Prove this BGP policy change is safe on R1"
    ↓
Ops Agent (ReAct, Tier 2)
    │
    ├─ 1. Query DuckDB (OpenConfig state)  → current R1 config
    │
    ├─ 2. Config Generator                 → proposed OC delta JSON
    │
    └─ 3. CAB Sub-Agent (sandbox)
              │
              ├─ Query clab_api_schema     → discover endpoints
              │    "POST /api/v1/labs — deploy topology"
              │    "GET  /api/v1/labs/{id} — poll readiness"
              │    "DELETE /api/v1/labs/{id} — destroy"
              │
              ├─ Generate + execute code
              │    deploy → wait → push OC config → collect → assert
              │
              └─ Return evidence artifact
    │
Ops Agent: "Change safe. 8/8 assertions passed. Lab: cab-R1-xyz"
```

---

## 4. OLAV-Native Design: Schema Import + Sandbox

### 4.1 Two Tools Only

The skill exposes exactly two tools — no per-operation scripts:

```yaml
# .olav/workspace/ops/clab/SKILL.md
tools:
  - name: clab_import_schema
    description: >
      Fetch the ContainerLab OpenAPI spec from {api_url}/openapi.yaml
      and store all endpoints + parameter schemas in DuckDB table
      `clab_api_schema`. Run once after configuring clab.yaml.

  - name: clab_sandbox
    description: >
      Schema-aware sandbox for ContainerLab operations. The agent queries
      clab_api_schema to discover the right endpoint, generates Python
      requests code, and executes it. Returns structured JSON.

static_context:
  - .olav/config/skills/clab.yaml
```

### 4.2 Schema Import (`clab_import_schema`)

```python
# Fetches CLAB OpenAPI spec → DuckDB
# Run once. Re-run after CLAB version upgrades.
GET {api_url}/openapi.yaml
→ parse endpoints, methods, parameter schemas
→ INSERT INTO clab_api_schema (endpoint, method, params_schema, description)
```

Result in DuckDB:
```
endpoint              | method | description
/api/v1/labs          | POST   | Deploy a new lab
/api/v1/labs          | GET    | List running labs
/api/v1/labs/{id}     | GET    | Get lab status and node list
/api/v1/labs/{id}     | DELETE | Destroy a lab
/api/v1/labs/{id}/nodes/{node} | GET | Get node details
...
```

### 4.3 Sandbox Execution (`clab_sandbox`)

The agent:
1. Queries `clab_api_schema` to find the right endpoint for the task
2. Generates Python `requests` code with the correct payload (informed by the param schema)
3. Executes in the sandbox
4. Parses the JSON response and returns structured output

```python
# Example: agent-generated sandbox code for "deploy lab"
import requests, os, yaml

cfg = yaml.safe_load(open(".olav/config/skills/clab.yaml"))["clab"]
headers = {"Authorization": f"Bearer {os.environ['CLAB_API_TOKEN']}"}

# Topology generated from DuckDB OpenConfig state
topology = {
  "name": "cab-R1-bgp-20260319",
  "nodes": [...],   # from DuckDB devices table
  "links": [...],   # from DuckDB topology_links table
}

r = requests.post(f"{cfg['api_url']}/api/v1/labs",
                  json=topology, headers=headers,
                  verify=cfg["tls_verify"])
r.raise_for_status()
print(r.json())     # → {"lab_id": "cab-R1-bgp-20260319", "status": "deploying"}
```

**When CLAB upgrades its API**, the agent re-runs `clab_import_schema` and the sandbox code adapts automatically — no script edits required.

---

## 5. End-to-End Flow

```
1. clab_import_schema          (one-time setup)
        ↓
2. Agent queries DuckDB:
   "Which OC JSON represents R1's current BGP config?"
        ↓
3. Agent generates topology from DuckDB devices + topology_links
        ↓
4. clab_sandbox: POST /api/v1/labs      → lab_id
        ↓
5. clab_sandbox: GET  /api/v1/labs/{id} → poll until all nodes "running"
        ↓
6. For each node: gNMI Set (OC delta JSON) via pygnmi
   (gNMI endpoint resolved from GET /api/v1/labs/{id}/nodes)
        ↓
7. Collect state from lab nodes (reuse collect_commands with target_hosts)
   → ingest into isolated temp DuckDB (not main.duckdb)
        ↓
8. Run SQL assertions against temp DuckDB
        ↓
9. clab_sandbox: DELETE /api/v1/labs/{id}   (always — even on failure)
        ↓
10. Return evidence artifact
```

---

## 6. Evidence Artifact

```json
{
  "lab_id": "cab-R1-bgp-policy-20260319T123000",
  "operator": "alice",
  "timestamp": "2026-03-19T12:30:00+11:00",
  "change_description": "Add BGP policy NO_EXPORT on R1 toward AS65002",
  "topology_snapshot_id": "2026-03-19",
  "assertions": {
    "passed": 8,
    "failed": 0,
    "details": [
      {"name": "bgp_sessions_established", "sql": "SELECT ...", "passed": true},
      {"name": "route_count_stable",        "sql": "SELECT ...", "passed": true}
    ]
  },
  "verdict": "SAFE_TO_PUSH",
  "audit_run_id": "3a1a02da-..."
}
```

`audit_run_id` links the evidence into `audit.duckdb` — the full lifecycle (detect → simulate → lab-prove → CAB) is auditable in one place.

---

## 7. Impact on Existing Codebase

| Component | Change |
|:---|:---|
| `.olav/config/skills/clab.yaml` | **New** — operator-supplied |
| `.olav/workspace/ops/clab/SKILL.md` | **New** — 2 tools only |
| `clab_api_schema` DuckDB table | **New** — populated by `clab_import_schema` |
| `collect_commands` | **Minor** — accept `target_hosts` override for lab nodes |
| `IngestManager` | **Minor** — accept `db_path` override for isolated lab DuckDB |
| Everything else | **No change** |

---

## 8. Operator Quick-Start

```bash
# 1. Configure remote CLAB server
cat > .olav/config/skills/clab.yaml << EOF
clab:
  api_url: "https://<your-clab-host>:8080"
  api_token: "${CLAB_API_TOKEN}"
  tls_verify: false
  default_timeout_s: 300
EOF

# 2. Export token
export CLAB_API_TOKEN=<token>

# 3. Import CLAB API schema into DuckDB (one-time)
uv run olav --agent ops "Run clab_import_schema()"

# 4. Prove a change
uv run olav --agent ops \
  "Add a static route 10.99.0.0/24 on R1 and R2. Prove it is safe before pushing."
```
