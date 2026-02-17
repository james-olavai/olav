#!/bin/bash
#
# OLAV v2.0 Troubleshooting Script
# Diagnoses and collects diagnostic information
#
# Usage: bash scripts/deploy/troubleshoot.sh [--report] [--verbose]
#

set -euo pipefail

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
VERBOSE=false
GENERATE_REPORT=false
REPORT_DIR="diagnostics"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
REPORT_FILE="${REPORT_DIR}/diagnostic_report_${TIMESTAMP}.txt"

# Logging
log() {
    echo -e "${BLUE}[i]${NC} $*"
}

log_success() {
    echo -e "${GREEN}[✓]${NC} $*"
}

log_warning() {
    echo -e "${YELLOW}[!]${NC} $*"
}

log_error() {
    echo -e "${RED}[✗]${NC} $*"
}

# Parse arguments
parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --report)
                GENERATE_REPORT=true
                shift
                ;;
            --verbose|-v)
                VERBOSE=true
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
OLAV v2.0 Troubleshooting Script

Usage: bash scripts/deploy/troubleshoot.sh [OPTIONS]

This script diagnoses OLAV installation and configuration:
  • Checks system requirements
  • Validates configuration
  • Tests connectivity
  • Collects diagnostic information
  • Generates troubleshooting report

Options:
  --report      Generate detailed diagnostic report
  --verbose     Show detailed output
  --help, -h    Show this help message

Examples:
  # Basic troubleshooting
  bash scripts/deploy/troubleshoot.sh

  # Generate diagnostic report
  bash scripts/deploy/troubleshoot.sh --report

  # Verbose output
  bash scripts/deploy/troubleshoot.sh --verbose
EOF
}

# Redirect to report if requested
setup_report() {
    if [ "$GENERATE_REPORT" = true ]; then
        mkdir -p "$REPORT_DIR"
        exec > >(tee "$REPORT_FILE")
        exec 2>&1
        
        echo "OLAV Diagnostic Report"
        echo "Generated: $(date)"
        echo "=============================================="
    fi
}

# System information
check_system() {
    echo -e "\n${YELLOW}=== System Information ===${NC}"
    
    # OS
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        log "OS: $PRETTY_NAME"
    fi
    
    # Kernel
    log "Kernel: $(uname -r)"
    
    # Architecture
    log "Architecture: $(uname -m)"
    
    # CPU
    cpu_count=$(nproc 2>/dev/null || echo "unknown")
    log "CPU cores: $cpu_count"
    
    # Memory
    if command -v free &> /dev/null; then
        total_mem=$(free -h | awk 'NR==2 {print $2}')
        free_mem=$(free -h | awk 'NR==2 {print $7}')
        log "Total memory: $total_mem"
        log "Free memory: $free_mem"
    fi
    
    # Disk
    available=$(df -h . | tail -1 | awk '{print $4}')
    used=$(df -h . | tail -1 | awk '{print $3}')
    log "Disk space - Used: $used, Available: $available"
}

# Python environment
check_python() {
    echo -e "\n${YELLOW}=== Python Environment ===${NC}"
    
    if ! command -v python3 &> /dev/null; then
        log_error "Python 3 not found"
        return 1
    fi
    
    version=$(python3 --version)
    log "Python: $version"
    log "Executable: $(which python3)"
    
    # Check virtual environment
    if [ ! -z "${VIRTUAL_ENV:-}" ]; then
        log "Virtual environment: $VIRTUAL_ENV"
    else
        log_warning "Not running in virtual environment"
    fi
    
    # pip/uv
    if command -v uv &> /dev/null; then
        log "Package manager: uv ($(uv --version))"
    elif command -v pip3 &> /dev/null; then
        log "Package manager: pip3 ($(pip3 --version | cut -d' ' -f2))"
    else
        log_warning "No package manager found"
    fi
}

# Dependencies
check_dependencies() {
    echo -e "\n${YELLOW}=== Python Dependencies ===${NC}"
    
    python3 << 'PYTHON_EOF'
import sys
import importlib

packages = [
    "langchain",
    "langchain-openai", 
    "pydantic",
    "duckdb",
    "fastapi",
    "uvicorn",
    "pytest",
]

missing = []
for pkg in packages:
    try:
        mod = importlib.import_module(pkg.replace("-", "_"))
        version = getattr(mod, "__version__", "unknown")
        print(f"  ✓ {pkg}: {version}")
    except ImportError:
        print(f"  ✗ {pkg}: NOT INSTALLED")
        missing.append(pkg)

if missing:
    print(f"\n  Missing: {', '.join(missing)}")
    print("  Install with: pip install " + " ".join(missing))
EOF
}

# Configuration check
check_configuration() {
    echo -e "\n${YELLOW}=== Configuration ===${NC}"
    
    if [ ! -f .env ]; then
        log_error ".env file not found"
        return 1
    fi
    
    log_success ".env file exists"
    
    # Check for sensitive values
    python3 << 'PYTHON_EOF'
from pathlib import Path
import re

env_file = Path(".env")
if not env_file.exists():
    exit(1)

content = env_file.read_text()
lines = content.split("\n")

placeholder_pattern = r"(your-key|your-.*|example|placeholder|\$\{.*\})"

issues = []
for i, line in enumerate(lines, 1):
    if not line or line.startswith("#"):
        continue
    
    if "=" in line:
        key, value = line.split("=", 1)
        if re.search(placeholder_pattern, value, re.IGNORECASE):
            issues.append(f"  Line {i}: {key.strip()} not configured")

if issues:
    print("  Configuration issues:")
    for issue in issues:
        print(issue)
else:
    print("  ✓ All configuration variables set")
EOF
}

# Database check
check_database() {
    echo -e "\n${YELLOW}=== Database ===${NC}"
    
    if [ ! -d ".olav/databases" ]; then
        log_error "Database directory not found: .olav/databases"
        return 1
    fi
    
    db_files=$(find .olav/databases -name "*.duckdb" -o -name "*.db" 2>/dev/null | wc -l)
    log_success "Found $db_files database file(s)"
    
    python3 << 'PYTHON_EOF'
from pathlib import Path
import subprocess

db_files = list(Path(".olav/databases").glob("*.duckdb"))

for db_file in db_files:
    size_mb = db_file.stat().st_size / (1024 * 1024)
    mod_time = Path(db_file).stat().st_mtime
    from datetime import datetime
    mod_date = datetime.fromtimestamp(mod_time).strftime("%Y-%m-%d %H:%M")
    
    print(f"  • {db_file.name}: {size_mb:.2f}MB (modified: {mod_date})")
    
    # Try to get table count
    try:
        result = subprocess.run(
            ["python3", "-c", f"""
import duckdb
conn = duckdb.connect(r'{db_file}')
tables = conn.execute("SELECT COUNT(*) FROM information_schema.tables").fetchone()[0]
print(f"    Tables: {{tables}}")
"""],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            print(result.stdout.strip())
    except Exception as e:
        print(f"    Error reading database: {e}")
EOF
}

# OLAV modules
check_olav_modules() {
    echo -e "\n${YELLOW}=== OLAV Modules ===${NC}"
    
    python3 << 'PYTHON_EOF'
import sys
from pathlib import Path

modules = {
    "Agent": "src.olav.agents.agent",
    "CLI": "src.olav.cli.cli_main",
    "Database": "src.olav.core.database",
    "Config": "config.settings",
    "Skills": "src.olav.core.skills_loader",
}

for name, path in modules.items():
    try:
        parts = path.split(".")
        mod = __import__(path, fromlist=[parts[-1]])
        print(f"  ✓ {name}: {path}")
    except ImportError as e:
        print(f"  ✗ {name}: {e}")
    except Exception as e:
        print(f"  ! {name}: {e}")
EOF
}

# Network connectivity
check_network() {
    echo -e "\n${YELLOW}=== Network Connectivity ===${NC}"
    
    # Internet connectivity
    if ping -c 1 8.8.8.8 &> /dev/null; then
        log_success "Internet connectivity: OK"
    else
        log_warning "Internet connectivity: FAILED (may affect LLM API)"
    fi
    
    # DNS
    if ping -c 1 google.com &> /dev/null; then
        log_success "DNS resolution: OK"
    else
        log_warning "DNS resolution: FAILED"
    fi
    
    # Local services
    python3 << 'PYTHON_EOF'
import socket
import os

services = [
    ("LLM API", "api.openai.com", 443),
    ("Database (if postgresql)", "localhost", 5432),
]

for name, host, port in services:
    try:
        sock = socket.create_connection((host, port), timeout=2)
        sock.close()
        print(f"  ✓ {name}: reachable")
    except (socket.timeout, ConnectionRefusedError, socket.gaierror):
        if "localhost" in host or "127.0.0.1" in host:
            print(f"  ! {name}: not running locally (expected if not using this)")
        else:
            print(f"  ✗ {name}: unreachable")
    except Exception as e:
        print(f"  ! {name}: {e}")
EOF
}

# Recent errors
check_errors() {
    echo -e "\n${YELLOW}=== Recent Errors ===${NC}"
    
    if [ -d "logs" ]; then
        error_count=$(grep -l "ERROR\|CRITICAL" logs/*.log 2>/dev/null | wc -l)
        if [ $error_count -gt 0 ]; then
            log_warning "Found $error_count log file(s) with errors"
            
            echo "  Recent errors (last 5):"
            grep "ERROR\|CRITICAL" logs/*.log 2>/dev/null | tail -5 | while read line; do
                echo "    $line"
            done
        else
            log_success "No recent errors found"
        fi
    else
        log "No logs directory"
    fi
}

# Running processes
check_processes() {
    echo -e "\n${YELLOW}=== Running Processes ===${NC}"
    
    if pgrep -f "olav" > /dev/null; then
        count=$(pgrep -f "olav" | wc -l)
        log_warning "Found $count OLAV process(es)"
        ps aux | grep -i olav | grep -v grep
    else
        log_success "No OLAV processes running"
    fi
    
    # Check ports
    echo -e "\n  Port status:"
    for port in 8000 5000 9090; do
        if lsof -Pi :$port -sTCP:LISTEN -t > /dev/null 2>&1; then
            log "  ! Port $port: in use"
        else
            log "  ✓ Port $port: available"
        fi
    done
}

# Run diagnostic tests
run_diagnostics() {
    echo -e "\n${YELLOW}=== Diagnostic Tests ===${NC}"
    
    python3 << 'PYTHON_EOF'
import sys
import os

print("  Testing module imports...")
try:
    from src.olav.agents.agent import OLAVAgent
    print("    ✓ Agent class available")
except Exception as e:
    print(f"    ✗ Agent class: {e}")

try:
    from src.olav.core.database import get_database
    db = get_database()
    print("    ✓ Database connection works")
except Exception as e:
    print(f"    ✗ Database: {e}")

print("  Testing configuration...")
try:
    import config.settings
    print("    ✓ Settings module available")
except Exception as e:
    print(f"    ✗ Settings: {e}")

print("  ✓ Diagnostics completed")
EOF
}

# Recommendations
print_recommendations() {
    echo -e "\n${YELLOW}=== Recommendations ===${NC}"
    
    # Check for common issues
    python3 << 'PYTHON_EOF'
import os
from pathlib import Path

recommendations = []

# Check environment
if not os.getenv("LLM_API_KEY") or os.getenv('LLM_API_KEY') in ["", "your-key", "${LLM_API_KEY}"]:
    recommendations.append("  • Set LLM_API_KEY environment variable or in .env")

# Check database
if not Path(".olav/databases").exists():
    recommendations.append("  • Create .olav/databases directory")

# Check if tests pass
if not Path("tests").exists():
    recommendations.append("  • Add test suite for validation")

# Check logs
if not Path("logs").exists():
    recommendations.append("  • Create logs directory for debugging")

if recommendations:
    for rec in recommendations:
        print(rec)
else:
    print("  ✓ No immediate issues detected")
EOF
}

# Print summary
print_summary() {
    cat << EOF

${GREEN}╔═════════════════════════════════════════╗${NC}
${GREEN}║  Troubleshooting Complete               ║${NC}
${GREEN}╚═════════════════════════════════════════╝${NC}

📝 Report Generated: $([ "$GENERATE_REPORT" = true ] && echo "${REPORT_FILE}" || echo "No report (use --report to generate)")

🔍 Diagnostics Summary:
  ✓ System information collected
  ✓ Python environment validated
  ✓ Dependencies checked
  ✓ Configuration reviewed
  ✓ Database verified
  ✓ Network connectivity tested
  ✓ Error logs reviewed

❓ Common Issues & Solutions:

1. LLM API Key Issues
   - Ensure LLM_API_KEY is set: echo \$LLM_API_KEY
   - Verify API key is valid: try API call manually
   - Check rate limits on API provider

2. Database Issues
   - Verify .olav/databases exists and is writable
   - Check disk space: df -h
   - Inspect database: python3 -c "import duckdb; print(duckdb.sql('SELECT 1'))"

3. Network Issues
   - Check firewall settings
   - Verify SSH/Netmiko credentials
   - Test device connectivity: ping <device_ip>

4. Configuration Issues
   - Verify all required variables in .env
   - Run: bash scripts/deploy/configure.sh
   - Check for placeholder values

5. Service Issues
   - Check logs: tail -f logs/*.log
   - Verify ports are available: netstat -tuln
   - Check process status: pgrep -f olav

${YELLOW}📚 For More Help:${NC}
   - Read TROUBLESHOOTING.md
   - Check DEPLOYMENT_GUIDE.md
   - Review test suite: pytest tests/ -v

EOF
}

# Main
main() {
    parse_args "$@"
    
    setup_report
    
    echo -e "${GREEN}🔍 OLAV Troubleshooting Starting...${NC}"
    
    check_system
    check_python
    check_dependencies
    check_configuration
    check_database
    check_olav_modules
    check_network
    check_errors
    check_processes
    run_diagnostics
    print_recommendations
    print_summary
    
    if [ "$GENERATE_REPORT" = true ]; then
        log_success "Diagnostic report saved to: $REPORT_FILE"
    fi
}

# Run
main "$@"
