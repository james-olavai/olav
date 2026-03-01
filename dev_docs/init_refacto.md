# OLAV Initialization & Collection Refactoring Plan (TDD)

## 1. Vision
Transform the currently fragmented and manually seeded collection system into a robust, automated, and platform-aware data pipeline that ensures data integrity and eliminates "cheating" scripts.

## 2. Core Objectives
1.  **Path Consistency**: Align `init` and `config` to use unified path constants.
2.  **Automated Command Selection**: Automatically select commands based on device platform from a combined library.
3.  **Reliable Parsing**: Ensure raw text is always accompanied by parsed JSON exports.
4.  **Unified Schema Mapping**: Implement a persistent mapping table for cross-platform key unification.
5.  **Remove Cheating Scripts**: Delete all manual seeding scripts and ensure topology is derived from real data.
6.  **Interactive Onboarding**: Provide a guided `onboard` CLI for first-time setup and E2E verification.

---

## 3. The New Onboarding Workflow (`uv run olav onboard`) — REDESIGNED

> **⚠️ Architecture Change [2026-03-01]**
> 
> 原始设计中的 onboard 流程由 Python 脚本手动编排所有步骤。
> 新设计将其重构为 **Agent-Driven**，通过 LLM 的语义理解与增量决策实现真正的智能初始化。
> 
> **关键改变**:
> - Phase 1 (Python/Phase 1): 仅做冷启动检查（无需 LLM）
> - Phase 2-7 (LLM/Agent): 完全由 Config Agent 驱动
> - 增量执行: 仅修复有问题的设备/命令（不全量重采）
> - 无 SSH 重解析: 模板修复后使用 `reparse_outputs` 工具
> 
> **详见**: [dev_docs/olav_onboard.md](./olav_onboard.md) — **完整的高级实现设计与 TDD 计划**

**代替原来的逐步分解**，流程现在概括为：

| 步骤 | 执行方 | 触发方式 | 增量优化 |
| :--- | :--- | :--- | :--- |
| **Phase 1** | Python onboard.py | 用户执行 `uv run olav onboard` | 冷启动检查 (api.json, hosts.yaml, TCP, LLM) |
| **Phase 2-7** | Config Agent | preflight_report.json 驱动 | DuckDB gap 查询 → 仅修复 gap 目标 |

## 3.5. Closed-Loop Feedback (Now Agent-Driven)

在新设计中，原来的 Step 6-7（自动修复、质量验证）现在完全由 Config Agent 驱动，基于 DuckDB 状态查询自动编排。见 [olav_onboard.md 第 4 节](./olav_onboard.md#4-gap-closure-roadmap-tdd)。

## 4. Agent-Driven Onboarding Implementation (TDD)

**Complete Design & Implementation Roadmap**: See [dev_docs/olav_onboard.md](./olav_onboard.md)

### Summary of Remaining Work

| Phase | Goal | Status | Timeline |
|---|---|---|---|
| **Phase A: Foundation** | Implement `reparse_outputs` tool + Orchestrator direct SQL | 🟡 Design → TDD | Week 1 |
| **Phase B: Intelligence** | Add `onboard` intent to Orchestrator + TUI preflight | 🟡 Design → TDD | Week 2 |
| **Phase C: E2E Validation** | Full flow test suite (empty DB, with gaps, idempotent) | 🔴 Not Started | Week 3 |

### Verification Plan

Once implementation complete, test matrix:

```bash
# Phase A: Tool tests
uv run pytest tests/sync/test_reparse_outputs.py
uv run pytest tests/config/test_orchestrator_tools.py

# Phase B: Intent & Integration
uv run pytest tests/config/test_onboard_intent.py
uv run pytest tests/cli/test_onboard_tui.py

# Phase C: E2E
uv run pytest tests/e2e/test_onboard_empty_db.py
uv run pytest tests/e2e/test_onboard_with_gaps.py
uv run pytest tests/e2e/test_onboard_idempotent.py
```

Manual verification post-implementation:
1. Run `uv run olav onboard` with empty DB
2. Verify preflight_report.json generated + TUI shows Agent:message
3. Confirm sync_schemas + sync_inventory + sync_commands all called
4. Check gap detection (if any parsing failures)
5. Verify reparse_outputs does NOT make new SSH connections
6. Validate topology_links populated from parsed data only

---

## 5. Garbage Code Cleanup
The following items must be DELETED to restore system integrity:

### [DELETE] Root Scripts (Cheating/Hardcoded)
- `seed_topo.py`: Hardcoded topology seeding.
- `learn_bgp_neighbors.py`: Simulated schema learning.
- `learn_bgp_neighbors_simplified.py`: Duplicate simulator.
- `verify_features.py`: Obsolete feature verification.

### [DELETE] Root Logs & Temp Files
- `snapshot_diag.log`, `sync_all_diag.log`, `sync_all_v2.log`, `sync_all_v3.log`.
- `ruff_detailed_report.json`.

### [DELETE] Incorrect Directories
- `./exports/sync/`: Should be unified into `./exports/snapshots/`.

---

## 6. Forbidden Practices (Strict Rules)
1.  **NO Hardcoding**: Topology, neighbor, or route data MUST NEVER be hardcoded into the DB via seeding scripts.
2.  **NO Simulated Output**: Never output "fake" successful results to bypass collection failures.
3.  **NO Path Diversion**: `init.py` and `config.py` MUST share the same `PathResolver`.
4.  **NO Raw-Only Exports**: Every `.txt` file in exports MUST have a corresponding `.json` file.
5.  **NO Manual Schema Manipulation**: Database tables must be created only via `database.py` schema migrations or `SQLReflector`.

---

---

## 7. Test Integrity (Fixing "Fake" Successes)
The existing E2E suite is providing a false sense of security by using circular logic. We must refactor them to ensure they test **REAL** pipelines.

### Issues Identified:
1.  **Circular Seeding**: `test_topology_judgement.py` seeds the DB with hardcoded data and then asks the agent about that data. This passes even if collection is broken.
2.  **Shallow Validation**: `test_init_pipeline.py` checks if tables/files *exist* but doesn't check if the TextFSM parsing actually worked or if the data is consistent.
3.  **Cheating Scripts**: Acceptance tests that rely on `seed_topo.py` are invalid.

### Refactoring Requirements:
1.  **MANDATORY: No Seeding in E2E**: E2E tests must start with `olav onboard` (Stage 0–4) and rely on Step 5 (Snapshot) to populate the DB from real/mock devices (using `nornir` with simulated outputs if real devices are unavailable).
2.  **Content Validation**: Tests must assert not just that `parsed_outputs` has rows, but that specific fields (e.g., `neighbor_id`) are populated and correctly mapped.
3.  **Topology from Data**: Topology tests must verify that the links in the DB were derived from LLDP/CDP parsed outputs, NOT from a `topology_links` table that was manually populated.

---

## 8. Definition of Done (Onboarding v2.0 Agent-Driven)

**Core Infrastructure (Already Complete)**:
1.  [x] `exports/sync` is completely removed; only `exports/snapshots` remains.
2.  [x] Path consistency: `SNAPSHOTS_STAGING_JSON` and `SNAPSHOTS_RAW_DIR` added to config.py.
3.  [x] Platform-aware command discovery: `get_platform_commands()` implemented in command_registry.py.
4.  [x] Schema mapper: `schema_mapper.py` created with `mapping_table` in DuckDB.
5.  [x] All root-level "learner" and "seed" scripts are deleted (already clean).

**Agent-Driven Onboarding (TDD Implementation — Planned)**:
6.  [ ] **PR A1**: `reparse_outputs` tool implemented + tests pass
7.  [ ] **PR A2**: `execute_sql` added to Orchestrator direct tools + tests pass
8.  [ ] **PR B1**: `onboard` intent added to orchestrator.md + intent tests pass
9.  [ ] **PR B2**: preflight_report.json generated by onboard.py + TUI integration
10. [ ] **PR C1-3**: E2E test suite (empty DB, with gaps, idempotent)
11. [ ] Gap-only `take_snapshot` calls verified (not full refresh)
12. [ ] No SSH calls after template repair (verified via `reparse_outputs`)
13. [ ] All tests pass: `ruff check` + `pyright` strict + pytest 100%
14. [ ] `00_e2e_acceptance_test.py` passes WITHOUT running any seeding scripts

**Data Quality & Validation**:
15. [ ] Snapshots produce both raw (.txt) and parsed (.json) files for all whitelisted commands.
16. [ ] Topology is generated automatically from parsed data, not seeded scripts.
17. [ ] `mapping_table` exists and is used for LLM queries.

**Cross-Cutting Concerns**:
18. [ ] Onboarding state persistence (checkpoint/resume on failure) — Phase 2
19. [ ] Concurrency: multiple users can run onboard simultaneously without conflict.
20. [ ] Audit logging: all onboard steps logged to `.olav/logs/users/{user}.log`
