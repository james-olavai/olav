"""Network context middleware injecting topology hints into model requests."""
from __future__ import annotations

from typing import Any
from langchain_core.messages import SystemMessage
from deepagents import AgentMiddleware, ModelRequest

# Placeholder topology fetcher; in future integrate NetBox queries.

def fetch_topology_snippet(device: str | None) -> str:
    if not device:
        return "No device specified; topology summary unavailable."
    # Future: query NetBox for site, role, connected peers, etc.
    return f"Device={device}; role=unknown; peers=0 (topology enrichment pending)"


class NetworkContextMiddleware(AgentMiddleware):
    """Injects lightweight network context before LLM invocation."""

    async def on_model_request(self, request: ModelRequest, state: dict[str, Any]):  # type: ignore[override]
        device = state.get("device")
        snippet = fetch_topology_snippet(device)
        request.messages.insert(0, SystemMessage(content=f"NetworkContext: {snippet}"))
        return request
