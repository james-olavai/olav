"""``_ensure_bootstrapped()`` — lazy first-run bootstrap (dev_docs/99 §3.2).

Collapses ``olav init`` into the default agent-launch path: on a bare
``olav`` or a natural-language query, missing ``.olav/`` scaffolding is
created silently (idempotent, matches ``olav init``), and the LLM API key
— the one genuinely irreducible input — is prompted for inline instead of
surfacing as a cryptic langchain error deep inside the agent call.

Covers:
1. missing .olav/ triggers InitCommand().execute() automatically
2. existing api_key short-circuits (no init re-run, no prompt)
3. OPENAI_API_KEY / OLAV_LLM_API_KEY env var short-circuits the prompt
4. missing key + non-TTY → returns False, no hang, no crash
5. missing key + TTY + user enters a key → key is persisted, returns True
6. missing key + TTY + empty input → returns False
7. real entry point: `olav` (bare argv) actually calls _ensure_bootstrapped()
   before launching the interactive agent (CLAUDE.md Definition of Done)
"""

from __future__ import annotations

import asyncio
import json
import sys

import olav.cli.main as main_mod


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# First run — missing scaffolding
# ---------------------------------------------------------------------------


def test_missing_scaffolding_triggers_init(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OLAV_LLM_API_KEY", raising=False)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

    called = {}

    class _StubInit:
        async def execute(self):
            called["ran"] = True
            (tmp_path / ".olav" / "config").mkdir(parents=True)
            (tmp_path / ".olav" / "config" / "api.json").write_text(
                json.dumps({"llm": {"api_key": ""}}), encoding="utf-8"
            )
            return "platform ready"

    import olav.cli.commands.init as init_mod
    monkeypatch.setattr(init_mod, "InitCommand", _StubInit)

    result = _run(main_mod._ensure_bootstrapped())
    assert called.get("ran") is True
    # No API key and no TTY → still returns False (correctly refuses to launch)
    assert result is False


def test_existing_scaffolding_skips_init(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".olav" / "config").mkdir(parents=True)
    (tmp_path / ".olav" / "config" / "api.json").write_text(
        json.dumps({"llm": {"api_key": "sk-existing"}}), encoding="utf-8"
    )

    import olav.cli.commands.init as init_mod

    def _boom():
        raise AssertionError("InitCommand must not be instantiated when api.json already exists")

    monkeypatch.setattr(init_mod, "InitCommand", _boom)

    result = _run(main_mod._ensure_bootstrapped())
    assert result is True


# ---------------------------------------------------------------------------
# API key resolution
# ---------------------------------------------------------------------------


def test_existing_api_key_short_circuits(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".olav" / "config").mkdir(parents=True)
    (tmp_path / ".olav" / "config" / "api.json").write_text(
        json.dumps({"llm": {"api_key": "sk-test"}}), encoding="utf-8"
    )
    result = _run(main_mod._ensure_bootstrapped())
    assert result is True


def test_env_var_short_circuits_prompt(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".olav" / "config").mkdir(parents=True)
    (tmp_path / ".olav" / "config" / "api.json").write_text(
        json.dumps({"llm": {"api_key": ""}}), encoding="utf-8"
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    result = _run(main_mod._ensure_bootstrapped())
    assert result is True


def test_missing_key_non_tty_returns_false_without_hanging(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OLAV_LLM_API_KEY", raising=False)
    (tmp_path / ".olav" / "config").mkdir(parents=True)
    (tmp_path / ".olav" / "config" / "api.json").write_text(
        json.dumps({"llm": {"api_key": ""}}), encoding="utf-8"
    )
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    result = _run(main_mod._ensure_bootstrapped())
    assert result is False


def test_missing_key_tty_prompts_and_persists(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OLAV_LLM_API_KEY", raising=False)
    (tmp_path / ".olav" / "config").mkdir(parents=True)
    (tmp_path / ".olav" / "config" / "api.json").write_text(
        json.dumps({"llm": {"api_key": ""}}), encoding="utf-8"
    )
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    from rich.prompt import Prompt
    monkeypatch.setattr(Prompt, "ask", classmethod(lambda cls, *a, **kw: "sk-typed-in"))

    result = _run(main_mod._ensure_bootstrapped())
    assert result is True

    saved = json.loads((tmp_path / ".olav" / "config" / "api.json").read_text())
    assert saved["llm"]["api_key"] == "sk-typed-in"


def test_missing_key_tty_empty_input_returns_false(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OLAV_LLM_API_KEY", raising=False)
    (tmp_path / ".olav" / "config").mkdir(parents=True)
    (tmp_path / ".olav" / "config" / "api.json").write_text(
        json.dumps({"llm": {"api_key": ""}}), encoding="utf-8"
    )
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    from rich.prompt import Prompt
    monkeypatch.setattr(Prompt, "ask", classmethod(lambda cls, *a, **kw: ""))

    result = _run(main_mod._ensure_bootstrapped())
    assert result is False


# ---------------------------------------------------------------------------
# Real entry point — `olav` (bare) must call _ensure_bootstrapped() before
# launching the interactive agent (CLAUDE.md Definition of Done: wiring
# must be verified from a real entry point, not just calling the helper
# directly).
# ---------------------------------------------------------------------------


def test_bare_invocation_calls_bootstrap_before_interactive(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    old_argv = sys.argv[:]
    sys.argv = ["olav"]
    try:
        called = {"bootstrap": False, "interactive": False}

        async def _fake_bootstrap():
            called["bootstrap"] = True
            return True

        async def _fake_run_interactive(**kwargs):
            called["interactive"] = True

        monkeypatch.setattr(main_mod, "_ensure_bootstrapped", _fake_bootstrap)
        monkeypatch.setattr(main_mod, "run_interactive", _fake_run_interactive)

        _run(main_mod.cli_main_impl())

        assert called["bootstrap"] is True, "cli_main_impl must call _ensure_bootstrapped()"
        assert called["interactive"] is True
    finally:
        sys.argv = old_argv


def test_bootstrap_abort_prevents_agent_launch(tmp_path, monkeypatch) -> None:
    """When _ensure_bootstrapped() returns False (no key, no TTY), the
    agent must NOT be launched — the whole point is to fail before the
    cryptic langchain error, not instead of it."""
    monkeypatch.chdir(tmp_path)
    old_argv = sys.argv[:]
    sys.argv = ["olav"]
    try:
        called = {"interactive": False}

        async def _fake_bootstrap():
            return False

        async def _fake_run_interactive(**kwargs):
            called["interactive"] = True

        monkeypatch.setattr(main_mod, "_ensure_bootstrapped", _fake_bootstrap)
        monkeypatch.setattr(main_mod, "run_interactive", _fake_run_interactive)

        with __import__("pytest").raises(SystemExit) as exc_info:
            _run(main_mod.cli_main_impl())

        assert exc_info.value.code == 1
        assert called["interactive"] is False
    finally:
        sys.argv = old_argv


def test_known_subcommand_does_not_trigger_bootstrap(tmp_path, monkeypatch) -> None:
    """`olav init` / `olav doctor` etc. have their own explicit dispatch and
    `return` before the fallback block — bootstrap must not double-fire.

    Stubs DoctorCommand itself (rather than letting it run for real) so this
    test only exercises the dispatch routing in cli_main_impl, not doctor's
    own LLM-import chain — that behavior is covered by test_doctor_command.py.
    """
    monkeypatch.chdir(tmp_path)
    old_argv = sys.argv[:]
    sys.argv = ["olav", "doctor"]
    try:
        called = {"bootstrap": False}

        async def _fake_bootstrap():
            called["bootstrap"] = True
            return True

        class _StubDoctor:
            async def execute(self, args=""):
                return "stubbed"

        import olav.cli.commands.doctor as doctor_mod

        monkeypatch.setattr(main_mod, "_ensure_bootstrapped", _fake_bootstrap)
        monkeypatch.setattr(doctor_mod, "DoctorCommand", _StubDoctor)

        _run(main_mod.cli_main_impl())

        assert called["bootstrap"] is False
    finally:
        sys.argv = old_argv


# ---------------------------------------------------------------------------
# _check_first_run_health() — dev_docs/99 §3.3: a real, non-blocking finding
# (e.g. embedding backend down) surfaces on the TUI's first screen instead
# of a generic random tip. Only runs once, on a fresh bootstrap.
# ---------------------------------------------------------------------------


def test_check_first_run_health_sets_finding_on_embedding_failure(monkeypatch) -> None:
    import olav.core.llm as llm_mod
    import olav.cli.tui_overlay as overlay

    monkeypatch.setattr(
        llm_mod.LLMFactory,
        "check_embedding_connectivity",
        staticmethod(lambda: (False, "sentence-transformers unavailable")),
    )
    overlay.consume_first_run_finding()  # clear any leftover state

    main_mod._check_first_run_health()

    finding = overlay.consume_first_run_finding()
    assert finding is not None
    assert "sentence-transformers unavailable" in finding
    assert "olav doctor" in finding


def test_check_first_run_health_no_finding_when_healthy(monkeypatch) -> None:
    import olav.core.llm as llm_mod
    import olav.cli.tui_overlay as overlay

    monkeypatch.setattr(
        llm_mod.LLMFactory,
        "check_embedding_connectivity",
        staticmethod(lambda: (True, "connected")),
    )
    overlay.consume_first_run_finding()

    main_mod._check_first_run_health()

    assert overlay.consume_first_run_finding() is None


def test_check_first_run_health_never_raises(monkeypatch) -> None:
    import olav.core.llm as llm_mod

    def _boom():
        raise RuntimeError("embedder exploded")

    monkeypatch.setattr(llm_mod.LLMFactory, "check_embedding_connectivity", staticmethod(_boom))

    main_mod._check_first_run_health()  # must not raise


def test_fresh_bootstrap_runs_first_run_health_check(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")  # short-circuits the key prompt

    class _StubInit:
        async def execute(self):
            (tmp_path / ".olav" / "config").mkdir(parents=True)
            (tmp_path / ".olav" / "config" / "api.json").write_text(
                json.dumps({"llm": {"api_key": ""}}), encoding="utf-8"
            )
            return "platform ready"

    import olav.cli.commands.init as init_mod
    monkeypatch.setattr(init_mod, "InitCommand", _StubInit)

    called = {"health": False}
    monkeypatch.setattr(
        main_mod, "_check_first_run_health", lambda: called.__setitem__("health", True)
    )

    result = _run(main_mod._ensure_bootstrapped())

    assert result is True
    assert called["health"] is True


def test_existing_scaffolding_skips_first_run_health_check(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".olav" / "config").mkdir(parents=True)
    (tmp_path / ".olav" / "config" / "api.json").write_text(
        json.dumps({"llm": {"api_key": "sk-existing"}}), encoding="utf-8"
    )

    called = {"health": False}
    monkeypatch.setattr(
        main_mod, "_check_first_run_health", lambda: called.__setitem__("health", True)
    )

    result = _run(main_mod._ensure_bootstrapped())

    assert result is True
    assert called["health"] is False
