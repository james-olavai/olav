"""LLMFactory.check_connectivity() / check_embedding_connectivity().

dev_docs/99 §3.1 — a single deterministic connectivity check shared by
``olav doctor`` and ``test_connectivity()`` (backward-compat bool wrapper).
Covers:
1. check_connectivity() returns (True, "connected") on success
2. check_connectivity() returns (False, <exception message>) on failure
3. test_connectivity() still returns a plain bool (existing callers/tests
   monkeypatch this name directly — must keep working unmodified)
4. check_embedding_connectivity() mirrors the same (ok, detail) contract
5. §3.4: both accept an ``overrides`` dict so a candidate (not-yet-
   committed) config can be probed before writing it, and ``strict``
   disables the embedding API→local fallback so a bad candidate key
   surfaces as a real failure instead of silently passing
"""

from __future__ import annotations

import olav.core.llm as llm_mod
from olav.core.llm import LLMFactory


def test_check_connectivity_success(monkeypatch) -> None:
    class _FakeLLM:
        def invoke(self, messages):
            return "OK"

    monkeypatch.setattr(LLMFactory, "get_chat_model", staticmethod(lambda **kw: _FakeLLM()))
    ok, detail = LLMFactory.check_connectivity()
    assert ok is True
    assert detail == "connected"


def test_check_connectivity_failure_returns_reason(monkeypatch) -> None:
    def _raise(**kw):
        raise RuntimeError("401 Unauthorized")

    monkeypatch.setattr(LLMFactory, "get_chat_model", staticmethod(_raise))
    ok, detail = LLMFactory.check_connectivity()
    assert ok is False
    assert "401 Unauthorized" in detail


def test_test_connectivity_still_returns_bool(monkeypatch) -> None:
    """Existing callers (init.py) and tests monkeypatch `test_connectivity`
    directly with a bare bool-returning lambda — that must keep working."""
    monkeypatch.setattr(llm_mod.LLMFactory, "test_connectivity", staticmethod(lambda: True))
    assert llm_mod.LLMFactory.test_connectivity() is True


def test_test_connectivity_delegates_to_check_connectivity(monkeypatch) -> None:
    monkeypatch.setattr(
        LLMFactory, "check_connectivity", staticmethod(lambda: (False, "boom"))
    )
    assert LLMFactory.test_connectivity() is False


def test_check_embedding_connectivity_success(monkeypatch) -> None:
    class _FakeEmbeddings:
        def embed_query(self, text):
            return [0.1, 0.2]

    monkeypatch.setattr(LLMFactory, "get_embeddings", staticmethod(lambda **kw: _FakeEmbeddings()))
    ok, detail = LLMFactory.check_embedding_connectivity()
    assert ok is True
    assert detail == "connected"


def test_check_embedding_connectivity_failure_returns_reason(monkeypatch) -> None:
    def _raise(**kw):
        raise RuntimeError("model download failed")

    monkeypatch.setattr(LLMFactory, "get_embeddings", staticmethod(_raise))
    ok, detail = LLMFactory.check_embedding_connectivity()
    assert ok is False
    assert "model download failed" in detail


def test_check_connectivity_forwards_overrides_to_get_chat_model(monkeypatch) -> None:
    seen = {}

    class _FakeLLM:
        def invoke(self, messages):
            return "OK"

    def _fake_get_chat_model(**kw):
        seen.update(kw)
        return _FakeLLM()

    monkeypatch.setattr(LLMFactory, "get_chat_model", staticmethod(_fake_get_chat_model))
    candidate = {"model": "deepseek-chat", "api_key": "sk-candidate"}
    ok, _ = LLMFactory.check_connectivity(overrides=candidate)
    assert ok is True
    assert seen.get("overrides") == candidate


def test_check_embedding_connectivity_forwards_overrides_and_strict(monkeypatch) -> None:
    seen = {}

    class _FakeEmbeddings:
        def embed_query(self, text):
            return [0.1]

    def _fake_get_embeddings(**kw):
        seen.update(kw)
        return _FakeEmbeddings()

    monkeypatch.setattr(LLMFactory, "get_embeddings", staticmethod(_fake_get_embeddings))
    candidate = {"mode": "api", "api_key": "sk-candidate"}
    ok, _ = LLMFactory.check_embedding_connectivity(overrides=candidate, strict=True)
    assert ok is True
    assert seen.get("overrides") == candidate
    assert seen.get("strict") is True


def test_get_chat_model_api_key_override_beats_config(monkeypatch) -> None:
    """dev_docs/99 §3.4: api_key must be override-able like model/base_url/
    model_provider already were — needed to validate a candidate config."""
    import olav.core.llm as llm_mod

    class _FakeLLMConfig:
        api_key = "config-key"
        model = "gpt-4o"
        temperature = 0.1
        max_tokens = None
        base_url = ""
        model_provider = ""
        timeout = 30

    monkeypatch.setattr(llm_mod, "init_chat_model", lambda **params: params)
    monkeypatch.setattr(
        "olav.core.config.get_llm_config", lambda: _FakeLLMConfig()
    )

    params = LLMFactory.get_chat_model(overrides={"api_key": "candidate-key"})
    assert params["api_key"] == "candidate-key"


def test_get_embeddings_mode_and_api_key_overridable(monkeypatch) -> None:
    """dev_docs/99 §3.4: mode/api_key/model must be override-able to
    validate a candidate embedding config before committing it."""
    import olav.core.llm as llm_mod

    class _FakeEmbeddingConfig:
        mode = "local"
        api_key = ""
        openai_model = "text-embedding-3-small"
        local_model = "BAAI/bge-small-zh-v1.5"
        base_url = ""
        normalize_embeddings = True
        fallback_enabled = True

    seen = {}

    class _FakeOpenAIEmbeddings:
        def __init__(self, **kw):
            seen.update(kw)

    monkeypatch.setattr(
        "olav.core.config.get_embedding_config", lambda: _FakeEmbeddingConfig()
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "langchain_openai",
        __import__("types").SimpleNamespace(OpenAIEmbeddings=_FakeOpenAIEmbeddings),
    )

    LLMFactory.get_embeddings(overrides={"mode": "api", "api_key": "candidate-key"})
    assert seen.get("api_key") == "candidate-key"
