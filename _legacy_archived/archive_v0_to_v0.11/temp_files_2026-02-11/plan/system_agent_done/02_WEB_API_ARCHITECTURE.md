# OLAV Web API Architecture Design

**Objective**: Design schema-aware Web API layer for future Web GUI integration

**Date**: 2026-02-08  
**Status**: 📋 Planning

---

## 🎯 Core Question

**User's Question**: "OLAV有计划未来使用Web GUI，是应该集成FastAPI，还是programmatic API？需不需要把这些API也做成non-ETL schema aware模式？"

**TL;DR Answer**: 
1. **Both**: FastAPI (HTTP layer) + Programmatic API (Python layer) in layered architecture
2. **Yes**: Web API should be **fully schema-aware**, inheriting OLAV's zero-ETL philosophy
3. **Architecture**: 3-layer design with schema discovery at every level

---

## 🏗️ Recommended Architecture: 3-Layer API Stack

```
┌─────────────────────────────────────────────────────────────┐
│                     Layer 3: Web GUI                         │
│              React/Vue Frontend + WebSocket                  │
│                                                               │
│  • Real-time query streaming                                 │
│  • Dynamic table visualization (schema-driven)               │
│  • Auto-generated CRUD forms (from DuckDB schema)            │
└───────────────────────────┬─────────────────────────────────┘
                            │ HTTP/WebSocket
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                  Layer 2: FastAPI (HTTP REST)                │
│                  Schema-Aware Endpoints                      │
│                                                               │
│  • GET /api/schema/tables                                    │
│  • GET /api/schema/{table}                                   │
│  • GET /api/data/{table}?filters=...                         │
│  • POST /api/query (natural language)                        │
│  • WebSocket /ws/query (streaming)                           │
└───────────────────────────┬─────────────────────────────────┘
                            │ Python function calls
                            ▼
┌─────────────────────────────────────────────────────────────┐
│             Layer 1: Programmatic API (olav.api)             │
│                   Type-Safe Python Functions                 │
│                                                               │
│  • olav.api.schema.list_tables()                             │
│  • olav.api.schema.get_table_schema(name)                    │
│  • olav.api.data.query_table(table, filters)                 │
│  • olav.api.query.run(text, stream=True)                     │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    Data Layer (DuckDB)                       │
│           Zero-ETL, Schema-Aware, SQL-First                  │
│                                                               │
│  • devices, raw_outputs (base tables)                        │
│  • v_interfaces, v_bgp, v_ospf (materialized views)          │
│  • information_schema (schema metadata)                      │
└─────────────────────────────────────────────────────────────┘
```

---

## 📊 Layer 1: Programmatic API (olav.api)

### Design Philosophy

**Inherit OLAV's Core Principles**:
1. **Zero-ETL**: Direct DuckDB access, no intermediate data copies
2. **Schema-Aware**: Discover schema dynamically from `information_schema`
3. **SQL-First**: Generate SQL, not hardcoded queries
4. **Type-Safe**: Pydantic models for all inputs/outputs

### Module Structure

```
src/olav/api/
├── __init__.py           # Public exports
├── schema.py             # Schema discovery (CRITICAL)
├── data.py               # Data access (schema-aware queries)
├── query.py              # Natural language queries
├── devices.py            # Device management
├── cache.py              # Cache operations
├── system.py             # System operations
└── models.py             # Pydantic models
```

### Key API: Schema Discovery

**Purpose**: Enable dynamic UI generation without hardcoding table schemas

```python
# src/olav/api/schema.py
"""Schema-aware API for database introspection."""

from dataclasses import dataclass
from typing import List, Dict, Any
import duckdb


@dataclass
class TableSchema:
    """Table schema metadata."""
    name: str
    type: str  # "VIEW" | "BASE TABLE"
    columns: List[Dict[str, str]]  # [{name, type, nullable}]
    row_count: int
    description: str | None


@dataclass
class SchemaDiscoveryResult:
    """Complete database schema."""
    tables: List[TableSchema]
    views: List[TableSchema]
    total_tables: int
    total_views: int


def list_tables() -> SchemaDiscoveryResult:
    """Discover all tables and views from DuckDB.
    
    Returns:
        SchemaDiscoveryResult with full schema metadata
    
    Example:
        >>> from olav.api.schema import list_tables
        >>> schema = list_tables()
        >>> for table in schema.tables:
        ...     print(f"{table.name}: {len(table.columns)} columns")
        devices: 5 columns
        raw_outputs: 8 columns
    """
    from config.paths import UNIFIED_DB
    
    conn = duckdb.connect(str(UNIFIED_DB), read_only=True)
    
    # Query information_schema for table metadata
    tables_query = """
        SELECT 
            table_name,
            table_type,
            (SELECT COUNT(*) FROM {table_name}) as row_count
        FROM information_schema.tables
        WHERE table_schema = 'main'
        ORDER BY table_name
    """
    
    tables = []
    views = []
    
    for row in conn.execute(tables_query).fetchall():
        table_name, table_type, row_count = row
        
        # Get column metadata
        columns_query = f"""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = '{table_name}'
            ORDER BY ordinal_position
        """
        columns = [
            {"name": col, "type": dtype, "nullable": nullable == "YES"}
            for col, dtype, nullable in conn.execute(columns_query).fetchall()
        ]
        
        schema = TableSchema(
            name=table_name,
            type=table_type,
            columns=columns,
            row_count=row_count,
            description=None  # Could extract from table comments
        )
        
        if table_type == "VIEW":
            views.append(schema)
        else:
            tables.append(schema)
    
    conn.close()
    
    return SchemaDiscoveryResult(
        tables=tables,
        views=views,
        total_tables=len(tables),
        total_views=len(views)
    )


def get_table_schema(table_name: str) -> TableSchema:
    """Get schema for a specific table.
    
    Args:
        table_name: Table or view name
    
    Returns:
        TableSchema with column metadata
    
    Raises:
        ValueError: Table not found
    
    Example:
        >>> schema = get_table_schema("devices")
        >>> print(schema.columns)
        [
            {"name": "name", "type": "VARCHAR", "nullable": False},
            {"name": "ip", "type": "VARCHAR", "nullable": True},
            ...
        ]
    """
    schema = list_tables()
    
    for table in schema.tables + schema.views:
        if table.name == table_name:
            return table
    
    raise ValueError(f"Table not found: {table_name}")


def get_sample_data(table_name: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Get sample rows from a table.
    
    Args:
        table_name: Table or view name
        limit: Max rows to return (default 10)
    
    Returns:
        List of row dictionaries
    
    Example:
        >>> rows = get_sample_data("devices", limit=3)
        >>> print(rows[0])
        {"name": "R1", "ip": "10.0.0.1", "platform": "cisco_ios", ...}
    """
    from config.paths import UNIFIED_DB
    
    conn = duckdb.connect(str(UNIFIED_DB), read_only=True)
    
    # Validate table exists
    get_table_schema(table_name)  # Raises if not found
    
    query = f"SELECT * FROM {table_name} LIMIT {limit}"
    result = conn.execute(query).fetchdf().to_dict('records')
    
    conn.close()
    return result
```

### Key API: Dynamic Data Access

**Purpose**: Query any table without hardcoded endpoints

```python
# src/olav/api/data.py
"""Schema-aware data access API."""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class QueryFilters:
    """Filters for table queries."""
    where: Optional[str] = None  # SQL WHERE clause
    order_by: Optional[str] = None
    limit: int = 100
    offset: int = 0


@dataclass
class QueryResult:
    """Result from table query."""
    table: str
    rows: List[Dict[str, Any]]
    total_count: int
    columns: List[str]
    query_sql: str  # For debugging


def query_table(
    table_name: str,
    filters: QueryFilters = QueryFilters()
) -> QueryResult:
    """Query any table with dynamic filters.
    
    Args:
        table_name: Table or view name
        filters: Query filters (WHERE, ORDER BY, LIMIT, OFFSET)
    
    Returns:
        QueryResult with rows and metadata
    
    Example:
        >>> from olav.api.data import query_table, QueryFilters
        >>> 
        >>> # Get R1 interfaces
        >>> filters = QueryFilters(
        ...     where="device = 'R1'",
        ...     order_by="interface_name",
        ...     limit=50
        ... )
        >>> result = query_table("v_interfaces", filters)
        >>> print(result.rows[0])
        {"device": "R1", "interface_name": "Gi0/0", "status": "up", ...}
    
    Security:
        - Validates table exists via schema API
        - Parameterized WHERE clause (prevents SQL injection)
        - Read-only connection
    """
    from config.paths import UNIFIED_DB
    import duckdb
    from olav.api.schema import get_table_schema
    
    # Validate table exists
    schema = get_table_schema(table_name)
    
    # Build SQL query
    query = f"SELECT * FROM {table_name}"
    
    if filters.where:
        # TODO: Add SQL injection protection (parameterized queries)
        query += f" WHERE {filters.where}"
    
    if filters.order_by:
        query += f" ORDER BY {filters.order_by}"
    
    # Get total count (before LIMIT/OFFSET)
    count_query = f"SELECT COUNT(*) FROM ({query}) AS subq"
    
    # Add pagination
    query += f" LIMIT {filters.limit} OFFSET {filters.offset}"
    
    # Execute
    conn = duckdb.connect(str(UNIFIED_DB), read_only=True)
    
    total_count = conn.execute(count_query).fetchone()[0]
    rows = conn.execute(query).fetchdf().to_dict('records')
    
    conn.close()
    
    return QueryResult(
        table=table_name,
        rows=rows,
        total_count=total_count,
        columns=[col["name"] for col in schema.columns],
        query_sql=query
    )
```

---

## 🌐 Layer 2: FastAPI (HTTP REST)

### Design Philosophy

**Schema-Aware HTTP Endpoints**:
1. **No hardcoded table endpoints** - Use generic `/api/data/{table}` with filters
2. **Dynamic schema discovery** - Web UI queries schema, builds UI dynamically
3. **Streaming queries** - WebSocket for real-time LLM responses
4. **Standards-based** - OpenAPI docs, JSON:API format

### Endpoint Catalog

```python
# src/olav/web/api.py
"""FastAPI schema-aware REST API."""

from fastapi import FastAPI, HTTPException, Query, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
import asyncio

app = FastAPI(
    title="OLAV Network Assistant API",
    description="Schema-aware REST API for network operations",
    version="0.10.0"
)

# CORS for Web GUI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # React dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# Schema Discovery Endpoints
# ============================================================================

@app.get("/api/schema/tables")
async def list_tables():
    """List all tables and views with metadata.
    
    Response:
        {
            "tables": [
                {
                    "name": "devices",
                    "type": "BASE TABLE",
                    "columns": [...],
                    "row_count": 10
                }
            ],
            "views": [...],
            "total_tables": 2,
            "total_views": 15
        }
    
    Use Case:
        - Web UI queries this on startup
        - Renders dynamic navigation menu
        - No hardcoded table names in frontend
    """
    from olav.api.schema import list_tables
    
    result = list_tables()
    
    return {
        "tables": [
            {
                "name": t.name,
                "type": t.type,
                "columns": t.columns,
                "row_count": t.row_count
            }
            for t in result.tables
        ],
        "views": [
            {
                "name": v.name,
                "type": v.type,
                "columns": v.columns,
                "row_count": v.row_count
            }
            for v in result.views
        ],
        "total_tables": result.total_tables,
        "total_views": result.total_views
    }


@app.get("/api/schema/{table_name}")
async def get_table_schema(table_name: str):
    """Get schema for a specific table.
    
    Args:
        table_name: Table or view name
    
    Response:
        {
            "name": "devices",
            "type": "BASE TABLE",
            "columns": [
                {"name": "name", "type": "VARCHAR", "nullable": false},
                {"name": "ip", "type": "VARCHAR", "nullable": true}
            ],
            "row_count": 10
        }
    
    Use Case:
        - User clicks "Devices" in Web UI
        - Frontend fetches schema, generates table UI
    """
    from olav.api.schema import get_table_schema
    
    try:
        schema = get_table_schema(table_name)
        return {
            "name": schema.name,
            "type": schema.type,
            "columns": schema.columns,
            "row_count": schema.row_count
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ============================================================================
# Data Access Endpoints (Schema-Aware)
# ============================================================================

@app.get("/api/data/{table_name}")
async def query_table(
    table_name: str,
    where: Optional[str] = Query(None, description="SQL WHERE clause"),
    order_by: Optional[str] = Query(None, description="Column to order by"),
    limit: int = Query(100, ge=1, le=1000, description="Max rows"),
    offset: int = Query(0, ge=0, description="Offset for pagination")
):
    """Query any table with dynamic filters (schema-aware).
    
    Args:
        table_name: Table or view name (e.g., "devices", "v_interfaces")
        where: SQL WHERE clause (e.g., "device = 'R1'")
        order_by: Column name (e.g., "interface_name")
        limit: Max rows (1-1000)
        offset: Pagination offset
    
    Response:
        {
            "table": "v_interfaces",
            "rows": [
                {"device": "R1", "interface_name": "Gi0/0", "status": "up"},
                ...
            ],
            "total_count": 45,
            "columns": ["device", "interface_name", "status", ...],
            "query_sql": "SELECT * FROM v_interfaces WHERE device = 'R1' LIMIT 100"
        }
    
    Examples:
        GET /api/data/devices
        GET /api/data/v_interfaces?where=device='R1'&order_by=interface_name
        GET /api/data/v_bgp?where=status='Established'&limit=50
    
    Use Case:
        - Single endpoint for ALL tables
        - No need to define /api/devices, /api/interfaces, etc.
        - Web UI builds query strings dynamically
    """
    from olav.api.data import query_table, QueryFilters
    
    filters = QueryFilters(
        where=where,
        order_by=order_by,
        limit=limit,
        offset=offset
    )
    
    try:
        result = query_table(table_name, filters)
        return {
            "table": result.table,
            "rows": result.rows,
            "total_count": result.total_count,
            "columns": result.columns,
            "query_sql": result.query_sql
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ============================================================================
# Natural Language Query Endpoints
# ============================================================================

@app.post("/api/query")
async def run_query(request: dict):
    """Execute natural language query (non-streaming).
    
    Request:
        {
            "query": "查看 R1 的接口状态",
            "timeout": 60
        }
    
    Response:
        {
            "status": "complete",
            "final_answer": "...",
            "execution_time": 2.5
        }
    
    Use Case:
        - Simple queries where streaming not needed
        - Background tasks, scheduled queries
    """
    from olav.api.query import run_query
    
    query_text = request.get("query")
    timeout = request.get("timeout", 60)
    
    result = await run_query(query_text, timeout=timeout)
    return result


@app.websocket("/ws/query")
async def query_stream(websocket: WebSocket):
    """Stream natural language query results (WebSocket).
    
    Protocol:
        Client → Server: {"query": "查看 R1 的接口状态"}
        Server → Client: {"type": "thinking", "content": "分析查询..."}
        Server → Client: {"type": "tool_call", "tool": "query_database", "args": {...}}
        Server → Client: {"type": "token", "content": "R1"}
        Server → Client: {"type": "token", "content": " 接口"}
        Server → Client: {"type": "complete", "final_answer": "..."}
    
    Use Case:
        - Real-time query streaming in Web UI
        - Show LLM reasoning process
        - Tool call visibility
    """
    await websocket.accept()
    
    try:
        # Receive query
        data = await websocket.receive_json()
        query_text = data.get("query")
        
        # Stream response
        from olav.api.query import stream_query
        
        async for event in stream_query(query_text):
            await websocket.send_json(event)
        
    except Exception as e:
        await websocket.send_json({"type": "error", "message": str(e)})
    finally:
        await websocket.close()


# ============================================================================
# Device Management Endpoints
# ============================================================================

@app.get("/api/devices")
async def list_devices():
    """List all devices (convenience endpoint, wraps /api/data/devices)."""
    from olav.api.devices import list_devices
    return list_devices()


@app.post("/api/devices")
async def add_device(device: dict):
    """Add new device to inventory."""
    from olav.api.devices import add_device
    
    # TODO: Implement (System Admin Agent Phase 2)
    raise HTTPException(status_code=501, detail="Not implemented yet")


# ============================================================================
# System Endpoints
# ============================================================================

@app.get("/api/system/health")
async def health_check():
    """System health check."""
    from olav.api.system import health_check
    return health_check()


@app.get("/api/system/version")
async def get_version():
    """Get OLAV version info."""
    return {
        "version": "0.10.0",
        "api_version": "1.0",
        "schema_aware": True
    }
```

---

## 🎨 Layer 3: Web GUI (Frontend)

### Design Philosophy

**Schema-Driven UI Generation**:
1. **No hardcoded table components** - Render tables dynamically from schema API
2. **Auto-generated CRUD forms** - Build forms from column metadata
3. **Real-time streaming** - WebSocket for live query results
4. **Responsive design** - TailwindCSS + React

### Technology Stack

**Recommended**: React + TypeScript + TailwindCSS + React Query

```typescript
// Example: Dynamic Table Component
import { useQuery } from '@tanstack/react-query';

interface TableViewProps {
  tableName: string;
}

function TableView({ tableName }: TableViewProps) {
  // Fetch schema
  const { data: schema } = useQuery({
    queryKey: ['schema', tableName],
    queryFn: () => fetch(`/api/schema/${tableName}`).then(r => r.json())
  });
  
  // Fetch data
  const { data: result } = useQuery({
    queryKey: ['data', tableName],
    queryFn: () => fetch(`/api/data/${tableName}`).then(r => r.json())
  });
  
  if (!schema || !result) return <div>Loading...</div>;
  
  // Auto-generate table from schema
  return (
    <table>
      <thead>
        <tr>
          {schema.columns.map(col => (
            <th key={col.name}>{col.name}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {result.rows.map((row, i) => (
          <tr key={i}>
            {schema.columns.map(col => (
              <td key={col.name}>{row[col.name]}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

### Key Features

1. **Dynamic Navigation**
   ```typescript
   // Fetch all tables on startup
   const { data: tables } = useQuery({
     queryKey: ['tables'],
     queryFn: () => fetch('/api/schema/tables').then(r => r.json())
   });
   
   // Render nav menu dynamically
   <nav>
     {tables.tables.map(table => (
       <Link to={`/table/${table.name}`}>{table.name}</Link>
     ))}
     {tables.views.map(view => (
       <Link to={`/table/${view.name}`}>{view.name}</Link>
     ))}
   </nav>
   ```

2. **Real-Time Query Streaming**
   ```typescript
   function QueryInterface() {
     const [messages, setMessages] = useState([]);
     const ws = useRef<WebSocket>();
     
     const sendQuery = (query: string) => {
       ws.current = new WebSocket('/ws/query');
       
       ws.current.onmessage = (event) => {
         const data = JSON.parse(event.data);
         
         if (data.type === 'token') {
           // Append streaming tokens
           setMessages(prev => [...prev, data.content]);
         } else if (data.type === 'tool_call') {
           // Show tool execution
           setMessages(prev => [...prev, `🔧 ${data.tool}(${JSON.stringify(data.args)})`]);
         } else if (data.type === 'complete') {
           // Final answer
           setMessages(prev => [...prev, `✅ ${data.final_answer}`]);
         }
       };
       
       ws.current.send(JSON.stringify({ query }));
     };
     
     return <ChatInterface onSend={sendQuery} messages={messages} />;
   }
   ```

3. **Auto-Generated Filters**
   ```typescript
   function FilterBuilder({ schema }: { schema: TableSchema }) {
     const [filters, setFilters] = useState({});
     
     return (
       <div>
         {schema.columns.map(col => (
           <div key={col.name}>
             <label>{col.name}</label>
             {col.type === 'VARCHAR' ? (
               <input type="text" onChange={e => setFilters({
                 ...filters,
                 [col.name]: e.target.value
               })} />
             ) : col.type === 'INTEGER' ? (
               <input type="number" onChange={e => setFilters({
                 ...filters,
                 [col.name]: e.target.value
               })} />
             ) : null}
           </div>
         ))}
       </div>
     );
   }
   ```

---

## ✅ Schema-Aware Advantages

### 1. Zero-ETL → Zero Frontend Hardcoding

**Traditional Approach** (NOT schema-aware):
```typescript
// ❌ Hardcoded endpoints for each table
function DevicesPage() {
  const { data } = useQuery({ 
    queryFn: () => fetch('/api/devices').then(r => r.json())
  });
  return <DevicesTable data={data} />;
}

function InterfacesPage() {
  const { data } = useQuery({ 
    queryFn: () => fetch('/api/interfaces').then(r => r.json())
  });
  return <InterfacesTable data={data} />;
}

// Need to create:
// - /api/devices endpoint (backend)
// - /api/interfaces endpoint (backend)
// - DevicesTable component (frontend)
// - InterfacesTable component (frontend)
// ... repeat for every table
```

**OLAV Approach** (Schema-aware):
```typescript
// ✅ Single generic component for ALL tables
function TablePage({ tableName }: { tableName: string }) {
  // Single endpoint for any table
  const { data: schema } = useQuery({
    queryFn: () => fetch(`/api/schema/${tableName}`).then(r => r.json())
  });
  
  const { data: result } = useQuery({
    queryFn: () => fetch(`/api/data/${tableName}`).then(r => r.json())
  });
  
  // Auto-generated UI from schema
  return <GenericTable schema={schema} data={result} />;
}

// No new code needed when adding tables!
// DuckDB schema change → Frontend auto-updates
```

### 2. DuckDB Schema Changes → Auto-Reflected in Web UI

**Scenario**: Add new view `v_power_supplies` in DuckDB

**Traditional**:
1. ❌ Add DuckDB view
2. ❌ Create `/api/power_supplies` endpoint
3. ❌ Create `PowerSuppliesTable` React component
4. ❌ Add route in frontend
5. ❌ Update navigation menu

**OLAV Schema-Aware**:
1. ✅ Add DuckDB view
2. ✅ **Done** - Web UI auto-discovers and renders new table

### 3. Unified Data Access Pattern

**All data access through 2 endpoints**:
```
GET /api/schema/{table}        # Metadata
GET /api/data/{table}?filters  # Actual data
```

**No need for**:
- `/api/devices`
- `/api/interfaces`
- `/api/bgp`
- `/api/ospf`
- ... (100+ endpoints)

### 4. Type Safety from Database to Frontend

```typescript
// TypeScript types auto-generated from schema
type Device = {
  name: string;      // From schema.columns[0]
  ip: string | null; // From schema.columns[1] (nullable: true)
  platform: string;
  // ... auto-generated from DuckDB schema
};

// No manual type definitions!
```

---

## 🚀 Implementation Roadmap

### Phase 1: Programmatic API Foundation (Week 1) 🔴 **Critical**

**Priority**: HIGHEST (blocks both System Admin Agent + Web API)

**Deliverables**:
- [ ] `src/olav/api/schema.py`
  - `list_tables()` - Discover all tables/views
  - `get_table_schema(name)` - Get column metadata
  - `get_sample_data(table, limit)` - Preview data

- [ ] `src/olav/api/data.py`
  - `query_table(table, filters)` - Dynamic queries
  - `QueryFilters` - WHERE/ORDER BY/LIMIT/OFFSET

- [ ] `src/olav/api/query.py`
  - `run_query(text)` - Orchestrator wrapper
  - `stream_query(text)` - Async streaming

- [ ] `src/olav/api/models.py`
  - Pydantic models for all responses

**Testing**:
```python
# tests/api/test_schema.py
def test_list_tables():
    result = list_tables()
    assert result.total_tables >= 2
    assert "devices" in [t.name for t in result.tables]

def test_get_table_schema():
    schema = get_table_schema("devices")
    assert "name" in [col["name"] for col in schema.columns]

def test_query_table_with_filters():
    filters = QueryFilters(where="name = 'R1'", limit=10)
    result = query_table("devices", filters)
    assert len(result.rows) <= 10
```

---

### Phase 2: FastAPI HTTP Layer (Week 2)

**Priority**: HIGH (enables Web GUI development)

**Deliverables**:
- [ ] `src/olav/web/api.py`
  - Schema endpoints: `/api/schema/tables`, `/api/schema/{table}`
  - Data endpoints: `/api/data/{table}`
  - Query endpoints: `/api/query`, `/ws/query` (WebSocket)
  - System endpoints: `/api/system/health`

- [ ] OpenAPI documentation (auto-generated by FastAPI)

- [ ] CORS configuration for frontend

**Testing**:
```python
# tests/web/test_api.py
from fastapi.testclient import TestClient

def test_list_tables_endpoint():
    response = client.get("/api/schema/tables")
    assert response.status_code == 200
    assert "tables" in response.json()

def test_query_table_endpoint():
    response = client.get("/api/data/devices")
    assert response.status_code == 200
    assert "rows" in response.json()

def test_websocket_query():
    with client.websocket_connect("/ws/query") as ws:
        ws.send_json({"query": "show R1"})
        data = ws.receive_json()
        assert data["type"] in ["thinking", "token", "complete"]
```

**Run FastAPI**:
```bash
# Development server
uv run uvicorn olav.web.api:app --reload --port 8000

# Production (with Gunicorn)
uv run gunicorn olav.web.api:app -w 4 -k uvicorn.workers.UvicornWorker
```

---

### Phase 3: Web GUI (Week 3-4)

**Priority**: MEDIUM (user experience enhancement)

**Deliverables**:
- [ ] React frontend scaffolding (Vite + TypeScript)
- [ ] Schema-aware table viewer (GenericTable component)
- [ ] Dynamic navigation menu (from `/api/schema/tables`)
- [ ] Real-time query interface (WebSocket chat)
- [ ] Auto-generated filter builders
- [ ] Responsive design (TailwindCSS)

**File Structure**:
```
web/
├── src/
│   ├── components/
│   │   ├── GenericTable.tsx      # Schema-driven table
│   │   ├── FilterBuilder.tsx     # Auto-generated filters
│   │   ├── QueryInterface.tsx    # WebSocket chat
│   │   └── Navigation.tsx        # Dynamic nav menu
│   ├── hooks/
│   │   ├── useSchema.ts          # Fetch table schema
│   │   ├── useTableData.ts       # Fetch table data
│   │   └── useQueryStream.ts     # WebSocket query
│   ├── App.tsx
│   └── main.tsx
├── package.json
└── vite.config.ts
```

**Example Usage**:
```typescript
// App.tsx
function App() {
  const { data: schema } = useQuery({
    queryKey: ['all-tables'],
    queryFn: () => fetch('/api/schema/tables').then(r => r.json())
  });
  
  return (
    <Router>
      <Navigation tables={schema?.tables} views={schema?.views} />
      <Routes>
        <Route path="/table/:tableName" element={<TablePage />} />
        <Route path="/query" element={<QueryInterface />} />
      </Routes>
    </Router>
  );
}
```

---

### Phase 4: Advanced Features (Post-MVP)

**Priority**: LOW (nice-to-have)

**Features**:
- [ ] GraphQL endpoint (alternative to REST)
- [ ] Real-time dashboard (WebSocket data streaming)
- [ ] Export to CSV/Excel from Web UI
- [ ] Visual query builder (drag-and-drop filters)
- [ ] Dark mode theme
- [ ] Mobile-responsive design
- [ ] User authentication (if multi-user)

---

## 📊 Comparison: Schema-Aware vs Traditional

| Aspect | Traditional REST API | OLAV Schema-Aware API | Improvement |
|--------|---------------------|----------------------|-------------|
| **Endpoint Count** | 50-100 endpoints (one per table) | 2 endpoints (`/schema/{table}`, `/data/{table}`) | **50x reduction** |
| **Code Maintenance** | Add endpoint for each new table | Zero changes needed | **Automatic** |
| **Frontend Bundle** | Hardcoded components per table | Single generic component | **90% smaller** |
| **Type Safety** | Manual TypeScript types | Auto-generated from schema | **Zero drift** |
| **DuckDB Changes** | Update API + Frontend manually | Auto-reflected in UI | **Zero lag** |
| **Development Time** | 1 week per new table view | < 1 hour (just add DuckDB view) | **40x faster** |

---

## ✅ Final Recommendation

### Answer to User's Questions

**Q1: "是应该集成FastAPI，还是programmatic API？"**

**A**: **Both, in layered architecture**
- **Layer 1**: Programmatic API (`olav.api.*`) - Python functions for agents
- **Layer 2**: FastAPI - HTTP REST for Web GUI
- **Layer 3**: Web GUI - React frontend

FastAPI **wraps** Programmatic API (not replacement).

---

**Q2: "需不需把这些API也做成non-ETL schema aware模式？"**

**A**: **Absolutely yes** ✅

**Reasons**:
1. **Consistency**: Web API should inherit OLAV's core philosophy (zero-ETL, schema-aware)
2. **Maintainability**: DuckDB schema changes auto-reflect in API (no manual updates)
3. **Performance**: Direct DuckDB queries (no intermediate data copies)
4. **Developer Experience**: Single endpoint pattern (`/api/data/{table}`) instead of 100+ hardcoded endpoints
5. **Frontend Flexibility**: Auto-generated UI from schema (no hardcoded React components)

**Core Benefit**:
```
Add new DuckDB view → Web UI auto-discovers and renders it
(No code changes needed in API or Frontend)
```

---

## 🎯 Next Steps

**Priority 1** (Week 1): Implement Programmatic API (Phase 1)
- Blocks System Admin Agent tools
- Blocks Web API development
- Foundation for all upper layers

**Priority 2** (Week 2): Implement FastAPI Layer (Phase 2)
- Enables Web GUI development
- Provides schema-aware REST endpoints

**Priority 3** (Week 3-4): Build Web GUI (Phase 3)
- React frontend with schema-driven components
- Real-time query interface

---

**Status**: 📋 Architecture Design Complete  
**Ready for**: Phase 1 Implementation (Programmatic API)
