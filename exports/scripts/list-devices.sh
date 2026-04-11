#!/bin/bash
    set -euo pipefail

    # List all devices from OLAV database
    # Usage: ./list-devices.sh [--dry-run]
    #   DRY_RUN=true ./list-devices.sh
    #   DB_PATH=/path/to/domain.duckdb ./list-devices.sh

    DRY_RUN="${DRY_RUN:-false}"
    DB_PATH="${DB_PATH:-.olav/databases/domain.duckdb}"

    if [[ "$DRY_RUN" == "true" ]]; then
      echo "DRY RUN: Would execute the following query on $DB_PATH:"
      echo "SELECT hostname, ip_address, platform, role, site FROM netops.devices;"
      echo
      echo "Expected columns: hostname, ip_address, platform, role, site"
      exit 0
    fi

    # Dependency check
    if ! command -v duckdb &>/dev/null; then
      echo "Error: duckdb CLI required. Install with: brew install duckdb (macOS) or https://duckdb.org/docs/installation" >&2
      exit 1
    fi

    # Validate DB path
    if [[ ! -f "$DB_PATH" ]]; then
      echo "Error: Database not found at $DB_PATH" >&2
      exit 1
    fi

    QUERY="SELECT hostname, ip_address, platform, role, site FROM netops.devices ORDER BY hostname;"

    echo "Querying devices from $DB_PATH..."
    echo

    # Execute query and format output
    duckdb -no-header "$DB_PATH" "$QUERY" | column -t -s $'\t' | sed '1i hostname\tip_address\tplatform\trole\tsite'

    COUNT=$(duckdb -no-header -c "$QUERY" | wc -l)
    echo
    echo "Summary: Found $COUNT devices."
    