# OLAV Development Issues & Refactoring Roadmap

## 1. Dual Configuration System Conflict 

**Status**: � Partially Resolved
**Updated**: 2026-02-28
**Description**: 
The codebase maintains two parallel configuration systems (`config/` root package vs `src/olav/core/config.py`). This leads to inconsistent settings (especially paths) depending on the import origin.

### 🔴 Identified & Fixed:
- **AttributeError**: `SettingsCompat` in `src/olav/core/config.py` was broken (attempted to access `.local.model` on a flattened object). **Fixed in v3.4.1**.
- **Import Confusion**: `src/olav/core/__init__.py` still exports the legacy `config.settings`, encouraging accidental use of old logic.

### 🛠️ Refactoring Opportunity:
1. **Consolidate**: Move all path resolution logic from `config/paths.py` to `src/olav/core/config.py`.
2. **Redirect**: Update `src/olav/core/__init__.py` to re-export the *new* unified settings and constants.
3. **Deprecate**: Mark the root `config/` package as legacy and prepare for deletion in v2.1.

### ✅ Verification Method:
- **Test**: `uv run python -c "from olav.core.config import settings; print(settings.llm_model_name)"` should return the value from `.olav/config/api.json`.
- **Audit**: `grep -r "from config import" src/olav` should return 0 results.

---

## 2. Knowledge Base (KB) Redundancy & Fragmentation

**Status**: 🔴 Critical Conflict
**Description**: 
KB implementation is fragmented across three layers, making it impossible to maintain a single source of truth for semantic metadata.

### Conflict Details:
- **Redundant Delegates**: `.olav/workspace/config/knowledge/` creates an extra indirection layer that refers to conflicting implementations.

### ✅ Verification Method:
- **Test**: `uv run olav admin kb-status` and `uv run olav admin kb-index` must execute successfully without referring to `.olav/skills`.
- **DB Check**: Inspect `knowledge.lancedb` to ensure new chunks are being added there instead of DuckDB.
- [ ] **Checkpointer Inconsistency**: `MemorySaver` is current default. Need persistent `DuckDBSaver` or `LanceDBSaver`.
- [ ] **Unified Database Missing**: Roadmap references `unified_database.py` but code only contains `database.py`.

## 🔵 Versioning & Branching Policy (v0.10.0+)

- **Primary Development Branch**: All core development now happens on the `0.10.0` branch.
- **Git-Centric Management**: Version control is handled exclusively via Gitea.
- **Archive Deprecation**: Abandon the practice of creating `.tar.gz` archives in the project root. All historical state is managed via Git tags and branches.
- **Version SSOT**: The version number in `src/olav/__init__.py` must match the branch major/minor version.
- [ ] **Unified Database Missing**: Roadmap references `unified_database.py` but code only contains `database.py`.

## 🟡 Critical `src` Technical Debt (New Internal Audit)

Following a deep dive into `src/olav`, the following architectural issues require immediate attention:

### 1. Versioning & Package Fragmentation
- **Version Drift**: `src/olav/__init__.py` (0.9.8), CLI (0.9.9), `AGENTS.md` (0.10.x). 
- **Shadow Entry Point**: `src/olav/main.py` is an obsolete wrapper for `olav.cli.main`. Should be removed in favor of `pyproject.toml` entries.
- **Lazy Load Failures**: `src/olav/__init__.py`'s `__all__` includes tools like `nornir_execute` that are missing from its `__getattr__` implementation.

### ✅ Verification Method:
- **CLI Check**: `olav --version` (if implemented) or `python -c "import olav; print(olav.__version__)"` must return `0.10.0`.
- **Import Test**: `python -c "from olav import create_olav_agent; print(create_olav_agent)"` should not raise AttributeError.

### 2. Database & State Mishandling
- **Concurrency Risks**: `src/olav/core/database.py` uses a global DuckDB connection without thread/process safety. Critical for the `olav daemon`.
- **Filename Mismatches**: Conflict between `memory.lance` (config) and `memory.lancedb` (usage).
- **Paths Confusion**: Slash commands (`builtin.py`) refer to `~/.olav/checkpoints/` while core uses local `.olav/databases/`.

### ✅ Verification Method:
- **Daemon Stress**: Run `olav daemon start` and send 3-5 simultaneous queries via `/admin query`. Monitor for "Database is locked" errors.
- **Path Audit**: Verify `ls .olav/databases/checkpoints.duckdb` exists and is used by the checkpointer.

### 3. Agent & CLI Performance Bottlenecks
- **Heavy Re-initialization**: Slash commands `/learn` and `/config` in `builtin.py` create a *new* `OLAVAgent` instance instead of using the existing one. This adds 3-5s latency per command.
- **Cosmetic Commands**: `/clear` returns success but doesn't actually clear the LangGraph checkpoint or LanceDB memory.
- **Import Collisions**: `tool_discovery.py` manipulates `sys.path` globally for each skill, risking module shadowing.

### ✅ Verification Method:
- **Latency Test**: Measure time difference between a standard query and a `/learn` command. The overhead should be < 500ms if instance is reused.
- **Memory Wipe Test**: Run `/clear`, then ask "What was my last query?". Agent should not know.

## 🟠 Proposed Quick Wins

1. **Purge `src/olav/main.py`** and unify version to `0.10.x` across all files.
2. **Standardize DB extensions** to `.lancedb` for vector stores and `.duckdb` for relational.
3. **Pass Agent Instance** to slash commands to avoid heavy re-init.
4. **Fix `__init__.py`** to properly export all items in `__all__`.

### 🛠️ Refactoring Opportunity (Skills-Centric Transformation):
1. **The "Single KB Engine" Policy**: Move all indexing/search logic to `src/olav/core/knowledge/`.
2. **Unified Scripts**: Expose KB operations as standalone scripts in `.olav/scripts/` (e.g., `index_knowledge.py`).
3. **Skill Cleanup**: Clean up `config-Knowledge` and `config-Infrastructure` to point to the shared core scripts.

---

## 3. Storage Architecture: The "Three-DB" Isolation Strategy

**Status**: � Proposed Design
**Discussion**: To resolve storage fragmentation, we move from a "Monolithic DuckDB" to isolated, specialized engines.

| Database | Role | Engine | Justification |
| :--- | :--- | :--- | :--- |
| **olav.duckdb** | Structured Lakehouse | DuckDB | Inventory, Topology (DuckPGQ), Audits. |
| **memory.lancedb** | Dynamic Agent Memory | LanceDB | LTM: Preferences, Facts, Decisions. |
| **knowledge.lancedb** | Static Knowledge Base | LanceDB | KB Chunks: Docs, Cheatsheets, Manuals. |

### 🛠️ Refactoring Opportunity:
- **KB Isolation**: Create `knowledge.lancedb` to allow the KB to be updated independently of the agent's runtime memory or network snapshots.

---

## 4. Stability & Persistence Audit

**Status**: � In Progress

### Identified Issues:
- **Non-Persistent Checkpoints**: The Orchestrator currently uses `MemorySaver` (RAM-only) because `DuckDBSaver` has async compatibility issues with LangGraph 1.0. This means agent state is lost on restart.
- **Log Boundaries**: System logs (`logs/olav.json`) are correctly isolated from the database but lack a semantic search interface for troubleshooting OLAV itself.
- **Cache Redundancy**: `QueryCache` (file-based) and `ResponseCache` (DuckDB-based) serve similar but distinct roles. 

### 🛠️ Refactoring Opportunity:
1. **Persistence Fix**: Implement a custom persistent checkpointer (via LanceDB or a stable DuckDB wrapper) to restore session continuity.
2. **Semantic Logs**: Periodically summarize OLAV system errors into `memory.lancedb` (under `AUDIT` category) for self-healing/diagnosis.

---

## 5. Unified Synthesis Pattern

**Status**: 📝 Planned
**Description**: Currently, various tools/agents return raw JSON or inconsistently formatted Markdown.
**Opportunity**: Enforce a **Universal Synthesis Middleware** where all tool outputs are passed through an LLM "Formatting Specialist" before being presented to the user, ensuring the "Tech-Luxury" aesthetic is consistent across all interfaces.
