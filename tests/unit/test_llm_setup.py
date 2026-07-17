"""Interactive first-run LLM provider setup (dev_docs/99 §7.8).

Covers the provider-selector flow that replaces the assume-OpenAI/gpt-4o
default: menu → endpoint auto-fill/custom → key → model auto-detect/type →
validate-before-return.

_fetch_models and LLMFactory.check_connectivity are monkeypatched so the
flow is exercised with no network.
"""

from __future__ import annotations

import olav.cli.llm_setup as m
import olav.core.llm as llm_mod
from rich.console import Console


class _Prompt:
    """Fake rich Prompt.ask returning queued answers in order."""

    def __init__(self, answers):
        self._it = iter(answers)

    def ask(self, msg, choices=None, default=None, password=False):
        try:
            return next(self._it)
        except StopIteration:  # pragma: no cover — a test queued too few answers
            raise AssertionError(f"prompt ran out of answers at: {msg!r}")


def _console():
    return Console(quiet=True)


def _always_ok(monkeypatch):
    monkeypatch.setattr(
        llm_mod.LLMFactory, "check_connectivity",
        staticmethod(lambda overrides=None: (True, "connected")),
    )


# ---------------------------------------------------------------------------
# happy paths per provider
# ---------------------------------------------------------------------------


def test_deepseek_autodetect_and_pick(monkeypatch) -> None:
    _always_ok(monkeypatch)
    monkeypatch.setattr(m, "_fetch_models", lambda b, k: ["deepseek-v4-flash", "deepseek-v4-pro"])
    # provider=2 (DeepSeek), key, model#2
    llm = m.interactive_llm_setup(_console(), prompt_cls=_Prompt(["2", "sk-x", "2"]))
    assert llm == {
        "provider": "openai", "model_provider": "openai",
        "model": "deepseek-v4-pro", "api_key": "sk-x",
        "base_url": "https://api.deepseek.com/v1",
    }


def test_openai_default_no_base_url(monkeypatch) -> None:
    _always_ok(monkeypatch)
    monkeypatch.setattr(m, "_fetch_models", lambda b, k: ["gpt-4o", "gpt-4o-mini"])
    llm = m.interactive_llm_setup(_console(), prompt_cls=_Prompt(["1", "sk-o", "1"]))
    assert llm["model"] == "gpt-4o"
    assert "base_url" not in llm          # OpenAI uses the client default


def test_local_server_placeholder_key(monkeypatch) -> None:
    _always_ok(monkeypatch)
    monkeypatch.setattr(m, "_fetch_models", lambda b, k: ["qwen3", "embeddinggemma"])
    # provider=5 (Local), blank key → placeholder, model#1
    llm = m.interactive_llm_setup(_console(), prompt_cls=_Prompt(["5", "", "1"]))
    assert llm["api_key"] == "local"
    assert llm["base_url"] == "http://localhost:11434/v1"
    assert llm["model"] == "qwen3"


def test_custom_asks_base_url(monkeypatch) -> None:
    _always_ok(monkeypatch)
    monkeypatch.setattr(m, "_fetch_models", lambda b, k: ["m1"])
    # provider=6 (Custom), base_url, key, model#1
    llm = m.interactive_llm_setup(
        _console(), prompt_cls=_Prompt(["6", "http://host:8000/v1", "k", "1"])
    )
    assert llm["base_url"] == "http://host:8000/v1"
    assert llm["model"] == "m1"


def test_anthropic_types_model_no_listing(monkeypatch) -> None:
    _always_ok(monkeypatch)
    called = {"fetch": False}
    monkeypatch.setattr(m, "_fetch_models", lambda b, k: called.__setitem__("fetch", True) or [])
    # provider=4 (Anthropic, lists_models=False), key, typed model
    llm = m.interactive_llm_setup(
        _console(), prompt_cls=_Prompt(["4", "sk-ant", "claude-sonnet-4-5"])
    )
    assert called["fetch"] is False       # anthropic never hits /models
    assert llm["model_provider"] == "anthropic"
    assert llm["model"] == "claude-sonnet-4-5"


def test_empty_model_list_falls_back_to_typed(monkeypatch) -> None:
    _always_ok(monkeypatch)
    monkeypatch.setattr(m, "_fetch_models", lambda b, k: [])   # detection failed
    llm = m.interactive_llm_setup(_console(), prompt_cls=_Prompt(["2", "sk-x", "deepseek-v4-flash"]))
    assert llm["model"] == "deepseek-v4-flash"


def test_huge_model_list_prompts_to_type(monkeypatch) -> None:
    _always_ok(monkeypatch)
    monkeypatch.setattr(m, "_fetch_models", lambda b, k: [f"model-{i}" for i in range(300)])
    # >cap → typed, not a 300-item menu
    llm = m.interactive_llm_setup(_console(), prompt_cls=_Prompt(["3", "sk-or", "anthropic/claude-x"]))
    assert llm["model"] == "anthropic/claude-x"


# ---------------------------------------------------------------------------
# abort + validation-retry
# ---------------------------------------------------------------------------


def test_abort_on_empty_required_key(monkeypatch) -> None:
    _always_ok(monkeypatch)
    monkeypatch.setattr(m, "_fetch_models", lambda b, k: ["gpt-4o"])
    # OpenAI (key required), blank key → abort
    assert m.interactive_llm_setup(_console(), prompt_cls=_Prompt(["1", ""])) is None


def test_abort_on_empty_custom_base_url(monkeypatch) -> None:
    _always_ok(monkeypatch)
    assert m.interactive_llm_setup(_console(), prompt_cls=_Prompt(["6", ""])) is None


def test_validation_failure_then_retry_succeeds(monkeypatch) -> None:
    monkeypatch.setattr(m, "_fetch_models", lambda b, k: ["m-bad", "m-good"])
    calls = {"n": 0}

    def _probe(overrides=None):
        calls["n"] += 1
        return (calls["n"] > 1, "connected" if calls["n"] > 1 else "401 bad model")

    monkeypatch.setattr(llm_mod.LLMFactory, "check_connectivity", staticmethod(_probe))
    # provider=2, key, model#1(bad) → probe fails → retry 'y' → model#2(good), keep key
    llm = m.interactive_llm_setup(
        _console(), prompt_cls=_Prompt(["2", "sk-x", "1", "y", "2", ""])
    )
    assert llm["model"] == "m-good"
    assert calls["n"] == 2


def test_validation_failure_saves_anyway_on_give_up(monkeypatch) -> None:
    monkeypatch.setattr(m, "_fetch_models", lambda b, k: ["m1"])
    monkeypatch.setattr(
        llm_mod.LLMFactory, "check_connectivity",
        staticmethod(lambda overrides=None: (False, "unreachable")),
    )
    # provider=2, key, model#1, fail → 'n' (give up) → still returns config
    llm = m.interactive_llm_setup(_console(), prompt_cls=_Prompt(["2", "sk-x", "1", "n"]))
    assert llm is not None and llm["model"] == "m1"


# ---------------------------------------------------------------------------
# §7.8 optional embedding step
# ---------------------------------------------------------------------------


def _emb_ok(monkeypatch):
    monkeypatch.setattr(
        llm_mod.LLMFactory, "check_embedding_connectivity",
        staticmethod(lambda overrides=None, strict=False: (True, "connected")),
    )


def test_embedding_local_server(monkeypatch) -> None:
    _emb_ok(monkeypatch)
    monkeypatch.setattr(m, "_fetch_models", lambda b, k: ["embeddinggemma"])
    # choice 1 (local server), base_url, blank key→local, model
    emb = m.interactive_embedding_setup(
        _console(), prompt_cls=_Prompt(["1", "http://localhost:11434/v1", "", "embeddinggemma"])
    )
    assert emb == {"mode": "api", "api": {
        "model": "embeddinggemma", "base_url": "http://localhost:11434/v1", "api_key": "local"}}


def test_embedding_cloud(monkeypatch) -> None:
    _emb_ok(monkeypatch)
    monkeypatch.setattr(m, "_fetch_models", lambda b, k: ["text-embedding-3-small"])
    emb = m.interactive_embedding_setup(
        _console(),
        prompt_cls=_Prompt(["2", "https://api.openai.com/v1", "sk-o", "text-embedding-3-small"]),
    )
    assert emb["mode"] == "api"
    assert emb["api"]["base_url"] == "https://api.openai.com/v1"
    assert emb["api"]["api_key"] == "sk-o"


def test_embedding_different_local_model_by_number(monkeypatch) -> None:
    _emb_ok(monkeypatch)
    # choice 3 (local model), pick #1 (the multilingual one)
    emb = m.interactive_embedding_setup(_console(), prompt_cls=_Prompt(["3", "1"]))
    assert emb == {"mode": "local", "local": {
        "model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"}}


def test_embedding_different_local_model_typed(monkeypatch) -> None:
    _emb_ok(monkeypatch)
    emb = m.interactive_embedding_setup(_console(), prompt_cls=_Prompt(["3", "BAAI/bge-m3"]))
    assert emb == {"mode": "local", "local": {"model": "BAAI/bge-m3"}}


def test_embedding_cloud_empty_base_url_keeps_default(monkeypatch) -> None:
    _emb_ok(monkeypatch)
    assert m.interactive_embedding_setup(_console(), prompt_cls=_Prompt(["2", ""])) is None


def test_embedding_validation_failure_keeps_default(monkeypatch) -> None:
    monkeypatch.setattr(
        llm_mod.LLMFactory, "check_embedding_connectivity",
        staticmethod(lambda overrides=None, strict=False: (False, "unreachable")),
    )
    monkeypatch.setattr(m, "_fetch_models", lambda b, k: ["x"])
    # local server, validation fails → None (keep default), nothing written
    emb = m.interactive_embedding_setup(
        _console(), prompt_cls=_Prompt(["1", "http://localhost:11434/v1", "", "x"])
    )
    assert emb is None
