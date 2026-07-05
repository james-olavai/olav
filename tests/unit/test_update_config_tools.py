"""admin/editor/tools/update_config.py — self-configuration via conversation,
gated by validate-before-commit (dev_docs/99 §3.4/§3.5).

Covers:
1. update_llm_config with no fields is a hard error, no probe attempted
2. update_llm_config rejects a candidate that fails the live probe — no
   snapshot, no write, no cache bust
3. update_llm_config commits on a successful probe — snapshots first,
   field-level merges into api.json (other keys untouched), busts the
   ConfigLoader cache so the change is live immediately
4. update_embedding_config rejects on failure the same way
5. update_embedding_config commits and writes the nested embedding.api.*
   shape correctly
6. rollback_config delegates to config_snapshot.restore_last_known_good
   and only busts the cache when something was actually restored
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

import olav.core.config_snapshot as snap
import olav.core.llm as llm_mod
from olav.core.config import ConfigLoader

REPO = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO / ".olav" / "workspace" / "admin" / "editor" / "tools" / "update_config.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("update_config_under_test", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def api_json(tmp_path, monkeypatch):
    path = tmp_path / "api.json"
    path.write_text(
        json.dumps({"llm": {"model": "gpt-4o", "provider": "openai"}, "other": "untouched"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(snap, "API_JSON_PATH", path)
    monkeypatch.setattr(snap, "SNAPSHOT_PATH", tmp_path / "api.json.lastgood")
    return path


# ---------------------------------------------------------------------------
# update_llm_config
# ---------------------------------------------------------------------------


def test_update_llm_config_no_fields_is_error(monkeypatch) -> None:
    mod = _load_module()
    called = {"probed": False}
    monkeypatch.setattr(
        llm_mod.LLMFactory, "check_connectivity",
        staticmethod(lambda **kw: called.__setitem__("probed", True) or (True, "connected")),
    )

    result = mod.update_llm_config.invoke({})

    assert "provide at least one" in result.lower()
    assert called["probed"] is False


def test_update_llm_config_rejects_on_failed_probe(api_json, monkeypatch) -> None:
    mod = _load_module()
    monkeypatch.setattr(
        llm_mod.LLMFactory, "check_connectivity",
        staticmethod(lambda overrides=None: (False, "401 Unauthorized")),
    )
    original = api_json.read_text()

    result = mod.update_llm_config.invoke({"api_key": "sk-bad"})

    assert "Rejected" in result
    assert "401 Unauthorized" in result
    assert api_json.read_text() == original, "rejected candidate must not touch api.json"
    assert not snap.SNAPSHOT_PATH.exists(), "rejected candidate must not snapshot"


def test_update_llm_config_commits_on_success(api_json, monkeypatch) -> None:
    mod = _load_module()
    monkeypatch.setattr(
        llm_mod.LLMFactory, "check_connectivity",
        staticmethod(lambda overrides=None: (True, "connected")),
    )
    ConfigLoader._loaded = True  # simulate an already-warm cache

    result = mod.update_llm_config.invoke({"model": "deepseek-chat", "api_key": "sk-new"})

    assert "updated" in result.lower()
    assert "rollback_config" in result
    saved = json.loads(api_json.read_text())
    assert saved["llm"]["model"] == "deepseek-chat"
    assert saved["llm"]["api_key"] == "sk-new"
    assert saved["llm"]["provider"] == "openai"  # untouched field preserved
    assert saved["other"] == "untouched"  # unrelated top-level key preserved
    assert snap.SNAPSHOT_PATH.exists()
    assert ConfigLoader._loaded is False, "cache must be busted so the change is live immediately"


# ---------------------------------------------------------------------------
# update_embedding_config
# ---------------------------------------------------------------------------


def test_update_embedding_config_rejects_on_failed_probe(api_json, monkeypatch) -> None:
    mod = _load_module()
    monkeypatch.setattr(
        llm_mod.LLMFactory, "check_embedding_connectivity",
        staticmethod(lambda overrides=None, strict=False: (False, "invalid key")),
    )
    original = api_json.read_text()

    result = mod.update_embedding_config.invoke({"mode": "api", "api_key": "sk-bad"})

    assert "Rejected" in result
    assert api_json.read_text() == original


def test_update_embedding_config_commits_nested_shape(api_json, monkeypatch) -> None:
    mod = _load_module()
    monkeypatch.setattr(
        llm_mod.LLMFactory, "check_embedding_connectivity",
        staticmethod(lambda overrides=None, strict=False: (True, "connected")),
    )

    result = mod.update_embedding_config.invoke(
        {"mode": "api", "api_key": "sk-embed", "model": "text-embedding-3-small"}
    )

    assert "updated" in result.lower()
    saved = json.loads(api_json.read_text())
    assert saved["embedding"]["mode"] == "api"
    assert saved["embedding"]["api"]["api_key"] == "sk-embed"
    assert saved["embedding"]["api"]["model"] == "text-embedding-3-small"
    assert saved["other"] == "untouched"


def test_update_embedding_config_local_ollama_with_base_url(api_json, monkeypatch) -> None:
    """dev_docs/100 demo Ch8b: point embedding at a local Ollama server.
    base_url must reach the candidate probe and land in embedding.api."""
    mod = _load_module()
    seen = {}
    monkeypatch.setattr(
        llm_mod.LLMFactory, "check_embedding_connectivity",
        staticmethod(
            lambda overrides=None, strict=False: (seen.update(overrides or {}) or (True, "connected"))
        ),
    )

    result = mod.update_embedding_config.invoke(
        {"mode": "api", "model": "embeddinggemma",
         "base_url": "http://localhost:11434/v1", "api_key": "ollama"}
    )

    assert "updated" in result.lower()
    # base_url reached the validate-before-commit probe
    assert seen.get("base_url") == "http://localhost:11434/v1"
    # and was persisted into the nested api section
    saved = json.loads(api_json.read_text())
    assert saved["embedding"]["api"]["base_url"] == "http://localhost:11434/v1"
    assert saved["embedding"]["api"]["model"] == "embeddinggemma"


# ---------------------------------------------------------------------------
# rollback_config
# ---------------------------------------------------------------------------


def test_rollback_config_restores_and_busts_cache(monkeypatch) -> None:
    mod = _load_module()
    monkeypatch.setattr(
        snap, "restore_last_known_good",
        lambda: {"restored": True, "message": "Restored api.json from the snapshot taken earlier."},
    )
    ConfigLoader._loaded = True

    result = mod.rollback_config.invoke({})

    assert "Restored" in result
    assert ConfigLoader._loaded is False


def test_rollback_config_no_snapshot_does_not_bust_cache(monkeypatch) -> None:
    mod = _load_module()
    monkeypatch.setattr(
        snap, "restore_last_known_good",
        lambda: {"restored": False, "message": "No last-known-good snapshot found."},
    )
    ConfigLoader._loaded = True

    result = mod.rollback_config.invoke({})

    assert "No last-known-good" in result
    assert ConfigLoader._loaded is True
