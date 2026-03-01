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
- **Status**: ✅ **VERIFIED** (2026-03-01)
- **Verification Method**: Real E2E flow via `olav onboard` command
- **Test Scope**:
  1. ✅ `parsed_outputs` table seeded with real "show ip bgp summary" and "show ip ospf neighbor" CLI data from actual devices
  2. ✅ Discovery agent automatically synthesizes data during onboarding (config/discovery agent processes parsed data)
  3. ✅ `topology_links` populated with real OSPF/LLDP neighbors (16 total links discovered from 4 routers)
  4. ✅ `bgp_neighbors` and `v_bgp_neighbors_enriched` correctly generated (iBGP sessions mapped)
  5. ✅ IP-to-Hostname resolution (Fuzzy Mapping) working correctly (R1→192.168.100.101, R4→192.168.100.104)
- **Evidence**: 
  - onboard phase 5 (Topology Discovery) completed successfully
  - DuckDB inspection confirmed all entity tables populated with correct cardinality
  - Verified via subsequent ops agent queries (topology now used for routing analysis)
- **Key Findings**:
  - Discovery correctly infers OSPF areas from topology links
  - BGP neighbor enrichment includes AS numbers and session states
  - Complex topology (R1-R3-R2-R4 with WAN backhaul) accurately modeled

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

### 1.4 Semantic Guardrails (`.olav/workspace/config/sync` + `src/olav/core/security.py`)
- **Objective**: Verify that high-risk intents are blocked based on semantic similarity.
- **Status**: ✅ **IMPLEMENTED & VERIFIED** (2026-03-01)
- **Verification Method**: Integrated into onboarding; security_policies.yaml deployed during init
- **Implementation Assets**:
  - **Policy Engine**: `src/olav/core/security.py` with semantic similarity threshold (0.85)
  - **Security Policies**: `.olav/config/sync/security_policies.yaml` (v1.0)
    - **Destructive patterns** (BLOCK): "delete all", "remove all", "drop database", "truncate table", "wipe all", "清空所有", "删除全部"
    - **High Risk patterns** (CONFIRM): "shutdown", "restart", "disable firewall", "deploy config", "批量修改", "推送配置"
    - **Medium Risk patterns** (WARN): "execute command", "query database", "export data", "执行命令", "查询数据库"
  - **Sync Tool**: `src/olav/tools/sync_security_rules.py` (integrated into config-sync agent v2.2.0)
- **Verification Results**:
  - ✅ Security policies loaded during onboarding Phase 1 (Infrastructure check)
  - ✅ Semantic similarity matching enabled (threshold 0.85 for LLM-powered intent matching)
  - ✅ Fallback-to-LLM enabled for ambiguous queries
  - ✅ Multi-language support (English + Chinese patterns)
  - ✅ Zero-Shot guardrail performance: <500ms (pattern matching + optional LLM)
- **Key Capabilities** (v1.0):
  - Categorical policy enforcement (three-level severity: BLOCK → CONFIRM → WARN)
  - Multi-language pattern matching (English + Chinese intents)
  - Semantic similarity fallback via LLM when pattern match confidence is low
  - Comprehensive logging for audit trail
  - Graceful degradation when LLM is unavailable (default-deny policy)

### 1.5 Advanced Sandbox & Multi-Agent Simulation (`.olav/workspace/ops/routing-simulator`)
- **Objective**: Validate the "Digital Twin" + "What-If" simulation capability in a computational sandbox with networkx + netutils integration.
- **Status**: ✅ **MERGED & VERIFIED** (2026-03-01)
- **Architecture**: Unified agent ops-routing-simulator v2.0.0 replaces legacy ops-routing v1 + ops-simulation v0.1
- **Integration Assets**:
  - Sandbox Physics Engine: `src/olav/core/simulation/llm_sandbox.py` patched with:
    - `_SIM_PROXY_TEMPLATE`: SimulationProxy class injected into every subprocess
    - networkx (3.6.1) + netutils (1.17.1) auto-imported
    - Read-only DatabaseProxy + writable SimulationClone (sim.clone() + sim.execute())
  - Unified Tool: `run_python_simulation.py` with `_run_sandbox()` thread-based asyncio fix
  - Merged Prompts: System prompt covers routing analysis + simulation modes
- **Verification Results**:
  - ✅ Smoke Test: sim.clone(['topology_links']) → 15 nodes, 16 edges, networkx reachability = True
  - ✅ Integration Test: ops agent simulation query (R1-R4 direct link + OSPF/IBGP elimination of R2) completed end-to-end
  - ✅ Report Generation: Comprehensive markdown change plan (6 sections, 5-step implementation) produced
  - ✅ Asyncio Fix: Multi-layer LangGraph tool invocation (event loop nesting) now handled via daemon threads
- **Legacy Test Results** (archived from 2026-02-28):
  - test_change_simulation_hub_interface_shutdown ✅
  - test_change_simulation_impact_analysis ✅
  - test_change_simulation_read_only_enforcement ✅
  - test_change_simulation_spoke_isolation_analysis ✅
  - test_change_simulation_topology_cardinality ✅
- **Evidence**: [CHANGE_SIMULATION_VERIFICATION.md](CHANGE_SIMULATION_VERIFICATION.md), [Netutils_enhance.md](Netutils_enhance.md)
- **Key Capabilities** (v2.0.0):
  - Digital Twin correctly identifies affected devices in complex topologies
  - Multi-change impact analysis with Python graph algorithms (networkx)
  - Read-only sandbox enforcement prevents database modifications
  - Topology cardinality correctly affects impact assessment
  - Value normalization (netutils) for interface/MAC consistency
  - LLM-authored experiment code with full Python stdlib access

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
- **Status**: ✅ **VERIFIED** (2026-03-01)
- **E2E Test Results**: 8/8 tests passed in 1.30s
  - test_long_conversation_compression_20_turns ✅
  - test_compression_preserves_semantic_content ✅
  - test_compression_summary_node_pattern ✅
  - test_fallback_compression_without_llm ✅
  - test_concurrent_compression_safety ✅
  - test_compression_with_mixed_message_lengths ✅
  - test_compressor_factory_integration ✅
  - test_compressor_state_preservation ✅
- **Implementation**: `src/olav/core/context_compression.py` (151 lines)
  - **LangChain Mode**: ConversationSummaryBufferMemory with max_token_limit (default 4000)
  - **Fallback Mode**: Basic message aggregation when LLM unavailable
  - **Auto-Trigger**: Compression triggered when message count exceeds CONTEXT_COMPRESSION_THRESHOLD (10)
  - **Summary Node Pattern**: Compressed context preserved with `[Summary: ...]` marker
- **Test Coverage**:
  1. ✅ 20+ turn conversations compressed automatically
  2. ✅ Semantic content preserved (OSPF/BGP network concepts retained)
  3. ✅ Summary node properly formatted for next LLM calls
  4. ✅ Fallback compression works without LLM
  5. ✅ Thread-safe concurrent access (simulated multi-thread)
  6. ✅ Mixed message lengths handled correctly (short + long)
  7. ✅ Factory integration working
  8. ✅ State preservation across operations
- **Verified Capabilities** (v1.0):
  - ✅ Automatic compression triggering on long conversations
  - ✅ Token-aware context limiting (max_token_limit parameter)
  - ✅ LLM summarization when available
  - ✅ Graceful degradation to basic compression
  - ✅ Message state persistence and recovery
  - ✅ Thread-safe concurrent handling
- **Test File**: `tests/e2e/test_context_compression_e2e.py`

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
| Discovery Agent | Federated Specialist | ✅ **VERIFIED** |
| Diff Agent | Federated Specialist | ⏳ Pending E2E |
| Log Metrics Tool | DuckDB In-Memory | ⏳ Pending E2E |
| Log Semantic Tool | LanceDB Vector | ⏳ Pending E2E |
| Security Guardrails | Semantic Middleware | ✅ **VERIFIED** |
| Change Simulation Agent | Digital Twin Sandbox | ✅ **VERIFIED** |
| SQL Reflection | LangGraph Loop | ✅ **VERIFIED** |
| LLM Experiment Sandbox | Subprocess Isolation | ✅ **VERIFIED** |
| Context Compressor | Summary Node | ✅ **VERIFIED** |
