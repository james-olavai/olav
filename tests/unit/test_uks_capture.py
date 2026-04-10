"""Phase 2 TDD — AutoCapture UKS enhancement.

C-KB-04: extracted items contain a "tags" array
C-KB-05: capture writes origin="agent", confidence=importance from LLM response
"""

import json
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import tempfile
import lancedb
import pyarrow as pa

DIM = 32
DUMMY_VECTOR = [0.0] * DIM


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_store(tmp_path):
    from olav.core.memory import LanceDBStore
    return LanceDBStore(db_path=str(tmp_path / "mem.db"), embedding_dim=DIM)


def _make_fake_llm(response_json: list) -> MagicMock:
    """Build a mock LangChain LLM that returns the given JSON as a response."""
    msg = MagicMock()
    msg.content = json.dumps(response_json)
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=msg)
    return llm


# ─── C-KB-04: _EXTRACT_PROMPT must include tags instruction ──────────────────

def test_extract_prompt_includes_tags_field():
    """C-KB-04: _EXTRACT_PROMPT must mention 'tags' field so the LLM emits them."""
    from olav.core.memory.middleware import _EXTRACT_PROMPT
    assert '"tags"' in _EXTRACT_PROMPT or "'tags'" in _EXTRACT_PROMPT, (
        "_EXTRACT_PROMPT must instruct the LLM to include a 'tags' array per item"
    )


def test_extract_prompt_tags_description():
    """C-KB-04: _EXTRACT_PROMPT should describe tags as entity/topic identifiers."""
    from olav.core.memory.middleware import _EXTRACT_PROMPT
    assert "tags" in _EXTRACT_PROMPT.lower(), (
        "_EXTRACT_PROMPT must include tags field description"
    )


# ─── C-KB-05: process() writes origin="agent" and confidence=importance ──────

@pytest.mark.asyncio
async def test_capture_writes_origin_agent(tmp_path):
    """C-KB-05: AutoCaptureMiddleware writes origin='agent' for captured memories."""
    store = _make_store(tmp_path)
    store.create_table()

    llm_items = [
        {"text": "OLAV uses LanceDB for long-term memory.", "category": "fact",
         "importance": 0.8, "tags": ["lancedb", "memory"]}
    ]
    llm = _make_fake_llm(llm_items)

    conversation_input = "Tell me about OLAV memory architecture and how it stores knowledge."
    from olav.core.memory.middleware import AutoCaptureMiddleware
    with patch("olav.core.memory.middleware.AutoCaptureMiddleware._embed",
               return_value=DUMMY_VECTOR), \
         patch("olav.core.memory.middleware.AutoCaptureMiddleware._is_duplicate",
               return_value=False):
        capture = AutoCaptureMiddleware(store, llm, similarity_dedup_threshold=0.92)
        await capture.process(conversation_input, {"messages": [], "status": "ok"},
                               scope="global")

    memories = store.get_memories(limit=10)
    assert len(memories) == 1, "Expected exactly 1 captured memory"
    assert memories[0]["origin"] == "agent", (
        f"Expected origin='agent', got {memories[0]['origin']!r}"
    )


@pytest.mark.asyncio
async def test_capture_writes_confidence_from_importance(tmp_path):
    """C-KB-05: confidence column must equal the importance from the LLM item."""
    store = _make_store(tmp_path)
    store.create_table()

    importance_value = 0.73
    llm_items = [
        {"text": "Policy X must be reviewed quarterly.", "category": "decision",
         "importance": importance_value, "tags": ["policy"]}
    ]
    llm = _make_fake_llm(llm_items)

    conversation_input = "Discussion about quarterly review policy and compliance requirements."
    from olav.core.memory.middleware import AutoCaptureMiddleware
    with patch("olav.core.memory.middleware.AutoCaptureMiddleware._embed",
               return_value=DUMMY_VECTOR), \
         patch("olav.core.memory.middleware.AutoCaptureMiddleware._is_duplicate",
               return_value=False):
        capture = AutoCaptureMiddleware(store, llm, similarity_dedup_threshold=0.92)
        await capture.process(conversation_input, {"messages": [], "status": "ok"},
                               scope="global")

    memories = store.get_memories(limit=10)
    assert len(memories) == 1
    stored_confidence = float(memories[0]["confidence"])
    assert abs(stored_confidence - importance_value) < 1e-4, (
        f"Expected confidence≈{importance_value}, got {stored_confidence}"
    )


@pytest.mark.asyncio
async def test_capture_writes_tags_from_llm(tmp_path):
    """C-KB-04+C-KB-05: tags extracted by LLM are stored as JSON string."""
    store = _make_store(tmp_path)
    store.create_table()

    llm_items = [
        {"text": "BGP neighbour R1 went down at 03:00.", "category": "fact",
         "importance": 0.9, "tags": ["bgp", "r1", "routing"]}
    ]
    llm = _make_fake_llm(llm_items)

    conversation_input = "Investigating BGP incident: R1 neighbour lost session at 03:00 UTC."
    from olav.core.memory.middleware import AutoCaptureMiddleware
    with patch("olav.core.memory.middleware.AutoCaptureMiddleware._embed",
               return_value=DUMMY_VECTOR), \
         patch("olav.core.memory.middleware.AutoCaptureMiddleware._is_duplicate",
               return_value=False):
        capture = AutoCaptureMiddleware(store, llm, similarity_dedup_threshold=0.92)
        await capture.process(conversation_input, {"messages": [], "status": "ok"},
                               scope="global")

    memories = store.get_memories(limit=10)
    assert len(memories) == 1
    tags_raw = memories[0]["tags"]
    assert isinstance(tags_raw, str), f"tags must be a JSON string, got {type(tags_raw)}"
    tags_parsed = json.loads(tags_raw)
    assert isinstance(tags_parsed, list), f"tags JSON must decode to a list, got {type(tags_parsed)}"
    assert "bgp" in tags_parsed, f"Expected 'bgp' in tags, got {tags_parsed}"


@pytest.mark.asyncio
async def test_capture_missing_tags_defaults_to_empty_list(tmp_path):
    """C-KB-04: LLM item without 'tags' key should default to '[]' not crash."""
    store = _make_store(tmp_path)
    store.create_table()

    # LLM item without tags key
    llm_items = [
        {"text": "User prefers dark mode.", "category": "preference", "importance": 0.6}
    ]
    llm = _make_fake_llm(llm_items)

    conversation_input = "User expressed a strong preference for using dark mode in all interfaces."
    from olav.core.memory.middleware import AutoCaptureMiddleware
    with patch("olav.core.memory.middleware.AutoCaptureMiddleware._embed",
               return_value=DUMMY_VECTOR), \
         patch("olav.core.memory.middleware.AutoCaptureMiddleware._is_duplicate",
               return_value=False):
        capture = AutoCaptureMiddleware(store, llm, similarity_dedup_threshold=0.92)
        await capture.process(conversation_input, {"messages": [], "status": "ok"},
                               scope="global")

    memories = store.get_memories(limit=10)
    assert len(memories) == 1
    tags_raw = memories[0]["tags"]
    tags_parsed = json.loads(tags_raw)
    assert tags_parsed == [], f"Expected empty list when tags missing, got {tags_parsed}"
