"""OLAV API - LangGraph Server API compatible layer.

This module provides a FastAPI-based API layer compatible with deep-agents-ui.

Endpoints:
- POST /threads - Create new conversation thread
- GET /threads/search - List existing threads
- POST /threads/{id}/runs/stream - Stream execution (primary)
- POST /runs/stream - Threadless streaming execution
- GET /health - Health check
"""

import json
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel

_STATIC_DIR = Path(__file__).parent / "static"


class ThreadCreate(BaseModel):
    metadata: dict[str, Any] | None = None


class RunStreamRequest(BaseModel):
    assistant_id: str = "olav-orchestrator"
    input: dict[str, Any]
    thread_id: str | None = None
    stream_mode: str = "messages-tuple"


class MessageInput(BaseModel):
    messages: list[dict[str, str]]


_agent_instance = None


async def get_agent():
    global _agent_instance
    if _agent_instance is None:
        from olav.agents.agent import create_olav_agent

        _agent_instance = create_olav_agent()
    return _agent_instance


@asynccontextmanager
async def lifespan(app):
    yield
    if _agent_instance is not None:
        await _agent_instance.close()


app = FastAPI(
    title="OLAV API",
    version="1.0.0",
    description="LangGraph Server API compatible layer for OLAV",
    lifespan=lifespan,
)


@app.get("/", include_in_schema=False)
async def root():
    """Serve the built-in chat UI (all assets are inlined)."""
    index = _STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index), media_type="text/html")
    return RedirectResponse(url="/docs")


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "olav-api"}


@app.post("/threads")
async def create_thread(body: ThreadCreate):
    thread_id = str(uuid.uuid4())
    return {"thread_id": thread_id, "metadata": body.metadata or {}}


@app.get("/threads/search")
async def search_threads():
    return {"threads": []}


@app.post("/threads/{thread_id}/runs/stream")
async def stream_run(thread_id: str, body: RunStreamRequest):
    agent = await get_agent()

    async def event_generator():
        try:
            config = {"configurable": {"thread_id": thread_id}}

            async for event in agent.graph.astream_events(
                body.input,
                config=config,
                version="v2",
                stream_subgraphs=True,
            ):
                event_type = event.get("event", "unknown")
                event_data = event.get("data", {})

                # Custom JSON encoder for LangChain objects
                def encode_obj(obj):
                    if hasattr(obj, "model_dump"):
                        return obj.model_dump()
                    if hasattr(obj, "dict"):
                        return obj.dict()
                    if hasattr(obj, "__dict__"):
                        return vars(obj)
                    return str(obj)

                # Serialize event data
                try:
                    # Quick test to see if standard works
                    json.dumps(event_data)
                    sse_event = {"event": event_type, "data": event_data}
                except (TypeError, ValueError):
                    # Fallback to custom encoder
                    try:
                        sse_event = {
                            "event": event_type,
                            "data": json.loads(json.dumps(event_data, default=encode_obj)),
                        }
                    except Exception:
                        sse_event = {
                            "event": event_type,
                            "data": {
                                "_serialization_error": str(type(event_data)),
                                "message": str(event_data)[:200],
                            },
                        }

                yield f"data: {json.dumps(sse_event)}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/runs/stream")
async def threadless_stream(body: RunStreamRequest):
    thread_id = body.thread_id or str(uuid.uuid4())
    body.thread_id = thread_id
    return await stream_run(thread_id, body)


if __name__ == "__main__":
    import uvicorn

    from olav.core.defaults import DEFAULT_WEB_PORT

    uvicorn.run(app, host="0.0.0.0", port=DEFAULT_WEB_PORT)
