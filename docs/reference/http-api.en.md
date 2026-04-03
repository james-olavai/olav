# HTTP API Reference

The OLAV Web service provides a REST + SSE streaming API, compatible with the LangGraph Server API protocol. Use it to integrate with external systems, build custom UIs, or call OLAV from CI/CD pipelines.

!!! abstract "Feature Claims"
    | ID | Claim | Status |
    |----|-------|--------|
    | C-L2-16 | Web service starts and listens | ✅ v0.10.0 |
    | C-L2-29 | `POST /runs/stream` SSE streaming queries | ✅ v0.10.0 |
    | C-L2-30 | `POST /threads` multi-turn conversation thread management | ✅ v0.10.0 |
    | C-L2-42 | `/openapi.json`, `/docs`, `/threads/search` introspection endpoints | ✅ v0.10.0 |

---

## Starting the Service

```bash
olav service web start                              # Default http://0.0.0.0:2280
olav service web start --host 127.0.0.1 --port 8080 # Custom address
olav service web stop                                # Stop
olav service web status                              # Check status
```

---

## Authentication

All endpoints except `/health` require a Bearer Token:

```http
Authorization: Bearer <your-olav-token>
```

The token is stored in `~/.olav/token`:

```bash
cat ~/.olav/token
```

---

## Endpoint Reference

### `GET /health` — Health Check

No authentication required. Used for load balancers or monitoring probes.

```bash
curl http://localhost:2280/health
```

```json
{"status": "healthy", "service": "olav-api"}
```

---

### `POST /runs/stream` — Execute a Query (Streaming)

Send a question to an Agent and receive an SSE streaming response. This is the most commonly used endpoint.

```bash
curl -X POST http://localhost:2280/runs/stream \
  -H "Authorization: Bearer $(cat ~/.olav/token)" \
  -H "Content-Type: application/json" \
  -d '{
    "input": {"messages": [{"role": "user", "content": "List all Agents"}]},
    "assistant_id": "quick"
  }'
```

The response is a Server-Sent Events stream:

```
data: {"type": "message_chunk", "content": "Available agents:\n"}
data: {"type": "message_chunk", "content": "- quick\n- config\n- audit\n"}
data: {"type": "done"}
```

**Request body fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `input.messages` | array | ✅ | Array of conversation messages (`role`: `user` or `assistant`) |
| `assistant_id` | string | | Target Agent (default: `olav-orchestrator`, auto-routes) |
| `thread_id` | string | | Specify a conversation thread (for multi-turn conversations) |
| `user_id` | string | | Override user identity |

---

### `POST /threads` — Create a Conversation Thread

Create a persistent conversation thread for multi-turn interactions. The Agent remembers context within the thread.

```bash
curl -X POST http://localhost:2280/threads \
  -H "Authorization: Bearer $(cat ~/.olav/token)" \
  -H "Content-Type: application/json" \
  -d '{}'
```

```json
{"thread_id": "550e8400-e29b-41d4-a716-446655440000"}
```

---

### `POST /threads/{thread_id}/runs/stream` — Continue a Conversation in a Thread

Send a new message in an existing thread — the Agent maintains the full conversation context:

```bash
THREAD_ID="550e8400-e29b-41d4-a716-446655440000"

curl -X POST http://localhost:2280/threads/$THREAD_ID/runs/stream \
  -H "Authorization: Bearer $(cat ~/.olav/token)" \
  -H "Content-Type: application/json" \
  -d '{
    "input": {"messages": [{"role": "user", "content": "Tell me more about the quick Agent"}]},
    "assistant_id": "quick"
  }'
```

---

### `GET /threads/search` — Search Conversation Threads

Find existing conversation threads:

```bash
curl "http://localhost:2280/threads/search?user_id=alice" \
  -H "Authorization: Bearer $(cat ~/.olav/token)"
```

---

## Integration Examples

=== "Python"

    ```python
    import httpx
    import json

    token = open("/home/user/.olav/token").read().strip()

    with httpx.Client() as client:
        with client.stream(
            "POST",
            "http://localhost:2280/runs/stream",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "input": {"messages": [{"role": "user", "content": "List all Agents"}]},
                "assistant_id": "quick",
            },
            timeout=60,
        ) as r:
            for line in r.iter_lines():
                if line.startswith("data: "):
                    event = json.loads(line[6:])
                    if event.get("type") == "message_chunk":
                        print(event["content"], end="", flush=True)
    ```

=== "JavaScript"

    ```javascript
    const token = process.env.OLAV_TOKEN;

    const response = await fetch("http://localhost:2280/runs/stream", {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        input: { messages: [{ role: "user", content: "List all Agents" }] },
        assistant_id: "quick",
      }),
    });

    const reader = response.body.getReader();
    const decoder = new TextDecoder();

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      const text = decoder.decode(value);
      // Parse SSE events
      console.log(text);
    }
    ```

=== "curl (Streaming)"

    ```bash
    curl -N -X POST http://localhost:2280/runs/stream \
      -H "Authorization: Bearer $(cat ~/.olav/token)" \
      -H "Content-Type: application/json" \
      -d '{"input": {"messages": [{"role": "user", "content": "List all Agents"}]}, "assistant_id": "quick"}'
    ```

---

## OpenAPI Specification

Full OpenAPI schema:

```
http://localhost:2280/openapi.json
```

Interactive API documentation (Swagger UI):

```
http://localhost:2280/docs
```
