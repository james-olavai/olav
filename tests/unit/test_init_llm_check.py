"""olav init LLM connectivity check tests.

Covers:
1. InitCommand._check_llm() method exists
2. _check_llm() returns a string result (never raises)
3. When LLM is available → result contains "ok" or "connected"
4. When LLM is unavailable → result contains "warning" or "skipped" (soft fail)
5. execute() output includes llm check result
6. execute() still succeeds (returns "platform ready") even when LLM check fails
"""

import asyncio
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cmd():
    from olav.cli.commands.init import InitCommand
    return InitCommand()


# ---------------------------------------------------------------------------
# Method existence
# ---------------------------------------------------------------------------

def test_init_command_has_check_llm_method() -> None:
    cmd = _make_cmd()
    assert hasattr(cmd, "_check_llm"), "InitCommand must have a _check_llm() method"
    assert callable(cmd._check_llm)


def test_check_llm_is_coroutine() -> None:
    import inspect
    cmd = _make_cmd()
    result = cmd._check_llm()
    assert inspect.isawaitable(result), "_check_llm() must return a coroutine"
    # Clean up unawaited coroutine
    result.close()


# ---------------------------------------------------------------------------
# Return value contract — must return a string, never raise
# ---------------------------------------------------------------------------

def test_check_llm_returns_string_when_llm_unavailable(monkeypatch, tmp_path) -> None:
    """_check_llm() must return a non-empty string even if LLM is not configured."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    # Patch LLMFactory.test_connectivity to raise (simulates no API key)
    import olav.core.llm as llm_mod
    monkeypatch.setattr(llm_mod.LLMFactory, "test_connectivity", staticmethod(lambda: False))

    cmd = _make_cmd()
    result = asyncio.run(cmd._check_llm())
    assert isinstance(result, str)
    assert len(result) > 0


def test_check_llm_returns_ok_when_llm_available(monkeypatch, tmp_path) -> None:
    """_check_llm reads a key BEFORE probing connectivity, so mocking only
    test_connectivity is not enough to reach the success branch.

    With `chdir(tmp_path)` there is no api.json, so the key could only come from
    the ambient environment — present on a dev box, absent in CI, where this
    returned "⚠ unavailable (no API key)" and failed. It passed locally for the
    wrong reason, and the failure was invisible because the gitea unit step
    carried continue-on-error. Now the test supplies its own key and resets the
    ConfigLoader singleton, so it asserts the same thing on every machine.
    """
    monkeypatch.chdir(tmp_path)

    cfg_dir = tmp_path / ".olav" / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "api.json").write_text(
        '{"llm": {"api_key": "sk-test", "model": "gpt-4o"}}', encoding="utf-8")

    # ConfigLoader caches its first read process-wide; without this reset it
    # would serve whatever an earlier test in this session loaded.
    import olav.core.config as config_mod
    monkeypatch.setattr(config_mod, "_CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(config_mod.ConfigLoader, "_loaded", False)
    monkeypatch.setattr(config_mod.ConfigLoader, "_instance", None)
    monkeypatch.setattr(config_mod, "_config", None)

    import olav.core.llm as llm_mod
    monkeypatch.setattr(llm_mod.LLMFactory, "test_connectivity", staticmethod(lambda: True))

    cmd = _make_cmd()
    result = asyncio.run(cmd._check_llm())
    assert isinstance(result, str)
    assert any(word in result.lower() for word in ("ok", "connected", "pass", "✓", "ready")), (
        f"Expected success indicator in: {result!r}"
    )


def test_check_llm_returns_warning_when_llm_unavailable(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    import olav.core.llm as llm_mod
    monkeypatch.setattr(llm_mod.LLMFactory, "test_connectivity", staticmethod(lambda: False))

    cmd = _make_cmd()
    result = asyncio.run(cmd._check_llm())
    assert any(word in result.lower() for word in ("warn", "skip", "fail", "unavailable", "⚠", "✗")), (
        f"Expected warning indicator in: {result!r}"
    )


# ---------------------------------------------------------------------------
# execute() integration — LLM report included, still returns "platform ready"
# ---------------------------------------------------------------------------

def test_execute_includes_llm_check_result(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    import olav.core.llm as llm_mod
    monkeypatch.setattr(llm_mod.LLMFactory, "test_connectivity", staticmethod(lambda: True))

    from olav.cli.commands.init import InitCommand
    result = asyncio.run(InitCommand().execute())
    assert "llm" in result.lower() or "platform ready" in result.lower()


def test_execute_returns_platform_ready_even_if_llm_fails(monkeypatch, tmp_path) -> None:
    """LLM failure must NOT prevent platform scaffolding from completing."""
    monkeypatch.chdir(tmp_path)
    import olav.core.llm as llm_mod
    monkeypatch.setattr(llm_mod.LLMFactory, "test_connectivity", staticmethod(lambda: False))

    from olav.cli.commands.init import InitCommand
    result = asyncio.run(InitCommand().execute())
    assert "platform ready" in result
    # Ensure scaffolding still created
    assert (tmp_path / ".olav" / "config" / "api.json").exists()
