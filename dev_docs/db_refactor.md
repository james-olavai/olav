# OLAV Dataset & Storage Refactoring Plan (v0.11.0)

## 1. Problem Statement
In high-concurrency environments (1000+ devices, 10+ users), the current DuckDB "Single-Writer" architecture causes frequent `Resource Locked` errors during concurrent `take_snapshot` operations. Coupling CLI data collection directly with database ingestion bottlenecks the entire system and prevents effective scaling.

## 2. Target Architecture: "Staging & Bulk Ingest"
We will transition to an asynchronous, tiered storage strategy to decouple collection from persistence.

### Storage Schema
| Content Type | Primary Path | Policy |
| :--- | :--- | :--- |
| **Raw Data** | `exports/snapshots/{YYYY-MM-DD}/{device}_{cmd}.txt` | Permanent record (No `raw/` subfolder) |
| **Staging JSON** | `exports/snapshots/json/{device}_{cmd}.json` | Daily overwritten (Current State Cache) |
| **Structured Data**| `main.duckdb` | Persistent historical & analytical data |

### Concurrency Policy
1. **CLI / Agents**: Open DuckDB in `READ_ONLY` mode by default for querying.
2. **Daemon (API Server)**: The sole process permitted to open DuckDB in `READ_WRITE` mode.
3. **Ingestion Flow**: 
   - CLI writes Parsed JSON to the Staging area.
   - CLI notifies the Daemon (via API) to perform a **Bulk Ingest**.
   - Daemon uses DuckDB `read_json_auto` for high-speed atomic merging.

---

## 3. Dataset Refactoring Plan (TDD)

### Phase 1: Configuration & Path Resolution (The "Zero Hardcoding" Baseline)
**Goal**: Centralize all storage paths in `.olav/config/paths.json`.

- **Test (TDD)**: `tests/unit/test_config_paths.py`
  - Verify `settings.exports_dir / "snapshots" / "json"` parses correctly.
  - Verify `raw` data follows `{date}/{device}_{cmd}.txt` pattern via unit tests.
- **Action**: Update `src/olav/core/config.py` to expose these new resolved paths without hardcoded strings.

### Phase 2: Staging Area Implementation (The "Collector" Logic)
**Goal**: Refactor `take_snapshot.py` to be IO-focused rather than DB-focused.

- **Test (TDD)**: `tests/unit/test_snapshot_staging.py`
  - Mock Nornir, execute `take_snapshot`.
  - Assert JSON exists in `exports/snapshots/json/`.
  - Assert Raw exists in `exports/snapshots/{date}/` (No `raw/` intermediate folder).
- **Action**: Remove `_insert_parsed_output` from `take_snapshot.py`. Update `_write_raw_file` and add `_write_staging_json`.

### Phase 3: Bulk Ingestion Engine (The "Persister" Logic)
**Goal**: Implement an atomic bulk loader in the Daemon/Core.

- **Test (TDD)**: `tests/unit/test_bulk_ingest.py`
  - Prepare 10 mock JSON files in staging.
  - Execute `IngestManager.bulk_load()`.
  - Assert `parsed_outputs` table count matches.
- **Action**: Implement `src/olav/core/ingest_manager.py` using DuckDB's native JSON loading.

### Phase 4: Hybrid Access Verification
**Goal**: Ensure CLI can query while Daemon is writing.

- **Test (TDD)**: `tests/integration/test_concurrency_lock.py`
  - Start a background process writing to DuckDB.
  - Attempt `execute_sql` via CLI (Read-Only).
  - Assert zero lock errors.

---

## 4. Implementation Guidelines
- **KISS**: Favor `read_json_auto` over complex Python-side dict iteration.
- **No Redundancy**: Delete legacy `raw/` subfolder logic completely.
- **Clean Registry**: Ensure `take_snapshot` Skill is updated in `.olav/skills/` (if versioned).

## 5. Timeline & Milestones
- [ ] Milestone 1: Paths & Config (Phase 1)
- [ ] Milestone 2: Functional Staging (Phase 2)
- [ ] Milestone 3: Database Decoupling & Bulk Import (Phase 3 & 4)
