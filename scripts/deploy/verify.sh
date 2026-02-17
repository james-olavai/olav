#!/bin/bash
#
# OLAV v2.0 Verification Script
# Verifies installation and system readiness
#
# Usage: bash scripts/deploy/verify.sh [--all] [--health] [--tests]
#

set -euo pipefail

# Color codes
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

FAILED_CHECKS=0
PASSED_CHECKS=0

# Counter functions
check_pass() {
    echo -e "${GREEN}[✓]${NC} $*"
    ((PASSED_CHECKS++))
}

check_fail() {
    echo -e "${RED}[✗]${NC} $*"
    ((FAILED_CHECKS++))
}

check_info() {
    echo -e "${BLUE}[i]${NC} $*"
}

# System checks
check_python() {
    echo -e "\n${YELLOW}=== Python Environment ===${NC}"
    
    if ! command -v python3 &> /dev/null; then
        check_fail "Python 3 not found"
        return 1
    fi
    
    version=$(python3 --version 2>&1 | awk '{print $2}')
    check_pass "Python $version installed"
    
    check_info "Executable: $(which python3)"
    
    return 0
}

# Dependencies check
check_dependencies() {
    echo -e "\n${YELLOW}=== Python Dependencies ===${NC}"
    
    python3 << 'PYTHON_EOF'
import sys
import importlib
from packaging import version

required_packages = {
    "langchain": ">=0.1.0",
    "pydantic": ">=2.0",
    "duckdb": ">=0.8.0",
    "fastapi": ">=0.109.0",
}

all_ok = True
for package_name, req_version in required_packages.items():
    try:
        mod = importlib.import_module(package_name.replace("-", "_"))
        pkg_version = getattr(mod, "__version__", "unknown")
        print(f"  ✓ {package_name}: {pkg_version}")
    except ImportError:
        print(f"  ✗ {package_name}: NOT INSTALLED")
        all_ok = False

sys.exit(0 if all_ok else 1)
PYTHON_EOF
    
    if [ $? -eq 0 ]; then
        check_pass "All required dependencies installed"
    else
        check_fail "Some dependencies are missing"
        return 1
    fi
}

# Configuration check
check_configuration() {
    echo -e "\n${YELLOW}=== Configuration ===${NC}"
    
    if [ ! -f .env ]; then
        check_fail ".env file not found"
        return 1
    fi
    
    check_pass ".env file exists"
    
    # Check required variables
    source .env
    
    required_vars=("LLM_API_KEY" "NETWORK_USERNAME" "NETWORK_PASSWORD")
    for var in "${required_vars[@]}"; do
        if [ -z "${!var:-}" ] || [ "${!var:-}" = "your-key" ] || [ "${!var:-}" = "your-production-key-here" ]; then
            check_fail "$var not configured (current: ${!var:-empty})"
        else
            check_pass "$var configured"
        fi
    done
}

# Database check
check_database() {
    echo -e "\n${YELLOW}=== Database ===${NC}"
    
    python3 << 'PYTHON_EOF'
from pathlib import Path
from src.olav.core.database import get_database

try:
    db = get_database()
    
    # Check if database file exists
    db_files = list(Path(".olav/databases").glob("*.duckdb"))
    if db_files:
        for f in db_files:
            print(f"  ✓ Database file: {f.name}")
    else:
        print("  ! No database files found (will be created on first use)")
    
    print("  ✓ Database connection successful")
except Exception as e:
    print(f"  ✗ Database check failed: {e}")
    exit(1)
PYTHON_EOF
    
    if [ $? -eq 0 ]; then
        check_pass "Database initialization verified"
    else
        check_fail "Database check failed"
        return 1
    fi
}

# Module check
check_modules() {
    echo -e "\n${YELLOW}=== OLAV Modules ===${NC}"
    
    python3 << 'PYTHON_EOF'
modules = [
    ("Agent", "src.olav.agents.agent"),
    ("CLI", "src.olav.cli.cli_main"),
    ("API", "src.olav.api.server"),
    ("Database", "src.olav.core.database"),
    ("Config", "config.settings"),
]

all_ok = True
for name, module_path in modules:
    try:
        parts = module_path.split(".")
        mod = __import__(module_path, fromlist=[parts[-1]])
        print(f"  ✓ {name}: {module_path}")
    except ImportError as e:
        print(f"  ✗ {name}: {e}")
        all_ok = False
    except Exception as e:
        print(f"  ! {name}: Warning - {e}")

exit(0 if all_ok else 1)
PYTHON_EOF
    
    if [ $? -eq 0 ]; then
        check_pass "All OLAV modules available"
    else
        check_fail "Some OLAV modules are not available"
        return 1
    fi
}

# Health check
check_health() {
    echo -e "\n${YELLOW}=== System Health ===${NC}"
    
    # Disk space
    available=$(df . | tail -1 | awk '{print $4}')
    available_gb=$((available / 1024 / 1024))
    if [ "$available_gb" -lt 1 ]; then
        check_fail "Low disk space: ${available_gb}GB available (need at least 1GB)"
    else
        check_pass "Disk space: ${available_gb}GB available"
    fi
    
    # Memory
    free_mem=$(free -h | awk 'NR==2 {print $7}')
    check_info "Free memory: $free_mem"
    
    # LLM connectivity (if API key is set)
    python3 << 'PYTHON_EOF'
import os
if os.getenv("LLM_API_KEY") and os.getenv("LLM_API_KEY") != "your-key":
    try:
        from langchain_openai import OpenAI
        llm = OpenAI(api_key=os.getenv("LLM_API_KEY"))
        # Don't actually call, just check if object creates properly
        print("  ✓ LLM client configured")
    except Exception as e:
        print(f"  ! LLM check: {e}")
else:
    print("  ! LLM_API_KEY not configured (LLM features will be unavailable)")
EOF
}

# Run tests
run_tests() {
    echo -e "\n${YELLOW}=== Running Tests ===${NC}"
    
    if [ ! -d "tests" ]; then
        check_info "No tests directory found"
        return 0
    fi
    
    python3 -m pytest tests/unit/ -q --tb=line 2>&1 | head -20
    
    if [ $? -eq 0 ]; then
        check_pass "Unit tests passed"
    else
        check_fail "Some tests failed"
    fi
}

# Print summary
print_summary() {
    echo -e "\n${BLUE}════════════════════════════════════════${NC}"
    echo -e "${BLUE}Installation Verification Summary${NC}"
    echo -e "${BLUE}════════════════════════════════════════${NC}"
    
    echo -e "\n${GREEN}Passed:${NC} $PASSED_CHECKS checks"
    echo -e "${RED}Failed:${NC} $FAILED_CHECKS checks"
    
    if [ $FAILED_CHECKS -eq 0 ]; then
        echo -e "\n${GREEN}✓ Installation verified successfully!${NC}"
        return 0
    else
        echo -e "\n${RED}✗ Some checks failed. Please review above.${NC}"
        return 1
    fi
}

# Usage
print_usage() {
    cat << EOF
OLAV v2.0 Verification Script

Usage: bash scripts/deploy/verify.sh [OPTIONS]

Options:
  --all          Run all checks (default)
  --health       Run health checks only
  --tests        Run tests only
  --help, -h     Show this help message
EOF
}

# Main
main() {
    VERIFY_MODE="all"
    
    if [ $# -gt 0 ]; then
        case $1 in
            --all) VERIFY_MODE="all" ;;
            --health) VERIFY_MODE="health" ;;
            --tests) VERIFY_MODE="tests" ;;
            --help|-h) print_usage; exit 0 ;;
            *) echo "Unknown option: $1"; print_usage; exit 1 ;;
        esac
    fi
    
    echo -e "${GREEN}🔍 OLAV v2.0 Installation Verification${NC}"
    
    case $VERIFY_MODE in
        all)
            check_python
            check_dependencies
            check_configuration
            check_database
            check_modules
            check_health
            run_tests
            ;;
        health)
            check_health
            ;;
        tests)
            run_tests
            ;;
    esac
    
    print_summary
}

# Run
main "$@"
