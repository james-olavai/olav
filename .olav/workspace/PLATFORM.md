---
active: quick
agents:
- quick
- ops
- ops-lab
- config
- audit
- core
- netbox
- olav
- venv-test
- netbox-circuits
- influxdb-orgs
platform:
  db: .olav/databases/olav.duckdb
  memory: .olav/databases/memory.lance
  registry: .olav/databases/olav_registry.duckdb
  services:
    clab: http://192.168.100.12:8080
  workspace: .olav/workspace
---

# OLAV Platform — Home Lab

Network operations platform running on a home lab with Nokia SR Linux nodes managed
via ContainerLab.

## Installed Agents

| Agent   | Role |
|---------|------|
| quick   | General-purpose: SQL queries, CLI commands, quick lookups |
| ops     | Deep network ops: topology analysis, routing simulation, lab management, probing |
| ops-lab | Standalone ContainerLab lab engineer: deploy SR Linux digital twin, verify convergence |
| config  | Config lifecycle: snapshot, sync, OpenConfig push |
| audit   | Compliance checks, drift detection, change audit |
| core    | Platform builder: install new skills, register APIs, run arbitrary code |
| netbox  | NetBox DCIM/IPAM: device inventory, IP management, VLANs, racks via REST API |

## Key Paths

- Database: `.olav/databases/olav.duckdb`
- Memory: `.olav/databases/memory.lance`
- API Registry: `.olav/databases/olav_registry.duckdb`
- Workspace: `.olav/workspace/`

## External Services

- **ContainerLab REST API**: `http://192.168.100.12:8080` — lab lifecycle (deploy, destroy, topology)
