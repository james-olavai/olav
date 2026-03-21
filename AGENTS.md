# OLAV - Project Knowledge Base (v0.11.0)

**Updated:** 2026-02-28
**Version:** v0.11.0 (Enterprise-Ready Architecture)

## 1. CORE PHILOSOPHY

*   **KISS 的核心是 LLM Native**: 保持代码简单的秘诀是将复杂的发现逻辑交给 LLM 语义识别（Semantic Discovery），而不是编写臃肿、脆弱的硬编码正则映射（Hardcoded Regex/Patterns）。
*   **Schema On-Read**: 数据库应作为原始解析结果的快照，更深层次的字段映射应在运行时通过语义感知的视图或索引动态生成。

## 2. CORE ARCHITECTURE

OLAV v0.11.0 implements a **Secure-Isolated & Central-Audited** Federated Specialist Architecture.

### The "Three-Layer" Truth
1.  **Config SSOT**: ALL settings must come from `src/olav/core/config.py`. **NEVER** hardcode paths.
2.  **Agent SSOT**: ALL agent definitions reside in `.olav/workspace/`.
3.  **Storage SSOT (Isolated vs. Centralized)**:
    *   **Isolated (User-Local)**: LangGraph Checkpoints (`~/.olav/sessions/`), LLM Cache (`~/.olav/cache/`).
    *   **Shared (Project-Global)**: DuckDB Network State (`.olav/databases/`), Logs (`.olav/logs/`), Knowledge (`.olav/databases/`).

### 4. Federated Specialist Agents (Dynamic Binding)
OLAV uses `deepagents.SkillsMiddleware` to dynamically bind scripts to agents based on `SKILL.md` metadata.
*   **Query Agent**: Translates Natural Language to SQL/Zero-Shot Queries.
*   **Ops Agent**: Deep troubleshooting — routing, topology, probing, log analysis, diff.
*   **Sync Agent**: Inventory, Snapshot collection, and Security Policy Sync.
*   **Ops Subagent (Sandbox)**: Computational analysis & high-concurrency calculation in a secure sandbox.

## 2. DIRECTORY CONVENTION

```
./
├── src/olav/           # Core Framework (Logic, Models, Middlewares)
│   ├── agents/         # Generic Agent orchestrators
│   ├── api/            # FastAPI HTTP server (server.py)
│   ├── core/           # Universal truth: config, llm, database, ingest
│   ├── services/       # Long-running background daemons (syslog_receiver.py)
│   └── knowledge/      # KB Engine (Embeddings, Chunking)
├── .olav/              # Runtime Global Environment
│   ├── workspace/      # Agent & Skill definitions (AGENT.md, SKILL.md)
│   │   └── <agent>/tools/  # LangChain tool modules for that agent
│   ├── logs/           # Legacy text logs (.olav/logs/users/*.log) — see audit.duckdb
│   └── databases/      # DuckDB + LanceDB (Shared data ONLY)
└── dev_docs/          # Architectural decisions and issues log
```

## 3. ANTI-PATTERNS (CRITICAL)

- **❌ NO Local Checkpoints**: Never store `checkpoints.duckdb` in the project root. Use `USER_SESSION_DIR`.
- **❌ NO Direct DB Writes**: Agent tools must **NEVER** call `duckdb.connect().execute("INSERT...")`. Use Staging files.
- **❌ NO Anonymous Agents**: Always pass `agent_id` to `LLMFactory` to enable model overrides in `api.json`.
- **❌ NO Hardcoded Paths**: Always use `PathsConfig` or constants from `olav.core.config`.
- **❌ NO Implicit Commits**: Ensure code quality (ruff + pyright) is passing **BEFORE** claiming completion.
- **❌ NO Daemons in Workspace**: Long-running services (HTTP, UDP) belong in `src/olav/services/`, not `.olav/workspace/`.

## 4. MULTI-USER SECURITY (V0.11.0+)

1.  **Concurrency**: Multiple users **WILL** operate on the same project.
2.  **Isolation**: Users must have their own private checkpoint and cache files in `~/.olav/`.
3.  **Auditing (UNIFIED TO DuckDB)**: Every CLI command (Slash or Natural) **MUST** be recorded in `.olav/databases/audit.duckdb` via `AuditEventRecorder`. This is the **single source of truth** for all audit data. Legacy paths (`~/.olav/history/`, `.olav/logs/users/*.log`) are **deprecated** and no longer maintained. `.olav/logs/` is reserved for application runtime logs only (e.g. `olav.log`, `web.log`).
4.  **Ownership**: Global state (Shared DuckDB) is read-only for agents; only `IngestManager` can perform batched, atomic writes.

## 5. TOOLING & DATA FLOW (STAGING-FIRST)

1.  **Collect**: Script writes parsed results to `exports/snapshots/json/*.staging.json`.
2.  **Ingest**: `IngestManager.bulk_load()` uses DuckDB `read_json_auto` for high-speed, atomic merging.
3.  **Query**: Specialized agents query the read-optimized DuckDB views.

## 6. LLM AGENT BINDING

Model selection is strictly configuration-driven:
*   **Default**: Defined in `api.json`'s `llm.model`.
*   **Per-Agent**: Defined in `api.json`'s `agent_overrides`.
*   **Requirement**: `LLMFactory.get_chat_model` must receive `agent_id` for correct mapping.

## 7. DEVELOPMENT WORKFLOW (FOR BAUs)

1.  **Add Setting**: Update `src/olav/core/config.py` (Centralized).
2.  **Implement Logic**: Move complex handling to `src/olav/core/` or `src/olav/services/`.
3.  **Agent Tool**: Create a LangChain tool in `.olav/workspace/<agent>/tools/` (invoked by the agent).
4.  **TDD**: Run `uv run pytest tests/00_e2e_acceptance_test.py` often. **Green = Done.**
5.  **NetOps tests**: `olav-netops` must be installed for full test coverage: `uv pip install -e olav-netops`. This is a separate optional package — not in the uv workspace due to heavy deps (nornir, netmiko). Run once after clone.

**Action**: Always check `dev_docs/issues.md` for active architectural pivots before starting a task.

#HV|
#HV|## 8. E2E TESTING REQUIREMENTS (MANDATORY)
#HV|
#HV|**This section is MANDATORY for all testing activities.**
#HV|
#HV|### 8.1 Core Principles
#HV|
#HV|- **✅ REAL LLM ONLY**: All tests must use real LLM API calls - NO mocking LLM responses
#HV|- **✅ REAL DEVICES ONLY**: All tests must connect to real network devices - NO mocked device data
#HV|- **✅ REAL OUTPUT ONLY**: All tests must write real files to disk - NO in-memory data
#HV|- **✅ VERIFIABLE**: All test results must be independently verifiable
#HV|
#HV|### 8.2 Anti-Patterns (Immediate Failure)
#HV|
#HV|- **❌ NO Mock Data**: Never insert fake data into database to "pass" tests
#HV|- **❌ NO Hardcoded Results**: Never hardcode expected output to bypass real execution
#HV|- **❌ NO Skipped Steps**: Never skip actual SSH connections, API calls, or file I/O
#HV|- **❌ NO Assumed Success**: Never assume collection succeeded without verification
#HV|
#HV|### 8.3 Required Verification Steps
#HV|
#HV|For every E2E test, you MUST verify:
#HV|
#HV|1. **Connection**: Device SSH connection succeeded (check logs)
#HV|2. **Raw Output**: CLI output files exist in `exports/snapshots/{date}/raw/`
#HV|3. **Parsed Data**: JSON files exist in `exports/snapshots/json/`
#HV|4. **Database**: Data actually inserted into DuckDB tables
#HV|5. **Topology**: CDP/LLDP neighbors correctly mapped to topology_links
#HV|
#HV|### 8.4 Test Evidence Requirements
#HV|
#HV|Each test completion MUST include:
#HV|
#HV|```bash
#HV|# Verify raw output files exist
#HV|ls exports/snapshots/{date}/raw/{device}/
#HV|
#HV|# Verify parsed JSON exists  
#HV|ls exports/snapshots/json/*.json
#HV|
#HV|# Verify database records
#HV|duckdb .olav/databases/main.duckdb "SELECT COUNT(*) FROM parsed_outputs"
#HV|
#HV|# Verify topology
#HV|duckdb .olav/databases/main.duckdb "SELECT * FROM topology_links"
#HV|```
#HV|
#HV|**FAILURE TO VERIFY = INCOMPLETE TEST**
#HV|
#HV|---