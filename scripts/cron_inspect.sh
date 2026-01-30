#!/bin/bash
# OLAV Scheduled Inspection Script
# Usage: Add to crontab -e
#   0 8 * * * /home/yhvh/Olav/scripts/cron_inspect.sh

set -e

# Configuration
OLAV_DIR="/home/yhvh/Olav"
LOG_FILE="$OLAV_DIR/logs/cron_inspect.log"

# Ensure log directory exists
mkdir -p "$(dirname "$LOG_FILE")"

# Change to OLAV directory
cd "$OLAV_DIR"

# Record start time
echo "[$(date)] Starting scheduled inspection..." >> "$LOG_FILE"

# Run inspection (using test mode to avoid snapshot overhead if preferred, 
# or remove --test to use latest snapshot with real LLM)
# We use --test here for safety in the template, users can customize.
/usr/bin/uv run olav inspect --test >> "$LOG_FILE" 2>&1

# Check exit code
if [ $? -eq 0 ]; then
    echo "[$(date)] Inspection completed successfully" >> "$LOG_FILE"
else
    echo "[$(date)] Inspection failed with error code $?" >> "$LOG_FILE"
fi
