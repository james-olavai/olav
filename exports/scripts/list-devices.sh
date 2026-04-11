#!/bin/bash
set -euo pipefail

usage() {
  cat << EOF
Usage: $0 [OPTIONS]

List all devices from OLAV database.

Options:
  --dry-run    Print SQL queries without executing (default: false)
EOF
}

DRY_RUN=false
while [[ $# -gt 0 ]]; do
  case $1 in
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      usage
      exit 1
      ;;
  esac
done

OLAV_DB_PATH="${OLAV_DB_PATH:-.olav/databases/domain.duckdb}"
OLAV_DB_PATH="${OLAV_DB_PATH:?OLAV database path required}"

command -v duckdb &>/dev/null || {
  echo "Error: duckdb required. Install via 'pip install duckdb' or your package manager."
  exit 1
}

COUNT_SQL="SELECT COUNT(*) as total_devices FROM netops.devices;"
LIST_SQL="SELECT hostname, ip_address, platform, role, site FROM netops.devices ORDER BY hostname;"

if [[ "$DRY_RUN" == true ]]; then
  echo "DRY-RUN mode:"
  echo "1. Count query: $COUNT_SQL"
  echo "2. List query: $LIST_SQL"
  exit 0
fi

echo "Querying OLAV database: $OLAV_DB_PATH"

total=$(duckdb "$OLAV_DB_PATH" "$COUNT_SQL" --no-header --quiet) || {
  echo "Error: Failed to query count from database."
  exit 1
}

echo "Found $total devices:"
echo "================================"

duckdb "$OLAV_DB_PATH" "$LIST_SQL" || {
  echo "Error: Failed to list devices from database."
  exit 1
}

echo "================================"
echo "Summary: Queried $total devices successfully."
