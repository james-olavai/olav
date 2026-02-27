# OLAV LanceDB Migration & Network Topology Tracking

**Status**: Active
**Methodology**: Test-Driven Development (TDD) required for all phases.
**Assigned To**: Development Team

## Core TDD Requirements
All development MUST follow the strict TDD cycle:
1. **Red**: Write a failing test in `tests/` that defines the desired interface and behavior. Run it and watch it fail.
2. **Green**: Write the minimal amount of code in `src/olav/` necessary to make the test pass.
3. **Refactor**: Clean up the code while ensuring tests remain green.

---

## Tracking Checklist

### Phase 1: Foundation (LanceDB Core & DuckDB VSS Purge)
*Goal: Establish LanceDB connection, basic RRF/BM25 pipeline, and remove legacy DuckDB vector dependencies.*

- [ ] **Task 1.1**: Setup `lancedb` dependencies in `pyproject.toml` (managed via `uv`).
- [ ] **Task 1.2**: Write test `tests/test_lancedb_connection.py` for connecting to local LanceDB instance.
- [ ] **Task 1.3**: Implement `src/olav/core/memory/lancedb_store.py` base connection class.
- [ ] **Task 1.4**: Write test `tests/test_hybrid_retrieval.py` for Vector + BM25 fusion logic.
- [ ] **Task 1.5**: Implement Python native RRF/BM25 retrieval pipeline bypassing LangChain VectorStore wrappers.
- [ ] **Task 1.6**: Write migration test `tests/test_kb_migration.py` mimicking legacy DuckDB chunk extraction to LanceDB.
- [ ] **Task 1.7**: Implement one-off migration script for existing KB chunks.
- [ ] **Task 1.8**: **[Cleanup]** Delete legacy `search_knowledge.py` relying on DuckDB VSS.
- [ ] **Task 1.9**: **[Cleanup]** Remove DuckDB VSS extension loading code and LangChain Vector dependencies from the codebase.

### Phase 2: Experience System (Categorized Memory & Isolation)
*Goal: Add taxonomy (Fact/Decision/Preference), Scope Isolation, and Memory Middleware.*

- [ ] **Task 2.1**: Write test `tests/test_memory_scopes.py` ensuring isolation (e.g., Agent A cannot read Agent B's memory).
- [ ] **Task 2.2**: Update `lancedb_store.py` schema with `category` and `scope` metadata fields.
- [ ] **Task 2.3**: Write test `tests/test_memory_middleware_recall.py` for pre-processing recall logic.
- [ ] **Task 2.4**: Implement `MemoryMiddleware` auto-recall hook in DeepAgents integration.
- [ ] **Task 2.5**: Write test `tests/test_memory_middleware_capture.py` for post-processing experience summarization.
- [ ] **Task 2.6**: Implement `MemoryMiddleware` auto-capture logic.

### Phase 3: Topological Graph Engine (DuckPGQ)
*Goal: Expand DuckDB topology capabilities with Graph queries and provide a dedicated tool to the Ops Agent.*

- [ ] **Task 3.1**: Write test `tests/test_duckpgq_extension.py` asserting `INSTALL pgq` and graph table creation on sample topology data.
- [ ] **Task 3.2**: Implement DuckPGQ initialization in `src/olav/core/unified_database.py`.
- [ ] **Task 3.3**: Write test `tests/test_analyze_network_topology.py` covering pathfinding and loop detection intents.
- [ ] **Task 3.4**: Implement `analyze_network_topology.py` skill script with predefined PGQ templates.
- [ ] **Task 3.5**: Register `analyze_network_topology` in `olav-ops` SKILL.md.

### Phase 4: Self-Learning Guardrails
*Goal: Dynamically inject historical failure contexts into prompts using LanceDB retrieval.*

- [ ] **Task 4.1**: Write test `tests/test_guardrail_injection.py` to assert historical failures limit/modify agent parameters.
- [ ] **Task 4.2**: Implement Guardrail synthesis in the agent prompt builder.

---

## Pull Request Guidelines
- Every PR must contain both the tests (failing on base branch, passing on PR branch) and the implementation.
- Maintain $>80\%$ test coverage in `src/olav/core/memory/`.
- Run complete E2E testing phase checking before merging (see `project-overview.md`).
