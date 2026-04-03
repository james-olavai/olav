# HTTP API 参考

OLAV Web 服务提供 REST + SSE 流式 API，兼容 LangGraph Server API 协议。适用于与外部系统集成、构建自定义 UI、或在 CI/CD 流水线中调用 OLAV。

!!! abstract "功能声明"
    | ID | 声明 | 状态 |
    |----|------|------|
    | C-L2-16 | Web 服务启动并监听 | ✅ v0.10.0 |
    | C-L2-29 | `POST /runs/stream` SSE 流式查询 | ✅ v0.10.0 |
    | C-L2-30 | `POST /threads` 多轮对话线程管理 | ✅ v0.10.0 |
    | C-L2-42 | `/openapi.json`、`/docs`、`/threads/search` 自省接口 | ✅ v0.10.0 |

---

## 启动服务

```bash
olav service web start                              # 默认 http://0.0.0.0:2280
olav service web start --host 127.0.0.1 --port 8080 # 自定义地址
olav service web stop                                # 停止
olav service web status                              # 查看状态
```

---

## 认证

除 `/health` 外，所有接口都需要 Bearer Token：

```http
Authorization: Bearer <your-olav-token>
```

令牌存储在 `~/.olav/token`：

```bash
cat ~/.olav/token
```

---

## 接口列表

### `GET /health` — 健康检查

无需认证。用于负载均衡器或监控探针。

```bash
curl http://localhost:2280/health
```

```json
{"status": "healthy", "service": "olav-api"}
```

---

### `POST /runs/stream` — 执行查询（流式）

向 Agent 发送问题，获取 SSE 流式响应。这是最常用的接口。

```bash
curl -X POST http://localhost:2280/runs/stream \
  -H "Authorization: Bearer $(cat ~/.olav/token)" \
  -H "Content-Type: application/json" \
  -d '{
    "input": {"messages": [{"role": "user", "content": "列出所有 Agent"}]},
    "assistant_id": "quick"
  }'
```

响应是 Server-Sent Events 流：

```
data: {"type": "message_chunk", "content": "Available agents:\n"}
data: {"type": "message_chunk", "content": "- quick\n- config\n- audit\n"}
data: {"type": "done"}
```

**请求体字段：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `input.messages` | array | ✅ | 对话消息数组（`role`: `user` 或 `assistant`） |
| `assistant_id` | string | | 目标 Agent（默认：`olav-orchestrator`，自动路由） |
| `thread_id` | string | | 指定会话线程（用于多轮对话） |
| `user_id` | string | | 覆盖用户身份 |

---

### `POST /threads` — 创建会话线程

创建一个持久化的对话线程，用于多轮交互。Agent 会记住线程内的上下文。

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

### `POST /threads/{thread_id}/runs/stream` — 在线程中继续对话

在已有线程中发送新消息，Agent 保持完整的对话上下文：

```bash
THREAD_ID="550e8400-e29b-41d4-a716-446655440000"

curl -X POST http://localhost:2280/threads/$THREAD_ID/runs/stream \
  -H "Authorization: Bearer $(cat ~/.olav/token)" \
  -H "Content-Type: application/json" \
  -d '{
    "input": {"messages": [{"role": "user", "content": "详细说说 quick Agent"}]},
    "assistant_id": "quick"
  }'
```

---

### `GET /threads/search` — 搜索会话线程

查找已有的会话线程：

```bash
curl "http://localhost:2280/threads/search?user_id=alice" \
  -H "Authorization: Bearer $(cat ~/.olav/token)"
```

---

## 集成示例

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
                "input": {"messages": [{"role": "user", "content": "列出所有 Agent"}]},
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
        input: { messages: [{ role: "user", content: "列出所有 Agent" }] },
        assistant_id: "quick",
      }),
    });

    const reader = response.body.getReader();
    const decoder = new TextDecoder();

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      const text = decoder.decode(value);
      // 解析 SSE 事件
      console.log(text);
    }
    ```

=== "curl（流式）"

    ```bash
    curl -N -X POST http://localhost:2280/runs/stream \
      -H "Authorization: Bearer $(cat ~/.olav/token)" \
      -H "Content-Type: application/json" \
      -d '{"input": {"messages": [{"role": "user", "content": "列出所有 Agent"}]}, "assistant_id": "quick"}'
    ```

---

## OpenAPI 规范

完整的 OpenAPI schema：

```
http://localhost:2280/openapi.json
```

交互式 API 文档（Swagger UI）：

```
http://localhost:2280/docs
```
