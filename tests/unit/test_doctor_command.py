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
from pathlib import Path

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
    assert check["detail"].startswith("connected")  # + config summary suffix
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

    _stub_methods = {
        "_check_workspace_integrity": "workspace",
        "_check_agents": "agents", "_check_subagents": "subagents",
        "_check_tools": "tools", "_check_memory": "memory", "_check_recall": "recall",
    }
    for _method, _name in _stub_methods.items():
        monkeypatch.setattr(
            DoctorCommand,
            _method,
            lambda self, _n=_name: {"name": _n, "ok": True, "detail": "stubbed", "fix": None},
        )


_ALL_CHECK_NAMES = {
    "scaffolding", "workspace", "llm", "embedding",
    "agents", "subagents", "tools", "memory", "recall",
}


def test_execute_reports_overall_healthy(tmp_path, monkeypatch) -> None:
    _mock_all_healthy(tmp_path, monkeypatch)
    result = asyncio.run(_make_cmd().execute())
    assert "healthy" in result and "checks passed" in result
    assert "fix:" not in result


def test_execute_json_output_is_valid(tmp_path, monkeypatch) -> None:
    _mock_all_healthy(tmp_path, monkeypatch)
    result = asyncio.run(_make_cmd().execute("--json"))
    payload = json.loads(result)
    assert payload["ok"] is True
    assert {c["name"] for c in payload["checks"]} == _ALL_CHECK_NAMES


class _StubLoader:
    """Minimal loader for constructing REAL config classes in tests —
    hand-rolled attr-bag fakes are how the base_url drift bug slipped
    through (see feedback memory: config-interface-drift-bugs)."""

    _shared: dict = {}

    def _env_override(self, section, key, default):
        return default


def test_llm_check_detail_names_model_and_endpoint(monkeypatch) -> None:
    """Doctor is the one-stop health view: 'connected' alone doesn't say
    WHAT is configured. Detail must name model + endpoint (+tier/timeout)."""
    from olav.core.config import LLMConfig

    real_cfg = LLMConfig(
        {"model": "gemma4-31b-it-qat", "base_url": "http://192.168.100.12:11433/v1",
         "api_key": "local", "timeout": 600},
        _StubLoader(),
    )
    monkeypatch.setattr(config_mod, "ConfigLoader", lambda: _FakeConfigLoader(api_key="k"))
    monkeypatch.setattr(config_mod, "get_llm_config", lambda: real_cfg)
    monkeypatch.setattr(
        llm_mod.LLMFactory, "check_connectivity", staticmethod(lambda: (True, "connected"))
    )
    detail = _make_cmd()._check_llm()["detail"]
    assert "gemma4-31b-it-qat" in detail
    assert "http://192.168.100.12:11433/v1" in detail
    assert "timeout=600s" in detail


def test_embedding_check_detail_names_mode_model_and_dim(monkeypatch) -> None:
    from olav.core.config import EmbeddingConfig

    real_cfg = EmbeddingConfig(
        {"mode": "api", "api": {"model": "embeddinggemma-300m",
                                "base_url": "http://192.168.100.12:11433/v1",
                                "api_key": "local"}},
        _StubLoader(),
    )
    monkeypatch.setattr(config_mod, "get_embedding_config", lambda: real_cfg)
    monkeypatch.setattr(
        llm_mod.LLMFactory, "check_embedding_connectivity",
        staticmethod(lambda: (True, "connected")),
    )
    import olav.core.embedder as emb_mod
    monkeypatch.setattr(emb_mod, "detect_embedding_dim", lambda: 768)
    detail = _make_cmd()._check_embedding()["detail"]
    assert "api/embeddinggemma-300m" in detail
    assert "http://192.168.100.12:11433/v1" in detail
    assert "768-dim" in detail


def test_embedding_check_local_mode_detail(monkeypatch) -> None:
    from olav.core.config import EmbeddingConfig

    real_cfg = EmbeddingConfig({"mode": "local"}, _StubLoader())
    monkeypatch.setattr(config_mod, "get_embedding_config", lambda: real_cfg)
    monkeypatch.setattr(
        llm_mod.LLMFactory, "check_embedding_connectivity",
        staticmethod(lambda: (True, "connected")),
    )
    import olav.core.embedder as emb_mod
    monkeypatch.setattr(emb_mod, "detect_embedding_dim", lambda: 512)
    detail = _make_cmd()._check_embedding()["detail"]
    assert "local/BAAI/bge-small-zh-v1.5" in detail and "512-dim" in detail


def test_execute_never_raises_on_unhealthy_system(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)  # no .olav/, no mocked config → everything fails
    result = asyncio.run(_make_cmd().execute())
    assert isinstance(result, str)
    assert "needs attention" in result


# ---------------------------------------------------------------------------
# Workspace-integrity check (ISSUE-PROJECT-ROOT-STRAY-DOTOLAV)
# ---------------------------------------------------------------------------


def _point_resolved_root(monkeypatch, root):
    class _Paths:
        project_root = str(root)
    monkeypatch.setattr(config_mod, "get_paths_config", lambda: _Paths())


def test_workspace_integrity_ok_when_no_competing_stray(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    (root / ".olav" / "config").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
    (tmp_path / "home").mkdir()
    _point_resolved_root(monkeypatch, root)
    monkeypatch.setenv("OLAV_HOME", str(root))
    check = _make_cmd()._check_workspace_integrity()
    assert check["ok"] is True and "OLAV_HOME pinned" in check["detail"]


def test_workspace_integrity_flags_competing_home_workspace(tmp_path, monkeypatch):
    """The burn: ~/.olav holds real workspace state distinct from the resolved
    deployment → warn with an OLAV_HOME fix."""
    home = tmp_path / "home"
    (home / ".olav" / "databases").mkdir(parents=True)
    (home / ".olav" / "databases" / "main.duckdb").write_text("x")
    (home / ".olav" / "config").mkdir()
    (home / ".olav" / "config" / "api.json").write_text("{}")
    root = tmp_path / "proj"
    (root / ".olav" / "config").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    _point_resolved_root(monkeypatch, root)
    check = _make_cmd()._check_workspace_integrity()
    assert check["ok"] is False
    assert "two workspaces" in check["detail"]
    assert "OLAV_HOME=" in check["fix"]


def test_workspace_integrity_ignores_by_design_cache_only_home(tmp_path, monkeypatch):
    """~/.olav holding ONLY cache/checkpoints (by-design user-isolated dirs)
    must NOT flag — else a correct install warns on every run."""
    home = tmp_path / "home"
    (home / ".olav" / "cache" / "olav").mkdir(parents=True)
    (home / ".olav" / "checkpoints").mkdir()
    root = tmp_path / "proj"
    (root / ".olav" / "config").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    _point_resolved_root(monkeypatch, root)
    monkeypatch.setenv("OLAV_HOME", str(root))
    check = _make_cmd()._check_workspace_integrity()
    assert check["ok"] is True


def test_workspace_integrity_hints_when_olav_home_unset(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    (root / ".olav").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
    (tmp_path / "home").mkdir()
    _point_resolved_root(monkeypatch, root)
    monkeypatch.delenv("OLAV_HOME", raising=False)
    check = _make_cmd()._check_workspace_integrity()
    assert check["ok"] is True and "set OLAV_HOME" in check["detail"]


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
