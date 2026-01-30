#!/usr/bin/env bash
# OLAV Test Runner - Convenient wrapper for running different test categories

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper functions
print_header() {
    echo -e "\n${BLUE}========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================${NC}\n"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

# Check prerequisites
check_prerequisites() {
    if [ "$1" == "e2e" ] || [ "$1" == "llm" ]; then
        if [ ! -f ".env" ]; then
            print_error ".env file not found!"
            echo "E2E and LLM tests require .env with API keys."
            echo "Create .env with OPENAI_API_KEY or DEEPSEEK_API_KEY."
            exit 1
        fi
        print_success ".env file found"
    fi
    
    if [ "$1" == "e2e" ] || [ "$1" == "network" ]; then
        if [ ! -f ".olav/inventory.yaml" ]; then
            print_warning "inventory.yaml not found - network tests may fail"
            echo "Create .olav/inventory.yaml with device credentials for network tests."
        else
            print_success "inventory.yaml found"
        fi
    fi
}

# Show usage
show_usage() {
    cat << EOF
${GREEN}OLAV Test Runner${NC}

Usage: $0 [COMMAND]

Commands:
    integration    Run integration tests (fast, free) - Default
    e2e           Run real E2E tests (slow, expensive)
    network       Run network device tests only
    llm           Run LLM API tests only
    all           Run all tests (integration + e2e)
    help          Show this help message

Examples:
    $0                      # Run integration tests
    $0 integration          # Run integration tests
    $0 e2e                  # Run real E2E tests (requires .env + inventory)
    $0 network              # Test device sync only
    $0 llm                  # Test LLM analysis only
    $0 all                  # Run everything

Cost Estimation:
    integration: \$0.00, ~2-5 seconds
    network:     \$0.00, ~10-60 seconds (depends on device count)
    llm:         \$0.05-\$0.20 per run
    e2e:         \$0.10-\$1.00 per run
    all:         \$0.10-\$1.20 per run

EOF
}

# Run tests based on command
run_tests() {
    case "$1" in
        integration|"")
            print_header "Running Integration Tests (Fast, Free)"
            uv run pytest tests/e2e/test_complete_e2e_validation.py -v -m "not e2e" --no-cov
            print_success "Integration tests completed"
            ;;
        
        e2e)
            print_header "Running Real E2E Tests (Slow, Expensive)"
            check_prerequisites "e2e"
            print_warning "This will consume LLM API tokens and take 30s-5min"
            uv run pytest tests/e2e/test_complete_e2e_validation.py -v -m e2e --no-cov
            print_success "E2E tests completed"
            ;;
        
        network)
            print_header "Running Network Device Tests"
            check_prerequisites "network"
            print_warning "This will connect to real devices"
            uv run pytest tests/e2e/ -v -m network --no-cov
            print_success "Network tests completed"
            ;;
        
        llm)
            print_header "Running LLM API Tests"
            check_prerequisites "llm"
            print_warning "This will consume LLM API tokens"
            uv run pytest tests/e2e/ -v -m llm --no-cov
            print_success "LLM tests completed"
            ;;
        
        all)
            print_header "Running All Tests (Integration + E2E)"
            check_prerequisites "e2e"
            print_warning "This will take several minutes and consume API tokens"
            uv run pytest tests/e2e/test_complete_e2e_validation.py -v --no-cov
            print_success "All tests completed"
            ;;
        
        help|--help|-h)
            show_usage
            exit 0
            ;;
        
        *)
            print_error "Unknown command: $1"
            echo ""
            show_usage
            exit 1
            ;;
    esac
}

# Main
main() {
    # Change to project root (scripts/ is one level down)
    cd "$(dirname "$0")/.."
    
    # Run tests
    run_tests "$1"
}

main "$@"
