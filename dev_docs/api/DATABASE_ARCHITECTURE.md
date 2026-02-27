# OLAV Database Architecture Analysis

**Version**: v1.0.0  
**Date**: 2026-02-23  
**Status**: Design

---

## Current State Analysis

### Database Usage Pattern

| Component | Database | Write Frequency | Read Frequency | Concurrency Need |
|-----------|----------|-----------------|----------------|------------------|
| Business Data | main.duckdb | **Low** (daily sync) | High | Low |
| LLM Cache | llm_cache.duckdb | **High** (every call) | High | High |
| DuckDBStore | main.duckdb (shared) | **Medium** | Medium | Medium |
| Checkpointer | MemorySaver | Medium | Medium | Medium |

### Current Problems

1. **Connection Conflict**: Multiple components share main.duckdb connection
2. **DuckDB Limitation**: Single writer, "different configuration" errors
3. **No Persistence**: Checkpointer is in-memory (MemorySaver)

### Key Insight

**Business data writes are infrequent** - only during:
- `sync_all()` (inventory sync) - once per day or on-demand
- Snapshot operations - on-demand
- Topology updates - during discovery runs

**High-frequency writes are from**:
- LLM cache (every LLM call)
- Conversation state (every message)

---

## Proposed Architecture: Separation of Concerns

```
┌─────────────────────────────────────────────────────────────────┐
│                        OLAV Database Layer                       │
├─────────────────┬─────────────────┬─────────────────────────────┤
│   Business Data │    LLM Cache    │    Conversation State       │
│   (DuckDB)      │    (SQLite)     │    (SQLite)                 │
├─────────────────┼─────────────────┼─────────────────────────────┤
│ • devices       │ • llm_calls     │ • checkpoints               │
│ • topology      │ • embeddings    │ • thread_state              │
│ • parsed_outputs│                 │                             │
├─────────────────┼─────────────────┼─────────────────────────────┤
│ Write: Low      │ Write: High     │ Write: Medium               │
│ (daily sync)    │ (every call)    │ (every message)             │
├─────────────────┼─────────────────┼─────────────────────────────┤
│ JSON Native ✅  │ Simple Cache ✅ | LangGraph Native ✅          │
│ OLAP Queries ✅ │ WAL Mode ✅     | SqliteSaver ✅               │
└─────────────────┴─────────────────┴─────────────────────────────┘
```

---

## Component-by-Component Design

### 1. Business Data: DuckDB (Keep As-Is)

**Why DuckDB?**
- ✅ Native JSON/JSONB support (perfect for `parsed_outputs.parsed_data`)
- ✅ OLAP-optimized for analytical queries
- ✅ Columnar storage for time-series data
- ✅ Zero external dependencies (embedded)

**Access Pattern**:
```python
# Low-frequency writes - no concurrency issues
from olav.core.database import get_database_connection

# Read-heavy operations
conn = get_database_connection(MAIN_DB_PATH, read_only=True)
devices = conn.execute("SELECT * FROM devices WHERE site = ?", [site]).fetchall()

# Occasional writes (sync, snapshot)
conn = get_database_connection(MAIN_DB_PATH, read_only=False)
conn.execute("INSERT INTO topology_links ...")
```

**Schema (Unchanged)**:
```sql
-- devices: Nornir inventory sync
CREATE TABLE devices (
    device_id VARCHAR PRIMARY KEY,
    name VARCHAR, hostname VARCHAR, platform VARCHAR,
    mgmt_ip VARCHAR, device_role VARCHAR, site VARCHAR,
    ...
);

-- topology_links: CDP/LLDP discovery
CREATE TABLE topology_links (
    link_id VARCHAR PRIMARY KEY,
    source_device VARCHAR, source_interface VARCHAR,
    destination_device VARCHAR, destination_interface VARCHAR,
    ...
);

-- parsed_outputs: JSON storage (DuckDB native)
CREATE TABLE parsed_outputs (
    id INTEGER PRIMARY KEY,
    device_name VARCHAR,
    command VARCHAR,
    parsed_data JSON NOT NULL,  -- ← Native JSON support!
    snapshot_date DATE,
    ...
);
```

---

### 2. LLM Cache: SQLite (Change from DuckDB)

**Why SQLite?**
- ✅ WAL mode enables concurrent read/write
- ✅ SQLAlchemyCache native support
- ✅ Simpler than DuckDB for key-value cache
- ✅ Single file deployment

**Implementation**:
```python
from langchain_community.cache import SQLiteCache
from langchain_core.globals import set_llm_cache

# SQLite with WAL mode for concurrent access
cache_path = db_dir / "llm_cache.sqlite"
set_llm_cache(SQLiteCache(database_path=str(cache_path)))
```

**SQLite WAL Mode**:
```python
# Enable WAL mode for better concurrency
import sqlite3
conn = sqlite3.connect(str(cache_path))
conn.execute("PRAGMA journal_mode=WAL")  # Concurrent read/write
conn.execute("PRAGMA synchronous=NORMAL")  # Faster writes
```

**Comparison**:
| Feature | DuckDB (Current) | SQLite (Proposed) |
|---------|------------------|-------------------|
| Concurrent R/W | ❌ Single writer | ✅ WAL mode |
| Complexity | Medium | Low |
| LangChain Support | Via SQLAlchemy | Native |
| Deployment | Same | Same |

---

### 3. Checkpointer: SQLite (Change from MemorySaver)

**Why SQLite?**
- ✅ LangGraph `SqliteSaver` has async support (unlike DuckDBSaver)
- ✅ Thread persistence across restarts
- ✅ Simple file-based deployment
- ✅ No external database needed

**Implementation**:
```python
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

# Async SQLite checkpointer
checkpointer_path = db_dir / "checkpoints.sqlite"
checkpointer = AsyncSqliteSaver.from_conn_string(f"sqlite:///{checkpointer_path}")
```

**Or Simple SQLite (Sync)**:
```python
from langgraph.checkpoint.sqlite import SqliteSaver

checkpointer = SqliteSaver.from_conn_string("checkpoints.sqlite")
```

---

### 4. Long-term Memory Store: Optional

**Question**: Does OLAV need DuckDBStore?

**Analysis**:
- DuckDBStore is for cross-thread, long-term agent memory
- OLAV use case: Network operations queries
- Most queries are stateless (device info, topology, etc.)

**Recommendation**: 
- **Disable DuckDBStore** for now
- If needed later, can add with separate connection

```python
# Simple: Just disable
self.store = None

# Or: Separate connection (if needed)
store_conn = duckdb.connect(str(db_dir / "memory.duckdb"))
self.store = DuckDBStore(store_conn)
```

---

## Revised Database File Structure

```
.olav/databases/
├── main.duckdb          # Business data (devices, topology, parsed_outputs)
│   └── Write: Low frequency (sync, snapshot)
│   └── Read: High frequency (queries)
│   └── JSON: Native support
│
├── llm_cache.sqlite     # LLM call deduplication
│   └── Write: High frequency (every LLM call)
│   └── Read: High frequency (cache lookup)
│   └── Mode: WAL for concurrency
│
└── checkpoints.sqlite   # Conversation state persistence
    └── Write: Medium frequency (every message)
    └── Read: Medium frequency (thread resume)
    └── Async: SqliteSaver supports async
```

---

## Multi-User Concurrency Analysis

### Scenario: 5 concurrent users

| Database | Before | After |
|----------|--------|-------|
| main.duckdb | ❌ Single writer lock | ✅ Write queue for sync |
| llm_cache | ❌ DuckDB single conn | ✅ SQLite WAL concurrent |
| checkpoints | ❌ In-memory (no share) | ✅ SQLite concurrent |

### Write Queue for main.duckdb (Optional)

For rare concurrent writes to business data:

```python
import asyncio

class AsyncDuckDBManager:
    """Serialize writes to DuckDB while allowing concurrent reads."""
    
    def __init__(self, db_path: Path):
        self._write_lock = asyncio.Lock()
        self._conn = duckdb.connect(str(db_path))
    
    async def execute_read(self, query: str, params=None):
        """Concurrent reads - no lock needed"""
        return self._conn.execute(query, params or []).fetchall()
    
    async def execute_write(self, query: str, params=None):
        """Serialized writes - single writer"""
        async with self._write_lock:
            self._conn.execute(query, params or [])
            return self._conn.fetchall()
```

---

## PostgreSQL vs SQLite vs DuckDB

| Feature | PostgreSQL | SQLite | DuckDB |
|---------|------------|--------|--------|
| **Deployment** | External server | Single file | Single file |
| **Concurrent Writes** | ✅ Excellent | ✅ WAL mode | ❌ Single writer |
| **JSON Support** | ✅ JSONB | ✅ JSON1 | ✅ Native |
| **OLAP Queries** | ⚠️ Row-oriented | ❌ Row-oriented | ✅ Column-oriented |
| **LangGraph Support** | AsyncPostgresSaver | AsyncSqliteSaver | ❌ No async |
| **Complexity** | High | Low | Low |
| **Use Case** | Enterprise | Simple persistence | Analytics |

**Recommendation**:
- **DuckDB**: Business data (analytics, JSON storage)
- **SQLite**: Cache + Checkpointer (concurrency, simplicity)
- **PostgreSQL**: Only if scaling to 100+ concurrent users

---

## Implementation Plan

### Phase 1: Separate LLM Cache

```python
# src/olav/agents/agent.py

# Before (DuckDB)
llm_cache_path = db_dir / "llm_cache.duckdb"
engine = sqlalchemy.create_engine(f"duckdb:///{llm_cache_path}")
set_llm_cache(SQLAlchemyCache(engine))

# After (SQLite)
llm_cache_path = db_dir / "llm_cache.sqlite"
set_llm_cache(SQLiteCache(database_path=str(llm_cache_path)))
```

### Phase 2: Add SQLite Checkpointer

```python
# src/olav/agents/agent.py

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

checkpointer_path = db_dir / "checkpoints.sqlite"
self.checkpointer = AsyncSqliteSaver.from_conn_string(f"sqlite:///{checkpointer_path}")
```

### Phase 3: Remove DuckDBStore (Simplify)

```python
# src/olav/agents/agent.py

# Disable long-term memory store (not needed for OLAV)
self.store = None
```

### Phase 4: Add Write Queue (Optional)

```python
# src/olav/core/database.py

class AsyncDuckDBManager:
    """For rare concurrent business data writes."""
    # Implementation as shown above
```

---

## Summary

| Change | Impact | Complexity |
|--------|--------|------------|
| LLM Cache: DuckDB → SQLite | ✅ Fixes cache concurrency | Low |
| Checkpointer: Memory → SQLite | ✅ Adds persistence | Low |
| Store: Disable | ✅ Simplifies architecture | None |
| Business Data: Keep DuckDB | ✅ Preserves JSON/OLAP | None |

**Result**:
- ✅ Multi-user concurrent access
- ✅ Conversation state persistence
- ✅ DuckDB JSON capabilities preserved
- ✅ Simple deployment (no PostgreSQL needed)
- ✅ Minimal code changes
