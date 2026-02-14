# OLAV Architecture Overview

**Version**: v1.0.0  
**Date**: 2026-02-08  
**Framework**: DeepAgents (LangGraph-based)

---

## 🎯 System Overview

OLAV is an **agentic network assistant** that bridges generative AI and deterministic network automation through a multi-agent orchestration architecture.

```
┌─────────────────────────────────────────────────────────────┐
│                       User Interface                         │
│                  (CLI / API / Web Console)                   │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                      Orchestrator                            │
│              (Plan Mode + SubAgent Router)                   │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  TodoListMiddleware (Plan Mode)                      │  │
│  │  SummarizationMiddleware (Long Conversations)        │  │
│  └──────────────────────────────────────────────────────┘  │
└──────┬────────┬──────────┬───────────┬──────────────────────┘
       │        │          │           │
       ▼        ▼          ▼           ▼
   ┌─────┐  ┌─────┐   ┌──────┐   ┌─────────┐
   │Query│  │Expert│  │ CLI  │   │Analysis │
   └─────┘  └─────┘   └──────┘   └─────────┘
   SubAgents (ReAct Mode)
       │
       ▼
┌─────────────────────────────────────────────────────────────┐
│                         Tools Layer                          │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐  ┌─────────┐│
│  │query_      │ │execute_    │ │analyze_    │  │format_  ││
│  │database    │ │command     │ │topology    │  │export   ││
│  └────────────┘ └────────────┘ └────────────┘  └─────────┘│
└──────┬──────────────────┬────────────────┬─────────────────┘
       │                  │                │
       ▼                  ▼                ▼
┌──────────┐      ┌────────────┐    ┌──────────┐
│  DuckDB  │      │  Nornir    │    │ TextFSM  │
│(Database)│      │(CLI Access)│    │(Parsing) │
└──────────┘      └────────────┘    └──────────┘
```

---

## 🏗️ Component Hierarchy

### Layer 1: Orchestrator (Meta-Agent)

**Role**: Unified entry point for all user queries

**Components**:
- **Plan Mode** (`create_planning_orchestrator`)
  - Uses `TodoListMiddleware` for multi-step task management
  - Tools: `write_todos`, `read_todos`, `format_and_export`
  - Triggered by `/plan` prefix

- **Standard Mode** (`create_orchestrator`)
  - SubAgent routing via DeepAgents native middleware
  - Conversation summarization (optional)
  - Real-time execution

**Key Features**:
- Dynamic SubAgent loading from `.olav/OLAV.md`
- Intent detection and routing
- Result aggregation
- Context management

**Implementation**: `src/olav/agents/orchestrator.py`

---

### Layer 2: SubAgents (Specialists)

SubAgents are **ReAct-mode agents** with specialized capabilities:

#### Query SubAgent
- **Intent**: `quick_query`
- **Tools**: `query_database`, `inspect_schema`, `smart_query`
- **Features**: DuckDB queries, schema discovery, data export
- **Persistence**: DuckDBSaver (sessions), DuckDBStore (aliases)
- **Implementation**: `src/olav/agents/query_agent.py`

#### Expert SubAgent
- **Intent**: `expert_diagnose`
- **Tools**: `query_database`, `analyze_topology`, `expand_scope_by_role`
- **Features**: Multi-domain expertise (BGP, OSPF, EIGRP), root cause analysis
- **Persistence**: None (stateless)
- **Implementation**: `src/olav/agents/analyzer.py`

#### CLI SubAgent
- **Intent**: `cli_execution`
- **Tools**: `execute_command`, `test_connectivity`
- **Features**: Network command execution via Nornir/Netmiko
- **Persistence**: None (stateless)
- **Implementation**: `src/olav/tools/ncm_client.py`

#### Analysis SubAgent
- **Intent**: `analysis`
- **Tools**: `query_database`, `analyze_network`
- **Features**: Health diagnostics, anomaly detection
- **Persistence**: None (stateless)
- **Implementation**: `src/olav/agents/analyzer.py`

#### Inspection SubAgent
- **Intent**: `inspection`
- **Tools**: `query_database`, `inspect_schema`
- **Features**: Multi-layer health checks (L1-L4), compliance validation
- **Persistence**: None (stateless)

---

### Layer 3: Tools (Functions)

Tools are **pure Python functions** that SubAgents invoke:

#### Data Tools
- `query_database(sql)` - Execute SQL on DuckDB
- `inspect_schema(table?)` - Discover database schema
- `discover_data()` - List exported files

#### Network Tools
- `execute_command(host, cmd)` - Run CLI commands
- `test_connectivity(host)` - Verify device reachability

#### Analysis Tools
- `analyze_topology(devices)` - Build network graph
- `expand_scope_by_role(role)` - Find related devices
- `analyze_network(query)` - Health diagnostics

#### Export Tools
- `format_and_export(data, format)` - Export to CSV/JSON/Markdown

**Implementation**: `src/olav/tools/`

---

### Layer 4: Infrastructure

#### DuckDB (Data Layer)
```
.olav/db/
├── main.duckdb        # Device metadata (devices table)
├── olav.duckdb        # CLI outputs (raw_outputs, device_capabilities)
└── snapshots.duckdb   # Query cache
```

**Unified Connection** (Critical Pattern):
- All databases attached to single in-memory connection
- Automatic cross-database JOINs
- Schema discovery via `SHOW ALL TABLES`
- Compatibility views for legacy queries

**Implementation**: `src/olav/lib/data_gateway.py::_create_unified_connection()`

#### Nornir (Network Access)
- Multi-threaded CLI execution
- Multi-vendor support (Cisco, Juniper, Arista, Huawei)
- Connection pooling and retry logic
- Inventory management

**Configuration**: `.olav/skills/network-cli/config/`
**Implementation**: `src/olav/lib/ncm_client.py`

#### TextFSM (Parsing)
- CLI output → Structured JSON
- NTC templates library integration
- Custom template management
- Automatic template generation

**Templates**: `.olav/templates/`
**Implementation**: `src/olav/agents/textfsm_agent.py`

---

## 🔄 Data Flow

### Typical Query Flow

```
1. User Query
   └─→ "show all BGP neighbors with status down"

2. Orchestrator (Intent Detection)
   └─→ Detects: database query + analysis
   └─→ Routes to: Query SubAgent

3. Query SubAgent (Schema Discovery)
   └─→ Calls: inspect_schema()
   └─→ Discovers: raw_outputs table
   └─→ Generates SQL: SELECT * FROM raw_outputs WHERE command LIKE '%bgp%'

4. Tool Execution (query_database)
   └─→ DuckDB executes SQL
   └─→ Returns: 15 rows

5. SubAgent (Result Processing)
   └─→ Parses BGP output
   └─→ Filters status = "down"
   └─→ Formats as markdown table

6. Orchestrator (Result Aggregation)
   └─→ Returns to user
   └─→ Stores in cache

Result: Markdown table with down BGP neighbors
```

### Complex Multi-Agent Flow (Plan Mode)

```
1. User Query
   └─→ "/plan audit all routers for security compliance"

2. Orchestrator (Plan Mode)
   └─→ Creates todo list:
       - [ ] Query all router devices
       - [ ] Check BGP MD5 authentication
       - [ ] Verify ACL configurations
       - [ ] Generate compliance report

3. Step 1: Query SubAgent
   └─→ SQL: SELECT * FROM devices WHERE role = 'router'
   └─→ Result: 50 routers

4. Step 2: Expert SubAgent
   └─→ Analyzes BGP configs for MD5
   └─→ Identifies: 5 routers without MD5

5. Step 3: CLI SubAgent (if needed)
   └─→ Executes: show access-list
   └─→ Validates ACL rules

6. Step 4: Format & Export
   └─→ format_and_export(findings, "csv")
   └─→ Generates: compliance_report.csv

Result: Structured compliance report
```

---

## 💾 Caching Architecture

OLAV implements **4-layer caching** for performance:

### Layer 0: Semantic Cache (0.2s)
- **Technology**: Vector embeddings + similarity search
- **Storage**: `.olav/cache/semantic_cache.db` (SQLite)
- **Use Case**: Semantically similar queries
- **Example**: "list devices" ≈ "show all routers"

### Layer 1: LLM Cache (0.5s)
- **Technology**: SQLiteCache (LangChain)
- **Storage**: `.olav/cache/llm_cache.db`
- **Use Case**: Identical prompts (transparent)
- **Scope**: Global (all agents)

### Layer 2: Application Cache (variable)
- **Technology**: Agent-specific caching
- **Examples**:
  - Query cache (SQL results)
  - Template cache (TextFSM templates)
  - Intent cache (routing decisions)
- **TTL**: Configurable per skill

### Layer 3: Full Execution (15-50s)
- **Trigger**: Cache miss on all layers
- **Process**: LLM reasoning + tool execution
- **Result**: Stored in all cache layers

**Configuration**: Skill frontmatter (`caching` section)

---

## 🎨 Backend Architecture (Storage Routing)

### CompositeBackend Pattern
```python
from olav.core.storage import get_composite_backend

backend = get_composite_backend()
# Routes storage requests to appropriate backends:
# - FilesystemBackend: Conversation history, summaries
# - StateBackend: Agent state, checkpoints
# - StoreBackend: Key-value pairs (aliases, preferences)
```

**Path Routing**:
- `conversational/*` → FilesystemBackend (`.olav/conversations/`)
- `summaries/*` → FilesystemBackend (`.olav/summaries/`)
- `checkpoints/*` → StateBackend (DuckDB)
- `store/*` → StoreBackend (DuckDB)

**Implementation**: `src/olav/core/storage.py`

---

## 🔧 Configuration Architecture (Skill-Centric)

### Configuration Priority Chain
```
.env (highest)
  ↓
.olav/settings.json
  ↓
SKILL.md frontmatter
  ↓
config/settings.py (defaults)
```

### Skill-Centric Design

**Principle**: All agent behavior flows from SKILL.md configuration

**Structure**:
```
.olav/skills/{skill-name}/
├── SKILL.md              # Main configuration
│   ├── [YAML frontmatter]  # Metadata, tools, caching
│   └── [Markdown body]     # System prompt, guidance
├── REFERENCE.md          # Advanced features (optional)
└── config/               # Skill-specific configs (optional)
```

**Loading Flow**:
1. Orchestrator reads `.olav/OLAV.md` (SubAgent registry)
2. For each SubAgent, loads `.olav/skills/{agent_skill}/SKILL.md`
3. Extracts: system prompt, tools, caching config
4. Creates SubAgent with loaded configuration

**Implementation**: `src/olav/core/subagent_loader.py`

---

## 🔐 Security Architecture

### 3-Tier Knowledge Model

**Tier 1: Public Knowledge** (Unrestricted)
- Network theory (OSPF, BGP, TCP/IP)
- Vendor documentation references
- Best practices guides

**Tier 2: Company Knowledge** (Read-Only)
- Network topology diagrams
- Device inventory
- Standard configurations

**Tier 3: Operational Knowledge** (Human Approval Required)
- Configuration changes
- Password resets
- Firmware upgrades

**HITL Gates**:
- TextFSM field approval (user confirms extracted fields)
- Configuration change approval (user reviews before apply)
- CLI command approval (optional, for sensitive operations)

---

## 📊 Performance Characteristics

### Latency Targets

| Operation | Target | Actual | Notes |
|-----------|--------|--------|-------|
| Semantic cache hit | <0.5s | 0.2s | Vector similarity search |
| LLM cache hit | <1s | 0.5s | Prompt hash lookup |
| Simple query | <5s | 3-5s | SQL generation + execution |
| Complex analysis | <30s | 15-25s | Multi-step ReAct loop |
| Plan mode (5 steps) | <60s | 40-50s | Sequential SubAgent execution |

### Scalability

- **Concurrent users**: 10+ (single instance)
- **Database size**: 100K+ rows (DuckDB)
- **Device inventory**: 1000+ devices
- **Conversation history**: 1000+ turns (with summarization)

---

## 🔌 Extension Points

### Adding New SubAgents
1. Define in `.olav/OLAV.md` (SubAgent registry)
2. Create `.olav/skills/{skill-name}/SKILL.md`
3. Implement tool functions (if needed)
4. Test with orchestrator

**No code changes required** - fully declarative.

### Adding New Tools
1. Create Python function in `src/olav/tools/`
2. Register in SKILL.md (`tools` section)
3. Document parameters and return type
4. Unit test the function

### Adding New Data Sources
1. Extend DataGateway (`src/olav/lib/data_gateway.py`)
2. Add database file to `.olav/db/`
3. Update unified connection logic
4. Add compatibility views if needed

---

## 🧪 Testing Architecture

### Test Pyramid

```
           ┌──────────┐
           │   E2E    │  ← Real user scenarios
           │ (10 tests)│
           └──────────┘
         ┌──────────────┐
         │ Integration  │  ← SubAgent + Tools
         │  (30 tests)  │
         └──────────────┘
      ┌────────────────────┐
      │     Unit Tests     │  ← Individual functions
      │    (100+ tests)    │
      └────────────────────┘
```

### Real E2E Testing (Critical)
- **No mocks** for business logic
- **Monitor side effects** (CLI execution, DB access, file I/O)
- **Test user workflows**, not component existence
- **Validate data flow** end-to-end

**Implementation**: `tests/e2e/test_real_scenarios.py`

---

## 🗺️ Decision Trees

### When to Use Which Agent?

```
User Query
    │
    ├─ Database query? ──────────── YES ──→ Query SubAgent
    │                                         (quick_query)
    │
    ├─ Complex troubleshooting? ─── YES ──→ Expert SubAgent
    │                                         (expert_diagnose)
    │
    ├─ CLI command execution? ───── YES ──→ CLI SubAgent
    │                                         (cli_execution)
    │
    ├─ Health diagnostics? ─────── YES ──→ Analysis SubAgent
    │                                         (analysis)
    │
    └─ Multi-step audit? ────────── YES ──→ Plan Mode
                                              (/plan prefix)
```

### When to Use Plan Mode vs Standard Mode?

**Use Plan Mode when**:
- Multi-step workflow (>3 steps)
- Human approval checkpoints needed
- Progress tracking required
- Step dependencies exist

**Use Standard Mode when**:
- Single query/action
- Real-time interaction
- No intermediate approvals

---

## 📚 References

### Core Implementation Files
- **Orchestrator**: `src/olav/agents/orchestrator.py`
- **QueryAgent**: `src/olav/agents/query_agent.py`
- **Expert/Analysis**: `src/olav/agents/analyzer.py`
- **SubAgent Loader**: `src/olav/core/subagent_loader.py`
- **Data Gateway**: `src/olav/lib/data_gateway.py`
- **Storage Backend**: `src/olav/core/storage.py`

### Configuration Files
- **SubAgent Registry**: `.olav/OLAV.md`
- **Skills**: `.olav/skills/*/SKILL.md`
- **App Settings**: `config/settings.py`
- **Path Constants**: `config/paths.py`

### Documentation
- **Developer Index**: [DEVELOPER_INDEX.md](../DEVELOPER_INDEX.md)
- **Sub-Agent Guide**: [SUB_AGENT_DEVELOPMENT_GUIDE.md](SUB_AGENT_DEVELOPMENT_GUIDE.md)
- **Skill Authoring**: [SKILL_AUTHORING_GUIDE.md](SKILL_AUTHORING_GUIDE.md)

---

**Version**: v1.0.0 (2026-02-08)  
**Status**: ✅ Production Architecture
