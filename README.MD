# OLAV (NetAIChatOps)

<div align="center">

```
   ____  _        ___     __
  / __ \| |      / \ \   / /
 | |  | | |     / _ \ \ / / 
 | |  | | |    / ___ \ V /  
 | |__| | |___/ ___ \ | |   
  \____/|_____/_/   \_\|_|  
                            
  NetAIChatOps CLI
```

**LangGraph Workflows + SuzieQ + NETCONF/gNMI + NetBox**

[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2+-green.svg)](https://langchain-ai.github.io/langgraph/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

</div>

---

## 🚀 Quick Start

### 1. Environment Setup

```bash
# Install uv (Linux/Mac)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone repository
git clone <repo-url>
cd Olav

# Install dependencies
uv sync --dev

# Configure environment variables
cp .env.example .env
# Edit .env, required: LLM_API_KEY
```

### 2. Start Services

```bash
# Start core infrastructure services (PostgreSQL, OpenSearch)
docker-compose up -d

# With Redis cache (optional, for multi-instance deployments)
docker-compose --profile cache up -d

# With built-in NetBox
docker-compose --profile netbox up -d

# Full stack (all optional components)
docker-compose --profile full --profile netbox up -d
```

### 3. Initialize

```bash
# Check index status
uv run olav init status

# Initialize all infrastructure (PostgreSQL + all indexes)
uv run olav init all

# Or initialize specific components:
uv run olav init schema    # Schema indexes only (SuzieQ/OpenConfig/NetBox)
uv run olav init rag       # RAG indexes only (episodic memory, docs)
uv run olav init postgres  # PostgreSQL Checkpointer only

# Import devices from config/inventory.csv to NetBox
uv run olav init netbox
```

### 4. Client Authentication

```bash
# Get server Master Token (check docker logs)
docker-compose logs olav-server | grep "ACCESS TOKEN"

# Register client to get Session Token (recommended)
uv run olav register --name "my-laptop" --token "<master-token>" --server http://localhost:8001

# Verify connection and system health
uv run olav doctor
```

### 5. Start Using

```bash
# Interactive Dashboard (default)
uv run olav

# Lightweight REPL mode
uv run olav repl

# Single query
uv run olav -q "Query BGP status of R1"

# Expert mode (complex diagnostics)
uv run olav -E -q "Audit security config of all border routers"

# TUI dashboard with batch queries
uv run olav dashboard -q "query1" -q "query2"
```

### 6. Administration (Server-Side)

```bash
# Create session tokens for clients
uv run olav-admin token create --name "alice-laptop" --role operator

# List active sessions
uv run olav-admin token list

# Revoke a session
uv run olav-admin token revoke <client_id>

# Initialize databases
uv run olav-admin init
```

---

## 📋 CLI Command Reference

### Main Command

```bash
olav [OPTIONS] COMMAND [ARGS]...
```

| Option | Description |
|--------|-------------|
| `-q, --query TEXT` | Single query text |
| `--server TEXT` | API Server URL (default: http://localhost:8000) |
| `-S, --standard` | Standard mode (default, fast path) |
| `-E, --expert` | Expert mode (Deep Dive recursive diagnostics) |
| `-v, --verbose` | Verbose output |
| `--status` | Check system status |

### Subcommands

| Command | Description |
|---------|-------------|
| `init` | Initialize infrastructure and indexes |
| `register` | Register client to get Session Token |
| `doctor` | System health check (server, auth, components) |
| `query` | Execute single query |
| `dashboard` | Launch full-screen TUI dashboard |
| `repl` | Lightweight REPL mode |
| `session` | Manage authentication sessions |
| `inspect` | Network inspection commands |
| `report` | View inspection reports |
| `doc` | RAG document management |
| `config` | CLI configuration management |
| `version` | Version information (use --banner for ASCII art) |

### Init Commands

```bash
# Initialize all components (PostgreSQL + all indexes)
olav init all

# Initialize with force reset (delete and recreate indexes)
olav init all --force

# Initialize schema indexes only (preserves RAG data)
olav init schema
olav init schema --force    # Force reset

# Initialize RAG indexes only (preserves schema data)
olav init rag
olav init rag --force       # Force reset

# Initialize PostgreSQL Checkpointer
olav init postgres

# Import devices from config/inventory.csv to NetBox
olav init netbox
olav init netbox --force    # Force import even if devices exist

# Check current index status
olav init status
```

### Authentication Commands

```bash
# Register client
olav register --name "client-name" --token "<master-token>" --server <url>

# Check status
olav status --server <url>

# Session management
olav session clients   # List all clients (requires admin privileges)
olav session threads   # List conversation threads
olav session logout    # Logout current session
```

### Inspection Commands

```bash
# List inspection configurations
olav inspect list

# Run inspection (async)
olav inspect run <profile>

# Wait for completion
olav inspect run <profile> --wait

# Check job status
olav inspect status <job-id>
olav inspect jobs
```

### Report Commands

```bash
# List reports
olav report list

# View report
olav report show <report-id>

# Download report
olav report download <report-id> -o report.md
```

### Document Management

```bash
# List indexed documents
olav doc list

# Upload document
olav doc upload <file>

# Search documents
olav doc search "BGP configuration best practices"
```

---

## 🔐 Authentication System

OLAV uses a two-tier Token authentication mechanism:

### Token Types

| Token Type | Validity | Purpose | Acquisition |
|------------|----------|---------|-------------|
| **Master Token** | 24 hours | Admin operations, client registration | Server startup logs |
| **Session Token** | 7 days | Regular client operations | `olav register` |

### Configure Token Validity

Set in `.env` or environment variables:

```bash
# Master Token validity (hours)
TOKEN_MAX_AGE_HOURS=48

# Session Token validity (hours)
SESSION_TOKEN_MAX_AGE_HOURS=720  # 30 days
```

### Authentication Flow

```
┌─────────────┐     Master Token      ┌─────────────┐
│   Server    │ ◄──────────────────── │   Admin     │
│  Startup    │    (from logs)        │             │
└─────────────┘                       └─────────────┘
       │
       │ POST /auth/register
       ▼
┌─────────────┐     Session Token     ┌─────────────┐
│   OLAV      │ ────────────────────► │   Client    │
│   Server    │    (7 days valid)     │  ~/.olav/   │
└─────────────┘                       │ credentials │
       ▲                              └─────────────┘
       │
       │ Bearer Token (auto-loaded)
       │
┌─────────────┐
│ olav status │
│ olav query  │
│ olav inspect│
└─────────────┘
```

### Credential Storage

```bash
# Credentials auto-saved to
~/.olav/credentials

# Content format
OLAV_SESSION_TOKEN=xxx
OLAV_CLIENT_ID=xxx
OLAV_CLIENT_NAME=my-laptop
```

---

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        OLAV CLI (Thin Client)                    │
│  olav register | status | query | inspect | report | session    │
└──────────────────────────────┬──────────────────────────────────┘
                               │ HTTP/SSE (Bearer Token)
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                      OLAV API Server (FastAPI)                   │
│  /auth/* | /orchestrator/stream | /inspections/* | /reports/*  │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Workflow Orchestrator                         │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐             │
│  │   Query      │ │   Device     │ │   NetBox     │             │
│  │  Diagnostic  │ │  Execution   │ │  Management  │             │
│  │  Workflow    │ │  Workflow    │ │  Workflow    │             │
│  └──────────────┘ └──────────────┘ └──────────────┘             │
└──────────────────────────────┬──────────────────────────────────┘
                               │
          ┌────────────────────┼────────────────────┐
          ▼                    ▼                    ▼
    ┌──────────┐         ┌──────────┐         ┌──────────┐
    │  SuzieQ  │         │ NETCONF/ │         │  NetBox  │
    │ Parquet  │         │  gNMI    │         │   API    │
    └──────────┘         └──────────┘         └──────────┘
```

### Core Components

| Component | Tech Stack | Purpose |
|-----------|------------|---------|
| **CLI** | Typer + Rich | Command-line interface, TUI dashboard |
| **API Server** | FastAPI + LangServe | RESTful API, SSE streaming responses |
| **Orchestrator** | LangGraph | Workflow orchestration, intent classification |
| **State Store** | PostgreSQL | Checkpointer state persistence |
| **Schema Index** | OpenSearch | SuzieQ/OpenConfig Schema indexing |
| **Cache** | Redis (optional) | Distributed cache (fallback: in-memory) |

---

## ⚙️ Configuration Reference

### Environment Variables (.env)

```bash
# ============================================
# Required - LLM Configuration
# ============================================
LLM_API_KEY=sk-...                    # OpenAI API Key
LLM_PROVIDER=openai                   # openai | ollama | azure
LLM_MODEL_NAME=gpt-4-turbo            # Model name

# ============================================
# Optional - NetBox Configuration
# ============================================
NETBOX_URL=http://localhost:8000      # NetBox URL
NETBOX_TOKEN=your-token               # NetBox API Token

# ============================================
# Optional - Device Credentials
# ============================================
DEVICE_USERNAME=admin                 # SSH/NETCONF username
DEVICE_PASSWORD=password              # SSH/NETCONF password

# ============================================
# Required - OpenSearch Authentication
# ============================================
OPENSEARCH_USERNAME=admin             # Default username
OPENSEARCH_PASSWORD=OlavOS123!        # Change in production!
OPENSEARCH_VERIFY_CERTS=false         # Set true for production TLS

# ============================================
# Optional - Token Validity
# ============================================
TOKEN_MAX_AGE_HOURS=24                # Master Token (default 24 hours)
SESSION_TOKEN_MAX_AGE_HOURS=168       # Session Token (default 7 days)

# ============================================
# Optional - Infrastructure (Docker auto-configured)
# ============================================
# POSTGRES_URI=postgresql://olav:xxx@localhost:5432/olav
# OPENSEARCH_URL=http://localhost:19200
# REDIS_URL=redis://localhost:6379    # Optional: enables distributed cache
```

### Docker Compose Ports

| Service | Internal Port | External Port | Notes |
|---------|---------------|---------------|-------|
| olav-server | 8000 | 8001 | API Server |
| postgres | 5432 | 15432 | State persistence |
| opensearch | 9200 | 19200 | Schema index |
| redis | 6379 | 6379 | Optional (--profile cache) |
| netbox | 8080 | 8080 | Optional (--profile netbox) |

---

## 🔧 Development Guide

### Code Quality

```bash
# Format
uv run ruff format src/ tests/

# Lint + auto-fix
uv run ruff check src/ tests/ --fix

# Type checking
uv run mypy src/ --strict

# Run tests
uv run pytest -v

# Test coverage
uv run pytest --cov=src/olav --cov-report=html
```

### Add Dependencies

```bash
uv add langchain-openai          # Runtime dependency
uv add --dev pytest-asyncio      # Dev dependency
```

### Local API Server Startup

```bash
# Development mode (auto-reload)
uv run python -m olav.main serve --reload

# Or use LangGraph Studio
uv add langgraph-cli[inmem]
langgraph dev
# Access: https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024
```

---

## 📚 Documentation Index

| Document | Description |
|----------|-------------|
| [MULTI_CLIENT_AUTH_DESIGN.md](docs/MULTI_CLIENT_AUTH_DESIGN.md) | Multi-client authentication design |
| [ARCHITECTURE_EVALUATION.md](docs/ARCHITECTURE_EVALUATION.md) | Architecture evaluation report |
| [DOCKER_DEPLOYMENT.md](docs/DOCKER_DEPLOYMENT.md) | Docker deployment guide |
| [CHECKPOINTER_SETUP.md](docs/CHECKPOINTER_SETUP.md) | PostgreSQL Checkpointer configuration |
| [API_USAGE.md](docs/API_USAGE.md) | API usage guide |

---

## ❓ FAQ

### Q: How to get the Master Token?

```bash
docker-compose logs olav-server | grep "ACCESS TOKEN"
# Output: 🔑 ACCESS TOKEN: http://localhost:3100?token=xxx
```

### Q: What to do when Session Token expires?

```bash
# Re-register
uv run olav register --name "my-laptop" --token "<master-token>"
```

### Q: Windows platform reports ProactorEventLoop error?

OLAV handles this automatically. If issues persist, add at script beginning:
```python
import asyncio
asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
```

### Q: How to disable authentication (dev environment only)?

```bash
# .env
AUTH_DISABLED=true
```

---

## 📄 License

MIT License - See [LICENSE](LICENSE) for details.

---

<div align="center">

**Built with ❄️ by OLAV Team**

*NetAIChatOps - Making Network Operations Smarter*

</div>
