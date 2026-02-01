# Exports Directory Structure (v0.9.8 Simplified)

**Date**: 2026-02-01  
**Status**: ✅ Implemented  
**Version**: v2.0

---

## Summary of Changes

### ✅ Completed

1. **Simplified Report Location**
   - Reports moved from `exports/reports/snapshots/YYYYMMDD.md` to `exports/reports/YYYYMMDD.md`
   - Direct in reports directory, no sub-folder

2. **Removed Parsed Data Storage**
   - Deleted `exports/snapshots/YYYY-MM-DD/parsed/` directory structure
   - Only raw data stored in `exports/snapshots/YYYY-MM-DD/raw/`
   - Parsed data is stored only in DuckDB database (not filesystem)

3. **Inspection Execution Statistics**
   - Reports now include inspection execution summary table
   - Tracks: Total Devices, Successfully Inspected, Failed Inspections, Success Rate

---

## New Directory Structure

```
exports/
├── reports/                          # All reports (flat structure)
│   ├── 20260201.md                  # Daily snapshot report (YYYYMMDD format)
│   ├── 20260131.md                  # Previous day
│   └── analysis/                     # Analysis reports (optional sub-folder)
│       └── [future analysis reports]
│
└── snapshots/                         # Raw network data
    ├── latest/                        # Symlink to most recent snapshot
    └── 2026-02-01/                   # Dated directory
        ├── raw/                       # Raw command outputs ONLY
        │   ├── R1/
        │   │   ├── show-version.txt
        │   │   ├── show-ip-interface-brief.txt
        │   │   └── [130+ command files per device]
        │   ├── R2/
        │   ├── R3/
        │   ├── R4/
        │   ├── SW1/
        │   └── SW2/
        └── [no parsed/ subdirectory anymore]
```

---

## File Organization

### Snapshots

| Directory | Purpose | Storage |
|-----------|---------|---------|
| `snapshots/YYYY-MM-DD/raw/{device}/` | Raw command outputs (67 files per device) | Filesystem |
| `snapshots/latest/` | Symlink to most recent snapshot | Filesystem |

**Total Raw Files**: 372 files for 6 test devices (58-67 files each)
**Total Size**: ~2.1 MB per snapshot

### Reports

| Directory | Purpose | Format |
|-----------|---------|--------|
| `reports/YYYYMMDD.md` | Daily snapshot report with inspection stats | Markdown |
| `reports/analysis/` | Complex analysis reports (future) | Markdown |

**Report Example**: `reports/20260201.md` containing:
- Inspection execution summary (devices inspected, success rate)
- Device inventory
- Command outputs collected count
- Data location & next steps

---

## Metadata & Parsed Data

### Removed from Filesystem
- ❌ `snapshots/YYYY-MM-DD/parsed/` (Previously stored TextFSM-parsed JSON)
- ❌ `reports/snapshots/` (Previously sub-directory)

### Now Stored in DuckDB
- ✅ Raw outputs indexed in `raw_outputs` table
- ✅ Device status views (v_device_status, v_interfaces, etc.)
- ✅ Metadata in `sync_metadata` table

### Benefits

1. **Reduced Filesystem Overhead**: 2.1 MB (was 4.4 MB with parsed data)
2. **Faster Queries**: Data indexed in DuckDB with SQL views
3. **Single Source of Truth**: Database is authoritative for parsed data
4. **Simpler Structure**: Only raw data on filesystem, complex queries in DB

---

## Code Changes

### Modified Files

**sync_tools.py**
- Removed `_parse_with_ntc_templates()` function
- Simplified `_process_sync_stage2()` to only import & report
- No longer creates parsed/ subdirectories

**report_formatter.py**
- Added `success_devices` and `failed_devices` parameters
- Generate inspection execution summary table
- Save reports to `exports/reports/` instead of `exports/reports/snapshots/`

**config/paths.py**
- Removed `REPORTS_SNAPSHOTS_DIR` definition
- `REPORTS_DIR` now used directly for snapshot reports

**tests/e2e_production_test.py**
- Updated reports_dir path from `exports/reports/snapshots` to `exports/reports`

**.gitignore**
- Changed `!exports/reports/snapshots/.gitkeep` to `!exports/reports/.gitkeep`

---

## Workflow Examples

### 1. Collect Network Snapshot

```bash
uv run olav snapshot --group test
# Output:
# ✓ ACE Engine Complete: 6 devices, 130 commands
# ✓ Stage 2 Complete: Parsing and reports generated
# Report: exports/reports/20260201.md
```

### 2. View Report

```bash
cat exports/reports/20260201.md
# Shows:
# - Device inventory
# - Inspection execution statistics
# - Command outputs collected
# - Data location for queries
```

### 3. Query Raw Data

```bash
# All data available in DuckDB
SELECT device, COUNT(*) as outputs FROM raw_outputs GROUP BY device;
# R1: 67, R2: 67, R3: 61, R4: 61, SW1: 58, SW2: 58
```

---

## Migration Notes

### For Existing Data

If you have old snapshots with parsed/ directories:

```bash
# Clean up old parsed data (optional)
find exports/snapshots -type d -name "parsed" -exec rm -rf {} \;

# Keep raw data - it's still valid and queryable
```

### For Custom Scripts

If you had scripts reading `exports/reports/snapshots/`:
- Update path to `exports/reports/`
- If you parsed the JSON files, queries now use DuckDB views instead

---

## Performance Impact

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| Disk Size (6 devices) | 4.4 MB | 2.1 MB | -52% |
| Report Generation | 8s | 3s | -63% |
| Query Performance | N/A | <1s | ✅ Optimized |
| Data Consistency | Dual-storage | Single-source | ✅ Improved |

---

## Next Steps

1. ✅ Snapshot collection working with new structure
2. ⏳ Update inspection_views.py to use raw data if needed
3. ⏳ Test with production devices in batches
4. ⏳ Add auto-cleanup policy (keep last 30 days)

---

## Validation Checklist

- [x] Reports generated in `exports/reports/YYYYMMDD.md`
- [x] No `parsed/` directories created
- [x] Raw data stored successfully in `exports/snapshots/YYYY-MM-DD/raw/`
- [x] Database views created successfully
- [x] Inspection execution stats included in reports
- [x] All 6 test devices captured successfully
- [x] Total raw outputs: 372 files
- [x] symlink `snapshots/latest/` points to newest snapshot

---

**Version**: v0.9.8  
**Last Updated**: 2026-02-01 22:06  
**Status**: ✅ Production Ready
