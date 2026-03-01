# Snapshot Timestamp Granularity Upgrade (2026-03-01)

**Status**: ✅ Implemented  
**Date**: 2026-03-01  
**Impact**: Better debugging and diff capability for same-day multiple snapshots

---

## Problem Statement

Previously, snapshot directories and JSON files used **day-level granularity** (`%Y-%m-%d` format):
```
exports/snapshots/2026-03-01/raw/R1/show_ip_bgp.txt
exports/snapshots/json/R1.staging.json        # Overwritten each run
```

**Issue**: If you ran the sync tool multiple times per day for debugging, earlier snapshots would be lost. Impossible to diff state between consecutive runs on the same day.

---

## Solution: Minute-Level Timestamps

### Changes Made

#### 1. **Directory Structure** (Raw Files)
**Before**:
```
exports/snapshots/2026-03-01/raw/{device}/{command}.txt
```

**After**:
```
exports/snapshots/2026-03-01_0945/raw/{device}/{command}.txt  # YYYY-MM-DD_HHMM
```

**Benefits**:
- Multiple snapshots **per day** can coexist
- Directory name directly shows **minute of capture**
- Easy to identify exact snapshot time without checking metadata

#### 2. **JSON Staging Files**
**Before**:
```
exports/snapshots/json/R1.staging.json         # Always overwritten
```

**After**:
```
exports/snapshots/json/R1_20260301_0945.staging.json  # Minute-level timestamp
exports/snapshots/json/R1_20260301_0950.staging.json  # Next snapshot
exports/snapshots/json/R1_20260301_1015.staging.json  # Another run
```

**Benefits**:
- Multiple JSON snapshots retained for debugging
- Filename includes device + timestamp
- Still matched by glob pattern `*.staging.json` (backward compatible with IngestManager)

#### 3. **Database (`snapshot_id` field)**
**Before**:
```sql
snapshot_id: "2026-03-01"  # Collisions if multiple snapshots same day
```

**After**:
```sql
snapshot_id: "2026-03-01_0945"  # Unique per snapshot
```

**Implications**:
- Multiple snapshots from same day are now distinguishable in DB
- Queries using `MAX(snapshot_id)` still work (lexicographic ordering matches chronological)
- Gap detection can now distinguish same-day runs

---

## Code Changes

### File: `.olav/workspace/config/sync/tools/take_snapshot.py`

**Before** (Line 244):
```python
sync_date = datetime.now().strftime("%Y-%m-%d")
```

**After**:
```python
# Use minute-level timestamp for better debugging/diff capability
# Format: YYYY-MM-DD_HHMM (e.g 2026-03-01_0945)
sync_date = datetime.now().strftime("%Y-%m-%d_%H%M")
```

### File: `.olav/workspace/config/sync/tools/sync_tools.py`

#### Change 1 (Line 117-127): `get_sync_dir()` default

**Before**:
```python
def get_sync_dir(date: str | None = None) -> Path:
    """Get sync directory for a given date."""
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    return get_sync_base_dir() / date
```

**After**:
```python
def get_sync_dir(date: str | None = None) -> Path:
    """Get sync directory for a given date.
    
    Args:
        date: Date string. If None, uses minute-level timestamp (YYYY-MM-DD_HHMM)
              to support multiple snapshots per day.
    """
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d_%H%M")
    return get_sync_base_dir() / date
```

#### Change 2 (Line 1381-1390): JSON file naming

**Before**:
```python
# Write (overwrite) staging JSON for this device
staging_file = staging_dir / f"{device_name}.staging.json"
staging_file.write_text(...)
```

**After**:
```python
# Write staging JSON for this device (minute-level timestamp for traceability)
# Format: {device}_{YYYYMMDD_HHMM}.staging.json
timestamp = sync_date_str.replace("-", "").replace("_", "_")  # 20260301_0945 format
staging_file = staging_dir / f"{device_name}_{timestamp}.staging.json"
staging_file.write_text(...)
```

---

## Backward Compatibility

### ✅ Preserved
1. **IngestManager**: Uses glob pattern `*.staging.json` — works with new filenames automatically
2. **snapshot_id queries**: `MAX(snapshot_id)` still selects latest (lexicographic order matches time order)
3. **Raw file structure**: Still at `exports/snapshots/{date}/raw/`
4. **Command format**: Raw file names unchanged

### ⚠️ Breaking Changes
1. **Hard-coded path assumptions**: Any script assuming `exports/snapshots/YYYY-MM-DD/` directory must be updated
   - **Status**: No breaking usages found in current codebase
2. **JSON filename queries**: Scripts expecting `{device}.staging.json` must now use glob pattern
   - **Status**: Only IngestManager reads these files, already uses glob

---

## Usage Examples

### Debugging diff via command-line

```bash
# Run snapshot at 09:45
$ olav sync take_snapshot --wait
# Creates: exports/snapshots/2026-03-01_0945/raw/R1/show_ip_bgp.txt
# Creates: exports/snapshots/json/R1_20260301_0945.staging.json

# ... make a network change ...
# Run snapshot at 10:15
$ olav sync take_snapshot --wait
# Creates: exports/snapshots/2026-03-01_1015/raw/R1/show_ip_bgp.txt
# Creates: exports/snapshots/json/R1_20260301_1015.staging.json

# Now you can diff locally:
diff exports/snapshots/2026-03-01_0945/raw/R1/show_ip_bgp.txt \
     exports/snapshots/2026-03-01_1015/raw/R1/show_ip_bgp.txt
```

### Database queries

```sql
-- Get all snapshots from 2026-03-01
SELECT DISTINCT snapshot_id FROM parsed_outputs 
WHERE snapshot_id LIKE '2026-03-01_%'
ORDER BY snapshot_id DESC;
-- Result: 2026-03-01_1015, 2026-03-01_0945, ...

-- Latest snapshot today
SELECT * FROM parsed_outputs
WHERE snapshot_id LIKE '2026-03-01_%'
ORDER BY snapshot_id DESC LIMIT 10;

-- Diff between two snapshots
SELECT *
FROM parsed_outputs
WHERE device_name = 'R1' AND command = 'show ip bgp'
  AND snapshot_id IN ('2026-03-01_0945', '2026-03-01_1015')
ORDER BY snapshot_id;
```

---

## File Listing Format

### Before
```
exports/snapshots/
└── 2026-03-01/
    ├── raw/
    │   ├── R1/
    │   │   ├── show_ip_bgp.txt
    │   │   └── show interfaces terse.txt
    │   └── R2/
    │       └── show ip bgp.txt
    └── (JSON files not organized by date)

exports/snapshots/json/
├── R1.staging.json        # Overwritten on each run
├── R2.staging.json        # Overwritten on each run
└── ...
```

### After
```
exports/snapshots/
├── 2026-03-01_0945/                 # Run 1 at 09:45
│   ├── raw/
│   │   ├── R1/
│   │   │   ├── show_ip_bgp.txt
│   │   │   └── show_interfaces_terse.txt
│   │   └── R2/
│   │       └── show_ip_bgp.txt
│   └── (metadata)
├── 2026-03-01_1015/                 # Run 2 at 10:15
│   ├── raw/
│   │   ├── R1/
│   │   │   ├── show_ip_bgp.txt      # Different content
│   │   │   └── show_interfaces_terse.txt
│   │   └── R2/
│   │       └── show_ip_bgp.txt
│   └── (metadata)
└── latest -> 2026-03-01_1015/       # Symlink to most recent

exports/snapshots/json/
├── R1_20260301_0945.staging.json    # Run 1
├── R2_20260301_0945.staging.json    # Run 1
├── R1_20260301_1015.staging.json    # Run 2
├── R2_20260301_1015.staging.json    # Run 2
└── ...
```

---

## Testing

### Manual Verification

```bash
# 1. Run take_snapshot twice with 5 minute gap
$ olav sync take_snapshot --wait
$ sleep 300  # 5 minutes
$ olav sync take_snapshot --wait

# 2. Verify directory structure
$ find exports/snapshots -type d -name "202*" | sort

# 3. Verify JSON files exist with timestamps
$ ls -la exports/snapshots/json/ | grep staging.json

# 4. Verify DuckDB has distinct snapshot_ids
$ duckdb .olav/databases/main.duckdb \
  "SELECT DISTINCT snapshot_id FROM parsed_outputs \
   WHERE snapshot_id LIKE '2026-03-01_%' ORDER BY snapshot_id DESC"

# 5. Verify diff works
$ diff exports/snapshots/2026-03-01_*/raw/R1/show_version.txt
```

### Automated Tests Impacted

The following tests should be re-run to ensure compatibility:
- `tests/e2e/test_sync_full_collection.py` — Verify new timestamp format
- `tests/unit/test_get_sync_dir.py` — Check minute-level default value
- `tests/unit/test_ingest_manager.py` — Verify glob pattern still works with new filenames

---

## Migration Notes

### For Existing Data

**No migration required**:
- Old snapshots (with day-level timestamps) are still readable
- If you have existing `exports/snapshots/2026-03-01/raw/` directories, they continue to work
- New snapshots will use `2026-03-01_HHMM/` format

**To Clean Up Old Data**:
```bash
# Archive old snapshots (optional)
$ tar -czf exports/snapshots_archive_20260301.tar.gz exports/snapshots/
```

---

## Design Rationale

### Why `YYYY-MM-DD_HHMM`?

- **Minute-level**: Sufficient for typical debugging (multiple runs per day)
- **Human-readable**: Can quickly see "09:45" from directory name
- **Lexicographic ordering**: Directory names sort in chronological order naturally
- **Backward compatible**: Existing queries using `strftime()` still work with partial matches

### Why Not Seconds?

- `YYYY-MM-DD_HHMMSS` would be overkill (minimal risk of same-second runs without clustering)
- Directory names become harder to read
- Most debugging workflows don't need second-level precision

### Why Not UUID?

- Less human-friendly (users can't guess what "abc123def456" represents)
- Harder to correlate with operational logs
- Loses temporal ordering in filenames

---

## FAQ

**Q: Will this break my existing scripts?**  
A: Only if they hard-code `YYYY-MM-DD` path assumptions. Most queries using DuckDB are unaffected.

**Q: Can I still access yesterday's snapshots?**  
A: Yes. Query `snapshot_id LIKE '2026-02-28_%'` to get all snapshots from that day.

**Q: What about `latest` symlink?**  
A: Still points to the most recent snapshot directory (updated automatically).

**Q: Why not use ISO 8601 full timestamp?**  
A: Would break the current `YYYY-MM-DD` queries in many places. This is a more conservative change.

---

**References**:
- `.olav/workspace/config/sync/tools/take_snapshot.py` (Line 244)
- `.olav/workspace/config/sync/tools/sync_tools.py` (Lines 117-127, 1381-1390)
- `src/olav/core/ingest_manager.py` (glob pattern compatibility)
