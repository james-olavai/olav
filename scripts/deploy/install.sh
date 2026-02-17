#!/bin/bash
#
# OLAV v2.0 Installation Script
# For fresh installation on new environments
#
# Usage: bash scripts/deploy/install.sh [--help] [--docker] [--skip-tests]
#

set -euo pipefail

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
INSTALL_DIR="${INSTALL_DIR:-.}"
BACKUP_DIR="${BACKUP_DIR:-.backup}"
LOG_FILE="${LOG_FILE:-${INSTALL_DIR}/install.log}"
DOCKER_MODE=false
SKIP_TESTS=false

# Logging functions
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
            --docker)
                DOCKER_MODE=true
                shift
                ;;
            --skip-tests)
                SKIP_TESTS=true
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
OLAV v2.0 Installation Script

Usage: bash scripts/deploy/install.sh [OPTIONS]

Options:
  --docker        Use Docker for installation (requires Docker to be installed)
  --skip-tests    Skip test suite after installation (not recommended)
  --help, -h      Show this help message

Examples:
  # Standard installation
  bash scripts/deploy/install.sh

  # Docker-based installation
  bash scripts/deploy/install.sh --docker

  # Skip tests after installation
  bash scripts/deploy/install.sh --skip-tests
EOF
}

# Check prerequisites
check_prerequisites() {
    log "🔍 Checking prerequisites..."
    
    # Check Python version
    if ! command -v python3 &> /dev/null; then
        log_error "Python 3 is not installed. Please install Python 3.11 or later."
        exit 1
    fi
    
    python_version=$(python3 --version | awk '{print $2}')
    log "  - Python version: $python_version"
    
    if ! python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"; then
        log_error "Python 3.11 or later is required. Current: $python_version"
        exit 1
    fi
    
    # Check pip/uv
    if command -v uv &> /dev/null; then
        log "  - Package manager: uv ($(uv --version))"
    elif command -v pip3 &> /dev/null; then
        log "  - Package manager: pip3"
    else
        log_error "Neither uv nor pip3 found. Please install one of them."
        exit 1
    fi
    
    # Check disk space (requirement: 1GB)
    available_space=$(df "$INSTALL_DIR" | tail -1 | awk '{print $4}')
    if [ "$available_space" -lt 1048576 ]; then  # 1GB in KB
        log_error "Insufficient disk space. Required: 1GB, Available: $(($available_space / 1024))MB"
        exit 1
    fi
    
    log_success "All prerequisites met"
}

# Create necessary directories
create_directories() {
    log "📁 Creating directories..."
    
    mkdir -p "$INSTALL_DIR/.olav/databases"
    mkdir -p "$INSTALL_DIR/.olav/skills/shared/tools"
    mkdir -p "$INSTALL_DIR/.olav/config"
    mkdir -p "$BACKUP_DIR"
    mkdir -p "$INSTALL_DIR/logs"
    
    log_success "Directories created"
}

# Install dependencies
install_dependencies() {
    log "📦 Installing dependencies..."
    
    cd "$INSTALL_DIR"
    
    if command -v uv &> /dev/null; then
        log "  - Using uv for dependency installation"
        uv pip install --no-cache-dir -e .
    else
        log "  - Using pip3 for dependency installation"
        pip3 install -e .
    fi
    
    log_success "Dependencies installed"
}

# Docker installation mode
docker_install() {
    log "🐳 Docker installation mode"
    
    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed. Please install Docker first."
        exit 1
    fi
    
    log "  - Building Docker image: olav:v2.0.0"
    docker build -t olav:v2.0.0 -f "$INSTALL_DIR/Dockerfile" "$INSTALL_DIR"
    
    log_success "Docker image built successfully"
    
    log "📝 Docker run example:"
    echo "  docker run -it \\
    -v \$PWD/.olav:/home/olav/.olav \\
    -e LLM_API_KEY='your-key' \\
    olav:v2.0.0 python -m olav ask 'your-query'"
}

# Initialize configuration
initialize_config() {
    log "⚙️  Initializing configuration..."
    
    # Copy environment template if not exists
    if [ ! -f "$INSTALL_DIR/.env" ]; then
        cp "$INSTALL_DIR/.env.production" "$INSTALL_DIR/.env"
        log_warning ".env created from template. Please edit with your credentials."
    fi
    
    log_success "Configuration initialized"
}

# Initialize database
initialize_database() {
    log "🗄️  Initializing database..."
    
    cd "$INSTALL_DIR"
    
    # Run database initialization
    python3 -c "
from src.olav.core.database import get_database, initialize_db
print('  - Initializing DuckDB schema...')
db = get_database()
initialize_db(db)
print('  - Database schema created')
"
    
    log_success "Database initialized"
}

# Run tests
run_tests() {
    if [ "$SKIP_TESTS" = true ]; then
        log_warning "Skipping tests (--skip-tests flag set)"
        return 0
    fi
    
    log "🧪 Running test suite..."
    
    cd "$INSTALL_DIR"
    
    # Run unit tests
    log "  - Running unit tests..."
    python3 -m pytest tests/unit/ -q --tb=short || {
        log_warning "Some unit tests failed, but continuing..."
    }
    
    # Run E2E tests
    log "  - Running E2E tests..."
    python3 -m pytest tests/e2e/ -q --tb=short || {
        log_warning "Some E2E tests failed, but continuing..."
    }
    
    log_success "Tests completed"
}

# Verify installation
verify_installation() {
    log "✅ Verifying installation..."
    
    cd "$INSTALL_DIR"
    
    # Check if main module can be imported
    if python3 -c "from src.olav.agents.agent import OLAVAgent; OLAVAgent()" 2>/dev/null; then
        log_success "OLAV Agent initialized successfully"
    else
        log_warning "Could not fully initialize agent (check LLM_API_KEY)"
    fi
    
    # Check core components
    python3 << 'PYTHON_EOF'
import sys
from pathlib import Path

checks = {
    "Database": "from src.olav.core.database import get_database",
    "Config": "from config.paths import DB_MAIN_PATH",
    "CLI": "from src.olav.cli.cli_main import main",
}

for name, import_stmt in checks.items():
    try:
        exec(import_stmt)
        print(f"  ✓ {name} module available")
    except ImportError as e:
        print(f"  ✗ {name} module failed: {e}")
        sys.exit(1)
PYTHON_EOF
    
    log_success "All installations verified"
}

# Print installation summary
print_summary() {
    cat << EOF

${GREEN}╔════════════════════════════════════════╗${NC}
${GREEN}║    OLAV v2.0 Installation Complete    ║${NC}
${GREEN}╚════════════════════════════════════════╝${NC}

📍 Installation Directory: $INSTALL_DIR
📋 Log File: $LOG_FILE

🚀 Next Steps:

1. Configure credentials:
   Edit .env file with your API keys and network credentials
   ${YELLOW}nano .env${NC}

2. Verify installation:
   ${YELLOW}bash scripts/deploy/verify.sh${NC}

3. Start using OLAV:
   ${YELLOW}python -m olav ask "your query here"${NC}

4. Interactive mode:
   ${YELLOW}python -m olav interactive${NC}

5. REST API server:
   ${YELLOW}python -m uvicorn src.olav.api.server:app --reload${NC}

📚 Documentation:
   - README.md
   - DEPLOYMENT_GUIDE.md
   - Troubleshooting: TROUBLESHOOTING.md

❓ Need help?
   Check the documentation or contact support.

EOF
}

# Main execution
main() {
    parse_args "$@"
    
    log "🚀 OLAV v2.0 Installation Starting..."
    log "Install Directory: $INSTALL_DIR"
    log "Log File: $LOG_FILE"
    
    check_prerequisites
    create_directories
    install_dependencies
    
    if [ "$DOCKER_MODE" = true ]; then
        docker_install
    fi
    
    initialize_config
    initialize_database
    run_tests
    verify_installation
    
    print_summary
    
    log_success "Installation completed successfully"
}

# Run main
main "$@"
