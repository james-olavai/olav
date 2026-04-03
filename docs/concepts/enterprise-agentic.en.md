# Enterprise Agentic Platform

OLAV is not just an AI chat tool -- it is a complete **Enterprise Agentic Platform** with multi-layer memory and caching, multi-user isolation, audit-driven LLM fine-tuning, and a federated Specialist Agent architecture. This page systematically introduces these production-grade features along with measured performance data.

!!! abstract "Feature Claims"
    | ID | Claim | Status |
    |----|-------|--------|
    | C-L2-38 | Per-Agent model assignment (`agent_overrides`) | ✅ v0.10.0 |
    | C-L2-22 | Audit data export in training formats (trajectory/sft/atif) | ✅ v0.10.0 |
    | C-L2-12 | Multi-user concurrent audit with no write conflicts | ✅ v0.10.0 |
    | C-L2-21 | Knowledge base semantic search (vector + BM25 hybrid) | ✅ v0.10.0 |

---

## Multi-Layer Agentic Architecture

```
User request
    |
+---------------------------------------------+
|  Tier-0  SemanticCache (LanceDB)             |  <- Vector similarity hit, 10ms response
|  Identical semantic queries never trigger     |
|  any LLM call                                |
+---------------------------------------------+
    | miss
+---------------------------------------------+
|  Tier-1  LLM SQLiteCache                    |  <- Exact prompt hit, <1ms response
|  Same conversation context avoids            |
|  redundant API calls                         |
+---------------------------------------------+
    | miss
+---------------------------------------------+
|  Tier-2  LLM API Call (OpenAI / OpenRouter)  |  <- Actual network request, ~2-30s
+---------------------------------------------+
    | result
+---------------------------------------------+
|  Episodic Memory (LanceDB)                  |  <- Run results written to long-term memory
|  LangGraph Checkpoint (DuckDB)              |  <- Conversation state persisted
|  Audit Log (audit.duckdb)                   |  <- Fully auditable trace
+---------------------------------------------+
```

---

## Multi-Layer Caching in Detail

### Tier-1: LLM SQLiteCache (Exact Match)

Each user has an independent SQLite cache at `~/.olav/cache/{username}/llm_cache.db`. When an Agent sends the exact same prompt, the response is returned directly from the local database with **zero token consumption**.

**Measured Performance (2026-04-03, model: x-ai/grok-4.1-fast):**

| Scenario | Response Time | Token Consumption | Speedup |
|----------|--------------|-------------------|---------|
| Cold call (no cache) | 2.78s | 323 tokens (in: 171 + out: 152) | baseline |
| Hot call (SQLiteCache hit) | **0.001s** | **0 tokens** | **2259x** |

```bash
# Cache file location
ls ~/.olav/cache/$(whoami)/llm_cache.db

# View cache statistics
sqlite3 ~/.olav/cache/$(whoami)/llm_cache.db \
  "SELECT COUNT(*) as entries FROM full_llm_cache"
```

!!! tip "Running the same Agent query multiple times"
    Overall Agent acceleration (including LangGraph reasoning and tool calls):
    
    | Run Number | Duration | Speedup |
    |------------|----------|---------|
    | 1st (cold start) | ~28s | 1x |
    | 2nd | ~19s | 1.5x |
    | 3rd+ | ~14s | **2x** |
    
    Because LangGraph message history contains dynamic IDs, the acceleration effect increases with each run and stabilizes at approximately 2x.

### Tier-0: SemanticCache (Vector Similarity Match)

SemanticCache is stored in `.olav/databases/memory.lance` (LanceDB) and provides semantic-level caching for vector retrieval operations such as Knowledge Base queries and Hybrid Search.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `cache_similarity_threshold` | `0.02` | Cosine distance threshold (<=0.02 = 99%+ similarity) |
| `cache_ttl_hours` | `24` | Cache entry expiration time |
| `cache_max_entries` | `500` | Maximum entries (evicted by LRU when exceeded) |

```bash
# Adjust threshold to cover more semantically similar queries (recommended 0.10~0.20)
export OLAV_MEMORY_CACHE_SIMILARITY_THRESHOLD=0.15
```

!!! warning "Threshold tuning advice"
    The default threshold `0.02` only hits near-duplicate queries. To cover semantically similar but differently worded queries like "Show BGP settings for R1" vs. "What is the BGP config of R1?" (measured distance ~ 0.78), increase the threshold to `0.15~0.20`.

### Anthropic Prompt Caching (Enterprise Exclusive)

When using Anthropic models, OLAV automatically adds `cache_control` markers to system prompts and static context via `deepagents.AnthropicPromptCachingMiddleware`:

```json
{
  "llm": {
    "provider": "anthropic",
    "model": "claude-3-5-sonnet-20241022"
  }
}
```

Anthropic Prompt Caching charges only once for the system prompt (typically thousands of tokens), with subsequent cache hits billed at only 10% of the read cost. This is especially effective for large static_context (such as Network Schema reference documents).

---

## Multi-Layer Memory System

OLAV uses a LanceDB vector database to store two types of persistent memory:

### Episodic Memory

Knowledge automatically accumulated by the Agent during execution, stored in `.olav/databases/memory.lance` (`memory` table).

| Category | Description | Example |
|----------|-------------|---------|
| `fact` | Environmental facts | "R1@192.168.100.101 is a Juniper border router" |
| `decision` | Decision records | "Chose OSPF over BGP for intra-DC routing" |
| `preference` | User preferences | "User prefers JSON format output" |
| `audit` | Constraint lessons | "execute_sql must use schema.table format" |

```python
# memory table structure
id, text, vector (384/1536-dim), category, scope (global|agent),
metadata, timestamp, access_count, weight (time-decay)
```

### LangGraph Checkpoint (Session State)

Each user's each Agent has an independent DuckDB checkpoint file, enabling cross-session conversation continuity:

```
~/.olav/checkpoints/{username}/{workspace}/{agent_id}/checkpoints.duckdb
```

After restarting OLAV, the Agent can resume the previous conversation context without the user needing to re-explain the background.

---

## Multi-User Isolation (Enterprise Security)

OLAV is designed for multi-user concurrent environments with strict data isolation between users:

```
User Alice                    User Bob
~/.olav/cache/alice/         ~/.olav/cache/bob/
~/.olav/checkpoints/alice/   ~/.olav/checkpoints/bob/
~/.olav/token                ~/.olav/token
        |                            |
        +------------+---------------+
                     |
          .olav/databases/        <- Read-only: globally shared
          .olav/logs/             <- Centralized: all user audits
          .olav/workspace/        <- Read-only: Agent definitions
```

| Data Type | Isolation Level | Storage Location |
|-----------|----------------|-----------------|
| LLM response cache | User-private | `~/.olav/cache/{user}/` |
| Conversation checkpoint | User-private | `~/.olav/checkpoints/{user}/` |
| Audit logs | Centralized | `.olav/databases/audit.duckdb` |
| Agent definitions | Globally shared | `.olav/workspace/` |
| Business data | Globally shared | `.olav/databases/main.duckdb` |

For details on authentication modes, role permissions, and user management, see [Security Model ->](security-model.md).

---

## Federated Specialist Agent Architecture

OLAV uses `deepagents.SkillsMiddleware` to dynamically bind Skills to Agents, forming a **federated specialist system**:

```
User request
    |
OLAVAgent (Semantic Router)
    +-- quick  -- Fast SQL/CLI queries
    +-- ops    -- Deep operations (routing, topology, log analysis, diff)
    +-- config -- Inventory sync, snapshot collection, API registration
    +-- core   -- Python/SQL/Shell code execution, web search
         +-- sandbox (SubAgent) -- High-concurrency compute isolation environment
```

Each Agent's toolset declares a **required information check** protocol through the `required_params` metadata in `SKILL.md` -- when required parameters are missing (such as target device or credentials), the Agent will stop and ask the user instead of executing blindly.

---

## Enterprise LLM Fine-Tuning

OLAV's audit database is not just a log -- it is a **continuously growing fine-tuning dataset**. For the three export formats and specific commands, see [Audit and Logs ->](../guides/audit-and-logs.md).

### Fine-Tuning Objectives

| Fine-Tuning Type | Data Source | Purpose |
|-----------------|-------------|---------|
| **Tool Call** (Tool Call FT) | Successful tool call trajectories | Improve the LLM's ability to directly generate correct SQL/CLI |
| **Domain Knowledge** (Domain FT) | Device information, network topology, alert rules | Reduce RAG queries by internalizing business knowledge into the LLM |
| **Constraint Learning** (Constraint FT) | Failure lessons extracted via `/trace-review` | Prevent known tool misuse patterns |

The fine-tuned model can replace the `llm.model` field in `api.json` without modifying any Agent logic:

```json
{
  "llm": {
    "provider": "custom",
    "model": "your-org/olav-finetuned-v1",
    "base_url": "https://your-inference-server/v1",
    "api_key": "..."
  },
  "agent_overrides": {
    "ops": {
      "model": "your-org/olav-ops-specialist-v1"
    }
  }
}
```

### Per-Agent Model Assignment

Different Agents can use different fine-tuned models, achieving a **fine-grained balance of cost and capability**:

```json
{
  "llm": {
    "model": "gpt-4o-mini"
  },
  "agent_overrides": {
    "ops":    { "model": "your-ops-specialist" },
    "config": { "model": "claude-3-5-sonnet-20241022" },
    "quick":  { "model": "gpt-4o-mini" },
    "core":   { "model": "gpt-4o" }
  }
}
```

The high-frequency `quick` Agent uses a low-cost model; the `ops` Agent that requires deep reasoning uses a dedicated fine-tuned model -- **overall token cost can be reduced by 40-70%**.

---

## Observability

All Agent activity is written to `.olav/databases/audit.duckdb` and can be queried directly with DuckDB:

```bash
# Query token consumption over the last 24h
duckdb .olav/databases/audit.duckdb "
  SELECT 
    agent_id,
    COUNT(*) AS runs,
    SUM(CAST(json_extract(payload, '$.tokens_total') AS INT)) AS total_tokens
  FROM audit_events
  WHERE event_type = 'chain_end'
    AND timestamp > NOW() - INTERVAL 24 HOURS
  GROUP BY agent_id
  ORDER BY total_tokens DESC
"

# View cache hit rate (semantic_cache_hit events)
duckdb .olav/databases/audit.duckdb "
  SELECT 
    DATE_TRUNC('hour', timestamp) AS hour,
    COUNT(*) AS cache_hits
  FROM audit_events
  WHERE event_type = 'semantic_cache_hit'
  GROUP BY 1
  ORDER BY 1 DESC
  LIMIT 24
"
```

This lets you answer precisely:
- Which Agent consumed the most tokens?
- What is the cache hit rate trend?
- Which types of queries are most frequent?
- Which run failed, and why?

---

## Next Steps

- [Agent Harness ->](agent-harness.md) -- Sandbox execution, HITL approval, injection protection
- [Self-Improving Loop ->](self-improving-loop.md) -- How to continuously improve Agents using audit data
- [Audit and Logs ->](../guides/audit-and-logs.md) -- Detailed log querying and export guide
- [Configuration Reference ->](../reference/configuration.md) -- Complete api.json configuration reference
- [Users and Roles ->](../reference/users-and-roles.md) -- RBAC permission controls
