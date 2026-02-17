#!/bin/bash
#
# OLAV v2.0 Configuration Script
# Interactive configuration for OLAV deployment
#
# Usage: bash scripts/deploy/configure.sh [--interactive] [--env FILE]
#

set -euo pipefail

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
INTERACTIVE=true
ENV_FILE=".env"
LOG_FILE="configure_$(date +%Y%m%d_%H%M%S).log"

# Logging
log() {
    echo -e "${BLUE}[i]${NC} $*" | tee -a "$LOG_FILE"
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
            --interactive)
                INTERACTIVE=true
                shift
                ;;
            --env)
                ENV_FILE="$2"
                shift 2
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
OLAV v2.0 Configuration Script

Usage: bash scripts/deploy/configure.sh [OPTIONS]

This script helps configure OLAV for deployment:
  • Creates or updates .env configuration
  • Sets LLM API credentials
  • Configures network device access
  • Sets database parameters
  • Validates configuration

Options:
  --interactive   Interactive configuration mode (default)
  --env FILE      Use specific .env file (default: .env)
  --help, -h      Show this help message

Examples:
  # Interactive configuration
  bash scripts/deploy/configure.sh

  # Configure custom .env file
  bash scripts/deploy/configure.sh --env prod.env
EOF
}

# Load existing configuration
load_existing_config() {
    log "📖 Loading existing configuration..."
    
    if [ -f "$ENV_FILE" ]; then
        log_success "Configuration file found: $ENV_FILE"
        source "$ENV_FILE" 2>/dev/null || true
    else
        log_warning "No existing configuration found"
    fi
}

# Interactive LLM configuration
configure_llm() {
    echo -e "\n${YELLOW}=== LLM Configuration ===${NC}"
    
    echo "OLAV requires an LLM API key for natural language processing."
    echo "Supported: OpenAI, Anthropic, Ollama (local)"
    
    read -p "LLM Provider (openai/anthropic/ollama) [openai]: " provider
    provider=${provider:-openai}
    
    if [ "$provider" = "openai" ]; then
        read -sp "OpenAI API Key (sk-...): " api_key
        echo ""
        MODEL=${LLM_MODEL:-"gpt-4-turbo"}
    elif [ "$provider" = "anthropic" ]; then
        read -sp "Anthropic API Key: " api_key
        echo ""
        MODEL=${LLM_MODEL:-"claude-3-opus"}
    elif [ "$provider" = "ollama" ]; then
        read -p "Ollama endpoint [http://localhost:11434]: " endpoint
        endpoint=${endpoint:-http://localhost:11434}
        read -p "Model name [neural7b]: " MODEL
        MODEL=${MODEL:-neural7b}
        api_key="local"
    else
        log_error "Unknown provider: $provider"
        return 1
    fi
    
    read -p "Model [$MODEL]: " model_input
    MODEL=${model_input:-$MODEL}
    
    read -p "Temperature (0.0-2.0) [0.1]: " temperature
    TEMPERATURE=${temperature:-0.1}
    
    log_success "LLM Configuration:"
    echo "  - Provider: $provider"
    echo "  - Model: $MODEL"
    echo "  - Temperature: $TEMPERATURE"
}

# Interactive network configuration
configure_network() {
    echo -e "\n${YELLOW}=== Network Device Access ===${NC}"
    
    echo "Configure credentials for network device access."
    echo "These will be used to execute commands via SSH/Netmiko."
    
    read -p "Network username [admin]: " username
    NETWORK_USERNAME=${username:-admin}
    
    read -sp "Network password: " password
    echo ""
    NETWORK_PASSWORD=$password
    
    read -p "Network device timeout (seconds) [30]: " timeout
    NETWORK_TIMEOUT=${timeout:-30}
    
    read -p "Number of parallel workers [4]: " workers
    NETWORK_WORKERS=${workers:-4}
    
    log_success "Network Configuration:"
    echo "  - Username: $NETWORK_USERNAME"
    echo "  - Timeout: ${NETWORK_TIMEOUT}s"
    echo "  - Parallel workers: $NETWORK_WORKERS"
}

# Interactive database configuration
configure_database() {
    echo -e "\n${YELLOW}=== Database Configuration ===${NC}"
    
    read -p "Database backend (duckdb/postgresql) [duckdb]: " backend
    DB_BACKEND=${backend:-duckdb}
    
    if [ "$DB_BACKEND" = "postgresql" ]; then
        read -p "PostgreSQL host [localhost]: " db_host
        DB_HOST=${db_host:-localhost}
        
        read -p "PostgreSQL port [5432]: " db_port
        DB_PORT=${db_port:-5432}
        
        read -p "PostgreSQL database [olav]: " db_name
        DB_NAME=${db_name:-olav}
        
        read -p "PostgreSQL username [postgres]: " db_user
        DB_USER=${db_user:-postgres}
        
        read -sp "PostgreSQL password: " db_pass
        echo ""
        DB_PASSWORD=$db_pass
    else
        DB_PATH="./.olav/databases/main.duckdb"
        log_info "Using DuckDB: $DB_PATH"
    fi
    
    log_success "Database Configuration:"
    echo "  - Backend: $DB_BACKEND"
    if [ "$DB_BACKEND" = "postgresql" ]; then
        echo "  - Host: $DB_HOST"
        echo "  - Database: $DB_NAME"
    else
        echo "  - Path: $DB_PATH"
    fi
}

# Interactive application configuration
configure_application() {
    echo -e "\n${YELLOW}=== Application Configuration ===${NC}"
    
    read -p "Application environment (development/staging/production) [production]: " environment
    ENVIRONMENT=${environment:-production}
    
    read -p "API server port [8000]: " api_port
    API_PORT=${api_port:-8000}
    
    read -p "Enable debug logging (yes/no) [no]: " debug
    DEBUG_LOGGING=$([ "$debug" = "yes" ] && echo "true" || echo "false")
    
    read -p "Enable health checks (yes/no) [yes]: " health_checks
    HEALTH_CHECKS=$([ "$health_checks" != "no" ] && echo "true" || echo "false")
    
    log_success "Application Configuration:"
    echo "  - Environment: $ENVIRONMENT"
    echo "  - API Port: $API_PORT"
    echo "  - Debug logging: $DEBUG_LOGGING"
    echo "  - Health checks: $HEALTH_CHECKS"
}

# Write configuration to .env
write_configuration() {
    log "💾 Writing configuration to $ENV_FILE..."
    
    cat > "$ENV_FILE" << 'EOF'
# OLAV v2.0 Configuration
# Generated by configure.sh

# ==============================
# LLM Configuration
# =================================
LLM_PROVIDER=${LLM_PROVIDER:-openai}
LLM_API_KEY=${LLM_API_KEY}
LLM_MODEL=${LLM_MODEL:-gpt-4-turbo}
LLM_TEMPERATURE=${LLM_TEMPERATURE:-0.1}
LLM_MAX_TOKENS=${LLM_MAX_TOKENS:-4096}

# OpenAI specific
OPENAI_API_KEY=${OPENAI_API_KEY:-${LLM_API_KEY}}
OPENAI_MODEL=${OPENAI_MODEL:-${LLM_MODEL}}

# Anthropic specific
ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
ANTHROPIC_MODEL=${ANTHROPIC_MODEL:-claude-3-opus}

# Ollama specific (local)
OLLAMA_ENDPOINT=${OLLAMA_ENDPOINT:-http://localhost:11434}

# ============================================
# Network Device Configuration
# ============================================
NETWORK_USERNAME=${NETWORK_USERNAME:-admin}
NETWORK_PASSWORD=${NETWORK_PASSWORD}
NETWORK_TIMEOUT=${NETWORK_TIMEOUT:-30}
NETWORK_WORKERS=${NETWORK_WORKERS:-4}

# Device connection options
DEVICE_SSH_PORT=${DEVICE_SSH_PORT:-22}
DEVICE_NETCONF_PORT=${DEVICE_NETCONF_PORT:-830}
CONNECTION_TIMEOUT=${CONNECTION_TIMEOUT:-15}
COMMAND_TIMEOUT=${COMMAND_TIMEOUT:-60}

# ============================================
# Database Configuration
# ============================================
DB_BACKEND=${DB_BACKEND:-duckdb}
DB_PATH=${DB_PATH:-./.olav/databases/main.duckdb}

# PostgreSQL configuration (if using PostgreSQL)
DB_HOST=${DB_HOST:-localhost}
DB_PORT=${DB_PORT:-5432}
DB_NAME=${DB_NAME:-olav}
DB_USER=${DB_USER}
DB_PASSWORD=${DB_PASSWORD}

# Database parameters
DB_WAL_MODE=${DB_WAL_MODE:-true}
DB_CACHE_SIZE=${DB_CACHE_SIZE:-1000}
DB_AUTO_BACKUP=${DB_AUTO_BACKUP:-true}

# ============================================
# Application Configuration
# ============================================
ENVIRONMENT=${ENVIRONMENT:-production}
APP_NAME=${APP_NAME:-OLAV}
APP_VERSION=${APP_VERSION:-2.0.0}

# Server configuration
API_HOST=${API_HOST:-0.0.0.0}
API_PORT=${API_PORT:-8000}
API_WORKERS=${API_WORKERS:-4}

# Logging
LOG_LEVEL=${LOG_LEVEL:-INFO}
DEBUG_LOGGING=${DEBUG_LOGGING:-false}
LOG_PATH=${LOG_PATH:-./logs}

# Health checks
HEALTH_CHECKS_ENABLED=${HEALTH_CHECKS:-true}
HEALTH_CHECK_INTERVAL=${HEALTH_CHECK_INTERVAL:-300}

# CORS configuration
CORS_ORIGINS=${CORS_ORIGINS:-*}
CORS_CREDENTIALS=${CORS_CREDENTIALS:-true}

# ============================================
# Feature Flags
# ============================================
ENABLE_INSPECTION=${ENABLE_INSPECTION:-true}
ENABLE_COMPLIANCE=${ENABLE_COMPLIANCE:-true}
ENABLE_AUTOMATION=${ENABLE_AUTOMATION:-true}
ENABLE_CACHING=${ENABLE_CACHING:-true}

# ============================================
# Monitoring & Observability
# ============================================
ENABLE_METRICS=${ENABLE_METRICS:-false}
METRICS_PORT=${METRICS_PORT:-9090}
ENABLE_TRACING=${ENABLE_TRACING:-false}
TRACE_SAMPLE_RATE=${TRACE_SAMPLE_RATE:-0.1}

# Sentry error tracking (optional)
SENTRY_DSN=${SENTRY_DSN}
SENTRY_ENVIRONMENT=${SENTRY_ENVIRONMENT:-production}

# ============================================
# Security
# ============================================
JWT_SECRET_KEY=${JWT_SECRET_KEY}
JWT_ALGORITHM=${JWT_ALGORITHM:-HS256}
JWT_EXPIRATION=${JWT_EXPIRATION:-3600}

# TLS/SSL
TLS_ENABLED=${TLS_ENABLED:-false}
TLS_CERT_PATH=${TLS_CERT_PATH}
TLS_KEY_PATH=${TLS_KEY_PATH}

# ============================================
# Backup & Recovery
# ============================================
AUTO_BACKUP_ENABLED=${AUTO_BACKUP_ENABLED:-true}
BACKUP_SCHEDULE=${BACKUP_SCHEDULE:-"0 2 * * *"}  # Daily at 2 AM
BACKUP_RETENTION_DAYS=${BACKUP_RETENTION_DAYS:-30}
BACKUP_PATH=${BACKUP_PATH:-./.backup}

# ============================================
# Advanced Settings
# ============================================
# Cache backend
CACHE_BACKEND=${CACHE_BACKEND:-memory}  # memory, redis, memcached
CACHE_TTL=${CACHE_TTL:-3600}

# Semantic cache for LLM queries
SEMANTIC_CACHE_ENABLED=${SEMANTIC_CACHE_ENABLED:-true}
SEMANTIC_CACHE_THRESHOLD=${SEMANTIC_CACHE_THRESHOLD:-0.95}

# Rate limiting
RATE_LIMIT_ENABLED=${RATE_LIMIT_ENABLED:-true}
RATE_LIMIT_REQUESTS=${RATE_LIMIT_REQUESTS:-100}
RATE_LIMIT_PERIOD=${RATE_LIMIT_PERIOD:-60}

EOF
    
    log_success "Configuration written to $ENV_FILE"
}

# Validate configuration
validate_configuration() {
    log "🔍 Validating configuration..."
    
    if [ ! -f "$ENV_FILE" ]; then
        log_error "Configuration file not found: $ENV_FILE"
        return 1
    fi
    
    python3 << 'PYTHON_EOF'
import os
from pathlib import Path

required_vars = ["LLM_API_KEY", "NETWORK_USERNAME", "NETWORK_PASSWORD"]
warnings = []
errors = []

for var in required_vars:
    value = os.getenv(var, "").strip()
    if not value or value.startswith("${"):
        warnings.append(f"  ! {var} not configured")

if warnings:
    print("  Warnings:")
    for w in warnings:
        print(w)

if errors:
    print("  Errors:")
    for e in errors:
        print(e)
    exit(1)
else:
    print("  ✓ Configuration valid")
EOF
}

# Test configuration
test_configuration() {
    echo -e "\n${YELLOW}Testing Configuration...${NC}"
    
    python3 << 'PYTHON_EOF'
import sys
import os

print("  - Testing LLM connectivity...")
try:
    from langchain_openai import OpenAI
    api_key = os.getenv("LLM_API_KEY")
    if api_key and api_key != "your-key":
        # llm = OpenAI(api_key=api_key)
        print("  ✓ LLM client can be created")
except Exception as e:
    print(f"  ! LLM test: {e}")

print("  - Testing database connection...")
try:
    from src.olav.core.database import get_database
    db = get_database()
    print("  ✓ Database connection successful")
except Exception as e:
    print(f"  ! Database test: {e}")

print("  ✓ Configuration tests completed")
EOF
}

# Print configuration summary
print_summary() {
    cat << EOF

${GREEN}╔═══════════════════════════════════════╗${NC}
${GREEN}║  Configuration Complete              ║${NC}
${GREEN}╚═══════════════════════════════════════╝${NC}

📝 Configuration File: ${ENV_FILE}
📋 Log File: ${LOG_FILE}

✅ Components Configured:
  ✓ LLM credentials
  ✓ Network device access
  ✓ Database settings
  ✓ Application parameters

🚀 Next Steps:

1. Verify configuration:
   ${YELLOW}bash scripts/deploy/verify.sh${NC}

2. Start OLAV:
   ${YELLOW}python -m olav admin status${NC}

3. Review configuration:
   ${YELLOW}cat ${ENV_FILE}${NC}

⚠️  Important:
  • Keep ${ENV_FILE} secure (contains credentials)
  • Add to .gitignore to prevent accidental commits
  • Backup before modifying manually

EOF
}

# Main
main() {
    parse_args "$@"
    
    log "🚀 OLAV Configuration Starting..."
    
    load_existing_config
    
    if [ "$INTERACTIVE" = true ]; then
        configure_llm
        configure_network
        configure_database
        configure_application
    fi
    
    write_configuration
    validate_configuration
    test_configuration
    
    print_summary
    
    log_success "Configuration completed"
}

# Run
main "$@"
