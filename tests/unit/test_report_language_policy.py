"""Report language follows the global output-language policy (option B).

render_report's _detect_report_language now honors api.json
agent.output_language BEFORE profile detection: a concrete zh/en forces the
whole report (so a Chinese user running a shipped English profile gets a
Chinese report), "auto" falls back to the profile's own language.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import olav.core.config as config_mod

REPO = Path(__file__).resolve().parents[2]
RR = REPO / "src/olav/data/workspace/audit/audit-runner/scripts/render_report.py"


def _load():
    spec = importlib.util.spec_from_file_location("render_report_under_test", RR)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _reset_cfg(monkeypatch, cfg_dir, output_language):
    cfg_dir.mkdir(parents=True, exist_ok=True)
    body = {"agent": {"output_language": output_language}} if output_language else {}
    (cfg_dir / "api.json").write_text(json.dumps(body), encoding="utf-8")
    monkeypatch.setattr(config_mod, "_CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(config_mod.ConfigLoader, "_loaded", False)
    monkeypatch.setattr(config_mod.ConfigLoader, "_instance", None)
    monkeypatch.setattr(config_mod, "_config", None)


_EN_PROFILE = {"jobs": {"j1": {"section_prompt": "Identify down interfaces"}}}
_ZH_PROFILE = {"jobs": {"j1": {"section_prompt": "识别宕掉的接口"}}}


def test_global_zh_forces_chinese_on_english_profile(tmp_path, monkeypatch):
    """The reported case: Chinese user, shipped English profile → zh report."""
    _reset_cfg(monkeypatch, tmp_path / ".olav" / "config", "zh")
    assert _load()._detect_report_language(_EN_PROFILE) == "zh"


def test_global_en_forces_english_on_chinese_profile(tmp_path, monkeypatch):
    _reset_cfg(monkeypatch, tmp_path / ".olav" / "config", "English")
    assert _load()._detect_report_language(_ZH_PROFILE) == "en"


def test_auto_falls_back_to_profile_language(tmp_path, monkeypatch):
    _reset_cfg(monkeypatch, tmp_path / ".olav" / "config", "auto")
    m = _load()
    assert m._detect_report_language(_EN_PROFILE) == "en"
    assert m._detect_report_language(_ZH_PROFILE) == "zh"


def test_no_config_falls_back_to_profile(tmp_path, monkeypatch):
    _reset_cfg(monkeypatch, tmp_path / ".olav" / "config", None)
    assert _load()._detect_report_language(_ZH_PROFILE) == "zh"


def test_profile_explicit_language_still_works_under_auto(tmp_path, monkeypatch):
    _reset_cfg(monkeypatch, tmp_path / ".olav" / "config", "auto")
    assert _load()._detect_report_language(
        {"language": "zh", "jobs": {"j1": {"section_prompt": "English text"}}}
    ) == "zh"
