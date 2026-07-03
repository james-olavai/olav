"""admin/ops check_health.py — live LLM/embedding connectivity (dev_docs/99 §3.3).

``_check_env(llm_connectivity=...)`` now shares the exact same deterministic
probes as ``olav doctor`` (``LLMFactory.check_connectivity`` /
``check_embedding_connectivity``) instead of only checking whether a key is
present — so a user chatting with the admin `ops` sub-agent ("why isn't X
working?") gets the same answer as running `olav doctor` from a shell,
from one shared source of truth.

Covers:
1. llm_connectivity=False skips the live probes entirely
2. no API key present → probes skipped (nothing to test against)
3. key present + both healthy → both entries "ok", overall status "ok"
4. key present + LLM probe fails → "LLM connectivity" is "error", overall "error"
5. key present + embedding probe fails (LLM ok) → "Embedding connectivity"
   is "warning", overall "warning" (does not downgrade an existing "error")
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import olav.core.llm as llm_mod

REPO = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO / ".olav" / "workspace" / "admin" / "ops" / "scripts" / "check_health.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("check_health_under_test", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _no_env_key(monkeypatch) -> None:
    for var in ("LLM_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)


def test_llm_connectivity_false_skips_probes(monkeypatch) -> None:
    mod = _load_module()
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    called = {"llm": False, "embedding": False}
    monkeypatch.setattr(
        llm_mod.LLMFactory, "check_connectivity",
        staticmethod(lambda: called.__setitem__("llm", True) or (True, "connected")),
    )
    monkeypatch.setattr(
        llm_mod.LLMFactory, "check_embedding_connectivity",
        staticmethod(lambda: called.__setitem__("embedding", True) or (True, "connected")),
    )

    result = mod._check_env(llm_connectivity=False)

    assert called == {"llm": False, "embedding": False}
    names = {c["name"] for c in result["checks"]}
    assert "LLM connectivity" not in names
    assert "Embedding connectivity" not in names


def test_no_key_skips_probes(monkeypatch, tmp_path) -> None:
    mod = _load_module()
    _no_env_key(monkeypatch)
    monkeypatch.setattr(mod, "_OLAV_DIR", tmp_path / ".olav")  # no api.json here → no json_key

    called = {"llm": False}
    monkeypatch.setattr(
        llm_mod.LLMFactory, "check_connectivity",
        staticmethod(lambda: called.__setitem__("llm", True) or (True, "connected")),
    )

    result = mod._check_env(llm_connectivity=True)

    assert called["llm"] is False
    names = {c["name"] for c in result["checks"]}
    assert "LLM connectivity" not in names


def test_both_healthy_reports_ok(monkeypatch) -> None:
    mod = _load_module()
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(
        llm_mod.LLMFactory, "check_connectivity", staticmethod(lambda: (True, "connected"))
    )
    monkeypatch.setattr(
        llm_mod.LLMFactory, "check_embedding_connectivity", staticmethod(lambda: (True, "connected"))
    )

    result = mod._check_env(llm_connectivity=True)

    by_name = {c["name"]: c for c in result["checks"]}
    assert by_name["LLM connectivity"]["status"] == "ok"
    assert by_name["Embedding connectivity"]["status"] == "ok"
    assert result["status"] == "ok"


def test_llm_probe_failure_is_error(monkeypatch) -> None:
    mod = _load_module()
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(
        llm_mod.LLMFactory, "check_connectivity",
        staticmethod(lambda: (False, "401 Unauthorized")),
    )
    monkeypatch.setattr(
        llm_mod.LLMFactory, "check_embedding_connectivity", staticmethod(lambda: (True, "connected"))
    )

    result = mod._check_env(llm_connectivity=True)

    by_name = {c["name"]: c for c in result["checks"]}
    assert by_name["LLM connectivity"]["status"] == "error"
    assert by_name["LLM connectivity"]["message"] == "401 Unauthorized"
    assert result["status"] == "error"


def test_embedding_probe_failure_is_warning_not_downgraded_by_llm_error(monkeypatch) -> None:
    mod = _load_module()
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(
        llm_mod.LLMFactory, "check_connectivity", staticmethod(lambda: (False, "boom"))
    )
    monkeypatch.setattr(
        llm_mod.LLMFactory, "check_embedding_connectivity",
        staticmethod(lambda: (False, "sentence-transformers unavailable")),
    )

    result = mod._check_env(llm_connectivity=True)

    by_name = {c["name"]: c for c in result["checks"]}
    assert by_name["Embedding connectivity"]["status"] == "warning"
    # LLM failure already set status to "error" — embedding warning must not downgrade it
    assert result["status"] == "error"
