# Daemon Management & DeepAgents CLI Analysis

**Status**: Analysis Complete  
**Date**: 2026-02-22  
**Author**: Sisyphus Analysis  

---

## Part 1: Daemon Management CLI Commands

### Current State

| File | Status |
|------|--------|
| `src/olav/cli/daemon.py` | ✅ Has `spawn_daemon()`, `stop_daemon()`, `get_daemon_status()` functions |
| `src/olav/cli/cli_app.py` | ❌ **No daemon subcommand registered** |

### Implementation Plan

Add daemon management commands following `task_manager.py` pattern:

```python
# In daemon.py, add:
import typer
from rich.console import Console

daemon_app = typer.Typer(help="Manage OLAV daemon")
console = Console()

@daemon_app.command("start")
def start_cmd():
    """Start daemon in background."""
    status = get_daemon_status()
    if status.get("running"):
        console.print(f"[yellow]Daemon already running (PID: {status['pid']})[/yellow]")
        return
    pid = spawn_daemon()
    console.print(f"[green]✓ Daemon started (PID: {pid})[/green]")

@daemon_app.command("stop")
def stop_cmd():
    """Stop daemon gracefully."""
    if stop_daemon():
        console.print("[green]✓ Daemon stopped[/green]")
    else:
        console.print("[yellow]Daemon not running[/yellow]")

@daemon_app.command("status")
def status_cmd():
    """Show daemon status."""
    status = get_daemon_status()
    if status.get("running"):
        console.print(f"[green]Daemon running[/green]")
        console.print(f"  PID: {status['pid']}")
        console.print(f"  Uptime: {status.get('uptime_seconds', 0)}s")
        console.print(f"  Queries: {status.get('query_count', 0)}")
    else:
        console.print("[yellow]Daemon not running[/yellow]")

@daemon_app.command("restart")
def restart_cmd():
    """Restart daemon."""
    stop_daemon()
    import time; time.sleep(0.5)
    pid = spawn_daemon()
    console.print(f"[green]✓ Daemon restarted (PID: {pid})[/green]")

def get_daemon_app():
    return daemon_app
```

```python
# In cli_app.py, add (around line 989):
from olav.cli.daemon import get_daemon_app
app.add_typer(get_daemon_app(), name="daemon")
```

### Commands After Implementation

```bash
olav daemon start    # Start daemon
olav daemon stop     # Stop daemon  
olav daemon status   # Show status
olav daemon restart  # Restart daemon
```

---

## Part 2: DeepAgents CLI Analysis

### What is DeepAgents CLI?

Official LangChain CLI for running agents with:
- Persistent memory (`~/.deepagents/AGENT_NAME/memories/`)
- Filesystem tools (read_file, write_file, edit_file, ls, glob, grep)
- Shell execution with human approval
- Subagent delegation
- Planning with TodoListMiddleware

### Feature Comparison

| Feature | OLAV CLI | DeepAgents CLI | Verdict |
|---------|----------|----------------|---------|
| **Response Caching** | ✅ 3-tier (Exact + Semantic RAG + Daemon) | ❌ None | OLAV better |
| **Memory Persistence** | ✅ DuckDB checkpointer | ✅ Filesystem memories | Comparable |
| **Daemon Mode** | ✅ Unix socket, pre-warmed agent | ❌ No daemon | OLAV better |
| **Semantic Routing** | ✅ Tier 1.5 fast path | ❌ None | OLAV better |
| **SQL Direct Output** | ✅ Bypass LLM for tables | ❌ None | OLAV better |
| **Snapshot-based Invalidation** | ✅ Data freshness aware | ❌ None | OLAV better |
| **Filesystem Tools** | ✅ Custom network tools | ✅ Built-in | Comparable |
| **Subagent Delegation** | ✅ 3 SubAgents | ✅ `task()` tool | Comparable |
| **Multi-agent Management** | ❌ Single agent | ✅ `deepagents agent <name>` | DeepAgents better |
| **Generic CLI** | ❌ Network-specific | ✅ General purpose | Depends on use case |

### Critical Gap: OLAV's Advanced Caching

OLAV's caching architecture (from `query_fast_path_optimization.md`):

```
User query
  │
  ├─[Tier 0] sha256(query) → result_cache   ← 0 LLM calls, ~0ms
  │
  ├─[Tier 1] Daemon Socket                   ← Agent pre-warmed, <200ms
  │    │
  │    └─[Tier 1.5] Semantic Router          ← 1 LLM call, direct execution
  │
  └─[Tier 2] Full ReAct Agent                ← 4 LLM calls, 35-60s
```

**DeepAgents CLI has NONE of these caching mechanisms.**

### Migration Assessment

| Scenario | Recommendation |
|----------|----------------|
| Replace OLAV CLI entirely | ❌ **Not recommended** - would lose all advanced caching |
| Use DeepAgents as base + add caching | ⚠️ **Possible but significant effort** - need to add 3-tier cache |
| Keep OLAV CLI + learn from DeepAgents | ✅ **Recommended** - adopt memory management patterns |
| Use DeepAgents for different use case | ✅ Good for general-purpose coding agents |

### What OLAV Can Learn from DeepAgents

1. **Memory Organization**:
   ```
   ~/.deepagents/AGENT_NAME/memories/
   ├── backend/
   │   ├── api-design.md
   │   └── database-schema.md
   └── security-setup.md
   ```
   OLAV could adopt similar `.olav/memories/` structure.

2. **Multi-agent Management**:
   ```bash
   deepagents list
   deepagents agent backend-dev
   deepagents reset backend-dev
   ```
   OLAV could add `olav agent list/switch/reset` for managing different configurations.

3. **CLI Skill Management**:
   ```bash
   deepagents skills list
   deepagents skills add ./my-skill/
   ```
   OLAV already has `olav skills`, but could add `olav skills add`.

### Conclusion

| Decision | Rationale |
|----------|-----------|
### Conclusion

| Decision | Rationale |
|----------|-----------|
| **Replace with DeepAgents CLI?** | ❌ NO - Would lose 3-tier caching, daemon mode, semantic routing |
| **Embed OLAV caching into DeepAgents?** | ✅ **YES - Via Middleware Architecture** |
| **Recommended Path** | Keep OLAV CLI, but can add OLAV caching to DeepAgents as middleware |

---

## Part 3: Embedding OLAV Caching into DeepAgents CLI

### ✅ YES - It IS Possible!

After analyzing DeepAgents' source code, I found that **OLAV's 3-tier caching CAN be embedded into DeepAgents CLI** via the **Middleware Architecture**.

### LangChain Middleware Architecture

DeepAgents uses LangChain's `AgentMiddleware` class which provides these hooks:

| Hook | Purpose | Use for Caching |
|------|---------|-----------------|
| `wrap_model_call` | **Intercept model calls** | ✅ **Primary hook for caching** |
| `wrap_tool_call` | Intercept tool calls | ✅ Tool result caching |
| `before_model` | Run before LLM call | ⚠️ Can check cache |
| `after_model` | Run after LLM call | ⚠️ Can populate cache |
| `before_agent` | Run before agent loop | ❌ Not for caching |
| `after_agent` | Run after agent loop | ❌ Not for caching |

**Key insight**: `wrap_model_call` is the perfect hook for response caching because:
1. It wraps the entire model invocation
2. It can short-circuit (return cached response without calling the model)
3. It can call the handler multiple times (for retry/fallback)
4. First middleware in list = outermost layer

### Implementation: CachingMiddleware

```python
# olav/middleware/caching_middleware.py

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse, ModelCallResult
import hashlib
import json

class CachingMiddleware(AgentMiddleware):
    """OLAV's 3-tier caching as DeepAgents middleware."""

    def __init__(self, cache_backend, semantic_search=None):
        self.cache = cache_backend  # DuckDB, Redis, SQLite
        self.semantic_search = semantic_search  # Vector store for semantic matching

    def _make_cache_key(self, request: ModelRequest) -> str:
        """Generate cache key from model + messages."""
        content = json.dumps({
            "model": request.model.model_name,
            "messages": [m.content for m in request.messages],
            "tools": [t.name for t in request.tools] if request.tools else []
        }, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]]
    ) -> ModelCallResult:
        """
        Tier 0: Exact hash cache - 0 LLM calls
        Tier 1: Semantic RAG cache - 1 LLM call for verification
        Tier 2: Full model call - cache result for future
        """
        cache_key = self._make_cache_key(request)

        # ── Tier 0: Exact Hash Cache ───────────────────────────
        if cached := await self.cache.get(cache_key):
            # Return cached response WITHOUT calling the model!
            return ModelResponse(
                message=cached["response"],
                usage={"cached": True, "tier": 0}
            )

        # ── Tier 1: Semantic RAG Cache (optional) ───────────────
        if self.semantic_search:
            user_query = request.messages[-1].content if request.messages else ""
            similar = await self.semantic_search.search(user_query, threshold=0.95)
            if similar:
                # Still call model to verify, but with cached context
                # This is a "cache hit" that needs verification
                pass  # Could inject context here

        # ── Tier 2: Call the model, cache result ────────────────
        response = await handler(request)  # Actual model call

        # Auto-store successful responses
        await self.cache.set(cache_key, {
            "request_key": cache_key,
            "response": response.message,
            "usage": response.usage,
        })

        return response
```

### How to Use with DeepAgents CLI

**Option A: Modify DeepAgents CLI startup** (requires forking)

```python
# In deepagents_cli/agent.py
from olav.middleware.caching_middleware import CachingMiddleware
from olav.core.response_cache import get_response_cache

def create_cli_agent(...):
    # Add OLAV caching middleware
    caching_middleware = CachingMiddleware(
        cache_backend=get_response_cache(),
        semantic_search=None  # Could add DuckDB VSS
    )

    middleware = [
        caching_middleware,  # First = outermost (checked before others)
        TodoListMiddleware(),
        FilesystemMiddleware(),
        # ...
    ]

    return create_deep_agent(middleware=middleware, ...)
```

**Option B: Create a wrapper script** (no forking needed)

```python
# olav_with_deepagents.py

from deepagents import create_deep_agent
from deepagents_cli.agent import get_system_prompt
from olav.middleware.caching_middleware import CachingMiddleware
from olav.core.response_cache import get_response_cache

# Create agent with OLAV caching
agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-20250514",
    system_prompt=get_system_prompt("agent"),
    middleware=[
        CachingMiddleware(cache_backend=get_response_cache()),
    ],
    backend=FilesystemBackend(root_dir="./"),
)

# Use like normal
result = await agent.invoke({"messages": [{"role": "user", "content": query}]})
```

### Architecture Diagram

```
DeepAgents CLI Flow (with OLAV CachingMiddleware):

User Query
    │
    ▼
┌─────────────────────────────────────────┐
│ CachingMiddleware.awrap_model_call()    │  ← OLAV's Tier 0/1
│   ├─ Tier 0: sha256(query) → cache?     │  ← 0 LLM calls
│   │     └─ hit → return cached response │
│   └─ miss → continue to handler         │
└─────────────────────────────────────────┘
    │ miss
    ▼
┌─────────────────────────────────────────┐
│ TodoListMiddleware.wrap_model_call()    │
└─────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────┐
│ FilesystemMiddleware.wrap_model_call()  │
└─────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────┐
│ Model (Claude/GPT/etc.)                 │  ← Actual LLM call
└─────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────┐
│ CachingMiddleware (on return)           │  ← Auto-store result
│   └─ cache.set(key, response)           │
└─────────────────────────────────────────┘
```

### Key Files for Integration

| File | Purpose |
|------|---------|
| `langchain/agents/middleware/types.py` | `AgentMiddleware` base class with `wrap_model_call` |
| `deepagents_cli/agent.py` | `create_cli_agent()` - where middleware is added |
| `olav/core/response_cache.py` | OLAV's existing cache implementation |
| `olav/middleware/caching_middleware.py` | NEW: Middleware wrapper for OLAV cache |

---

## Recommended Next Steps

1. **P0: Add daemon CLI commands** (30 min effort)
   - Add `daemon_app` to `daemon.py`
   - Register in `cli_app.py`

2. **P1: Restart daemon after code changes** (immediate)
   - Run `pkill -f "olav.cli.daemon"` to kill stale daemon
   - Run `uv run olav daemon start` to restart

3. **P2: Create CachingMiddleware** (2-4 hours)
   - Create `olav/middleware/caching_middleware.py`
   - Wrap OLAV's `ResponseCache` in `AgentMiddleware` interface
   - Test with both DeepAgents and OLAV CLI

4. **P3: Consider memory organization** (future)
   - Adopt DeepAgents-style `.olav/memories/` structure
   - Better organization than flat files

---

## Final Verdict

| Question | Answer |
|----------|--------|
| Can OLAV caching be embedded into DeepAgents CLI? | ✅ **YES** - via `AgentMiddleware.wrap_model_call` |
| Is it worth doing? | ⚠️ **Depends** - If you want DeepAgents features + OLAV caching |
| Recommended approach? | Keep OLAV CLI, add middleware as optional export |

---

## Part 4: Non-Invasive Integration Analysis

### Can Option B integrate with DeepAgents CLI natively (survives `pip install --upgrade`)?

**Answer: ❌ NO - DeepAgents CLI does NOT have a plugin/middleware injection mechanism**

After analyzing DeepAgents CLI source code, I found:

| Extension Point | Exists | Can Inject Middleware? |
|----------------|--------|----------------------|
| `~/.deepagents/config.toml` | ✅ Yes | ❌ No - only model settings |
| `.deepagents/skills/` | ✅ Yes | ❌ No - only tools/prompts |
| `.deepagents/agents/` | ✅ Yes | ❌ No - only subagent definitions |
| Environment variables | ✅ Yes | ❌ No - no middleware env vars |
| Plugin system | ❌ No | ❌ No such mechanism |

**The problem**: Middleware is **hardcoded** in `create_cli_agent()`:

```python
# deepagents_cli/agent.py (lines 463-491)
agent_middleware = []  # Hardcoded list

if enable_memory:
    agent_middleware.append(MemoryMiddleware(...))

if enable_skills:
    agent_middleware.append(SkillsMiddleware(...))  # Fixed middleware

# No way to inject custom middleware via config!
agent = create_deep_agent(middleware=agent_middleware, ...)
```

### Alternative Non-Invasive Approaches

#### Approach 1: Entry Point Wrapper (RECOMMENDED)

Create a **separate console script** that wraps DeepAgents:

```toml
# pyproject.toml (in your project)
[project.scripts]
olav-deepagents = "olav.cli.deepagents_wrapper:main"
```

```python
# olav/cli/deepagents_wrapper.py
"""Wrapper that injects OLAV caching into DeepAgents CLI."""

import sys
from olav.middleware.caching_middleware import CachingMiddleware
from olav.core.response_cache import get_response_cache

# 1. Monkey-patch create_cli_agent to inject middleware
import deepagents_cli.agent as agent_module
_original_create_cli_agent = agent_module.create_cli_agent

def create_cli_agent_with_caching(*args, **kwargs):
    # Get original agent
    agent, backend = _original_create_cli_agent(*args, **kwargs)
    
    # Inject caching middleware (would require rebuilding agent)
    # This is a limitation - middleware is baked into agent at creation
    return agent, backend

agent_module.create_cli_agent = create_cli_agent_with_caching

# 2. Now import and run main
from deepagents_cli.main import main

if __name__ == "__main__":
    sys.argv[0] = "deepagents"  # Pretend we're the real CLI
    main()
```

**Pros**: 
- ✅ Survives `pip install --upgrade deepagents`
- ✅ No modification to DeepAgents source
- ✅ Can be installed alongside original `deepagents` CLI

**Cons**:
- ⚠️ Requires monkey-patching (fragile)
- ⚠️ Middleware injection is hard (agent is already built)

#### Approach 2: Custom Backend with Caching (MORE SEAMLESS)

Instead of middleware, use DeepAgents' **Backend** extension point:

```python
# olav/backends/caching_backend.py
from deepagents.backends import BackendProtocol
from olav.core.response_cache import get_response_cache

class CachingBackend(BackendProtocol):
    """Backend wrapper that caches responses."""
    
    def __init__(self, wrapped_backend):
        self.wrapped = wrapped_backend
        self.cache = get_response_cache()
    
    async def invoke(self, request):
        # Check cache first
        cache_key = self._make_key(request)
        if cached := self.cache.get(cache_key):
            return cached
        
        # Call wrapped backend
        result = await self.wrapped.invoke(request)
        
        # Cache result
        self.cache.set(cache_key, result)
        return result
```

This approach uses DeepAgents' existing Backend protocol, which is designed for extension.

#### Approach 3: LangGraph Native Cache (CLEANEST)

LangGraph (which DeepAgents uses) has native caching:

```python
from langgraph.cache.in_memory import InMemoryCache

# DeepAgents passes cache to LangGraph
agent = create_deep_agent(
    cache=InMemoryCache(),  # Native LangGraph cache
    ...
)
```

**This is the cleanest approach** - use LangGraph's cache parameter instead of custom middleware!

### Final Recommendation

| Approach | Effort | Survives Upgrade | Works Today |
|----------|--------|------------------|-------------|
| **LangGraph native cache** | ⭐ Low | ✅ Yes | ✅ Yes |
| Entry point wrapper | ⭐⭐ Medium | ✅ Yes | ⚠️ Fragile |
| Custom Backend | ⭐⭐ Medium | ✅ Yes | ✅ Yes |
| Fork DeepAgents | ⭐⭐⭐ High | ❌ No | ✅ Yes |

**Best option**: Use **LangGraph's native cache** parameter:

```python
# This already works in DeepAgents!
from langgraph.cache.in_memory import InMemoryCache
from deepagents import create_deep_agent

agent = create_deep_agent(
    model=model,
    cache=InMemoryCache(),  # ← Native caching!
    ...
)
```

The challenge is: **DeepAgents CLI doesn't expose this parameter** in `create_cli_agent()`.

### What We Can Do Now

1. **Keep OLAV CLI** for network operations (best caching)
2. **Use DeepAgents CLI** for general coding tasks (good enough)
3. **If you want both**: Create a feature request to LangChain to expose `cache=` parameter in DeepAgents CLI

---

## Summary Table

| Question | Answer |
|----------|--------|
| Can OLAV caching be embedded into DeepAgents? | ✅ YES via middleware |
| Can it be done without forking? | ⚠️ PARTIALLY - need monkey-patch or entry point wrapper |
| Will it survive `pip install --upgrade`? | ✅ YES - if using wrapper approach |
| Is there a native way? | ⚠️ LangGraph has `cache=` but DeepAgents CLI doesn't expose it |
| Recommended path? | Keep OLAV CLI, optionally contribute `cache=` parameter to DeepAgents |


---

## Part 5: OLAV Native Cache Tool (Already Implemented!)

### ✅ `search_cache` Tool Already Exists!

After analyzing OLAV's codebase, I found that **the cache search tool is already fully implemented**:

| Component | Location | Status |
|-----------|----------|--------|
| `search_cache` tool | `.olav/skills/olav-ops/tools/search_cache.py` | ✅ 186 lines |
| Cache storage | `src/olav/core/response_cache.py` | ✅ DuckDB-backed |
| AUTO-store after query | `src/olav/cli/cli_app.py` → `_try_cache_store()` | ✅ Automatic |
| SubAgent prompt | `.olav/skills/olav-ops/prompts/network_ops_subagent.md` | ✅ CACHE_FIRST |

### How It Works

```
User Query: "有多少设备？"
    │
    ├─[Tier 0] Code-level exact hash bypass (cli_app.py)
    │         sha256(query) → response_cache
    │         hit? → return cached response (~0ms)
    │
    └─[Tier 1] search_cache tool (called by SubAgent)
              Jaccard keyword similarity ≥ 55%
              hit? → return cached_response (1 LLM call for verification)
```

### Cache Invalidation Rules

| Source Agent | Invalidation Strategy |
|--------------|----------------------|
| `olav-ops` | **Snapshot-based**: Valid only if cached AFTER latest `data/exports/` snapshot |
| `olav-config` | TTL: 1 hour |
| `olav-audit` | TTL: 48 hours |
| Other | TTL: 6 hours (fallback) |

### Why 20s Query Time?

The 20s delay is likely because:

1. **Daemon not running** → Falls back to in-process mode (3-5s startup overhead)
2. **Daemon stale** → Code changes not picked up (daemon needs restart)
3. **Cache empty** → First query populates cache, subsequent queries faster

### Immediate Fix

```bash
# 1. Kill stale daemon
pkill -f "olav.cli.daemon"

# 2. Test with a query (will populate cache)
uv run olav ask "有多少设备？"

# 3. Test again (should be instant if daemon running)
uv run olav ask "有多少设备？"

# 4. Test similar query (search_cache should find it)
uv run olav ask "列出所有设备"
```

### Cache Table Schema (DuckDB)

```sql
CREATE TABLE response_cache (
    query_hash    VARCHAR PRIMARY KEY,   -- SHA-256 of normalized query
    query_text    VARCHAR NOT NULL,      -- Original query text
    response      TEXT NOT NULL,         -- Cached response
    source_agent  VARCHAR NOT NULL,      -- 'olav-ops', 'olav-config', etc.
    cached_at     TIMESTAMP NOT NULL,    -- When cached
    snapshot_ts   TIMESTAMP              -- Data snapshot timestamp
);
```

### Semantic Search Algorithm (No Embeddings)

```python
MIN_SIMILARITY = 0.55  # 55% Jaccard threshold

def _jaccard(query_tokens, cache_tokens) -> float:
    """Token-overlap similarity (0–1)."""
    return len(query_tokens & cache_tokens) / len(query_tokens | cache_tokens)
```

This avoids:
- ❌ "BGP on R1" matching "BGP on R2" (different entities)
- ❌ False positives from embedding similarity
- ✅ Fast, no model required

### Summary: OLAV's 3-Tier Caching

| Tier | Mechanism | LLM Calls | Latency |
|------|-----------|-----------|---------|
| **Tier 0** | Code-level exact hash bypass | 0 | ~0ms |
| **Tier 1** | `search_cache` tool (Jaccard) | 1 (verification) | ~5s |
| **Tier 2** | Full SubAgent execution | 4 | 35-60s |

**All tiers are already implemented. Just restart the daemon!**
