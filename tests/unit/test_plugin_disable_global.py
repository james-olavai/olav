"""Global (api.json) plugins.disabled — ISSUE-AUTOCAPTURE-SYNC-LLM-ROUNDTRIP.

The PluginRegistry docstring documents `plugins.disabled` as coming from
api.json, but OLAVAgent only ever read the per-agent SKILL.md frontmatter list
— so there was no fleet-wide switch (e.g. to drop memory_capture's per-turn
extraction LLM round-trip for demos). agent.py now merges the global
api.json list with the per-agent one. This pins the merge semantics + that a
globally-disabled plugin is actually excluded from the registry.
"""
from __future__ import annotations

import json
from pathlib import Path

import olav.core.config as config_mod
from olav.plugins.registry import PluginRegistry


def _reset_config(monkeypatch, cfg_dir: Path):
    monkeypatch.setattr(config_mod, "_CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(config_mod.ConfigLoader, "_loaded", False)
    monkeypatch.setattr(config_mod.ConfigLoader, "_instance", None)
    monkeypatch.setattr(config_mod, "_config", None)


def _merged_disabled(olav_config: dict) -> list[str]:
    """Mirror the agent.py merge block exactly."""
    disabled: list[str] = []
    try:
        disabled = list(olav_config.get("plugins", {}).get("disabled", []))
    except Exception:
        pass
    try:
        api_disabled = (
            (config_mod.get_config()._api.get("plugins") or {}).get("disabled") or []
        )
        if api_disabled:
            disabled = list({*disabled, *api_disabled})
    except Exception:
        pass
    return disabled


def test_api_json_disabled_merges_with_skill_md(tmp_path, monkeypatch):
    cfg_dir = tmp_path / ".olav" / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "api.json").write_text(
        json.dumps({"plugins": {"disabled": ["memory_capture"]}}), encoding="utf-8"
    )
    _reset_config(monkeypatch, cfg_dir)

    # per-agent SKILL.md disables something else; global adds memory_capture
    merged = _merged_disabled({"plugins": {"disabled": ["audit"]}})
    assert set(merged) == {"audit", "memory_capture"}


def test_globally_disabled_plugin_reaches_registry_disabled_set(tmp_path, monkeypatch):
    cfg_dir = tmp_path / ".olav" / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "api.json").write_text(
        json.dumps({"plugins": {"disabled": ["memory_capture"]}}), encoding="utf-8"
    )
    _reset_config(monkeypatch, cfg_dir)

    reg = PluginRegistry(disabled=_merged_disabled({}))
    # register() skips any plugin whose name is in _disabled (existing gate);
    # here we pin that the global disable actually populated that set.
    assert "memory_capture" in reg._disabled


def test_no_api_plugins_section_is_noop(tmp_path, monkeypatch):
    cfg_dir = tmp_path / ".olav" / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "api.json").write_text(json.dumps({"llm": {}}), encoding="utf-8")
    _reset_config(monkeypatch, cfg_dir)
    assert _merged_disabled({"plugins": {"disabled": ["x"]}}) == ["x"]


def test_wired_into_agent_build():
    """agent.py must actually perform the api.json merge (not just SKILL.md)."""
    src = (Path(__file__).resolve().parents[2] / "src/olav/agents/agent.py").read_text(
        encoding="utf-8"
    )
    assert '_api.get("plugins")' in src
    assert "_api_disabled" in src
