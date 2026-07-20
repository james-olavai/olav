"""Unified output-language directive (agent.py).

Language handling moved from scattered per-audit-SKILL.md rules to a single
platform-global directive injected into every agent's system prompt
(orchestrator + sub-agents), driven by api.json agent.output_language.
"""
from __future__ import annotations

import json
from pathlib import Path

import olav.core.config as config_mod
from olav.agents.agent import _language_directive

REPO = Path(__file__).resolve().parents[2]


def _reset_cfg(monkeypatch, cfg_dir):
    monkeypatch.setattr(config_mod, "_CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(config_mod.ConfigLoader, "_loaded", False)
    monkeypatch.setattr(config_mod.ConfigLoader, "_instance", None)
    monkeypatch.setattr(config_mod, "_config", None)


def _write_api(cfg_dir, agent_block):
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "api.json").write_text(json.dumps({"agent": agent_block}), encoding="utf-8")


def test_default_auto_mirrors_input_language(tmp_path, monkeypatch):
    cfg = tmp_path / ".olav" / "config"
    _write_api(cfg, {})
    _reset_cfg(monkeypatch, cfg)
    d = _language_directive()
    assert "Output language" in d
    assert "same language" in d and "Chinese in → Chinese out" in d
    # structured content stays English
    assert "SQL" in d and "English" in d


def test_fixed_language_overrides_input(tmp_path, monkeypatch):
    cfg = tmp_path / ".olav" / "config"
    _write_api(cfg, {"output_language": "zh"})
    _reset_cfg(monkeypatch, cfg)
    d = _language_directive()
    assert "in zh" in d and "regardless of the user's input" in d


def test_missing_config_defaults_to_auto(tmp_path, monkeypatch):
    cfg = tmp_path / ".olav" / "config"
    cfg.mkdir(parents=True)
    (cfg / "api.json").write_text("{}", encoding="utf-8")
    _reset_cfg(monkeypatch, cfg)
    assert "same language" in _language_directive()  # auto


def test_output_language_config_property(tmp_path, monkeypatch):
    cfg = tmp_path / ".olav" / "config"
    _write_api(cfg, {"output_language": "English"})
    _reset_cfg(monkeypatch, cfg)
    assert config_mod.get_config().agent.output_language == "English"
    # env override wins
    monkeypatch.setenv("OLAV_AGENT_OUTPUT_LANGUAGE", "auto")
    assert config_mod.get_config().agent.output_language == "auto"


def test_directive_injected_at_both_prompt_points():
    """Wiring: orchestrator prompt AND sub-agent prompt both append it."""
    src = (REPO / "src/olav/agents/agent.py").read_text(encoding="utf-8")
    assert src.count("_language_directive()") >= 2, (
        "directive must be appended to both orchestrator and sub-agent prompts"
    )
    # orchestrator injection sits in _get_orchestrator_prompt
    idx_fn = src.index("def _get_orchestrator_prompt")
    assert "_language_directive()" in src[idx_fn:idx_fn + 4000]


def test_scattered_audit_conversational_rules_removed():
    """The old per-SKILL.md 'detect the user's language and respond in it'
    conversational rules are gone (now global); the audit-specific
    section_prompt-VALUE language note stays."""
    for base in ("src/olav/data/workspace/audit",):
        orch = (REPO / base / "SKILL.md").read_text(encoding="utf-8")
        author = (REPO / base / "audit-author" / "SKILL.md").read_text(encoding="utf-8")
        runner = (REPO / base / "audit-runner" / "SKILL.md").read_text(encoding="utf-8")
        # redundant conversational rule removed
        assert "respond in that same language throughout the conversation" not in orch
        assert "produce all conversational output in that same language" not in runner
        # domain-specific section_prompt-value language preserved
        assert "section_prompt" in author and "section_prompt language" in author
