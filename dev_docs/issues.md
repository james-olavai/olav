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

---

## 2. Knowledge Base (KB) Redundancy & Fragmentation

**Status**: 🔴 Critical Conflict
**Description**: 
KB implementation is fragmented across three layers, making it impossible to maintain a single source of truth for semantic metadata.

### Conflict Details:
- **Logic Split**: Framework code in `src`, but primary indexing logic is still buried in `.olav/skills/config-Infrastructure/tools/kb_manager.py`.
- **Backend Mismatch**: `kb_manager.py` still uses **DuckDB** for vector storage, while the development goal is **LanceDB**.
- **Redundant Delegates**: `.olav/workspace/config/knowledge/` creates an extra indirection layer that refers to conflicting implementations.
- [ ] **Checkpointer Inconsistency**: `MemorySaver` is current default. Need persistent `DuckDBSaver` or `LanceDBSaver`.
- [ ] **Unified Database Missing**: Roadmap references `unified_database.py` but code only contains `database.py`.

## 🟡 Critical `src` Technical Debt (New Internal Audit)

Following a deep dive into `src/olav`, the following architectural issues require immediate attention:

### 1. Versioning & Package Fragmentation
- **Version Drift**: `src/olav/__init__.py` (0.9.8), CLI (0.9.9), `AGENTS.md` (0.10.x). 
- **Shadow Entry Point**: `src/olav/main.py` is an obsolete wrapper for `olav.cli.main`. Should be removed in favor of `pyproject.toml` entries.
- **Lazy Load Failures**: `src/olav/__init__.py`'s `__all__` includes tools like `nornir_execute` that are missing from its `__getattr__` implementation.

### 2. Database & State Mishandling
- **Concurrency Risks**: `src/olav/core/database.py` uses a global DuckDB connection without thread/process safety. Critical for the `olav daemon`.
- **Filename Mismatches**: Conflict between `memory.lance` (config) and `memory.lancedb` (usage).
- **Paths Confusion**: Slash commands (`builtin.py`) refer to `~/.olav/checkpoints/` while core uses local `.olav/databases/`.

### 3. Agent & CLI Performance Bottlenecks
- **Heavy Re-initialization**: Slash commands `/learn` and `/config` in `builtin.py` create a *new* `OLAVAgent` instance instead of using the existing one. This adds 3-5s latency per command.
- **Cosmetic Commands**: `/clear` returns success but doesn't actually clear the LangGraph checkpoint or LanceDB memory.
- **Import Collisions**: `tool_discovery.py` manipulates `sys.path` globally for each skill, risking module shadowing.

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
