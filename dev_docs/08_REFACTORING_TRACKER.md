# 📈 Agent Refactoring Tracking & Implementation Guide

This document tracks the decomposition of the monolithic `olav-ops` agent into a **Federated Specialist Matrix**.

## 1. Refactoring Goals
- **Context Isolation**: Each specialist should only know the schema/tools relevant to its domain.
- **Speed Optimization**: Tier 1 (SQL/CLI) must bypass the ReAct loop.
- **Reliable Hand-off**: Orchestrator must accurately delegate complex queries based on specialist descriptions.

---

## 2. Implementation Tracking

| Task | Status | Owner | Notes |
| :--- | :--- | :--- | :--- |
| **Phase 0: Time-Series Foundation** | ✅ Done | Dev | Establish Snapshot History |
| ├─ Add `snapshot_id` | ✅ Done | Dev | Update all tables in `sync_schemas.py` to append-only |
| ├─ Update Data Seeding | ✅ Done | - | Ensure snapshot logic in tests/ingestion captures ID |
| **Phase 1: Skill Decomposition** | 🔄 In Progress | Dev | Extracting tools from `olav-ops` |
| ├─ Create `skill-discovery` | ⬜ Todo | - | 接管 Topology/Neighbor 写入逻辑 |
| ├─ Create `skill-topology` | ⬜ Todo | - | 仅负责路径分析 (Read-only) |
| ├─ Create `skill-routing` | ⬜ Todo | - | 仅负责路由逻辑 (Read-only) |
| ├─ Create `skill-probe` | ⬜ Todo | - | Move `execute_cli_parallel` here |
| **Phase 2: Prompt Engineering** | ⬜ Todo | - | - |
| ├─ Specialist-Discovery Prompt | ⬜ Todo | - | **"Modeling Expert"**: Writes logical tables; performs LLM Fuzzy Mapping to Cisco schema |
| ├─ Specialist-Topology Prompt | ⬜ Todo | - | Focus on path-finding. Default query: MAX(snapshot_id) |
| ├─ Specialist-Routing Prompt | ⬜ Todo | - | Focus on reachability. Default query: MAX(snapshot_id) |
| ├─ Specialist-Diff Prompt | ⬜ Todo | - | Multi-dimensional state comparison between snapshots |
| └─ Orchestrator Prompt | ⬜ Todo | - | "Head Doctor" mentality; routing focus |
| **Phase 3: Config & Integration** | ⬜ Todo | - | - |
| ├─ Update `OLAV.md` | ⬜ Todo | - | Define specialists and Hand-off triggers |
| └─ Fast-Path Logic | ⬜ Todo | - | bypass loop for simple SQL/CLI queries |
| **Phase 4: Verification** | ⬜ Todo | - | - |
| ├─ E2E Hand-off Test | ⬜ Todo | - | Verify R1->R2->R3 logic multi-agent flow |
| └─ Performance Audit | ⬜ Todo | - | Compare T1 latency vs T2 latency |

---

## 3. Migration Instructions for Developers

### How to Decompose a Skill
1. **Move Code**: Move Python tools from `src/olav/tools/ops/` to specialized directories (e.g., `src/olav/tools/routing/`).
2. **Update Metadata**: Create/Update `SKILL.md` in the new directory. Only include the subset of the database schema that this specialist *must* know.
3. **Isolate Prompts**: Create a system prompt that explicitly tells the specialist: *"You are an expert in [Domain]. If you need data outside [Domain], return a concise report to the Orchestrator."*

### Orchestrator Hand-off Configuration
In `.olav/OLAV.md`, the `description` is critical. It must clearly state the expertise so the Orchestrator knows when to call it.
```yaml
- name: specialist-routing
  description: "Use this for BGP/OSPF protocol analysis and IP routing table lookups."
```

## 4. Current Blockers / Open Questions
- [ ] Should `format_and_export` be shared via a common skill or kept strictly in the Orchestrator? (Current Decision: Orchestrator only).
- [ ] How to handle shared tables (like `devices`) across multiple specialists? (Current Decision: Most specialists need `devices` for resolution).
