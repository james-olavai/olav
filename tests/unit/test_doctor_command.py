"""``olav doctor`` — zero-LLM preflight/health check.

dev_docs/99 §3.1. Covers:
1. missing .olav/ scaffolding is reported with a fix hint
2. missing LLM api_key / embedding api_key is reported with a fix hint
3. healthy LLM + embedding produces an "overall: healthy" report
4. --json emits machine-readable output
5. execute() never raises, always returns a string
6. real CLI entry point: `doctor` is a known command and dispatches through
   the actual argparse tree (CLAUDE.md Definition of Done — wiring must be
   verified from a real entry point, not just by constructing the class)
"""

from __future__ import annotations

import asyncio
import json
import sys

import olav.core.config as config_mod
import olav.core.llm as llm_mod


def _make_cmd():
    from olav.cli.commands.doctor import DoctorCommand
    return DoctorCommand()


# ---------------------------------------------------------------------------
# Scaffolding check — pure filesystem, no mocking needed beyond chdir
# ---------------------------------------------------------------------------


def test_scaffolding_missing_reports_fix(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    check = _make_cmd()._check_scaffolding()
    assert check["ok"] is False
    assert "olav init" in check["fix"]


def test_scaffolding_present_is_ok(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".olav" / "config").mkdir(parents=True)
    (tmp_path / ".olav" / "config" / "api.json").write_text("{}", encoding="utf-8")
    (tmp_path / ".olav" / "workspace").mkdir(parents=True)
    check = _make_cmd()._check_scaffolding()
    assert check["ok"] is True


# ---------------------------------------------------------------------------
# LLM check — mock ConfigLoader / LLMFactory directly (ConfigLoader is a
# process-wide singleton, so file-based isolation via chdir is unreliable)
# ---------------------------------------------------------------------------


class _FakeLLMSection:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key


class _FakeConfigLoader:
    def __init__(self, api_key: str = "") -> None:
        self.llm = _FakeLLMSection(api_key)


def test_llm_check_reports_missing_api_key(monkeypatch) -> None:
    monkeypatch.setattr(config_mod, "ConfigLoader", lambda: _FakeConfigLoader(api_key=""))
    check = _make_cmd()._check_llm()
    assert check["ok"] is False
    assert "API key" in check["detail"]
    assert "api.json" in check["fix"]


def test_llm_check_reports_connected(monkeypatch) -> None:
    monkeypatch.setattr(config_mod, "ConfigLoader", lambda: _FakeConfigLoader(api_key="sk-test"))
    monkeypatch.setattr(
        llm_mod.LLMFactory, "check_connectivity", staticmethod(lambda: (True, "connected"))
    )
    check = _make_cmd()._check_llm()
    assert check["ok"] is True
    assert check["detail"] == "connected"
    assert check["fix"] is None


def test_llm_check_reports_connectivity_failure_reason(monkeypatch) -> None:
    monkeypatch.setattr(config_mod, "ConfigLoader", lambda: _FakeConfigLoader(api_key="sk-test"))
    monkeypatch.setattr(
        llm_mod.LLMFactory,
        "check_connectivity",
        staticmethod(lambda: (False, "401 Unauthorized")),
    )
    check = _make_cmd()._check_llm()
    assert check["ok"] is False
    assert "401 Unauthorized" in check["detail"]


# ---------------------------------------------------------------------------
# Embedding check
# ---------------------------------------------------------------------------


class _FakeEmbeddingConfig:
    def __init__(self, mode: str = "local", api_key: str = "") -> None:
        self.mode = mode
        self.api_key = api_key


def test_embedding_check_reports_missing_api_key_in_api_mode(monkeypatch) -> None:
    monkeypatch.setattr(
        config_mod, "get_embedding_config", lambda: _FakeEmbeddingConfig(mode="api", api_key="")
    )
    check = _make_cmd()._check_embedding()
    assert check["ok"] is False
    assert "API key" in check["detail"]


def test_embedding_check_local_mode_skips_api_key_requirement(monkeypatch) -> None:
    monkeypatch.setattr(
        config_mod, "get_embedding_config", lambda: _FakeEmbeddingConfig(mode="local")
    )
    monkeypatch.setattr(
        llm_mod.LLMFactory,
        "check_embedding_connectivity",
        staticmethod(lambda: (True, "connected")),
    )
    check = _make_cmd()._check_embedding()
    assert check["ok"] is True


# ---------------------------------------------------------------------------
# execute() — full report + never raises + --json
# ---------------------------------------------------------------------------


def _mock_all_healthy(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".olav" / "config").mkdir(parents=True)
    (tmp_path / ".olav" / "config" / "api.json").write_text("{}", encoding="utf-8")
    (tmp_path / ".olav" / "workspace").mkdir(parents=True)
    monkeypatch.setattr(config_mod, "ConfigLoader", lambda: _FakeConfigLoader(api_key="sk-test"))
    monkeypatch.setattr(
        config_mod, "get_embedding_config", lambda: _FakeEmbeddingConfig(mode="local")
    )
    monkeypatch.setattr(
        llm_mod.LLMFactory, "check_connectivity", staticmethod(lambda: (True, "connected"))
    )
    monkeypatch.setattr(
        llm_mod.LLMFactory,
        "check_embedding_connectivity",
        staticmethod(lambda: (True, "connected")),
    )
    # v0.23 added workspace/memory checks that read the real deployed
    # workspace + LanceDB store (they resolve paths from the import-time
    # project root, not tmp_path). These execute() tests cover report
    # assembly, not the individual probes — stub them healthy. Each probe
    # has its own dedicated tests above / in its own module.
    from olav.cli.commands.doctor import DoctorCommand

    for _name in ("agents", "subagents", "tools", "memory", "recall"):
        monkeypatch.setattr(
            DoctorCommand,
            f"_check_{_name}",
            lambda self, _n=_name: {"name": _n, "ok": True, "detail": "stubbed", "fix": None},
        )


_ALL_CHECK_NAMES = {
    "scaffolding", "llm", "embedding",
    "agents", "subagents", "tools", "memory", "recall",
}


def test_execute_reports_overall_healthy(tmp_path, monkeypatch) -> None:
    _mock_all_healthy(tmp_path, monkeypatch)
    result = asyncio.run(_make_cmd().execute())
    assert "overall: healthy" in result
    assert "fix:" not in result


def test_execute_json_output_is_valid(tmp_path, monkeypatch) -> None:
    _mock_all_healthy(tmp_path, monkeypatch)
    result = asyncio.run(_make_cmd().execute("--json"))
    payload = json.loads(result)
    assert payload["ok"] is True
    assert {c["name"] for c in payload["checks"]} == _ALL_CHECK_NAMES


def test_execute_never_raises_on_unhealthy_system(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)  # no .olav/, no mocked config → everything fails
    result = asyncio.run(_make_cmd().execute())
    assert isinstance(result, str)
    assert "overall: needs attention" in result


# ---------------------------------------------------------------------------
# Real entry point — must be reachable via `olav doctor`, not just via
# constructing DoctorCommand directly.
# ---------------------------------------------------------------------------


def test_doctor_registered_in_known_commands() -> None:
    from olav.cli.main import _get_known_commands
    assert "doctor" in _get_known_commands()


def test_doctor_parses_through_real_argparse_tree() -> None:
    old_argv = sys.argv[:]
    sys.argv = ["olav", "doctor", "--json"]
    try:
        from olav.cli.main import parse_args

        args = parse_args()
        assert args.command == "doctor"
        assert args.json is True
    finally:
        sys.argv = old_argv
