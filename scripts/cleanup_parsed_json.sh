#!/bin/bash
###############################################################################
# OLAV v0.9 - JSON Cleanup Script
###############################################################################
set -euo pipefail

# Configuration
EXPORTS_DIR="${EXPORTS_DIR:-exports}"
SNAPSHOTS_DIR="${EXPORTS_DIR}/snapshots"
RETENTION_DAYS=${RETENTION_DAYS:-7}
DRY_RUN=false

# Parse arguments
for arg in "$@"; do
    case $arg in
        --dry-run)
            DRY_RUN=true
            echo "DRY RUN MODE: No files will be deleted"
            shift
            ;;
        --help)
            echo "Usage: $0 [--dry-run]"
            echo ""
            echo "Cleanup parsed JSON files older than ${RETENTION_DAYS} days."
            exit 0
            ;;
    esac
done

# Validate directories
if [ ! -d "$SNAPSHOTS_DIR" ]; then
    echo "Error: Snapshots directory not found: $SNAPSHOTS_DIR" >&2
    exit 1
fi

# Count total JSON files
TOTAL_JSON=$(find "$SNAPSHOTS_DIR" -type f -name "*.json" 2>/dev/null | wc -l)
echo "OLAV v0.9 - JSON Cleanup Script"
echo "Total JSON files: $TOTAL_JSON"
echo "Retention Days: $RETENTION_DAYS"
echo "Dry Run: $DRY_RUN"
echo ""

# Find files to delete
FILES_TO_DELETE=$(find "$SNAPSHOTS_DIR" -type f -name "*.json" -mtime +${RETENTION_DAYS} 2>/dev/null || true)
FILES_COUNT=$(echo "$FILES_TO_DELETE" | grep -c "^" || echo "0")

if [ "$FILES_COUNT" -eq 0 ]; then
    echo "No files to delete (all JSON files are within retention period)."
    exit 0
fi

echo "Files to delete: $FILES_COUNT"
echo ""

if [ "$DRY_RUN" = true ]; then
    echo "$FILES_TO_DELETE" | head -10 | while read -r file; do
        echo "[DRY-RUN] Would delete: $file"
    done
    echo ""
    echo "DRY RUN COMPLETE - No files were actually deleted"
else
    echo "$FILES_TO_DELETE" | while read -r file; do
        if [ -n "$file" ]; then
            rm -f "$file"
            echo "Deleted: $file"
        fi
    done
    echo ""
    echo "CLEANUP COMPLETE"
fi

REMAINING_JSON=$(find "$SNAPSHOTS_DIR" -type f -name "*.json" 2>/dev/null | wc -l)
echo "Remaining JSON files: $REMAINING_JSON"
