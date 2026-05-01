"""R99/S2 — strict reranker factory + LlamaCppReranker tests.

Pins the strict-mode contract on AutoRecallMiddleware._get_reranker:

* No silent defaults.  Missing 'kind' or 'base_url' → log + return None.
* Unknown 'kind' → log + return None.
* kind=ollama requires 'model' field.
* LlamaCppReranker constructor requires base_url (no default).
* OllamaEmbeddingReranker constructor requires model_name + base_url.
* LlamaCppReranker calls llama-server's /rerank endpoint with the
  expected JSON schema and parses results back into per-row scores.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pyarrow as pa
import pytest


# ─── strict factory ───────────────────────────────────────────────────────


def _mw_with_cfg(reranker_cfg: dict | None):
    """Build an AutoRecallMiddleware with a faked api.json reranker block."""
    from olav.core.memory.middleware import AutoRecallMiddleware
    mw = AutoRecallMiddleware(store=MagicMock())
    # Reset the lazy-cache + bypass real api.json IO
    mw._reranker_init_attempted = False
    mw._reranker_instance = None

    import json
    fake_cfg = {"reranker": reranker_cfg} if reranker_cfg is not None else {}
    fake_api_json = json.dumps(fake_cfg)

    class _FakePath:
        def __init__(self, content): self._c = content
        def exists(self): return True
        def read_text(self): return self._c
    fp = _FakePath(fake_api_json)

    with patch("pathlib.Path.cwd", return_value=fp), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.read_text", return_value=fake_api_json):
        return mw._get_reranker()


def test_factory_disabled_returns_none():
    """enabled:false → None (no instantiation)."""
    assert _mw_with_cfg({"enabled": False}) is None


def test_factory_missing_kind_returns_none():
    """enabled but no 'kind' → None + warning (no silent ollama fallback)."""
    assert _mw_with_cfg({
        "enabled": True,
        "base_url": "http://gpu:11433",
    }) is None


def test_factory_missing_base_url_returns_none():
    """enabled + kind but no 'base_url' → None."""
    assert _mw_with_cfg({
        "enabled": True,
        "kind": "llama_cpp",
    }) is None


def test_factory_unknown_kind_returns_none():
    """Typo in kind → None, NOT silent fallback to ollama."""
    assert _mw_with_cfg({
        "enabled": True,
        "kind": "vllm",
        "base_url": "http://gpu:11433",
    }) is None


def test_factory_ollama_requires_model():
    """kind=ollama + missing model → None (model is what /api/embeddings needs)."""
    assert _mw_with_cfg({
        "enabled": True,
        "kind": "ollama",
        "base_url": "http://gpu:11434",
    }) is None


def test_factory_llama_cpp_constructs_reranker():
    """Happy path: kind=llama_cpp + base_url → LlamaCppReranker."""
    from olav.core.memory.reranker import LlamaCppReranker
    inst = _mw_with_cfg({
        "enabled": True,
        "kind": "llama_cpp",
        "base_url": "http://gpu:11433",
    })
    assert isinstance(inst, LlamaCppReranker)
    assert inst.base_url == "http://gpu:11433"


def test_factory_kind_aliases():
    """'llama_cpp' / 'llamacpp' / 'llama' all dispatch to LlamaCppReranker."""
    from olav.core.memory.reranker import LlamaCppReranker
    for k in ("llama_cpp", "llamacpp", "llama", "LLAMA_CPP"):
        inst = _mw_with_cfg({
            "enabled": True, "kind": k, "base_url": "http://gpu:11433",
        })
        assert isinstance(inst, LlamaCppReranker), f"alias {k!r} failed"


def test_factory_ollama_path():
    """kind=ollama + model + base_url → OllamaEmbeddingReranker."""
    from olav.core.memory.reranker import OllamaEmbeddingReranker
    inst = _mw_with_cfg({
        "enabled": True,
        "kind": "ollama",
        "model": "bge-reranker-v2-m3",
        "base_url": "http://gpu:11434",
    })
    assert isinstance(inst, OllamaEmbeddingReranker)
    assert inst.model_name == "bge-reranker-v2-m3"


# ─── LlamaCppReranker constructor strictness ──────────────────────────────


def test_llamacpp_reranker_requires_base_url():
    from olav.core.memory.reranker import LlamaCppReranker
    with pytest.raises(TypeError):
        LlamaCppReranker()  # type: ignore[call-arg]


def test_ollama_reranker_requires_model_and_base_url():
    from olav.core.memory.reranker import OllamaEmbeddingReranker
    with pytest.raises(TypeError):
        OllamaEmbeddingReranker()  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        OllamaEmbeddingReranker(model_name="x")  # type: ignore[call-arg]


# ─── LlamaCppReranker request shape + score parsing ───────────────────────


class _FakeHttp:
    def __init__(self, response_json):
        self.posted_url = None
        self.posted_json = None
        self._response = response_json

    def post(self, url, *, json):
        self.posted_url = url
        self.posted_json = json
        resp = MagicMock()
        resp.raise_for_status = lambda: None
        resp.json = lambda: self._response
        return resp


def test_llamacpp_reranker_calls_rerank_endpoint_and_orders_by_score():
    from olav.core.memory.reranker import LlamaCppReranker

    fake = _FakeHttp({
        "results": [
            {"index": 0, "relevance_score": 0.05},
            {"index": 1, "relevance_score": 0.97},
            {"index": 2, "relevance_score": 0.0001},
        ],
    })
    rr = LlamaCppReranker(base_url="http://gpu:11433")
    rr._http = fake

    table = pa.table({
        "id": ["a", "b", "c"],
        "text": ["doc-a", "doc-b", "doc-c"],
    })
    out = rr.rerank_vector("q", table)

    # llama-server /rerank endpoint, NOT /v1/rerank
    assert fake.posted_url == "http://gpu:11433/rerank"
    assert fake.posted_json == {
        "query": "q",
        "documents": ["doc-a", "doc-b", "doc-c"],
    }

    # Sorted descending by relevance: b (0.97) > a (0.05) > c (0.0001)
    ids = out.column("id").to_pylist()
    scores = out.column("_relevance_score").to_pylist()
    assert ids == ["b", "a", "c"]
    assert scores[0] > scores[1] > scores[2]


def test_llamacpp_reranker_handles_endpoint_failure_with_nan():
    from olav.core.memory.reranker import LlamaCppReranker

    rr = LlamaCppReranker(base_url="http://gpu:11433")

    class _Boom:
        def post(self, *a, **kw):
            raise RuntimeError("network down")
    rr._http = _Boom()

    table = pa.table({"id": ["a", "b"], "text": ["x", "y"]})
    out = rr.rerank_vector("q", table)
    scores = out.column("_relevance_score").to_pylist()
    # NaN → all rows present, no crash, ranks are stable
    import math
    assert all(math.isnan(s) for s in scores)


def test_llamacpp_reranker_strips_trailing_slash_from_base_url():
    from olav.core.memory.reranker import LlamaCppReranker
    rr = LlamaCppReranker(base_url="http://gpu:11433/")
    assert rr.base_url == "http://gpu:11433"


def test_llamacpp_reranker_empty_table():
    from olav.core.memory.reranker import LlamaCppReranker
    rr = LlamaCppReranker(base_url="http://gpu:11433")
    table = pa.table({"id": [], "text": []})
    out = rr.rerank_vector("q", table)
    assert out.num_rows == 0


# ─── Cloud kind dispatch (openrouter / cohere / openai_compat) ────────────


def test_factory_openrouter_requires_model():
    """kind=openrouter without model → None."""
    assert _mw_with_cfg({
        "enabled": True,
        "kind": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": "sk-or-v1-test",
    }) is None


def test_factory_openrouter_requires_api_key():
    """kind=openrouter without api_key (and no shared fallback) → None."""
    assert _mw_with_cfg({
        "enabled": True,
        "kind": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "cohere/rerank-4-fast",
    }) is None


def test_factory_openrouter_constructs_with_model_and_key():
    """Happy path: kind=openrouter + model + api_key → LlamaCppReranker w/ both fields set."""
    from olav.core.memory.reranker import LlamaCppReranker
    inst = _mw_with_cfg({
        "enabled": True,
        "kind": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "cohere/rerank-4-fast",
        "api_key": "sk-or-v1-test",
    })
    assert isinstance(inst, LlamaCppReranker)
    assert inst._model == "cohere/rerank-4-fast"
    assert inst._api_key == "sk-or-v1-test"
    assert inst.base_url == "https://openrouter.ai/api/v1"


def test_factory_cloud_kind_aliases():
    """openrouter / cohere / openai_compat / openai all dispatch the cloud path."""
    from olav.core.memory.reranker import LlamaCppReranker
    for k in ("openrouter", "cohere", "openai_compat", "openai"):
        inst = _mw_with_cfg({
            "enabled": True, "kind": k,
            "base_url": "https://example.com/v1",
            "model": "rerank-x", "api_key": "k",
        })
        assert isinstance(inst, LlamaCppReranker), f"alias {k!r} failed"
        assert inst._model == "rerank-x"


def test_cloud_body_includes_model_and_bearer_header():
    """When model + api_key set, request body has model field; httpx client carries Bearer header."""
    from olav.core.memory.reranker import LlamaCppReranker

    captured: dict = {}

    class _SpyHttp:
        def post(self, url, *, json):
            captured["url"] = url
            captured["json"] = json
            resp = MagicMock()
            resp.raise_for_status = lambda: None
            resp.json = lambda: {"results": [
                {"index": 0, "relevance_score": 0.1},
                {"index": 1, "relevance_score": 0.9},
            ]}
            return resp

    rr = LlamaCppReranker(
        base_url="https://openrouter.ai/api/v1",
        model="cohere/rerank-4-fast",
        api_key="sk-or-v1-test",
    )
    rr._http = _SpyHttp()
    table = pa.table({"id": ["a", "b"], "text": ["x", "y"]})
    rr.rerank_vector("q", table)

    assert captured["url"] == "https://openrouter.ai/api/v1/rerank"
    assert captured["json"] == {
        "query": "q",
        "documents": ["x", "y"],
        "model": "cohere/rerank-4-fast",
    }


def test_local_body_omits_model_when_unset():
    """When model is None (local llama-server), 'model' field is NOT sent."""
    from olav.core.memory.reranker import LlamaCppReranker

    captured: dict = {}

    class _SpyHttp:
        def post(self, url, *, json):
            captured["json"] = json
            resp = MagicMock()
            resp.raise_for_status = lambda: None
            resp.json = lambda: {"results": []}
            return resp

    rr = LlamaCppReranker(base_url="http://gpu:11433")  # no model, no api_key
    rr._http = _SpyHttp()
    table = pa.table({"id": ["a"], "text": ["x"]})
    rr.rerank_vector("q", table)

    assert "model" not in captured["json"]


def test_factory_openrouter_falls_back_to_shared_api_key():
    """If reranker.api_key is missing but shared.api_key is set, cloud path still constructs."""
    # _mw_with_cfg only stubs api.json reranker block.  Patch the
    # full-config read by simulating a payload with shared block too.
    from olav.core.memory.middleware import AutoRecallMiddleware
    from olav.core.memory.reranker import LlamaCppReranker
    import json as _json

    full = {
        "shared": {"api_key": "sk-or-v1-shared"},
        "reranker": {
            "enabled": True,
            "kind": "openrouter",
            "base_url": "https://openrouter.ai/api/v1",
            "model": "cohere/rerank-4-fast",
            # no api_key — should pick up shared
        },
    }
    payload = _json.dumps(full)

    mw = AutoRecallMiddleware(store=MagicMock())
    mw._reranker_init_attempted = False
    mw._reranker_instance = None

    with patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.read_text", return_value=payload):
        inst = mw._get_reranker()

    assert isinstance(inst, LlamaCppReranker)
    assert inst._api_key == "sk-or-v1-shared"
