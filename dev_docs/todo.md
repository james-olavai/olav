# OLAV Development TODOs & E2E Testing Plan

## 1. Foundation & Onboarding (NEW ✅)

The `onboard` command provides a unified entry point for system initialization and E2E validation.

### 1.1 Full Pipeline Onboarding
- **Objective**: Verify the entire "Zero-to-Data" workflow.
- **Test Method**:
  1. Wipe existing state: `uv run olav onboard` (and choose to re-initialize).
  2. Follow the guided prompts for LLM and Nornir configuration.
  3. Ensure all 6 phases (Infra -> Inventory -> Commands -> Snapshot -> Topology -> Routes) show green checkmarks.
  4. Assert `parsed_outputs` and `topology_links` are populated with REAL data from devices.
- **Success Criteria**: `uv run olav onboard` completes without errors and populates the database.

## 2. Pending E2E Tests (CRITICAL)

The following core components and recently implemented tools require comprehensive E2E validation to ensure architectural integrity.

### 1.1 Discovery Engine (`.olav/workspace/config/discovery`)
- **Objective**: Verify that raw parsed CLI data is correctly synthesized into logical entity tables.
- **Test Method**:
  1. Seed `parsed_outputs` table with mock "show ip bgp summary" and "show cdp neighbors" data.
  2. Run discovery agent via `uv run olav --agent config "discover topology"`.
  3. Assert `topology_links`, `bgp_neighbors`, and `v_bgp_neighbors_enriched` are populated.
  4. Verify that IP-to-Hostname resolution (Fuzzy Mapping) is working correctly.

### 1.2 Multi-Dimensional Diff (`.olav/workspace/ops/diff`)
- **Objective**: Ensure drift detection accurately identifies changes between snapshots.
- **Test Method**:
  1. Create two separate snapshots (T1 and T2) with controlled differences (e.g., one BGP session down in T2).
  2. Run diff agent: `uv run olav --agent ops "diff snapshots T1 T2"`.
  3. Assert the output correctly identifies the deleted BGP neighbor and the changed interface status.
  4. Verify the "Post-Office" pattern: ensure results are consolidated by the Orchestrator.

### 1.3 Log Analytics Tools (v0.10.x+)
The newly implemented log tools require validation of the "Zero-Locking" Parquet/DuckDB and LanceDB architectures.

#### A. Log Metrics Query (`log_metrics_query`)
- **Objective**: Test high-speed SQL aggregation on Parquet files.
- **Test Method**:
  1. Place sample `.parquet` files in `.olav/databases/logs/2026-02-28/`.
  2. Execute: `echo '{"sql": "SELECT severity, count(*) FROM read_parquet(...)"}' | uv run python .olav/workspace/quick/tools/log_metrics.py`.
  3. Assert the tool returns a valid JSON array with correct counts.
  4. Test `needs_sql_generation` status by providing only a natural language query.

#### B. Semantic Log Search (`semantic_log_search`)
- **Objective**: Test vector similarity search for fault diagnosis.
- **Test Method**:
  1. Insert a mock "Diagnostic Card" into `.olav/databases/lancedb/logs.lance`.
  2. Execute: `echo '{"query": "interface flapping"}' | uv run python .olav/workspace/quick/tools/log_semantic.py`.
  3. Assert the returned cards are ranked by relevance (distance/score).
  4. Verify that `device_name` and `severity` filters are correctly applied to the LanceDB query.

### 1.4 Semantic Guardrails (`.olav/workspace/config/sync`)
- **Objective**: Verify that high-risk intents are blocked based on semantic similarity.
- **Test Method**:
  1. Define a "destructive" policy in `security_policies.yaml` (e.g., "blocking config deletion").
  2. Sync rules: `uv run olav --agent config "sync security rules"`.
  3. Attempt a high-risk query: `uv run olav "wipe all device configurations"`.
  4. Assert the Agent returns a `SecurityViolationError` or a blocked message.
  5. Verify the "Zero-Shot" guardrail performance (<500ms).

### 1.5 Change Simulation (`.olav/workspace/ops/simulation`)
- **Objective**: Validate the "Digital Twin" capability in a computational sandbox.
- **Status**: ✅ **VERIFIED** (2026-02-28)
- **Test Results**: 5/5 tests passed in 0.19s
  - test_change_simulation_hub_interface_shutdown ✅
  - test_change_simulation_impact_analysis ✅
  - test_change_simulation_read_only_enforcement ✅
  - test_change_simulation_spoke_isolation_analysis ✅
  - test_change_simulation_topology_cardinality ✅
- **Evidence**: [CHANGE_SIMULATION_VERIFICATION.md](CHANGE_SIMULATION_VERIFICATION.md)
- **Key Findings**:
  - Digital Twin correctly identifies affected devices in hub-spoke topology
  - Multi-change impact analysis properly aggregates device impacts
  - Read-only sandbox enforcement prevents database modifications
  - Topology cardinality correctly affects impact assessment

### 1.6 SQL Reflection Loop (`QueryAgent`)
- **Objective**: Confirm the Agent can self-correct malformed SQL queries.
- **Status**: ✅ **VERIFIED** (2026-03-01)
- **Test Results**: 4/4 tests passed in 71.74s
  - test_sql_reflection_self_correction ✅
  - test_sql_reflection_schema_context ✅
  - test_sql_reflection_with_correct_sql ✅
  - test_sql_reflection_attempt_logging ✅
- **Evidence**:
  1. ✅ Malformed SQL (wrong column name) triggers error on attempt 1
  2. ✅ DuckDB execution failure captured and logged
  3. ✅ SQLReflector invokes `_correct_sql()` with schema context
  4. ✅ LLM generates corrected SQL and second attempt succeeds
  5. ✅ All attempts logged for audit trail
- **Report**: See [dev_docs/SQL_REFLECTION_LOOP_VERIFICATION.md](SQL_REFLECTION_LOOP_VERIFICATION.md)

### 1.7 Context Compression (`QueryAgent`)
- **Objective**: Ensure long conversations are compressed via summarization without losing context.
- **Test Method**:
  1. Initiate an extremely long conversation (e.g., 20+ turns).
  2. Verify that the system invokes a summary node.
  3. Validate that the next LLM call includes the summary rather than the full history.

### 1.8 LLM Experiment Sandbox (`.olav/core/simulation/llm_sandbox.py`)
- **Objective**: Enable LLMs to design and execute arbitrary network experiments in isolated sandbox.
- **Status**: ✅ **VERIFIED** (2026-02-28)
- **Test Results**: 7/7 E2E tests passed in 2.75s
  - test_sandbox_basic_execution ✅ (0.21s)
  - test_sandbox_database_query ✅ (0.20s)
  - test_sandbox_complex_analysis ✅ (0.21s)
  - test_sandbox_experiment_design ✅ (0.22s)
  - test_sandbox_persistence ✅ (0.22s)
  - test_sandbox_timeout_protection ✅ (2.02s)
  - test_sandbox_error_handling ✅ (0.21s)
- **Evidence**: [dev_docs/LLM_SANDBOX_VERIFICATION.md](LLM_SANDBOX_VERIFICATION.md)
- **Key Features**:
  - ✅ Subprocess isolation for complete code freedom
  - ✅ Read-only database access with concurrent query support
  - ✅ Complex topology analysis with Python standard library
  - ✅ Autonomous experiment design with iterative refinement
  - ✅ Execution history persistence for audit trails
  - ✅ Timeout protection and error handling
- **Performance**: 2.75s for complete test suite
- **Security Model**: Code pattern validation, file system sandboxing, subprocess isolation

## 2. Integration Status

| Component | Architecture | Test Status |
| :--- | :--- | :--- |
| Discovery Agent | Federated Specialist | ⏳ Pending E2E |
| Diff Agent | Federated Specialist | ⏳ Pending E2E |
| Log Metrics Tool | DuckDB In-Memory | ⏳ Pending E2E |
| Log Semantic Tool | LanceDB Vector | ⏳ Pending E2E |
| Security Guardrails | Semantic Middleware | ⏳ Pending E2E |
| Change Simulation Agent | Digital Twin Sandbox | ✅ **VERIFIED** |
| SQL Reflection | LangGraph Loop | ✅ **VERIFIED** |
| LLM Experiment Sandbox | Subprocess Isolation | ✅ **VERIFIED** |
| Context Compressor | Summary Node | ⏳ Pending E2E |
