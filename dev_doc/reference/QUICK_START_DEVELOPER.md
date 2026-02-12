# OLAV Quick Start (Developer)

**Version**: v1.0.0  
**Date**: 2026-02-08  
**Target**: New developers - 5-minute onboarding

---

## ⚡ 5-Minute Setup

### Prerequisites
- Python 3.12+
- [uv](https://github.com/astral-sh/uv) package manager
- LLM API key (OpenRouter, OpenAI, Groq, etc.)
- Git

### 1. Clone & Setup (2 minutes)
```bash
# Clone repository
git clone <repository-url>
cd Olav

# Install dependencies
uv sync

# Copy environment template
cp .env.example .env

# Edit .env - add your API key
nano .env  # or vim, code, etc.
```

**Required in `.env`**:
```bash
LLM_API_KEY=sk-or-v1-xxx...              # Your API key
LLM_BASE_URL=https://openrouter.ai/api/v1  # Base URL (if using OpenRouter)
LLM_MODEL_NAME=x-ai/grok-beta            # Model name
```

### 2. First Query (1 minute)
```bash
# Test basic query
uv run olav ask "list all devices"

# Expected output: Markdown table with device info
```

**Success Indicators**:
- ✅ Query completes without errors
- ✅ Returns markdown table
- ✅ Fast response (~2-3s with cache, ~10-15s first run)

### 3. Verify Setup (1 minute)
```bash
# Check database
uv run python -c "import duckdb; print(duckdb.connect('.olav/db/main.duckdb').execute('SELECT COUNT(*) FROM devices').fetchone())"

# Check cache
ls -lh .olav/cache/

# Run basic test
uv run pytest tests/e2e/test_real_scenarios.py::TestRealUserScenarios::test_export_devices_version_no_cli_execution -v
```

### 4. Development Workflow (1 minute)
```bash
# Run tests before committing
uv run pytest tests/e2e/test_real_scenarios.py -v

# Code quality (optional - not required for acceptance)
uv run ruff check src/ --fix
uv run ruff format src/

# Development mode (auto-reload)
uv run olav ask "your query" --debug
```

---

## 📁 Key Directories (Know Before Coding)

### Critical Paths
```
Olav/
├── .olav/                    ← OLAV runtime (NOT in Git)
│   ├── OLAV.md               ← SubAgent registry (READ THIS FIRST)
│   ├── settings.json         ← Your config overrides
│   ├── skills/               ← Skill configurations
│   │   ├── orchestrator/     ← Main orchestrator
│   │   ├── network-query/    ← Database query agent
│   │   ├── network-expert/   ← CCIE-level troubleshooting
│   │   ├── network-cli/      ← CLI execution agent
│   │   ├── network-analysis/ ← Data analysis agent
│   │   └── network-inspection/ ← Schema inspection
│   └── db/                   ← DuckDB databases
│       ├── main.duckdb       ← Device metadata
│       ├── olav.duckdb       ← CLI outputs
│       └── snapshots.duckdb  ← Query cache
│
├── config/                   ← Application config
│   ├── paths.py              ← Path constants (READ THIS)
│   └── settings.py           ← Settings schema (READ THIS)
│
├── src/olav/                 ← Source code
│   ├── agents/               ← Agent implementations
│   │   ├── orchestrator.py   ← Main orchestrator
│   │   ├── query_agent.py    ← Query agent
│   │   └── expert_agent.py   ← Expert agent
│   ├── tools/                ← Tool functions
│   │   ├── react_query.py    ← Database tools
│   │   └── react_expert.py   ← Expert tools
│   ├── core/                 ← Core utilities
│   │   ├── subagent_loader.py ← Load agents from SKILL.md
│   │   └── skill_adapter.py   ← Load tools from SKILL.md
│   └── lib/                  ← External integrations
│       ├── data_gateway.py   ← Database access
│       └── ncm_client.py     ← Nornir integration
│
├── tests/                    ← Test suite
│   └── e2e/
│       └── test_real_scenarios.py ← REAL E2E tests (NEW STANDARD)
│
└── docs/reference/           ← Developer documentation
    ├── ARCHITECTURE.md       ← System architecture
    ├── CONFIGURATION_REFERENCE.md ← Config guide
    ├── SKILL_AUTHORING_GUIDE.md ← Skill config
    └── SUB_AGENT_DEVELOPMENT_GUIDE.md ← Agent dev guide
```

---

## 🎯 Common Development Tasks

### 1. Add a New Tool
**Goal**: Create a new tool function for agents

**Steps**:
1. **Create tool function** (`src/olav/tools/my_tools.py`)
   ```python
   def my_tool(param: str) -> str:
       """Tool description for LLM."""
       # Implementation
       return result
   ```

2. **Register in SKILL.md** (`.olav/skills/network-query/SKILL.md`)
   ```yaml
   tools:
     - name: my_tool
       module: olav.tools.my_tools
       function: my_tool
       description: Tool description
   ```

3. **Test**
   ```bash
   uv run olav ask "use my_tool"
   ```

**Reference**: [TOOL_DEVELOPMENT_GUIDE.md](TOOL_DEVELOPMENT_GUIDE.md) (P1 - coming soon)

---

### 2. Create a New SubAgent
**Goal**: Add a specialized agent (e.g., security analyst, config generator)

**Steps**:
1. **Create skill directory**
   ```bash
   mkdir -p .olav/skills/my-agent
   ```

2. **Create SKILL.md** (`.olav/skills/my-agent/SKILL.md`)
   ```yaml
   ---
   name: my-agent
   description: What this agent does
   version: 1.0.0
   
   prompts:
     system: |
       You are a specialized agent...
   
   tools:
     - name: tool1
       module: olav.tools.my_tools
       function: tool1
       description: Tool description
   ---
   ```

3. **Register in OLAV.md** (`.olav/OLAV.md`)
   ```yaml
   ### my_agent
   ```yaml
   ---
   name: my_agent
   agent_skill: my-agent
   description: Agent description
   capabilities:
     - Capability 1
     - Capability 2
   enabled: true
   ---
   ```
   ```

4. **Create agent** (`src/olav/agents/my_agent.py`)
   ```python
   from deepagents import SubAgent
   from olav.core.subagent_loader import SubAgentLoader
   
   def create_my_agent():
       loader = SubAgentLoader()
       skill = loader.get_skill("my-agent")
       
       agent = SubAgent(
           name="my-agent",
           system_prompt=skill.system_prompt,
           tools=skill.tools,
       )
       
       return agent
   ```

5. **Test**
   ```bash
   uv run olav ask "task for my agent"
   ```

**Reference**: [SUB_AGENT_DEVELOPMENT_GUIDE.md](SUB_AGENT_DEVELOPMENT_GUIDE.md)

---

### 3. Modify Routing Logic
**Goal**: Change how queries are routed to agents

**Current**: Routing happens in orchestrator via TodoList planning

**Location**: `src/olav/agents/orchestrator.py::create_planning_orchestrator()`

**Test**:
```bash
uv run pytest tests/e2e/test_real_scenarios.py -v
```

**Reference**: [ARCHITECTURE.md](ARCHITECTURE.md) - Routing section

---

### 4. Add Database Tables
**Goal**: Extend database schema

**Steps**:
1. **Choose database**
   - `main.duckdb`: Device metadata (inventories, properties)
   - `olav.duckdb`: CLI outputs, capabilities, runtime data

2. **Create SQL migration** (`migrations/001_add_my_table.sql`)
   ```sql
   CREATE TABLE IF NOT EXISTS my_table (
       id INTEGER PRIMARY KEY,
       name VARCHAR,
       created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
   );
   ```

3. **Apply migration**
   ```python
   import duckdb
   from config.paths import DB_MAIN_PATH
   
   conn = duckdb.connect(str(DB_MAIN_PATH))
   with open("migrations/001_add_my_table.sql") as f:
       conn.execute(f.read())
   ```

**Reference**: [DATABASE_GUIDE.md](DATABASE_GUIDE.md) (P1 - coming soon)

---

### 5. Debug Cache Issues
**Goal**: Understand cache behavior

**Check semantic cache**:
```bash
sqlite3 .olav/cache/semantic_cache.db "SELECT COUNT(*), AVG(similarity) FROM cache_entries;"
```

**Check LLM cache**:
```bash
sqlite3 .olav/cache/llm_cache.db ".tables"
```

**Disable cache for debugging**:
```bash
# In .env
LLM_CACHE_ENABLED=false

# Or in .olav/skills/network-query/SKILL.md
caching:
  enabled: false
```

**Reference**: [ARCHITECTURE.md](ARCHITECTURE.md) - Caching section

---

## 🧪 Testing Standards

### Real E2E Tests (New Standard - v0.9.8+)
**Location**: `tests/e2e/test_real_scenarios.py`

**Principles**:
1. ✅ No mocks for business logic
2. ✅ Test complete user scenarios
3. ✅ Monitor side effects (CLI, database, file I/O)
4. ✅ Validate data correctness

**Example Test**:
```python
@pytest.mark.asyncio
async def test_my_scenario(self):
    """
    User Story: Export devices' version to CSV
    
    Acceptance Criteria:
    1. Query succeeds
    2. CSV file created
    3. NO CLI commands executed
    """
    cli_tracker = CLICommandTracker()
    
    with cli_tracker:
        result = await orchestrate_query("save devices' version to csv")
        assert result is not None
    
    cli_tracker.assert_no_commands()
    assert Path("exports/devices_version.csv").exists()
```

**Run tests**:
```bash
# All E2E tests
uv run pytest tests/e2e/test_real_scenarios.py -v

# Specific test
uv run pytest tests/e2e/test_real_scenarios.py::TestRealUserScenarios::test_export_devices_version_no_cli_execution -v
```

**Reference**: [TESTING_QUICK_REFERENCE.md](TESTING_QUICK_REFERENCE.md)

---

## 🐛 Debugging Tips

### 1. Enable Debug Logging
```bash
# Environment variable
OLAV_LOG_LEVEL=DEBUG uv run olav ask "query"

# Or in .env
OLAV_LOG_LEVEL=DEBUG
```

### 2. Check Agent Execution
```python
# Add logging in agent code
from config.logging import logger

logger.debug(f"Tool called: {tool_name} with {args}")
logger.info(f"Agent iteration {i}: {thought}")
```

### 3. Inspect Database
```bash
# Check devices table
uv run python -c "import duckdb; conn = duckdb.connect('.olav/db/main.duckdb'); print(conn.execute('SELECT * FROM devices LIMIT 5').fetchdf())"

# Check raw outputs
uv run python -c "import duckdb; conn = duckdb.connect('.olav/db/olav.duckdb'); print(conn.execute('SELECT * FROM raw_outputs LIMIT 5').fetchdf())"
```

### 4. Test Tool Directly
```python
# Test tool without agent
from olav.tools.react_query import query_database

result = query_database("SELECT * FROM devices LIMIT 5")
print(result)
```

---

## 📚 Next Steps

### Understand Architecture
**Read**: [ARCHITECTURE.md](ARCHITECTURE.md)
- Component hierarchy
- Data flow diagrams
- Caching layers
- Backend routing

### Learn Configuration
**Read**: [CONFIGURATION_REFERENCE.md](CONFIGURATION_REFERENCE.md)
- Environment variables
- SKILL.md structure
- Database paths
- Tool registration

### Write Skills
**Read**: [SKILL_AUTHORING_GUIDE.md](SKILL_AUTHORING_GUIDE.md)
- YAML frontmatter
- System prompts
- Tool registry
- Progressive disclosure

### Build Agents
**Read**: [SUB_AGENT_DEVELOPMENT_GUIDE.md](SUB_AGENT_DEVELOPMENT_GUIDE.md)
- DeepAgents patterns
- LangGraph persistence
- Multi-layer caching
- Third-party LLM config

---

## 🚫 Common Pitfalls

### 1. Hardcoded Paths
```python
# ❌ WRONG
db_path = ".olav/db/main.duckdb"

# ✅ CORRECT
from config.paths import DB_MAIN_PATH
db_path = DB_MAIN_PATH
```

### 2. Direct Database Access
```python
# ❌ WRONG - separate connections
conn1 = duckdb.connect(".olav/db/main.duckdb")
conn2 = duckdb.connect(".olav/db/olav.duckdb")

# ✅ CORRECT - unified connection
from olav.lib.data_gateway import DataGateway
gateway = DataGateway()
result = gateway.query("SELECT * FROM devices JOIN raw_outputs")
```

### 3. Missing Environment Variables
```python
# ❌ WRONG - will fail if not set
import os
api_key = os.getenv("LLM_API_KEY")  # None if not set

# ✅ CORRECT - use settings with defaults
from config.settings import settings
api_key = settings.llm_api_key  # Falls back to default
```

### 4. Modifying SKILL.md Without Testing
```yaml
# After changing SKILL.md, always test
uv run olav ask "query related to this skill"

# Check logs for errors
tail -f logs/olav.log
```

### 5. Not Using Real E2E Tests
```python
# ❌ OLD WAY - mock-heavy
def test_agent_exists():
    agent = create_query_agent()
    assert agent is not None  # Tests nothing useful

# ✅ NEW WAY - real scenarios
async def test_export_devices_no_cli():
    cli_tracker = CLICommandTracker()
    with cli_tracker:
        result = await orchestrate_query("export devices to csv")
    cli_tracker.assert_no_commands()  # Verify behavior
    assert Path("exports/devices.csv").exists()  # Verify output
```

---

## 🔧 Development Tools

### Code Quality (Optional - Not Required for Acceptance)
```bash
# Format code
uv run ruff format src/

# Fix linting issues
uv run ruff check src/ --fix

# Type checking
uv run pyright src/
```

### Database Tools
```bash
# Query databases
uv run python -c "import duckdb; conn = duckdb.connect('.olav/db/main.duckdb'); print(conn.execute('SHOW TABLES').fetchall())"

# Export data
uv run python -c "import duckdb; duckdb.connect('.olav/db/main.duckdb').execute('COPY devices TO \"devices.csv\"')"
```

### Git Workflow
```bash
# Create feature branch
git checkout -b feature/my-feature

# Make changes, test
uv run pytest tests/e2e/test_real_scenarios.py -v

# Commit
git add .
git commit -m "feat(agent): add my feature"

# Push
git push origin feature/my-feature
```

---

## 📋 Quick Reference

### Essential Commands
```bash
# Run query
uv run olav ask "your query"

# Run tests
uv run pytest tests/e2e/test_real_scenarios.py -v

# Check database
uv run python -c "import duckdb; print(duckdb.connect('.olav/db/main.duckdb').execute('SELECT COUNT(*) FROM devices').fetchone())"

# View logs
tail -f logs/olav.log

# Clear cache
rm -rf .olav/cache/*.db
```

### Essential Files
- `.olav/OLAV.md` - SubAgent registry
- `.olav/skills/*/SKILL.md` - Skill configurations
- `config/paths.py` - Path constants
- `config/settings.py` - Settings schema
- `tests/e2e/test_real_scenarios.py` - Real E2E tests

### Essential Documentation
- [ARCHITECTURE.md](ARCHITECTURE.md) - System architecture
- [CONFIGURATION_REFERENCE.md](CONFIGURATION_REFERENCE.md) - Config guide
- [SUB_AGENT_DEVELOPMENT_GUIDE.md](SUB_AGENT_DEVELOPMENT_GUIDE.md) - Agent dev
- [SKILL_AUTHORING_GUIDE.md](SKILL_AUTHORING_GUIDE.md) - Skill config

---

## 🆘 Getting Help

### Documentation Hub
**Start here**: [DEVELOPER_INDEX.md](../DEVELOPER_INDEX.md)
- Complete documentation index
- Navigation by role
- Status tracking (✅ Complete, ⚠️ Planned, 🔄 In Progress)

### Common Questions
1. **"How do I add a new tool?"** → See "Common Development Tasks" above
2. **"How do I debug cache issues?"** → See "Debugging Tips" above
3. **"How do I write tests?"** → See [TESTING_QUICK_REFERENCE.md](TESTING_QUICK_REFERENCE.md)
4. **"How do I configure skills?"** → See [SKILL_AUTHORING_GUIDE.md](SKILL_AUTHORING_GUIDE.md)

### Still Stuck?
- Check [TROUBLESHOOTING.md](TROUBLESHOOTING.md) (P2 - coming soon)
- Search existing issues
- Ask in team chat

---

**Version**: v1.0.0 (2026-02-08)  
**Status**: ✅ Production Reference  
**Target**: New developers - 5-minute onboarding
