"""An agent error with code 400 is usually the context wall — make it visible.

Reproduced against the real endpoint:

    HTTP 400 {"error":{"code":400,
      "message":"request (120013 tokens) exceeds the available context size
                 (65536 tokens), try increasing it",
      "type":"exceed_context_size_error","n_prompt_tokens":120013,"n_ctx":65536}}

The user sees a bare "agent error, code 400". What decides whether a run hits it
is OLAV's context budget: deepagents falls back to a 170000-token summarisation
trigger when the model profile carries no ``max_input_tokens``, so on a local
llama.cpp endpoint nothing compacts before the wall — agent.py primes the profile
from ``llm.context_budget`` or the tier default. A budget larger than the served
window is therefore a latent 400 on every long run, and it can be checked without
running inference: llama-swap's /v1/models carries each model's preset, which
includes ``ctx-size``.
"""

from __future__ import annotations

import pytest

from olav.cli.commands.doctor import DoctorCommand


def _cfg(budget, tier="medium", model="m", base_url="http://x/v1"):
    return type(
        "C", (),
        {"context_budget": budget, "model_tier": tier,
         "model": model, "base_url": base_url},
    )()


@pytest.fixture
def doctor(monkeypatch):
    d = DoctorCommand()
    monkeypatch.setattr(
        "olav.core.config.TIER_DEFAULTS",
        {"medium": {"context_budget": 32000}, "large": {"context_budget": 200000}},
    )
    return d


class TestContextBudgetCheck:
    def test_budget_over_the_served_window_is_flagged(self, doctor, monkeypatch):
        """The latent 400: nothing fails until a run gets long."""
        monkeypatch.setattr("olav.core.config.get_llm_config", lambda: _cfg(200000))
        monkeypatch.setattr(DoctorCommand, "_server_ctx_size", staticmethod(lambda *a: 65536))
        r = doctor._check_context_budget()
        assert r["ok"] is False
        assert "exceed_context_size_error" in r["detail"], (
            "name the error the user will actually see"
        )
        assert "65536" in r["fix"]

    def test_budget_within_the_window_passes(self, doctor, monkeypatch):
        monkeypatch.setattr("olav.core.config.get_llm_config", lambda: _cfg(None))
        monkeypatch.setattr(DoctorCommand, "_server_ctx_size", staticmethod(lambda *a: 65536))
        r = doctor._check_context_budget()
        assert r["ok"] is True
        assert "32000" in r["detail"] and "65536" in r["detail"]
        assert "tier=medium default" in r["detail"], "say where the budget came from"

    def test_explicit_budget_is_named_as_the_source(self, doctor, monkeypatch):
        monkeypatch.setattr("olav.core.config.get_llm_config", lambda: _cfg(48000))
        monkeypatch.setattr(DoctorCommand, "_server_ctx_size", staticmethod(lambda *a: 65536))
        r = doctor._check_context_budget()
        assert "llm.context_budget" in r["detail"]

    def test_unknown_server_window_does_not_fail_the_check(self, doctor, monkeypatch):
        """A plain OpenAI endpoint advertises no ctx-size; report, don't guess."""
        monkeypatch.setattr("olav.core.config.get_llm_config", lambda: _cfg(None))
        monkeypatch.setattr(DoctorCommand, "_server_ctx_size", staticmethod(lambda *a: None))
        r = doctor._check_context_budget()
        assert r["ok"] is True
        assert "not advertised" in r["detail"]

    def test_no_budget_at_all_is_an_error(self, doctor, monkeypatch):
        monkeypatch.setattr("olav.core.config.get_llm_config", lambda: _cfg(None, tier="unknown"))
        monkeypatch.setattr(DoctorCommand, "_server_ctx_size", staticmethod(lambda *a: 65536))
        r = doctor._check_context_budget()
        assert r["ok"] is False and "no context budget" in r["detail"]


class TestServerCtxDiscovery:
    def test_parses_ctx_size_out_of_the_llama_swap_preset(self, monkeypatch):
        import json
        from unittest.mock import MagicMock

        payload = {
            "data": [
                {"id": "other", "status": {"preset": "ctx-size = 999"}},
                {"id": "target", "status": {
                    "preset": "[target]\nmodel = /m.gguf\nctx-size = 65536\n"}},
            ]
        }
        cm = MagicMock()
        cm.__enter__.return_value.read.return_value = json.dumps(payload).encode()
        monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: cm)
        assert DoctorCommand._server_ctx_size("http://x/v1", "target") == 65536

    def test_unreachable_endpoint_returns_none_rather_than_raising(self, monkeypatch):
        def _boom(*a, **k):
            raise OSError("refused")

        monkeypatch.setattr("urllib.request.urlopen", _boom)
        assert DoctorCommand._server_ctx_size("http://x/v1", "m") is None


def test_context_check_is_wired_into_doctor():
    from pathlib import Path

    import olav.cli.commands.doctor as _d

    text = Path(_d.__file__).read_text(encoding="utf-8")
    body = text[text.index("checks = ["):text.index("_check_services")]
    assert "self._check_context_budget()" in body
