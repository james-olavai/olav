# Sub-Agent Development Guide

**Version**: v1.0.0  
**Date**: 2026-02-08  
**Framework**: DeepAgents (Native Patterns)

---

## 📚 Overview

This guide provides a complete reference for developing Sub-Agents in OLAV using **DeepAgents native patterns**. It consolidates best practices from production implementations (QueryAgent, TextFSMInteractiveAgent, Expert, Inspection) into a systematic development framework.

**Key Principles**:
- **Orchestrator uses Plan Mode** - TodoListMiddleware for multi-step coordination
- **SubAgents use ReAct Mode** - Tool-based iterative problem solving
- **Skill-Centric Configuration** - All behavior flows from SKILL.md
- **Multi-Layer Caching** - Semantic, query, and LLM-level caching
- **CompositeBackend Integration** - Unified storage routing

---

## 🏗️ Architecture Overview

### Agent Hierarchy

```
Orchestrator (Plan Mode)
├── TodoListMiddleware (task management)
├── SubAgent Router (declarative dispatch)
└── SubAgents (ReAct Mode)
    ├── query: Database specialist
    ├── expert: CCIE-level troubleshooting
    ├── cli: Command execution
    ├── analysis: Health diagnostics
    └── inspection: Batch audits
```

### Pattern Matrix

| Component | Mode | Middleware | Tools | Checkpointer | Store |
|-----------|------|------------|-------|--------------|-------|
| **Orchestrator** | Plan | TodoList, Summarization | format_and_export, write_todos, read_todos | None (in-memory) | None |
| **SubAgent (query)** | ReAct | Summarization (optional) | query_database, inspect_schema, smart_query | DuckDBSaver | DuckDBStore |
| **SubAgent (expert)** | ReAct | - | query_database, analyze_topology, expand_scope | None | None |
| **SubAgent (textfsm)** | ReAct | - | execute_command, analyze_fields, test_template | None | None |

---

## 📋 Part 1: Configuration Architecture

> 💡 **Companion Guide**: For detailed SKILL.md authoring best practices, see **[02_skill_authoring_guide.md](02_skill_authoring_guide.md)**  
> This guide focuses on **implementation** (Python code), while the Skill Authoring Guide covers **configuration** (SKILL.md writing).

### 1.1 OLAV.md - SubAgent Registry

**Location**: `.olav/OLAV.md`

**Purpose**: Declare SubAgent metadata and routing information

**Format**:
```yaml
### agent_name
```yaml
---
name: agent_name
agent_skill: skill-name        # Links to .olav/skills/skill-name/
description: What the agent does and when to use it
capabilities:
  - Capability 1
  - Capability 2
enabled: true
---
```

**Example - Query SubAgent**:
```yaml
### query
```yaml
---
name: query
agent_skill: network-query
description: Database query specialist - SQL queries, schema inspection, data discovery
capabilities:
  - Device inventory queries (devices table)
  - SQL execution on network database
  - Schema inspection and data discovery
  - Automatic LLM caching for repeated queries
enabled: true
---
```

**Key Points**:
- Orchestrator dynamically loads SubAgents from this section
- No hardcoded tool lists here (tools loaded from SKILL.md)
- `enabled: false` can disable a SubAgent without code changes

---

### 1.2 SKILL.md - SubAgent Detailed Configuration

**Location**: `.olav/skills/{skill-name}/SKILL.md`

**Purpose**: Complete agent specification (system prompt, tools, caching)

> 📖 **Detailed Guide**: See **[02_skill_authoring_guide.md](02_skill_authoring_guide.md)** for:
> - YAML frontmatter best practices
> - Progressive disclosure strategies (3-level content loading)
> - Writing concise, effective skill content
> - Schema discovery vs hardcoding patterns
> - Testing and iteration workflows

**Structure**:
```yaml
---
name: skill-name
description: Skill description
version: 1.0.0

# System Prompts (Orchestrator uses 'system', SubAgent uses prompts.system)
prompts:
  system: |
    You are a specialized network query agent...
    
    ## Available Tools
    - query_database: Execute SQL against main.duckdb
    - inspect_schema: Discover database schema
    
    ## Response Format
    Always return results as markdown tables.

# Tool Configuration (Dynamic Loading)
tools:
  - name: query_database
    module: olav.tools.react_query
    function: query_database
    description: Execute SQL queries
    
  - name: inspect_schema
    module: olav.tools.react_query
    function: inspect_schema
    description: Inspect database structure

# Caching Configuration
caching:
  enabled: true
  backend: semantic_cache
  ttl_seconds: 3600
  cache_key_fields: [query, schema_context]
  
# Agent-Specific Settings
agent:
  max_iterations: 10
  enable_summarization: false
  temperature: 0.1
---

# Skill Content (Markdown)

Additional guidance, examples, troubleshooting tips...
```
**Best Practices** (from [02_skill_authoring_guide.md](02_skill_authoring_guide.md)):
- ✅ Use schema discovery, NOT hardcoded schema
- ✅ Keep SKILL.md body under 400 lines
- ✅ Use progressive disclosure (split to reference files)
- ✅ Declare `intent` type for orchestrator routing
- ✅ Write concise prompts (avoid over-explanation)


**Key Fields**:
- `prompts.system`: System prompt for SubAgent (loaded by `subagent_loader.py`)
- `tools`: Tool registry (dynamically loaded via SkillAdapter)
- `caching`: Cache configuration (semantic cache, LLM cache)
- `agent`: Agent-specific parameters

---

## 📦 Part 2: SubAgent Implementation Patterns

### 2.1 Pattern 1: Simple ReAct SubAgent (No Persistence)

**Use Case**: Stateless operations (CLI execution, one-off analysis)

**Example**: Expert SubAgent

**Implementation**:
```python
# src/olav/agents/expert_subagent.py
from deepagents import create_deep_agent
from olav.core.llm import LLMFactory
from olav.core.storage import get_composite_backend

def create_expert_subagent():
    """Create expert SubAgent without persistence."""
    
    # 1. Load configuration from SKILL.md
    from olav.core.skill_loader import get_skill_loader
    loader = get_skill_loader()
    skill = loader.get_skill("network-expert")
    
    # 2. Create LLM instance
    llm = LLMFactory.get_chat_model(
        temperature=float(skill.frontmatter.get("agent", {}).get("temperature", 0.1))
    )
    
    # 3. Load tools from skill
    from olav.core.skill_adapter import SkillAdapter
    adapter = SkillAdapter()
    tools = adapter.load_tools_from_skill(skill)
    
    # 4. Get system prompt
    system_prompt = skill.frontmatter.get("prompts", {}).get("system", "")
    
    # 5. Get CompositeBackend for storage routing
    backend = get_composite_backend()
    
    # 6. Create agent (NO checkpointer/store for stateless agents)
    agent = create_deep_agent(
        model=llm,
        system_prompt=system_prompt,
        tools=tools,
        backend=backend,
        checkpointer=None,  # ⚠️ Stateless
        store=None,         # ⚠️ No persistent store
        middleware=[],      # ⚠️ No middleware for simple agents
        name="expert",
    )
    
    return agent
```

**Characteristics**:
- ✅ No session persistence
- ✅ No conversation history
- ✅ Fast initialization (<50ms)
- ✅ Suitable for: CLI execution, one-shot analysis

---

### 2.2 Pattern 2: ReAct SubAgent with Persistence

**Use Case**: Conversational agents, session management, history tracking

**Example**: QueryAgent

**Implementation**:
```python
# src/olav/agents/query_subagent.py
from pathlib import Path
from deepagents import create_deep_agent
from langgraph.checkpoint.duckdb import DuckDBSaver
from langgraph.store.duckdb import DuckDBStore
from deepagents.middleware.summarization import SummarizationMiddleware

from config.paths import USER_CHECKPOINT_PATH
from olav.core.llm import LLMFactory
from olav.core.storage import get_composite_backend

class QuerySubAgent:
    """Query SubAgent with full persistence."""
    
    def __init__(self, user_id: str = "default", enable_summarization: bool = False):
        self.user_id = user_id
        self.enable_summarization = enable_summarization
        
        # 1. Setup user-specific persistence
        self._init_user_database()
        
        # 2. Load configuration
        from olav.core.skill_loader import get_skill_loader
        loader = get_skill_loader()
        self.skill = loader.get_skill("network-query")
        
        # 3. Load tools
        from olav.core.skill_adapter import SkillAdapter
        adapter = SkillAdapter()
        self.tools = adapter.load_tools_from_skill(self.skill)
        
        # 4. Setup backend
        self.backend = get_composite_backend()
        
        # 5. Create agent
        self._create_agent()
    
    def _init_user_database(self):
        """Initialize user-specific DuckDB persistence."""
        user_db_path = Path(USER_CHECKPOINT_PATH) / f"{self.user_id}.duckdb"
        user_db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # DuckDBSaver: Session checkpointing (conversation state)
        self.checkpointer = DuckDBSaver.from_conn_string(str(user_db_path))
        
        # DuckDBStore: Key-value store (aliases, preferences)
        self.store = DuckDBStore.from_conn_string(str(user_db_path))
    
    def _create_agent(self):
        """Create DeepAgent with full middleware stack."""
        llm = LLMFactory.get_chat_model()
        system_prompt = self.skill.frontmatter.get("prompts", {}).get("system", "")
        
        # Optional: Add SummarizationMiddleware
        middleware = []
        if self.enable_summarization:
            summ_llm = LLMFactory.get_chat_model(temperature=0.1)
            middleware.append(
                SummarizationMiddleware(
                    model=summ_llm,
                    backend=self.backend,
                    trigger=("tokens", 4000),
                    keep=("messages", 10),
                )
            )
        
        self.agent = create_deep_agent(
            model=llm,
            system_prompt=system_prompt,
            tools=self.tools,
            backend=self.backend,
            checkpointer=self.checkpointer,  # ✅ Persistent sessions
            store=self.store,                # ✅ KV store
            middleware=middleware,           # ✅ Summarization support
            name="query",
        )
    
    async def ainvoke(self, query: str, thread_id: str = None):
        """Execute query with session management."""
        import uuid
        if not thread_id:
            thread_id = str(uuid.uuid4())
        
        config = {"configurable": {"thread_id": thread_id}}
        result = await self.agent.ainvoke({"messages": [query]}, config=config)
        return result
    
    def close(self):
        """Close DuckDB connections."""
        if hasattr(self.checkpointer, '__exit__'):
            self.checkpointer.__exit__(None, None, None)
        if hasattr(self.store, '__exit__'):
            self.store.__exit__(None, None, None)
```

**Characteristics**:
- ✅ Persistent conversation history
- ✅ Session resumption via thread_id
- ✅ Optional summarization (long conversations)
- ✅ Suitable for: Chat interfaces, complex multi-turn queries

---

### 2.3 Pattern 3: Interactive ReAct SubAgent (User Approval)

**Use Case**: Multi-step workflows with human-in-the-loop

**Example**: TextFSMInteractiveAgent

**Implementation**:
```python
# src/olav/agents/textfsm_interactive_agent/deepagent.py
import logging
from typing import Any
from .config import get_config
from .template_cache import get_template_cache

logger = logging.getLogger(__name__)

class TextFSMInteractiveAgent:
    """Interactive ReAct agent with user approval steps."""
    
    def __init__(
        self,
        max_iterations: int = None,
        success_threshold: float = None,
    ):
        config = get_config()
        self.max_iterations = max_iterations or config.max_iterations
        self.success_threshold = success_threshold or config.success_threshold
        self.cache = get_template_cache()
    
    async def generate_with_ntc_references(
        self,
        raw_output: str,
        command_name: str,
        platform: str,
        approved_fields: list[str],  # 👈 From user approval
        ntc_references: list[str],
        sample_outputs: list[str] = None,
    ) -> dict[str, Any]:
        """Execute ReAct generation loop with caching."""
        
        # 1. Check cache first (0.2s fast path)
        cache_key = f"{platform}:{command_name}:{','.join(sorted(approved_fields))}"
        cached = self.cache.get(cache_key)
        if cached:
            logger.info(f"✅ Cache HIT: {cache_key}")
            return {
                "template": cached.template,
                "metrics": cached.metrics,
                "iterations": 0,
                "cached": True,
            }
        
        # 2. Execute ReAct loop
        history = []
        best_template = None
        best_success_rate = 0.0
        
        for iteration in range(1, self.max_iterations + 1):
            logger.info(f"ReAct iteration {iteration}/{self.max_iterations}")
            
            # Generate template (Tool: generate_template_tool)
            template = await self._generate_template(
                raw_output=raw_output,
                approved_fields=approved_fields,
                ntc_references=ntc_references,
                previous_errors=history[-1].get("errors", []) if history else [],
            )
            
            # Test template (Tool: test_template_tool)
            test_result = await self._test_template(
                template=template,
                sample_outputs=sample_outputs or [raw_output],
            )
            
            # Track best attempt
            if test_result["success_rate"] > best_success_rate:
                best_success_rate = test_result["success_rate"]
                best_template = template
            
            history.append({
                "iteration": iteration,
                "template": template,
                "success_rate": test_result["success_rate"],
                "errors": test_result.get("errors", []),
            })
            
            # Stop if threshold reached
            if test_result["success_rate"] >= self.success_threshold:
                logger.info(f"✅ Threshold reached ({best_success_rate:.2%})")
                break
        
        # 3. Cache successful result
        if best_success_rate >= self.success_threshold:
            self.cache.set(
                cache_key,
                template=best_template,
                metrics={"success_rate": best_success_rate},
                iterations=len(history),
            )
        
        return {
            "template": best_template,
            "metrics": {"parse_success": best_success_rate},
            "iterations": len(history),
            "final_success": best_success_rate >= self.success_threshold,
            "history": history,
        }
    
    async def _generate_template(self, **kwargs) -> str:
        """Tool function: Generate TextFSM template using LLM."""
        # Implementation: Call LLM with NTC references and approved fields
        pass
    
    async def _test_template(self, template: str, sample_outputs: list[str]) -> dict:
        """Tool function: Test template against sample outputs."""
        # Implementation: Use textfsm library to parse and calculate metrics
        pass
```

**6-Step Workflow** (Full Orchestrator Integration):
```python
# src/olav/agents/textfsm_interactive_agent/orchestrator.py
async def generate_textfsm_template(
    target_host: str,
    command: str,
    platform: str,
) -> dict[str, Any]:
    """6-step interactive workflow."""
    
    # Step 1: Execute command
    raw_output = await execute_command_tool(target_host, command)
    
    # Step 2: Analyze fields (LLM)
    analysis_result = await analyze_fields_tool(raw_output, command, platform)
    
    # Step 3: User approval (HITL)
    print(f"Detected fields: {analysis_result.detected_fields}")
    approval = await get_user_approval(analysis_result)  # Rich UI prompt
    
    # Step 4: Fetch NTC references
    ntc_refs = await get_ntc_references_tool(command, platform, approval.approved_fields)
    
    # Step 5: ReAct generation (DeepAgent)
    agent = TextFSMInteractiveAgent()
    result = await agent.generate_with_ntc_references(
        raw_output=raw_output,
        command_name=command,
        platform=platform,
        approved_fields=approval.approved_fields,
        ntc_references=ntc_refs,
    )
    
    # Step 6: Save template
    template_path = await save_template_tool(
        template=result["template"],
        command=command,
        platform=platform,
        metadata={"user": "admin", "iterations": result["iterations"]},
    )
    
    return {"template_path": template_path, "metrics": result["metrics"]}
```

**Characteristics**:
- ✅ User approval checkpoints (transparent workflow)
- ✅ Iterative improvement with error feedback
- ✅ Multi-dimensional quality metrics
- ✅ Suitable for: Code generation, template creation, config synthesis

---

## 🎯 Part 3: Orchestrator Integration

### 3.1 Creating Planning Orchestrator (Plan Mode)

**Function**: `create_planning_orchestrator()` in `orchestrator.py`

**Features**:
- TodoListMiddleware for task management
- write_todos / read_todos tools
- SubAgent coordination
- Optional summarization

**Implementation**:
```python
# src/olav/agents/orchestrator.py
def create_planning_orchestrator(
    user_id: str | None = None,
    thread_id: str | None = None,
    enable_summarization: bool | None = None,
):
    """Create orchestrator with TodoListMiddleware (Plan Mode)."""
    
    # 1. Check TodoListMiddleware availability
    try:
        from deepagents.middleware.todo import TodoListMiddleware
        from deepagents.tools.todo import write_todos, read_todos
        todolist_available = True
    except ImportError:
        logger.warning("TodoListMiddleware not available - using standard orchestrator")
        return create_orchestrator(user_id, thread_id, enable_summarization)
    
    # 2. Load SubAgents from OLAV.md
    from olav.core.subagent_loader import load_subagents_from_olav
    subagents = load_subagents_from_olav()
    
    # 3. Load orchestrator skill
    from olav.core.skill_loader import get_skill_loader
    loader = get_skill_loader()
    orch_skill = loader.get_skill("orchestrator")
    system_prompt = orch_skill.frontmatter.get("prompts", {}).get("system", "")
    
    # 4. Prepare tools (orchestrator's own + todo tools)
    from olav.tools.data_export import format_and_export
    orchestrator_tools = [format_and_export, write_todos, read_todos]
    
    # 5. Setup backend and middleware
    backend = get_composite_backend()
    middleware = [TodoListMiddleware()]
    
    if enable_summarization:
        from deepagents.middleware.summarization import SummarizationMiddleware
        summ_llm = LLMFactory.get_chat_model(temperature=0.1)
        middleware.append(
            SummarizationMiddleware(
                model=summ_llm,
                backend=backend,
                trigger=("tokens", 4000),
                keep=("messages", 10),
            )
        )
    
    # 6. Create orchestrator
    llm = LLMFactory.get_chat_model()
    agent = create_deep_agent(
        model=llm,
        system_prompt=system_prompt,
        tools=orchestrator_tools,
        subagents=subagents,
        middleware=middleware,
        backend=backend,
        checkpointer=None,  # Orchestrator doesn't persist (SubAgents do)
        store=None,
        name="orchestrator",
    )
    
    return agent
```

**Usage**:
```python
# CLI entry point
async def main():
    orchestrator = create_planning_orchestrator(
        user_id="admin",
        thread_id="plan_session_001",
    )
    
    result = await orchestrator.ainvoke({
        "messages": ["/plan export all OSPF interfaces to CSV"]
    })
    
    print(result["messages"][-1].content)
```

---

### 3.2 SubAgent Registration

**Dynamic Loading** from `.olav/OLAV.md`:

```python
# src/olav/core/subagent_loader.py
def load_subagents_from_olav(olav_path: Path | None = None) -> list[SubAgent]:
    """Load SubAgent configurations from OLAV.md."""
    
    # 1. Parse OLAV.md SubAgent Registry section
    content = olav_path.read_text()
    subagent_section = _extract_subagent_section(content)
    configs = _parse_subagent_configs(subagent_section)
    
    # 2. Build SubAgent instances
    subagents = []
    for config in configs:
        if not config.get("enabled", True):
            continue
        
        # Load from skill file
        skill_name = config["agent_skill"]
        system_prompt, tools = _load_from_skill(skill_name, config["name"])
        
        # Create SubAgent (DeepAgents native class)
        subagent = SubAgent(
            name=config["name"],
            description=config["description"],
            system_prompt=system_prompt,
            tools=tools,
        )
        subagents.append(subagent)
    
    return subagents

def _load_from_skill(skill_name: str, agent_name: str) -> tuple[str, list]:
    """Load system prompt and tools from SKILL.md."""
    loader = get_skill_loader()
    skill = loader.get_skill(skill_name)
    
    # Extract system prompt
    system_prompt = skill.frontmatter.get("prompts", {}).get("system", "")
    
    # Load tools
    adapter = SkillAdapter()
    tools = adapter.load_tools_from_skill(skill)
    
    return system_prompt, tools
```

**Benefits**:
- Zero-code SubAgent addition (edit OLAV.md + create SKILL.md)
- Centralized configuration management
- Easy enable/disable without code changes

---

## 💾 Part 4: Caching Strategy

### 4.1 Multi-Layer Cache Architecture

```
Layer 0: Semantic Cache (0.2s)
  └─→ Query embedding → Vector similarity → Cached result
       Location: .olav/cache/semantic_cache.db
       Use: Repeated similar queries

Layer 1: LLM Cache (0.5s)
  └─→ Prompt hash → Cached completion
       Location: .olav/cache/llm_cache.db (SQLiteCache)
       Use: Identical prompts (transparent caching)

Layer 2: Application Cache (variable)
  └─→ Query-specific caching (query_cache, template_cache)
       Location: Agent-specific
       Use: Structured results (SQL, templates)

Layer 3: Full Execution (15-50s)
  └─→ LLM reasoning + Tool execution
       Use: Novel queries, complex analysis
```

### 4.2 Semantic Cache Implementation

**Configuration** in SKILL.md:
```yaml
caching:
  enabled: true
  backend: semantic_cache
  ttl_seconds: 3600
  cache_key_fields: [query, schema_context]
  similarity_threshold: 0.85
```

**Usage** in SubAgent:
```python
from olav.core.query_cache import get_query_cache

class QuerySubAgent:
    def __init__(self):
        self.query_cache = get_query_cache()
    
    async def ainvoke(self, query: str):
        # Check cache
        cached = self.query_cache.get(query)
        if cached:
            logger.info(f"✅ Cache HIT: {query[:50]}")
            return cached
        
        # Execute agent
        result = await self.agent.ainvoke({"messages": [query]})
        
        # Store in cache
        self.query_cache.set(
            query,
            result,
            context={"schema": "main.devices"},
            metadata={"mode": "standard"},
        )
        
        return result
```

### 4.3 LLM Cache (SQLiteCache)

**Configuration** in `config/settings.py`:
```python
class Settings(BaseSettings):
    llm_cache_enabled: bool = True
    llm_cache_path: str = ".olav/cache/llm_cache.db"
```

**Auto-configured** in LLMFactory:
```python
# src/olav/core/llm.py
from langchain.cache import SQLiteCache
import langchain

class LLMFactory:
    @classmethod
    def configure_cache(cls):
        """Configure global LLM cache (transparent)."""
        if settings.llm_cache_enabled:
            cache_path = Path(settings.llm_cache_path)
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            langchain.llm_cache = SQLiteCache(database_path=str(cache_path))
```

**Benefits**:
- Transparent caching (no code changes)
- Prompt-level deduplication
- Cross-session reuse

---

## 🔧 Part 5: Third-Party LLM API Configuration

### 5.1 Problem: DeepAgents Default Uses OpenAI

**Issue**: DeepAgents expects OpenAI API by default, but OLAV uses third-party providers (OpenRouter, Groq, etc.)

**Solution**: Environment variable configuration + base URL override

### 5.2 Configuration Pattern (CRITICAL)

**Every SubAgent/Orchestrator MUST set environment variables**:

```python
# src/olav/agents/your_agent.py
import os
from config.settings import settings

class YourAgent:
    def __init__(self):
        # ⚠️ CRITICAL: Configure environment BEFORE creating LLM instances
        self._configure_llm_environment()
        
        # Now safe to create LLM instances
        self.llm = LLMFactory.get_chat_model()
    
    def _configure_llm_environment(self):
        """Auto-configure LLM API environment for third-party providers."""
        
        # Set OPENAI_API_KEY (DeepAgents/LangChain expect this)
        if settings.llm_api_key and not os.getenv("OPENAI_API_KEY"):
            os.environ["OPENAI_API_KEY"] = settings.llm_api_key
        
        # Set OPENAI_BASE_URL (override default OpenAI endpoint)
        if settings.llm_base_url and not os.getenv("OPENAI_BASE_URL"):
            os.environ["OPENAI_BASE_URL"] = settings.llm_base_url
        
        # Special handling for OpenRouter (x-ai/ model prefix)
        if settings.llm_base_url and "openrouter" in settings.llm_base_url.lower():
            if not os.getenv("OPENAI_MODEL_NAME"):
                os.environ["OPENAI_MODEL_NAME"] = settings.llm_model_name
```

### 5.3 Example .env Configuration

```bash
# .env file
LLM_API_KEY=sk-or-v1-xxx...
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL_NAME=x-ai/grok-beta

# Optional: Override for specific components
OPENAI_API_KEY=sk-or-v1-xxx...
OPENAI_BASE_URL=https://openrouter.ai/api/v1
OPENAI_MODEL_NAME=x-ai/grok-beta
```

### 5.4 Priority Order

```
Environment variables (OPENAI_*) 
  ↓ Highest priority
.env file (LLM_*)
  ↓
.olav/settings.json (llm_*)
  ↓
config/settings.py defaults
  ↓ Lowest priority
```

---

## 🎓 Part 6: Complete Example - Building a Custom SubAgent

### Step 1: Define SubAgent in OLAV.md

```yaml
### security
```yaml
---
name: security
agent_skill: network-security
description: Security audit specialist - vulnerability scanning, compliance checks
capabilities:
  - CVE vulnerability scanning
  - Configuration compliance (CIS benchmarks)
  - Access control audit (ACL, firewall rules)
  - Security baseline validation
enabled: true
---
```

### Step 2: Create SKILL.md

> 📖 **Tip**: See [02_skill_authoring_guide.md](02_skill_authoring_guide.md) for detailed SKILL.md writing best practices

```yaml
---
name: network-security
description: Security audit and compliance validation for network devices
version: 1.0.0
intent: inspection  # Maps to OLAV's agent routing

prompts:
  system: |
    You are a CISSP-certified network security specialist.
    
    ## Capabilities
    - CVE database queries
    - Configuration compliance validation
    - Access control audits
    
    ## Response Format
    Provide findings in markdown with severity levels (CRITICAL, HIGH, MEDIUM, LOW).

tools:
  - name: scan_vulnerabilities
    module: olav.tools.security
    function: scan_cve_database
    description: Scan device versions against CVE database
    
  - name: check_compliance
    module: olav.tools.security
    function: validate_cis_benchmark
    description: Validate configuration against CIS benchmarks
    
  - name: audit_access_control
    module: olav.tools.security
    function: analyze_acl_rules
    description: Analyze ACL and firewall rules

caching:
  enabled: true
  backend: semantic_cache
  ttl_seconds: 7200

agent:
  max_iterations: 15
  temperature: 0.2
---

# Security Audit Guide

## CVE Scanning
Query the CVE database for known vulnerabilities...

## Compliance Validation
CIS benchmarks for network devices...
```

### Step 3: Implement Tool Functions

```python
# src/olav/tools/security.py
"""Security audit tools for network devices."""

import logging
from typing import Any

logger = logging.getLogger(__name__)

async def scan_cve_database(
    vendor: str,
    product: str,
    version: str,
) -> dict[str, Any]:
    """Scan CVE database for vulnerabilities.
    
    Args:
        vendor: Device vendor (cisco, juniper, arista)
        product: Product line (ios, nxos, eos)
        version: Software version
    
    Returns:
        Dictionary with CVE findings
    """
    # Implementation: Query CVE API
    return {
        "vendor": vendor,
        "product": product,
        "version": version,
        "vulnerabilities": [
            {"cve_id": "CVE-2023-12345", "severity": "HIGH", "description": "..."},
        ],
    }

async def validate_cis_benchmark(
    device_name: str,
    config_lines: list[str],
) -> dict[str, Any]:
    """Validate configuration against CIS benchmarks.
    
    Args:
        device_name: Target device
        config_lines: Configuration lines to validate
    
    Returns:
        Compliance report
    """
    # Implementation: Parse config and validate against CIS rules
    return {
        "device": device_name,
        "benchmark": "CIS Cisco IOS v3.0",
        "compliance_score": 0.87,
        "violations": [
            {"rule": "2.1.1", "description": "Enable password encryption", "severity": "MEDIUM"},
        ],
    }

async def analyze_acl_rules(
    device_name: str,
    acl_name: str,
) -> dict[str, Any]:
    """Analyze ACL rules for security issues.
    
    Args:
        device_name: Target device
        acl_name: ACL name to analyze
    
    Returns:
        Security analysis report
    """
    # Implementation: Parse ACL and detect issues
    return {
        "device": device_name,
        "acl": acl_name,
        "findings": [
            {"type": "OVERLY_PERMISSIVE", "rule": "permit ip any any", "line": 10},
        ],
    }
```

### Step 4: Test SubAgent

```python
# tests/e2e/test_security_subagent.py
import pytest
from olav.agents.orchestrator import orchestrate_query

@pytest.mark.asyncio
async def test_security_audit():
    """Test security audit workflow."""
    
    query = "scan all devices for CVE vulnerabilities and generate a report"
    
    result = await orchestrate_query(query)
    
    assert result["status"] == "complete"
    assert "CVE" in result["final_answer"]
    assert "severity" in result["final_answer"].lower()
```

### Step 5: Usage

```bash
# CLI
$ olav query "audit security for router-01"

# Programmatic
from olav.agents.orchestrator import orchestrate_query

result = await orchestrate_query("scan all routers for high-severity CVEs")
print(result["final_answer"])
```

---

## 📊 Part 7: Testing Guidelines

### 7.1 Real E2E Testing (Not Mocks)

**Rule**: Test actual user workflows, not component existence

**Example** (Good E2E Test):
```python
# tests/e2e/test_real_scenarios.py
@pytest.mark.asyncio
async def test_export_devices_version_no_cli_execution():
    """
    User Story: Export all devices' version info to CSV
    
    Acceptance Criteria:
    1. Query succeeds
    2. CSV file is created
    3. NO CLI commands executed (pure database query)
    4. Uses main.duckdb, not olav.duckdb
    """
    cli_tracker = CLICommandTracker()
    db_monitor = DatabaseAccessMonitor()
    
    with cli_tracker, db_monitor:
        result = await orchestrate_query(
            "save all devices' version info to a csv file"
        )
        
        assert result["status"] == "complete"
    
    # Verify no unauthorized CLI execution
    cli_tracker.assert_no_commands()
    
    # Verify correct database accessed
    db_monitor.assert_correct_db("main.duckdb")
    
    # Verify CSV file created
    csv_files = list(Path("exports").glob("devices_*.csv"))
    assert len(csv_files) > 0
```

**Example** (Bad E2E Test - Deprecated):
```python
# ❌ DEPRECATED: Mock-heavy, doesn't test real scenarios
def test_query_agent_exists():
    """Test that QueryAgent can be instantiated."""
    agent = QueryAgent()
    assert agent is not None
```

### 7.2 Test Utilities

```python
# tests/e2e/utils/monitors.py
class CLICommandTracker:
    """Monitor CLI execution during tests."""
    
    def __init__(self):
        self.commands = []
    
    def __enter__(self):
        # Monkey-patch CLI execution functions
        self._patch_cli()
        return self
    
    def __exit__(self, *args):
        self._unpatch_cli()
    
    def assert_no_commands(self):
        """Fail test if any CLI commands executed."""
        assert len(self.commands) == 0, f"Unexpected CLI commands: {self.commands}"

class DatabaseAccessMonitor:
    """Monitor which databases are accessed."""
    
    def assert_correct_db(self, expected_db: str):
        """Fail if wrong database accessed."""
        assert any(expected_db in db for db in self.accesses)
```

### 7.3 Running Tests

```bash
# Run real E2E tests (new standard)
uv run pytest tests/e2e/test_real_scenarios.py -v

# Run specific test
uv run pytest tests/e2e/test_real_scenarios.py::TestRealUserScenarios::test_export_devices_version_no_cli_execution -v

# Full test suite (includes unit + integration)
uv run pytest tests/ -v --tb=short
```

---

## 🚀 Part 8: Deployment Checklist
 (See [02_skill_authoring_guide.md](02_skill_authoring_guide.md))
  - [ ] OLAV.md entry created
  - [ ] SKILL.md with all required fields (name, description, intent)
  - [ ] System prompt is concise (<400 lines)
  - [ ] Uses schema discovery (NOT hardcoded schema)
- [ ] **Configuration**
  - [ ] OLAV.md entry created
  - [ ] SKILL.md with all required fields
  - [ ] Tools registered in skill
  - [ ] Caching configuration defined

- [ ] **Implementation**
  - [ ] LLM environment configured (`_configure_llm_environment()`)
  - [ ] CompositeBackend integrated
  - [ ] Proper error handling
  - [ ] Logging statements added

- [ ] **Testing**
  - [ ] Real E2E tests written (not mocks)
  - [ ] Side effects monitored (CLI, DB access)
  - [ ] Cache hit/miss tested
  - [ ] All tests pass

- [ ] **Documentation**
  - [ ] Tool function docstrings complete
  - [ ] SKILL.md examples added
  - [ ] README updated (if applicable)

---

## 🔮 Part 9: Advanced Patterns

### 9.1 SubAgent Composition

**Pattern**: SubAgent calls another SubAgent

```python
# Expert SubAgent delegating to Query SubAgent
async def analyze_topology(device_group: str):
    # Call query SubAgent for data
    query_result = await orchestrator.route_to_subagent(
        "query",
        f"get all devices in group {device_group}",
    )
    
    # Analyze data
    devices = parse_query_result(query_result)
    topology = build_topology_graph(devices)
    
    return topology
```

### 9.2 Parallel SubAgent Execution

**Pattern**: Run multiple SubAgents concurrently

```python
# Phase 5: Collaborative Mode (from PHASE_5_COLLABORATIVE_MODE.md)
async def collaborative_analysis(device_name: str):
    """Parallel SubAgent execution with dependency management."""
    
    # Define dependencies
    dependencies = [
        {"agent": "query", "depends_on": []},
        {"agent": "expert", "depends_on": ["query"]},
        {"agent": "cli", "depends_on": ["expert"]},
    ]
    
    # Topological sort
    execution_order = _topological_sort(dependencies)
    
    # Execute in parallel where possible
    results = {}
    for agent_name in execution_order:
        deps = _get_dependencies(agent_name, dependencies)
        context = {dep: results[dep] for dep in deps}
        
        results[agent_name] = await orchestrator.route_to_subagent(
            agent_name,
            query=f"analyze {device_name}",
            context=context,
        )
    
    return results
```

### 9.3 Tool Fallback Chain

**Pattern**: Try primary tool, fallback to secondary

```python
async def smart_query(query: str):
    """Query with intelligent fallback."""
    
    # Try database query
    try:
        result = await query_database(query)
        if result["rows"]:
            return result
    except Exception as e:
        logger.warning(f"Database query failed: {e}")
    
    # Fallback to CLI execution
    logger.info("Falling back to CLI execution")
    retuDocumentation
- ⭐ **Skill Authoring Guide**: [docs/02_skill_authoring_guide.md](02_skill_authoring_guide.md) - **How to write SKILL.md files**
- **Architecture Guide**: [docs/architecture_correct_understanding.md](architecture_correct_understanding.md)
- **Audit Report**: [docs/99_audit.md](99_audit.md)
- **Plan Mode**: [docs/plan_mode_architecture.md](plan_mode_architecture.md)

### Key Files
- **SubAgent Loader**: `src/olav/core/subagent_loader.py`
- **Orchestrator**: `src/olav/agents/orchestrator.py`
- **QueryAgent**: `src/olav/agents/query_agent.py`
- **TextFSM Agent**: `src/olav/agents/textfsm_interactive_agent/`
- **Storage Backend**: `src/olav/core/storage.pyteractive_agent/`
- **Storage Backend**: `src/olav/core/storage.py`

### Documentation
- **Architecture Guide**: `docs/architecture_correct_understanding.md`
- **Skill Authoring**: `docs/02_skill_authoring_guide.md`
- **Audit Report**: `docs/99_audit.md`
- **Plan Mode**: `docs/plan_mode_architecture.md`

### DeepAgents References
- Official Docs: (Check internal DeepAgents documentation)
- Middleware: TodoListMiddleware, SummarizationMiddleware, SubAgents
- Backends: CompositeBackend, FilesystemBackend, StateBackend
- Checkpoints: DuckDBSaver, DuckDBStore (LangGraph)

---

## 🎯 Quick Reference Card

### Orchestrator (Plan Mode)
```python
orchestrator = create_planning_orchestrator(user_id, thread_id)
# ✅ TodoListMiddleware
# ✅ write_todos / read_todos tools
# ✅ SubAgent routing
```

### SubAgent (ReAct Mode)
```python
agent = create_deep_agent(
    model=llm,
    system_prompt=prompt,
    tools=tools,
    backend=backend,
    checkpointer=checkpointer,  # Optional: DuckDBSaver
    store=store,                # Optional: DuckDBStore
    middleware=[],              # Optional: SummarizationMiddleware
)
```

### Configuration Priority
```
.env > .olav/settings.json > SKILL.md > settings.py
```

### Caching Layers
```
Semantic (0.2s) → LLM (0.5s) → App (variable) → Full Execution (15-50s)
```

---

**Version**: v1.0.0  
**Last Updated**: 2026-02-08  
**Status**: ✅ Production Ready
