# OLAV API Design Document

**Version**: v1.0.0  
**Date**: 2026-02-23  
**Status**: Planning

---

## Overview

This document defines the API strategy for OLAV to support:
1. **Multi-user concurrent access**
2. **WebUI integration** (deep-agents-ui)
3. **IDE integration** (ACP protocol)
4. **Streaming responses** (SSE)

---

## Architecture Decision

### Why Not ACP?

| Protocol | Purpose | Use Case |
|----------|---------|----------|
| **ACP** (Agent Client Protocol) | Agent ↔ IDE | IDE plugins (Zed, JetBrains) |
| **LangGraph Server API** | Agent ↔ Web Client | Web dashboards, microservices |
| **MCP** (Model Context Protocol) | Agent ↔ Tools | Tool discovery and execution |

**Decision**: Implement **LangGraph Server API** as primary API layer. ACP can be added later for IDE integration if needed.

**Reasoning**:
- ACP is specialized for IDE integration (JSON-RPC 2.0 + stdio)
- deep-agents-ui expects LangGraph Server API (HTTP/SSE)
- LangGraph Server API is REST-friendly and widely compatible

---

## API Standard: LangGraph Server API

### Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/threads` | POST | Create new conversation thread |
| `/threads/search` | GET | List existing threads |
| `/threads/{id}/runs/stream` | POST | Stream execution (primary) |
| `/threads/{id}/state` | POST | Update thread state (HITL) |
| `/threads/{id}/runs/{run_id}/resume` | POST | Resume after interrupt |
| `/runs/stream` | POST | Threadless streaming execution |
| `/health` | GET | Health check |

### Request Format

```json
{
  "assistant_id": "olav-orchestrator",
  "input": {
    "messages": [
      {"role": "user", "content": "How many devices?"}
    ]
  },
  "thread_id": "uuid-string",
  "stream_mode": "messages-tuple"
}
```

### Response Format (SSE)

```
data: {"event": "on_chat_model_stream", "data": {"chunk": {"content": "Hello"}}}

data: {"event": "on_tool_start", "data": {"name": "execute_sql", "input": {...}}}

data: {"event": "on_tool_end", "data": {"output": {...}}}

data: {"event": "on_custom_event", "data": {"status": "planning"}}

data: {"event": "on_chain_end", "data": {"output": "Done"}}
```

---

## Streaming Implementation

### Core Pattern: FastAPI + SSE + astream_events

```python
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
import json

async def event_generator(agent, user_input: str, thread_id: str):
    config = {"configurable": {"thread_id": thread_id}}
    
    # CRITICAL: stream_subgraphs=True enables SubAgent streaming
    async for event in agent.graph.astream_events(
        {"messages": [{"role": "user", "content": user_input}]},
        config=config,
        version="v2",
        stream_subgraphs=True
    ):
        yield f"data: {json.dumps(event)}\n\n"

@app.post("/threads/{thread_id}/runs/stream")
async def stream_run(thread_id: str, body: RunStreamRequest):
    return StreamingResponse(
        event_generator(get_agent(), body.input, thread_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )
```

### Event Types

| Event | Description |
|-------|-------------|
| `on_chat_model_stream` | LLM token chunks |
| `on_tool_start` | Tool invocation started |
| `on_tool_end` | Tool execution completed |
| `on_chain_start` | Node entered |
| `on_chain_end` | Node completed |
| `on_custom_event` | Custom progress updates (via `get_stream_writer`) |

### Custom Progress Updates

```python
from langgraph.config import get_stream_writer

def my_node(state):
    writer = get_stream_writer()
    writer({"status": "analyzing", "progress": 50})  # Emits on_custom_event
    # ... node logic
```

---

## WebUI Integration: deep-agents-ui

### Architecture

```
┌─────────────────┐     HTTP/SSE      ┌─────────────────┐
│  deep-agents-ui │ ───────────────── │   OLAV API      │
│  (Next.js)      │                   │  (FastAPI)      │
└─────────────────┘                   └────────┬────────┘
                                               │
                                               ▼
                                      ┌─────────────────┐
                                      │  OLAV Agent     │
                                      │  (DeepAgents)   │
                                      └─────────────────┘
```

### Required State Schema

deep-agents-ui expects this state structure:

```python
class OLAVState(TypedDict):
    messages: Annotated[list, add_messages]  # Required: chat history
    todos: list[dict]                         # Required: task list
    files: dict[str, str]                     # Required: file management
    ui: dict | None                           # Optional: Generative UI
    # OLAV custom fields
    devices: list[dict] | None
    inspection_results: dict | None
```

### Frontend Configuration

```typescript
// deep-agents-ui expects these headers
const client = new Client({
  apiUrl: "http://localhost:2024",
  defaultHeaders: {
    "Content-Type": "application/json",
    "X-Api-Key": "your-api-key",  // Optional auth
  },
});
```

### Deployment

```yaml
# docker-compose.yml
services:
  olav-api:
    build: .
    ports: ["2024:2024"]
    environment:
      - DATABASE_URL=postgresql://...
  
  ui:
    image: langchain/deep-agents-ui:latest
    ports: ["3000:3000"]
    environment:
      - NEXT_PUBLIC_API_URL=http://olav-api:2024
```

---

## IDE Integration: ACP (Future)

### When to Use ACP

ACP (Agent Client Protocol) is designed for **IDE integration**:

- **Zed Industries**: Native ACP support
- **JetBrains**: PyCharm, IntelliJ plugin

### Protocol Overview

| Feature | Specification |
|---------|---------------|
| Foundation | JSON-RPC 2.0 |
| Transport | stdio (local) or Streamable HTTP (remote) |
| State | Session-based (`session/new`, `session/load`) |
| Streaming | Bidirectional via `session/update` |

### Implementation (Future)

```python
# olav/acp/server.py
from deepagents_acp import ACPServer

class OLAVACPHandler:
    async def handle_prompt(self, session, prompt):
        # Bridge to OLAV agent
        result = await self.agent.invoke(prompt)
        return result

# Expose via stdio for IDE integration
server = ACPServer(handler=OLAVACPHandler())
server.run()
```

### Use Case

```
Network Engineer in PyCharm:
1. Edit hosts.yaml (Nornir inventory)
2. Right-click → "OLAV: Validate Config"
3. OLAV agent analyzes via ACP
4. Suggestions appear in IDE
```

---

## Thread & State Management

### Thread ID

- **Purpose**: Unique conversation session identifier
- **Usage**: Passed in `config["configurable"]["thread_id"]`
- **Persistence**: Checkpointer saves state per thread_id

### Checkpointer Options

| Option | Multi-user | Persistence | Performance |
|--------|------------|-------------|-------------|
| MemorySaver | ❌ Process-bound | In-memory | Fastest |
| AsyncPostgresSaver | ✅ | PostgreSQL | Good |
| SQLiteSaver | ⚠️ Single writer | SQLite file | Medium |

### State Persistence Flow

```
User Request → thread_id → Checkpointer.load(thread_id)
                              ↓
                         Agent Execution
                              ↓
                         Checkpointer.save(thread_id, state)
```

---

## Authentication

### API Key (Simple)

```python
from fastapi import Header, HTTPException

async def verify_api_key(x_api_key: str = Header()):
    if x_api_key != settings.API_KEY:
        raise HTTPException(401, "Invalid API key")
```

### LangSmith Integration (deep-agents-ui default)

```python
# deep-agents-ui sends X-Api-Key with LangSmith key
# Can validate against LangSmith API or use custom mapping
```

---

## Implementation Roadmap

### Phase 1: Database Layer
- [ ] Separate high-frequency writes (cache, memory) from business data
- [ ] Implement connection pooling for business data
- [ ] Test multi-user concurrent access

### Phase 2: API Layer
- [ ] Create `src/olav/api/server.py`
- [ ] Implement `/threads`, `/runs/stream` endpoints
- [ ] Add SSE streaming with `astream_events`
- [ ] Test with curl and Python SDK

### Phase 3: WebUI Integration
- [ ] Align State schema with deep-agents-ui expectations
- [ ] Deploy deep-agents-ui with OLAV backend
- [ ] Test end-to-end chat flow

### Phase 4: IDE Integration (Optional)
- [ ] Implement ACP handler
- [ ] Test with Zed/JetBrains
- [ ] Document IDE plugin setup

---

## References

- [LangGraph Server API Docs](https://docs.langchain.com/oss/python/langgraph/local-server)
- [deep-agents-ui GitHub](https://github.com/langchain-ai/deep-agents-ui)
- [ACP Specification](https://docs.langchain.com/oss/python/deepagents/acp)
- [LangGraph Streaming Guide](https://docs.langchain.com/oss/python/deepagents/streaming)
