# OLAV Database Refactoring Plan (v0.11.0) - Implementation

## Overview

**Goal**: Transition from "Single-Writer" DuckDB architecture to "Staging & Bulk Ingest" tiered storage strategy to resolve concurrency issues in high-concurrency environments (1000+ devices, 10+ users).

**Problem**: Current architecture causes frequent `Resource Locked` errors during concurrent `take_snapshot` operations.

## Architecture Summary

### New Storage Schema

| Content Type | Primary Path | Policy |
| :--- | :--- | :--- |
| **Raw Data** | `exports/snapshots/{YYYY-MM-DD}/{device}_{cmd}.txt` | Permanent record (No `raw/` subfolder) |
| **Staging JSON** | `exports/snapshots/json/{device}_{cmd}.json` | Daily overwritten (Current State Cache) |
| **Structured Data** | `main.duckdb` | Persistent historical & analytical data |

### Concurrency Policy

1. **CLI / Agents**: Open DuckDB in `READ_ONLY` mode by default for querying.
2. **Daemon (API Server)**: The sole process permitted to open DuckDB in `READ_WRITE` mode.
3. **Ingestion Flow**:
   - CLI writes Parsed JSON to the Staging area.
   - CLI notifies the Daemon (via API) to perform a **Bulk Ingest**.
   - Daemon uses DuckDB `read_json_auto` for high-speed atomic merging.

---

## Phase 1: Configuration & Path Resolution

**Objective**: Centralize all storage paths in `.olav/config/paths.json`.

### Task 1.1: Update paths.json

**File**: `.olav/config/paths.json`

**Add new snapshot paths**:
```json
"snapshots": {
  "description": "Snapshot storage paths for tiered storage strategy",
  "raw_pattern": "exports/snapshots/{date}/{device}_{cmd}.txt",
  "staging_json": "exports/snapshots/json"
}
```

### Task 1.2: Update config.py

**File**: `src/olav/core/config.py`

**Add to PathsConfig class**:
```python
@property
def snapshots_raw_pattern(self) -> str:
    snapshots = self._data.get("snapshots", {})
    return snapshots.get("raw_pattern", "exports/snapshots/{date}/{device}_{cmd}.txt")

@property
def snapshots_staging_json(self) -> str:
    snapshots = self._data.get("snapshots", {})
    return snapshots.get("staging_json", "exports/snapshots/json")

# Module-level path constants
SNAPSHOTS_RAW_PATTERN = _path_resolver.resolve("snapshots_raw_pattern")
SNAPSHOTS_STAGING_JSON = _path_resolver.resolve("snapshots_staging_json")
```

**Update exports**:
- Add `SNAPSHOTS_RAW_PATTERN`, `SNAPSHOTS_STAGING_JSON` to `__all__`

### Task 1.3: Verify paths

**Test command** (after implementation):
```python
from olav.core.config import SNAPSHOTS_RAW_PATTERN, SNAPSHOTS_STAGING_JSON
print(f"Raw pattern: {SNAPSHOTS_RAW_PATTERN}")
print(f"Staging JSON: {SNAPSHOTS_STAGING_JSON}")
```

---

## Phase 2: Staging Area Implementation

**Objective**: Refactor `take_snapshot.py` to be IO-focused rather than DB-focused.

### Task 2.1: Create unit test for staging

**File**: Create `tests/unit/test_snapshot_staging.py` (if tests directory doesn't exist, create it)

**Test cases**:
- Mock Nornir, execute `take_snapshot`
- Assert JSON exists in `exports/snapshots/json/`
- Assert Raw exists in `exports/snapshots/{date}/` (No `raw/` intermediate folder)

### Task 2.2: Refactor take_snapshot.py

**File**: `.olav/workspace/config/tools/take_snapshot.py`

**Changes**:

1. **Remove `_insert_parsed_output` function** - DB writing is removed

2. **Update `_write_raw_file` function**:
   ```python
   def _write_raw_file(device: str, command: str, raw: str, snapshot_date: str) -> None:
       safe_cmd = re.sub(r"[^\w]", "_", command.lower()).strip("_")
       out_dir = (
           _PROJECT_ROOT
           / "exports"
           / "snapshots"
           / snapshot_date
       )
       out_dir.mkdir(parents=True, exist_ok=True)
       (out_dir / f"{device}_{safe_cmd}.txt").write_text(raw, encoding="utf-8")
   ```

3. **Add `_write_staging_json` function**:
   ```python
   def _write_staging_json(device: str, command: str, parsed: list[dict] | None, raw: str, snapshot_id: str) -> None:
       safe_cmd = re.sub(r"[^\w]", "_", command.lower()).strip("_")
       staging_dir = (
           _PROJECT_ROOT
           / "exports"
           / "snapshots"
           / "json"
       )
       staging_dir.mkdir(parents=True, exist_ok=True)
       
       data = {
           "device": device,
           "command": command,
           "snapshot_id": snapshot_id,
           "parsed": parsed,
           "raw": raw[:20000],  # Truncate for staging
       }
       (staging_dir / f"{device}_{safe_cmd}.json").write_text(
           json.dumps(data, ensure_ascii=False), encoding="utf-8"
       )
   ```

4. **Update `take_snapshot` function**:
   - Remove DB connection (`_ddb.connect`)
   - Replace `_insert_parsed_output` call with `_write_staging_json` call
   - Keep `_write_raw_file` call (but with updated path)
   - Update return message to indicate staging location

### Task 2.3: Migrate existing raw files

**Command** (optional migration):
```bash
# Move existing raw files from exports/snapshots/{date}/raw/{device}/ to exports/snapshots/{date}/{device}_{cmd}.txt
find exports/snapshots -type f -name "*.txt" -path "*/raw/*" | while read f; do
    new_path=$(echo "$f" | sed 's|/raw/|/|')
    mv "$f" "$new_path"
done
# Clean up empty raw directories
find exports/snapshots -type d -name "raw" -empty -delete
```

---

## Phase 3: Bulk Ingestion Engine

**Objective**: Implement an atomic bulk loader in the Daemon/Core using DuckDB's native JSON loading.

### Task 3.1: Create IngestManager

**File**: `src/olav/core/ingest_manager.py`

```python
"""Bulk Ingestion Manager for DuckDB.

Provides high-speed atomic merging of staging JSON files into main.duckdb.
"""
import json
import logging
from datetime import date
from pathlib import Path

import duckdb

from olav.core.config import MAIN_DB_PATH, SNAPSHOTS_STAGING_JSON

logger = logging.getLogger(__name__)


class IngestManager:
    """Manager for bulk ingesting staging JSON files into DuckDB."""
    
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = db_path or MAIN_DB_PATH
        self.staging_dir = Path(SNAPSHOTS_STAGING_JSON)
    
    def bulk_load(self, snapshot_date: date | None = None) -> dict:
        """Load all staging JSON files into DuckDB.
        
        Args:
            snapshot_date: Optional date to filter staging files.
                         If None, loads all available.
        
        Returns:
            Dict with status, files_processed, records_inserted.
        """
        staging_files = list(self.staging_dir.glob("*.json"))
        
        if not staging_files:
            return {
                "status": "no_files",
                "files_processed": 0,
                "records_inserted": 0,
            }
        
        # Use DuckDB read_json_auto for high-speed atomic merging
        with duckdb.connect(str(self.db_path), read_only=False) as conn:
            # Read all JSON files
            result = conn.execute("""
                SELECT * FROM read_json_auto(?)
            """, [str(f) for f in staging_files]).fetchall()
            
            # Insert into parsed_outputs
            records_inserted = 0
            for row in result:
                try:
                    conn.execute("""
                        INSERT INTO parsed_outputs 
                        (device_name, command, parsed_data, snapshot_date)
                        VALUES (?, ?, ?::JSON, ?)
                        ON CONFLICT (device_name, command, snapshot_date) 
                        DO UPDATE SET parsed_data = EXCLUDED.parsed_data
                    """, [
                        row[0],  # device
                        row[1],  # command
                        json.dumps(row[2]) if isinstance(row[2], dict) else row[2],  # parsed
                        snapshot_date or date.today()
                    ])
                    records_inserted += 1
                except Exception as e:
                    logger.warning(f"Failed to insert {row[0]}/{row[1]}: {e}")
            
            return {
                "status": "success",
                "files_processed": len(staging_files),
                "records_inserted": records_inserted,
            }
    
    def clear_staging(self) -> int:
        """Clear staging directory after successful ingest.
        
        Returns:
            Number of files deleted.
        """
        staging_files = list(self.staging_dir.glob("*.json"))
        for f in staging_files:
            f.unlink()
        return len(staging_files)


def bulk_ingest(snapshot_date: date | None = None) -> dict:
    """Convenience function for bulk ingestion."""
    manager = IngestManager()
    result = manager.bulk_load(snapshot_date)
    if result["status"] == "success":
        manager.clear_staging()
    return result
```

### Task 3.2: Add bulk_load as a tool

**File**: Create `.olav/workspace/shared/tools/ingest.py` or add to existing data gateway tool

```python
@tool
def bulk_ingest(snapshot_date: str | None = None) -> dict:
    """Bulk ingest staging JSON files into DuckDB.
    
    This tool reads all JSON files from exports/snapshots/json/ and
    bulk loads them into the parsed_outputs table in DuckDB.
    
    Use this after running take_snapshot to persist the results.
    
    Args:
        snapshot_date: Optional date string (YYYY-MM-DD) to filter.
                      If not provided, loads all available files.
    
    Returns:
        {
            "status": "success|no_files",
            "files_processed": 5,
            "records_inserted": 10
        }
    """
    from datetime import date
    
    parsed_date = None
    if snapshot_date:
        parsed_date = date.fromisoformat(snapshot_date)
    
    result = bulk_ingest(parsed_date)
    return result
```

---

## Phase 4: Hybrid Access Verification

**Objective**: Ensure CLI can query while Daemon is writing.

### Task 4.1: Update database.py for READ_ONLY access

**File**: `src/olav/core/database.py`

**Ensure read_only mode is properly supported**:
- Already has `read_only` parameter in `OlavDatabase.__init__`
- Verify thread-safe access via `_db_lock`

### Task 4.2: Update CLI tools to use READ_ONLY

**File**: `.olav/workspace/shared/tools/data_gateway.py` (or wherever execute_sql is defined)

**Change**:
```python
# Change from
conn = duckdb.connect(str(MAIN_DB_PATH))
# To
conn = duckdb.connect(str(MAIN_DB_PATH), read_only=True)
```

### Task 4.3: Create concurrency test

**File**: `tests/integration/test_concurrency_lock.py`

```python
"""Test concurrent read/write access to DuckDB."""
import threading
import time
from pathlib import Path

import duckdb

from olav.core.config import MAIN_DB_PATH


def test_concurrent_read_write():
    """Test that read-only queries don't block during writes."""
    errors = []
    
    def writer():
        try:
            with duckdb.connect(str(MAIN_DB_PATH), read_only=False) as conn:
                for i in range(10):
                    conn.execute("""
                        INSERT INTO parsed_outputs 
                        (device_name, command, parsed_data, snapshot_date)
                        VALUES (?, ?, ?, ?)
                    """, [f"test_dev_{i}", "test_cmd", "[]", "2026-01-01"])
                    time.sleep(0.1)
        except Exception as e:
            errors.append(f"Writer: {e}")
    
    def reader():
        try:
            with duckdb.connect(str(MAIN_DB_PATH), read_only=True) as conn:
                for i in range(10):
                    conn.execute("SELECT COUNT(*) FROM parsed_outputs").fetchall()
                    time.sleep(0.1)
        except Exception as e:
            errors.append(f"Reader: {e}")
    
    # Start writer and reader concurrently
    writer_thread = threading.Thread(target=writer)
    reader_thread = threading.Thread(target=reader)
    
    writer_thread.start()
    reader_thread.start()
    
    writer_thread.join()
    reader_thread.join()
    
    assert len(errors) == 0, f"Errors occurred: {errors}"


if __name__ == "__main__":
    test_concurrent_read_write()
    print("Concurrent access test passed!")
```

---

## Implementation Order

1. **Phase 1**: Update paths.json and config.py
2. **Phase 2**: Refactor take_snapshot.py (most impactful change)
3. **Phase 3**: Create IngestManager
4. **Phase 4**: Update database access patterns and test

---

## Verification Commands

After each phase:

```bash
# Phase 1 - Verify paths
python3 -c "from olav.core.config import SNAPSHOTS_RAW_PATTERN, SNAPSHOTS_STAGING_JSON; print(SNAPSHOTS_RAW_PATTERN, SNAPSHOTS_STAGING_JSON)"

# Phase 2 - Verify staging works
uv run olav ask "take snapshot from R1 with command show version"

# Phase 3 - Verify bulk ingest
python3 -c "from olav.core.ingest_manager import bulk_ingest; print(bulk_ingest())"

# Phase 4 - Verify concurrency
python3 tests/integration/test_concurrency_lock.py
```

---

## Files Modified Summary

| File | Action |
| :--- | :--- |
| `.olav/config/paths.json` | Add snapshots section |
| `src/olav/core/config.py` | Add SNAPSHOTS_RAW_PATTERN, SNAPSHOTS_STAGING_JSON |
| `.olav/workspace/config/tools/take_snapshot.py` | Refactor to staging-only |
| `src/olav/core/ingest_manager.py` | Create new file |
| `.olav/workspace/shared/tools/ingest.py` | Add bulk_ingest tool |
| `tests/integration/test_concurrency_lock.py` | Create test |

---

## Rollback Plan

If issues occur:
1. Revert `take_snapshot.py` to use direct DB writes
2. Keep staging directory for debugging
3. Run manual DB insert if needed

