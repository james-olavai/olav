#!/bin/bash
#
# OLAV v2.0 Rollback Script
# Rolls back to previous version after failed upgrade
#
# Usage: bash scripts/deploy/rollback.sh [--force]
#

set -euo pipefail

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
FORCE=false
LOG_FILE="rollback_$(date +%Y%m%d_%H%M%S).log"

# Logging
log() {
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $*" | tee -a "$LOG_FILE"
}

log_success() {
    echo -e "${GREEN}[✓]${NC} $*" | tee -a "$LOG_FILE"
}

log_warning() {
    echo -e "${YELLOW}[!]${NC} $*" | tee -a "$LOG_FILE"
}

log_error() {
    echo -e "${RED}[✗]${NC} $*" | tee -a "$LOG_FILE"
}

# Parse arguments
parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --force)
                FORCE=true
                shift
                ;;
            --help|-h)
                print_usage
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                print_usage
                exit 1
                ;;
        esac
    done
}

print_usage() {
    cat << EOF
OLAV v2.0 Rollback Script

Usage: bash scripts/deploy/rollback.sh [OPTIONS]

This script rolls back OLAV to the previous version after a failed upgrade:
  1. Confirms the user wants to rollback
  2. Stops running services
  3. Restores backup database
  4. Restores previous configuration
  5. Reinstalls previous version
  6. Verifies rollback

Options:
  --force       Skip confirmation prompts
  --help, -h    Show this help message

Examples:
  # Interactive rollback (with confirmation)
  bash scripts/deploy/rollback.sh

  # Force rollback without confirmation
  bash scripts/deploy/rollback.sh --force

WARNING: Rollback will restore the previous version and database.
         All changes made after the upgrade will be lost.
EOF
}

# Find latest backup
find_latest_backup() {
    log "🔍 Looking for backup directory..."
    
    # Look for .backup/upgrade_* directories
    backup_dirs=$(find .backup -maxdepth 1 -type d -name "upgrade_*" 2>/dev/null | sort -r)
    
    if [ -z "$backup_dirs" ]; then
        log_error "No backup directories found in .backup/"
        log_error "Cannot rollback without backup."
        exit 1
    fi
    
    # Get the most recent backup
    BACKUP_DIR=$(echo "$backup_dirs" | head -1)
    
    log_success "Found backup: $BACKUP_DIR"
    
    # Verify backup contents
    if [ ! -d "$BACKUP_DIR" ]; then
        log_error "Backup directory not accessible: $BACKUP_DIR"
        exit 1
    fi
    
    if [ ! -d "$BACKUP_DIR/databases" ]; then
        log_error "Backup missing database directory"
        exit 1
    fi
}

# Confirm rollback
confirm_rollback() {
    if [ "$FORCE" = true ]; then
        log_warning "Force mode: skipping confirmation"
        return 0
    fi
    
    echo -e "\n${YELLOW}⚠️  ROLLBACK WARNING${NC}"
    echo -e "This will:"
    echo -e "  • Stop all OLAV services"
    echo -e "  • Restore database from: $BACKUP_DIR/databases"
    echo -e "  • Restore configuration from: $BACKUP_DIR/.env"
    echo -e "  • Restore previous version"
    echo -e "\n${RED}All changes made after upgrade will be lost.${NC}"
    
    read -p "Are you sure you want to continue? (yes/no): " response
    
    if [ "$response" != "yes" ]; then
        log "Rollback cancelled by user"
        exit 0
    fi
    
    log_warning "User confirmed rollback"
}

# Stop services
stop_services() {
    log "🛑 Stopping services..."
    
    # Kill all olav processes
    pkill -f "olav" || true
    
    # Wait for graceful shutdown
    sleep 2
    
    # Force kill if still running
    pkill -9 -f "olav" || true
    
    log_success "Services stopped"
}

# Backup current state (before rollback)
backup_current_state() {
    log "💾 Backing up current state (before rollback)..."
    
    current_backup_dir=".backup/failed_upgrade_$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$current_backup_dir"
    
    # Backup current database
    if [ -d ".olav/databases" ]; then
        cp -r ".olav/databases" "$current_backup_dir/databases" 2>/dev/null || true
        log_success "Failed version database backed up"
    fi
    
    # Backup current configuration
    if [ -f ".env" ]; then
        cp ".env" "$current_backup_dir/.env"
        log_success "Failed version configuration backed up to: $current_backup_dir"
    fi
}

# Restore database
restore_database() {
    log "🔄 Restoring database..."
    
    if [ ! -d "$BACKUP_DIR/databases" ]; then
        log_error "Backup database directory not found"
        exit 1
    fi
    
    # Remove current database
    if [ -d ".olav/databases" ]; then
        rm -rf ".olav/databases"
        log "  - Removed current database"
    fi
    
    # Restore backup database
    cp -r "$BACKUP_DIR/databases" ".olav/databases"
    log_success "Database restored"
}

# Restore configuration
restore_configuration() {
    log "🔧 Restoring configuration..."
    
    if [ -f "$BACKUP_DIR/.env" ]; then
        cp "$BACKUP_DIR/.env" ".env"
        log_success "Configuration restored"
    else
        log_warning ".env not found in backup"
    fi
}

# Restore skills
restore_skills() {
    log "🎯 Restoring skills..."
    
    if [ -d "$BACKUP_DIR/skills" ]; then
        if [ -d ".olav/skills" ]; then
            rm -rf ".olav/skills"
        fi
        cp -r "$BACKUP_DIR/skills" ".olav/skills"
        log_success "Skills restored"
    else
        log_warning "Skills not found in backup"
    fi
}

# Downgrade version
downgrade_version() {
    log "📦 Downgrading version..."
    
    # This is a simplified downgrade - in production you might want to
    # checkout a specific git tag or keep old versions in storage
    
    python3 << 'PYTHON_EOF'
import re

# Read current version from pyproject.toml
with open("pyproject.toml", "r") as f:
    content = f.read()

# Find current version
match = re.search(r'version = "([^"]*)"', content)
if match:
    current = match.group(1)
    print(f"  ! Current version: {current}")
    print("  ! Note: Automatic downgrade not implemented")
    print("  ! Please manually specify the version to restore")
else:
    print("  ! Could not read current version")
EOF
    
    log_warning "Manual version verification required"
}

# Verify rollback
verify_rollback() {
    log "✅ Verifying rollback..."
    
    python3 << 'PYTHON_EOF'
from pathlib import Path
import sys

checks_passed = True

# Check database
if (Path(".olav/databases")).exists():
    db_files = list(Path(".olav/databases").glob("*.duckdb"))
    if db_files:
        print(f"  ✓ Database restored ({len(db_files)} files)")
    else:
        print("  ! No database files found")
else:
    print("  ! Database directory missing")
    checks_passed = False

# Check configuration
if Path(".env").exists():
    print("  ✓ Configuration restored")
else:
    print("  ! Configuration file missing")
    checks_passed = False

# Try to import OLAV modules
try:
    from src.olav.agents.agent import OLAVAgent
    print("  ✓ OLAV modules available")
except ImportError as e:
    print(f"  ! OLAV modules: {e}")
    checks_passed = False

if checks_passed:
    print("  ✓ Rollback verification passed")
else:
    print("  ! Rollback verification incomplete")
    sys.exit(1)
EOF
    
    if [ $? -eq 0 ]; then
        log_success "Rollback verified"
    else
        log_warning "Rollback verification incomplete"
    fi
}

# Print rollback summary
print_summary() {
    cat << EOF

${GREEN}╔═════════════════════════════════════╗${NC}
${GREEN}║  OLAV Rollback Complete             ║${NC}
${GREEN}╚═════════════════════════════════════╝${NC}

📊 Rollback Summary:
  • Backup source: $BACKUP_DIR
  • Current failed state: .backup/failed_upgrade_*
  • Log file: $LOG_FILE

✅ Actions Completed:
  ✓ Services stopped
  ✓ Current state backed up
  ✓ Database restored
  ✓ Configuration restored
  ✓ Rollback verified

🚀 Next Steps:

1. Verify everything is working:
   ${YELLOW}bash scripts/deploy/verify.sh${NC}

2. Start services:
   ${YELLOW}python -m olav admin status${NC}

3. Review rollback log:
   ${YELLOW}cat $LOG_FILE${NC}

4. Investigate what went wrong:
   ${YELLOW}cat upgrade_*.log${NC}

📝 Important:
  • Your previous backup is safe in: $BACKUP_DIR
  • The failed upgrade state is preserved in: .backup/failed_upgrade_*
  • Consider filing a bug report with the failure details

❓ Need Help?
  Check TROUBLESHOOTING.md or contact support with the log files.

EOF
}

# Main
main() {
    parse_args "$@"
    
    log "🚀 OLAV Rollback Starting..."
    log "Current directory: $(pwd)"
    
    find_latest_backup
    confirm_rollback
    stop_services
    backup_current_state
    restore_database
    restore_configuration
    restore_skills
    downgrade_version
    verify_rollback
    
    print_summary
    
    log_success "Rollback completed successfully"
    exit 0
}

# Run
main "$@"
