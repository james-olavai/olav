# OLAV Developer Documentation Index

**Version**: v1.0.0  
**Last Updated**: 2026-02-08  
**Target Audience**: OLAV Developers & Contributors

---

## 🚀 Quick Navigation

### For New Developers
1. **[Quick Start for Developers](reference/QUICK_START_DEVELOPER.md)** ✅ - Get started in 5 minutes
2. **[Architecture Overview](reference/ARCHITECTURE.md)** ✅ - Understand the system design
3. **[Configuration Reference](reference/CONFIGURATION_REFERENCE.md)** ✅ - All config files explained

### For Feature Development
4. **[Sub-Agent Development Guide](reference/SUB_AGENT_DEVELOPMENT_GUIDE.md)** ✅ - Build new agents (Python implementation)
5. **[Skill Authoring Guide](reference/SKILL_AUTHORING_GUIDE.md)** ✅ - Write SKILL.md files (configuration)
6. **[Tool Development Guide](#tool-development-guide)** ⚠️ *TODO* - Create tool functions
7. **[Database Guide](#database-guide)** ⚠️ *TODO* - Work with DuckDB

### For Maintenance & Operations
8. **[Testing Guide](reference/TESTING_QUICK_REFERENCE.md)** ✅ - Write and run tests
9. **[Troubleshooting Guide](#troubleshooting)** ⚠️ *TODO* - Debug common issues
10. **[Deployment Guide](#deployment)** ⚠️ *TODO* - Production deployment

### For Contributors
11. **[Contributing Guidelines](#contributing)** ⚠️ *TODO* - Code standards & PR workflow
12. **[API Reference](#api-reference)** ⚠️ *TODO* - Core APIs documentation

---

## 📚 Documentation Status

| Document | Status | Priority | Description |
|----------|--------|----------|-------------|
| **DEVELOPER_INDEX.md** | ✅ Current | P0 | This file - documentation hub |
| **[QUICK_START_DEVELOPER.md](reference/QUICK_START_DEVELOPER.md)** | ✅ Complete | P0 | 5-minute developer onboarding |
| **[ARCHITECTURE.md](reference/ARCHITECTURE.md)** | ✅ Complete | P0 | System architecture overview |
| **[CONFIGURATION_REFERENCE.md](reference/CONFIGURATION_REFERENCE.md)** | ✅ Complete | P0 | All config paths and files |
| **[SUB_AGENT_DEVELOPMENT_GUIDE.md](reference/SUB_AGENT_DEVELOPMENT_GUIDE.md)** | ✅ Complete | P0 | Sub-Agent implementation patterns |
| **[SKILL_AUTHORING_GUIDE.md](reference/SKILL_AUTHORING_GUIDE.md)** | ✅ Complete | P0 | SKILL.md writing best practices |
| **[TESTING_QUICK_REFERENCE.md](reference/TESTING_QUICK_REFERENCE.md)** | ✅ Complete | P1 | Testing standards and examples |
| **[TOOL_DEVELOPMENT_GUIDE.md](reference/TOOL_DEVELOPMENT_GUIDE.md)** | ✅ Complete | P1 | How to create tool functions |
| **[DATABASE_GUIDE.md](reference/DATABASE_GUIDE.md)** | ✅ Complete | P1 | DuckDB integration guide |
| **[CONTRIBUTING.md](reference/CONTRIBUTING.md)** | ✅ Complete | P1 | Code style & PR guidelines |
| **[INTELLIGENT_ROUTING_v0.11.4.md](reference/INTELLIGENT_ROUTING_v0.11.4.md)** | ✅ Complete | P0 | LLM-based query routing |
| **[EXPERT_HALLUCINATION_FIX_v0.11.4.1.md](reference/EXPERT_HALLUCINATION_FIX_v0.11.4.1.md)** | ✅ Complete | P0 | Data validation prevents Expert hallucination |
| **TROUBLESHOOTING.md** | ⚠️ TODO | P2 | Common issues & solutions |
| **DEPLOYMENT.md** | ⚠️ TODO | P2 | Production deployment guide |
| **API_REFERENCE.md** | ⚠️ TODO | P2 | Core API documentation |

**Legend**: ✅ Complete | ⚠️ TODO | 🔄 In Progress

---

## 📖 Detailed Guide

### <a name="quick-start-developer"></a>1. Quick Start for Developers ✅

**File**: `docs/reference/QUICK_START_DEVELOPER.md`  
**Status**: ✅ Complete  
**Priority**: P0 (Critical)

**Content Includes**:
- ✅ Prerequisites (Python, uv, Git)
- ✅ Clone and setup development environment
- ✅ Run first query
- ✅ Development workflow (edit → test → commit)
- ✅ Key directories overview
- ✅ Common development tasks
- ✅ Debugging tips
- ✅ Quick reference commands

**Target**: New developers productive in 5 minutes.

---

### <a name="architecture"></a>2. Architecture Overview ✅

**File**: `docs/reference/ARCHITECTURE.md`  
**Status**: ✅ Complete  
**Priority**: P0 (Critical)

**Content Includes**:
- ✅ System architecture diagram
- ✅ Component hierarchy (Orchestrator → SubAgents → Tools)
- ✅ Data flow diagrams
- ✅ DeepAgents integration architecture
- ✅ Caching layers (Semantic → LLM → App → Full)
- ✅ Backend architecture (CompositeBackend, FilesystemBackend)
- ✅ Database architecture (DuckDB multi-file strategy)
- ✅ Skill-Centric vs Code-Centric design
- ✅ Decision trees (when to use which agent)

**Target**: Developers understand how components interact.

---

### <a name="configuration-reference"></a>3. Configuration Reference ✅

**File**: `docs/reference/CONFIGURATION_REFERENCE.md`  
**Status**: ✅ Complete  
**Priority**: P0 (Critical)

**Content Includes**:
- ✅ Application structure (directory tree)
- ✅ Environment variables (.env)
- ✅ .olav/OLAV.md (SubAgent registry)
- ✅ .olav/skills/*/SKILL.md (Skill configs)
- ✅ .olav/settings.json (User overrides)
- ✅ config/settings.py (Application defaults)
- ✅ config/paths.py (Path constants)
- ✅ Database configuration
- ✅ Tool registration
- ✅ Cache configuration
- ✅ Network configuration (Nornir)
- ✅ Logging configuration
- ✅ Security configuration
- ✅ Configuration checklist

**Target**: Developers find any configuration option instantly.

---

### 4. Sub-Agent Development Guide ✅

---

### 4. Sub-Agent Development Guide ✅

**File**: [SUB_AGENT_DEVELOPMENT_GUIDE.md](reference/SUB_AGENT_DEVELOPMENT_GUIDE.md)  
**Status**: ✅ Complete  
**Last Updated**: 2026-02-08

**Contents**:
- Part 1: Configuration Architecture (OLAV.md + SKILL.md)
- Part 2: SubAgent Implementation Patterns (3 patterns)
- Part 3: Orchestrator Integration
- Part 4: Caching Strategy (4 layers)
- Part 5: Third-Party LLM Configuration
- Part 6: Complete Example (Security SubAgent)
- Part 7: Testing Guidelines
- Part 8: Deployment Checklist
- Part 9: Advanced Patterns

**Use Cases**:
- ✅ Create a new SubAgent
- ✅ Implement ReAct/Plan modes
- ✅ Configure caching
- ✅ Integrate with CompositeBackend

---

### 5. Skill Authoring Guide ✅

**File**: [SKILL_AUTHORING_GUIDE.md](reference/SKILL_AUTHORING_GUIDE.md)  
**Status**: ✅ Complete  
**Last Updated**: 2026-02-08

**Contents**:
- Part 1: Architecture & Design
- Part 2: YAML Frontmatter Requirements
- Part 3: Skill Structure & Progressive Disclosure
- Part 4: Writing Effective SKILL.md Body
- Part 5: Tools & Code in Skills
- Part 6: Workflows & Feedback Loops
- Part 7: OLAV-Specific Patterns
- Part 8: Testing & Iteration
- Part 9-13: Examples, Anti-Patterns, Resources

**Use Cases**:
- ✅ Write a new SKILL.md
- ✅ Optimize system prompts
- ✅ Implement progressive disclosure
- ✅ Configure intent mapping

---

### <a name="tool-development-guide"></a>6. Tool Development Guide ✅

**File**: [TOOL_DEVELOPMENT_GUIDE.md](reference/TOOL_DEVELOPMENT_GUIDE.md)  
**Status**: ✅ Complete  
**Last Updated**: 2026-02-08
**Priority**: P1 (High)

**Content Includes**:

#### Tool Design Principles
- ✅ When to create a new tool vs. extend existing
- ✅ Naming conventions (verb-noun pattern: `query_database`, `inspect_schema`)
- ✅ Function signatures (type hints, async support)
- ✅ Error handling patterns
- ✅ Logging best practices

#### Tool Registration
- ✅ Register in SKILL.md (`tools` section)
- ✅ Dynamic loading via SkillAdapter

#### Tool Categories
- ✅ **Data Tools**: query_database, inspect_schema, discover_data
- ✅ **Network Tools**: execute_command, test_connectivity
- ✅ **Analysis Tools**: analyze_topology, expand_scope_by_role
- ✅ **Export Tools**: format_and_export, save_to_csv

#### Example: Create a New Tool
```python
# src/olav/tools/my_category.py
"""My tool category description."""

import logging
from typing import Any

logger = logging.getLogger(__name__)

async def my_tool_function(
    param1: str,
    param2: int,
) -> dict[str, Any]:
    """Tool function description.
    
    Args:
        param1: Parameter description
        param2: Parameter description
    
    Returns:
        Dictionary with results
    
    Raises:
        ValueError: When validation fails
    """
    # Implementation
    logger.info(f"Executing my_tool with {param1}")
    return {"status": "success", "result": ...}
```

#### Tool Testing
- ✅ Unit tests for tool logic
- ✅ Integration tests with agents
- ✅ E2E tests for real scenarios

**Use Cases**:
- ✅ Create new tool functions
- ✅ Register tools in SKILL.md
- ✅ Test tools with agents

---

### <a name="database-guide"></a>7. Database Guide ✅

**File**: [DATABASE_GUIDE.md](reference/DATABASE_GUIDE.md)  
**Status**: ✅ Complete  
**Last Updated**: 2026-02-08
**Priority**: P1 (High)

**Content Includes**:

#### DuckDB Architecture in OLAV

**Database Files**:
```
.olav/db/
├── main.duckdb         # Device metadata (devices table)
├── olav.duckdb         # CLI outputs (raw_outputs, device_capabilities)
└── snapshots.duckdb    # Query cache
```

**Unified Connection** (Critical):
```python
# Automatic cross-database access via unified connection
from olav.lib.data_gateway import get_gateway

gateway = get_gateway()
conn = gateway._create_unified_connection()

# Can query across all databases
result = conn.execute("""
    SELECT d.hostname, r.output 
    FROM devices d 
    JOIN raw_outputs r ON d.hostname = r.device
""").fetchdf()
```

#### Schema Discovery Pattern
- ✅ Never hardcode table names
- ✅ Always use `inspect_schema()` first
- ✅ Dynamic SQL generation

#### Adding New Tables
- ✅ Table design principles
- ✅ Which database file to use (routing logic)
- ✅ Schema migration strategy
- ✅ Indexing best practices

#### Query Optimization
- ✅ Use projections (SELECT specific columns)
- ✅ Avoid SELECT * in production
- ✅ Leverage DuckDB's columnar storage
- ✅ Parquet for large datasets

**Use Cases**:
- ✅ Work with unified database connection
- ✅ Query across multiple databases
- ✅ Add new tables to appropriate database
- ✅ Optimize query performance

---

### 8. Testing Guide ✅

**File**: [TESTING_QUICK_REFERENCE.md](reference/TESTING_QUICK_REFERENCE.md)  
**Status**: ✅ Complete

**Contents**:
- Real E2E testing standards (not mocks)
- Test utilities (CLICommandTracker, DatabaseAccessMonitor)
- Writing new tests
- Running tests

**Use Cases**:
- ✅ Write E2E tests for new features
- ✅ Monitor side effects (CLI, DB access)
- ✅ Validate user workflows

---

### <a name="troubleshooting"></a>9. Troubleshooting Guide ⚠️ TODO

**File**: `docs/TROUBLESHOOTING.md`  
**Status**: ⚠️ Needs Creation  
**Priority**: P2 (Medium)

**Proposed Content**:

#### Common Issues

**Issue 1: LLM API Connection Fails**
- Symptom: `ConnectionError: Could not connect to LLM API`
- Cause: Missing/incorrect API key or base URL
- Solution:
  ```bash
  # Check .env
  cat .env | grep LLM_
  
  # Verify environment variables are set
  python -c "import os; print(os.getenv('OPENAI_API_KEY'))"
  ```

**Issue 2: Database Table Not Found**
- Symptom: `Table 'xxx' not found`
- Cause: Hardcoded table name, schema changed
- Solution: Use `inspect_schema()` for dynamic discovery

**Issue 3: Cache Not Working**
- Symptom: Queries are slow despite caching
- Solution: Check cache configuration in SKILL.md

**Issue 4: Tool Not Found by Agent**
- Symptom: `Tool 'xxx' not registered`
- Solution: Check SKILL.md `tools` section

#### Debug Mode
```bash
# Enable verbose logging
export OLAV_LOG_LEVEL=DEBUG
uv run olav ask "query"

# Check logs
tail -f logs/olav.log
```

#### Performance Profiling
- [ ] Using cProfile
- [ ] Cache hit rate analysis
- [ ] LLM token usage tracking

---

### <a name="deployment"></a>10. Deployment Guide ⚠️ TODO

**File**: `docs/DEPLOYMENT.md`  
**Status**: ⚠️ Needs Creation  
**Priority**: P2 (Medium)

**Proposed Content**:

#### Production Checklist
- [ ] Environment variables configured (`.env`)
- [ ] Nornir inventory file prepared
- [ ] Database files initialized
- [ ] API keys secured (not in Git)
- [ ] Logging configured
- [ ] Health checks enabled

#### Docker Deployment (Optional)
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install uv && uv sync --frozen
CMD ["uv", "run", "olav"]
```

#### Systemd Service (Linux)
```ini
[Unit]
Description=OLAV Network AI Assistant
After=network.target

[Service]
Type=simple
User=olav
WorkingDirectory=/opt/olav
ExecStart=/usr/local/bin/uv run olav
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

#### Security Best Practices
- [ ] Never commit `.env` files
- [ ] Use environment-specific configs
- [ ] Rotate API keys regularly
- [ ] Limit database file permissions

---

### <a name="advanced-features"></a>11. Advanced Features & Improvements

#### Intelligent Query Routing (v0.11.4+)

**File**: [INTELLIGENT_ROUTING_v0.11.4.md](reference/INTELLIGENT_ROUTING_v0.11.4.md)  
**Status**: ✅ Complete  
**Last Updated**: 2026-02-09  
**Priority**: P0 (Routing System)

**Content**:
- Three-layer routing architecture (Score → Route → Escalate)
- LLM-based complexity scoring (not keyword matching)
- QueryComplexityScorer class for dynamic routing
- QueryEscalationMarker for runtime escalation
- Expert Agent automatic detection and escalation
- Routing examples, troubleshooting, testing

**Use Cases**:
- ✅ Understand how queries are routed between agents
- ✅ Implement dynamic complexity scoring
- ✅ Debug routing decisions

---

#### Expert Agent Hallucination Fix (v0.11.4.1)

**File**: [EXPERT_HALLUCINATION_FIX_v0.11.4.1.md](reference/EXPERT_HALLUCINATION_FIX_v0.11.4.1.md)  
**Status**: ✅ Complete  
**Last Updated**: 2026-02-10  
**Priority**: P0 (Data Quality)

**Core Issue**:
- Expert Agent was hallucinating answers when database lacked required data
- Example: "interface errors analysis" when interfaces table doesn't exist
- Root cause: SKILL.md used "Simulating..." language that triggered fabrication

**Solution (v0.11.4.1)**:
1. **Enhanced Expert SKILL.md**
   - Added CRITICAL RULE: DATA-DRIVEN ANALYSIS ONLY
   - Added STEP 0: DATA VALIDATION (Mandatory)
   - Modified Hypothesis/Validation/Root Cause sections
   - NO fabrication, NO "Simulating" language

2. **New SchemaDataValidator Class**
   - `has_sufficient_data_for_expert()` checks schema before analysis
   - Returns missing_data list and recommendations
   - Located in `src/olav/core/query_confidence.py`

3. **Orchestrator Phase 0.5**
   - Schema validation before Expert routing
   - Early exit if data insufficient
   - Honest error messages instead of hallucination

**Test Results**: ✅ All 4 tests passing
- Expert refuses analysis without data ✅
- SKILL.md contains data validation ✅
- SchemaDataValidator properly integrated ✅
- Simple queries unaffected ✅

**Use Cases**:
- ✅ Understand Expert Agent limitations
- ✅ Debug hallucination issues
- ✅ Implement data-driven validation for other agents

---

### <a name="contributing"></a>12. Contributing Guidelines ✅

**File**: [CONTRIBUTING.md](reference/CONTRIBUTING.md)  
**Status**: ✅ Complete  
**Last Updated**: 2026-02-08
**Priority**: P1 (High)

**Content Includes**:

#### Code Standards

**Python Style**:
- ✅ Follow PEP 8
- ✅ Type hints required
- ✅ Docstrings required (Google format)

**Linting**:
```bash
# Before committing
uv run ruff check src/ --fix
uv run ruff format src/
uv run pyright src/
```

#### Git Workflow

**Branch Naming**:
- Feature: `feature/add-security-agent`
- Bugfix: `fix/cache-key-collision`
- Docs: `docs/update-deployment-guide`

**Commit Messages** (Conventional Commits):
```
<type>(<scope>): <subject>

<body>

<footer>
```

Examples:
- `feat(agent): add security audit SubAgent`
- `fix(cache): resolve cache key collision issue`
- `docs(guide): update tool development guide`

#### Pull Request Process
✅ Complete workflow documented:
1. Fork repository
2. Create feature branch
3. Make changes + tests
4. Run linting
5. Submit PR with description
6. Address review comments
7. Squash and merge

#### Testing Requirements
- ✅ All new features must have tests
- ✅ Tests must pass: `uv run pytest tests/`
- ✅ E2E tests for user-facing features

**Use Cases**:
- ✅ Code style and formatting guidelines
- ✅ Git workflow and commit messages
- ✅ Pull request process
- ✅ Testing requirements

---

### <a name="api-reference"></a>13. API Reference ⚠️ TODO

**File**: `docs/API_REFERENCE.md`  
**Status**: ⚠️ Needs Creation  
**Priority**: P2 (Medium)

**Proposed Content**:

#### Core APIs

**Orchestrator API**:
```python
from olav.agents.orchestrator import orchestrate_query

result = await orchestrate_query(
    user_query="show all BGP neighbors",
    user_id="admin",
    thread_id="session_001"
)
```

**Query Agent API**:
```python
from olav.agents.query_agent import QueryAgent

agent = QueryAgent(enable_summarization=False)
result = await agent.ainvoke({
    "messages": ["list all devices"]
})
```

**Data Gateway API**:
```python
from olav.lib.data_gateway import get_gateway

gateway = get_gateway()
df = gateway.query("SELECT * FROM devices")
```

**Skill Loader API**:
```python
from olav.core.skill_loader import get_skill_loader

loader = get_skill_loader()
skill = loader.get_skill("network-query")
```

#### Tool APIs
- [ ] query_database
- [ ] inspect_schema
- [ ] execute_command
- [ ] analyze_topology

---

## 🗂️ Documentation Organization

### Current Structure
```
docs/
├── DEVELOPER_INDEX.md              # ✅ This file (hub)
├── SUB_AGENT_DEVELOPMENT_GUIDE.md  # ✅ Sub-Agent implementation
├── 02_skill_authoring_guide.md     # ✅ Skill authoring
├── TESTING_QUICK_REFERENCE.md      # ✅ Testing guide
├── ARCHITECTURE.md                 # ⚠️ TODO - System architecture
├── CONFIGURATION_REFERENCE.md      # ⚠️ TODO - Config paths
├── TOOL_DEVELOPMENT_GUIDE.md       # ⚠️ TODO - Tool creation
├── DATABASE_GUIDE.md               # ⚠️ TODO - DuckDB guide
├── QUICK_START_DEVELOPER.md        # ⚠️ TODO - 5-min onboarding
├── CONTRIBUTING.md                 # ⚠️ TODO - Code standards
├── TROUBLESHOOTING.md              # ⚠️ TODO - Debug guide
├── DEPLOYMENT.md                   # ⚠️ TODO - Production deploy
├── API_REFERENCE.md                # ⚠️ TODO - API docs
└── _archive/                       # Historical docs
```

---

## 🎯 Documentation Roadmap

### Phase 1: Critical Foundation (P0) - Week 1
- [ ] ARCHITECTURE.md - System design overview
- [ ] CONFIGURATION_REFERENCE.md - All config files
- [ ] QUICK_START_DEVELOPER.md - 5-minute onboarding

### Phase 2: Developer Productivity (P1) - Week 2
- [ ] TOOL_DEVELOPMENT_GUIDE.md - Tool creation
- [ ] DATABASE_GUIDE.md - DuckDB integration
- [ ] CONTRIBUTING.md - Code standards & workflow

### Phase 3: Operations & Support (P2) - Week 3
- [ ] TROUBLESHOOTING.md - Debug guide
- [ ] DEPLOYMENT.md - Production deployment
- [ ] API_REFERENCE.md - API documentation

---

## 📞 Getting Help

- **Questions?** Open a GitHub Discussion
- **Bug Reports?** File a GitHub Issue
- **Feature Requests?** Create a GitHub Issue with `enhancement` label
- **Security Issues?** Email maintainers directly (not public)

---

## 📜 Version History

| Version | Date | Changes |
|---------|------|---------|
| v1.0.0 | 2026-02-08 | Initial developer documentation index |

---

**Next Steps**: Create missing P0 (Critical) documents first:
1. ARCHITECTURE.md
2. CONFIGURATION_REFERENCE.md  
3. QUICK_START_DEVELOPER.md
