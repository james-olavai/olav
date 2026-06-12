"""
tests/unit/test_tui_overlay.py
──────────────────────────────
Unit coverage for src/olav/cli/tui_overlay.py — the OLAV overlay on top
of deepagents-code's Textual TUI.

Guarantees:
  1. Module is importable without pulling the TUI libs eagerly.
  2. `apply_olav_overlay()` returns False (safe fallback) when the
     deepagents-code version does not match `_SUPPORTED_VERSIONS`.
  3. On a supported version, banner constants are swapped, the
     Textual TITLE/SUB_TITLE are set, and `/workspace` lands in the
     command registry + autocomplete list.
  4. `consume_pending_workspace()` returns and clears the module flag.
  5. The module is idempotent — calling apply twice does not duplicate
     the `/workspace` entry.
"""

from __future__ import annotations

import sys
import types

import pytest


def _install_stub_deepagents_code(
    monkeypatch: pytest.MonkeyPatch, *, version: str
) -> tuple[types.ModuleType, types.ModuleType, type, types.ModuleType]:
    """Install stand-in modules for ``deepagents_code`` and submodules.

    Returns ``(config_mod, command_registry_mod, DeepAgentsApp,
    update_check_mod)`` so tests can assert against them.
    """
    # Root package — version attr is what the overlay's version guard reads.
    pkg = types.ModuleType("deepagents_code")
    pkg.__version__ = version  # type: ignore[attr-defined]
    pkg.__path__ = []  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "deepagents_code", pkg)

    # config module with the private banner constants.
    config_mod = types.ModuleType("deepagents_code.config")
    config_mod._UNICODE_BANNER = "ORIGINAL_UNICODE"  # type: ignore[attr-defined]
    config_mod._ASCII_BANNER = "ORIGINAL_ASCII"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "deepagents_code.config", config_mod)

    # command_registry with SlashCommand, BypassTier, COMMANDS, SLASH_COMMANDS.
    cr = types.ModuleType("deepagents_code.command_registry")

    class _BypassTier:
        IMMEDIATE_UI = "immediate_ui"
        QUEUED = "queued"

    class _CommandEntry:
        def __init__(
            self,
            *,
            name: str,
            description: str,
            hidden_keywords: str = "",
            argument_hint: str = "",
        ) -> None:
            self.name = name
            self.description = description
            self.hidden_keywords = hidden_keywords
            self.argument_hint = argument_hint

    class _SlashCommand:
        def __init__(
            self,
            *,
            name: str,
            description: str,
            bypass_tier: str,
            hidden_keywords: str = "",
            argument_hint: str = "",
            aliases: tuple[str, ...] = (),
        ) -> None:
            self.name = name
            self.description = description
            self.bypass_tier = bypass_tier
            self.hidden_keywords = hidden_keywords
            self.argument_hint = argument_hint
            self.aliases = aliases

        def to_entry(self) -> _CommandEntry:
            return _CommandEntry(
                name=self.name,
                description=self.description,
                hidden_keywords=self.hidden_keywords,
                argument_hint=self.argument_hint,
            )

    cr.SlashCommand = _SlashCommand  # type: ignore[attr-defined]
    cr.BypassTier = _BypassTier  # type: ignore[attr-defined]
    cr.CommandEntry = _CommandEntry  # type: ignore[attr-defined]
    # COMMANDS is a tuple on the real module; mimic with upgrade-related
    # entries so tests can check the overlay filters them out.
    cr.COMMANDS = (
        _SlashCommand(
            name="/help", description="Show help", bypass_tier="immediate_ui"
        ),
        _SlashCommand(
            name="/update", description="Upgrade the CLI", bypass_tier="queued"
        ),
        _SlashCommand(
            name="/auto-update",
            description="Toggle auto-update",
            bypass_tier="queued",
        ),
    )
    cr.SLASH_COMMANDS = [cmd.to_entry() for cmd in cr.COMMANDS]
    monkeypatch.setitem(sys.modules, "deepagents_code.command_registry", cr)

    # app module with DeepAgentsApp carrying TITLE/SUB_TITLE/_handle_command.
    app_mod = types.ModuleType("deepagents_code.app")

    class _DeepAgentsApp:
        TITLE = "Deep Agents"
        SUB_TITLE = None

        async def _handle_command(self, command: str) -> None:  # pragma: no cover
            # Tests only exercise the wrapped override.
            self.last_original_command = command  # type: ignore[attr-defined]

    app_mod.DeepAgentsApp = _DeepAgentsApp  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "deepagents_code.app", app_mod)

    # update_check stub with the two entry points the overlay neutralises.
    uc = types.ModuleType("deepagents_code.update_check")

    def _orig_auto_update() -> bool:  # pragma: no cover
        return True

    async def _orig_perform() -> tuple[bool, str]:  # pragma: no cover
        return True, "upgraded"

    uc.is_auto_update_enabled = _orig_auto_update  # type: ignore[attr-defined]
    uc.perform_upgrade = _orig_perform  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "deepagents_code.update_check", uc)

    # widgets.welcome stub — needed by _patch_welcome_footer.
    widgets_pkg = types.ModuleType("deepagents_code.widgets")
    widgets_pkg.__path__ = []  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "deepagents_code.widgets", widgets_pkg)

    welcome_mod = types.ModuleType("deepagents_code.widgets.welcome")

    class _FakeTheme:
        PRIMARY = "blue"

    welcome_mod.theme = _FakeTheme()  # type: ignore[attr-defined]
    welcome_mod.build_welcome_footer = lambda **kw: None  # type: ignore[attr-defined]
    # _TIPS / _pick_tip mirror deepagents_code 0.1.8 — consumed by _patch_tips.
    welcome_mod._TIPS = {  # type: ignore[attr-defined]
        "Use /copy to copy the latest assistant message": 3,
        "Deep Agents can explain its own features": 2,
    }

    def _pick_tip() -> str:  # pragma: no cover - exercised indirectly
        return next(iter(welcome_mod._TIPS))

    welcome_mod._pick_tip = _pick_tip  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "deepagents_code.widgets.welcome", welcome_mod)

    # server_manager stub — needed by _patch_scaffold_for_olav_graph.
    sm_mod = types.ModuleType("deepagents_code.server_manager")
    sm_mod._scaffold_workspace = lambda work_dir: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "deepagents_code.server_manager", sm_mod)

    # server stub — needed by _patch_scaffold_for_olav_graph.
    server_mod = types.ModuleType("deepagents_code.server")
    server_mod.generate_langgraph_json = lambda wd, *, graph_ref, checkpointer_path: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "deepagents_code.server", server_mod)

    return config_mod, cr, _DeepAgentsApp, uc


def _fresh_overlay(monkeypatch: pytest.MonkeyPatch):
    """Re-import the overlay module with a clean ``_applied`` flag."""
    monkeypatch.delitem(sys.modules, "olav.cli.tui_overlay", raising=False)
    import olav.cli.tui_overlay as overlay

    return overlay


# ── 1. importable ────────────────────────────────────────────────────────────


def test_tui_overlay_importable() -> None:
    import olav.cli.tui_overlay as overlay

    assert hasattr(overlay, "apply_olav_overlay")
    assert hasattr(overlay, "consume_pending_workspace")
    assert overlay.OLAV_UNICODE_BANNER.strip()
    assert overlay.OLAV_ASCII_BANNER.strip()


# ── 2. version guard rejects unsupported versions ────────────────────────────


def test_overlay_skips_on_unsupported_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_mod, cr, app, _uc = _install_stub_deepagents_code(
        monkeypatch, version="999.999.999"
    )
    overlay = _fresh_overlay(monkeypatch)

    assert overlay.apply_olav_overlay() is False
    # Nothing mutated on fallback.
    assert config_mod._UNICODE_BANNER == "ORIGINAL_UNICODE"
    assert config_mod._ASCII_BANNER == "ORIGINAL_ASCII"
    assert app.TITLE == "Deep Agents"
    assert all(cmd.name != "/workspace" for cmd in cr.COMMANDS)


# ── 3. supported version applies every patch ─────────────────────────────────


def test_overlay_applies_on_supported_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_mod, cr, app, uc = _install_stub_deepagents_code(
        monkeypatch, version="0.1.8"
    )
    overlay = _fresh_overlay(monkeypatch)

    assert overlay.apply_olav_overlay() is True

    # Banner replaced.
    assert config_mod._UNICODE_BANNER == overlay.OLAV_UNICODE_BANNER
    assert config_mod._ASCII_BANNER == overlay.OLAV_ASCII_BANNER

    # Textual title set.
    assert app.TITLE == "OLAV"
    assert app.SUB_TITLE and "Agentic" in app.SUB_TITLE

    # /workspace registered in COMMANDS and SLASH_COMMANDS.
    cmd_names = [c.name for c in cr.COMMANDS]
    assert cmd_names.count("/workspace") == 1
    entry_names = [e.name for e in cr.SLASH_COMMANDS]
    assert entry_names.count("/workspace") == 1

    # /update and /auto-update filtered out of the menus.
    assert "/update" not in cmd_names
    assert "/auto-update" not in cmd_names
    assert "/update" not in entry_names
    assert "/auto-update" not in entry_names

    # update_check entry points neutralised.
    assert uc.is_auto_update_enabled() is False
    import asyncio

    ok, msg = asyncio.run(uc.perform_upgrade())
    assert ok is False
    assert "OLAV" in msg

    # Handler is swapped on the class.
    assert app._handle_command.__name__ == "_olav_handle_command"


# ── 4. idempotent: apply twice, no duplicate /workspace ──────────────────────


def test_overlay_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    _, cr, _, _uc = _install_stub_deepagents_code(monkeypatch, version="0.1.8")
    overlay = _fresh_overlay(monkeypatch)

    assert overlay.apply_olav_overlay() is True
    # Second call must be a no-op: still one /workspace entry.
    assert overlay.apply_olav_overlay() is True
    cmd_names = [c.name for c in cr.COMMANDS]
    assert cmd_names.count("/workspace") == 1


# ── 5. /workspace handler sets pending flag and exits app ────────────────────


def test_workspace_command_sets_pending_and_exits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, app_cls, _uc = _install_stub_deepagents_code(monkeypatch, version="0.1.8")
    overlay = _fresh_overlay(monkeypatch)
    overlay.apply_olav_overlay()

    # Simulate a valid workspace directory so the handler accepts 'ops'.
    monkeypatch.setattr(overlay, "_discover_workspaces", lambda: {"ops", "core"})

    class _FakeApp:
        def __init__(self) -> None:
            self._assistant_id = "core"
            self.exited = False
            self.notices: list[tuple[str, str]] = []

        def notify(self, message: str, *, severity: str = "information", markup: bool = True) -> None:  # noqa: ARG002
            self.notices.append((severity, message))

        def exit(self) -> None:
            self.exited = True

    fake = _FakeApp()

    import asyncio

    asyncio.run(app_cls._handle_command(fake, "/workspace ops"))

    assert overlay.consume_pending_workspace() == "ops"
    # Second consume returns None — flag is cleared.
    assert overlay.consume_pending_workspace() is None
    assert fake.exited is True


# ── 6. /workspace with no args prints usage and does NOT set pending flag ───


def test_workspace_command_without_args_is_informational(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, app_cls, _uc = _install_stub_deepagents_code(monkeypatch, version="0.1.8")
    overlay = _fresh_overlay(monkeypatch)
    overlay.apply_olav_overlay()
    monkeypatch.setattr(overlay, "_discover_workspaces", lambda: {"ops"})

    class _FakeApp:
        def __init__(self) -> None:
            self._assistant_id = "core"
            self.exited = False
            self.notices: list[tuple[str, str]] = []

        def notify(self, message: str, *, severity: str = "information", markup: bool = True) -> None:  # noqa: ARG002
            self.notices.append((severity, message))

        def exit(self) -> None:  # pragma: no cover  # must not fire
            self.exited = True

    fake = _FakeApp()

    import asyncio

    asyncio.run(app_cls._handle_command(fake, "/workspace"))

    assert overlay.consume_pending_workspace() is None
    assert fake.exited is False
    assert fake.notices, "expected usage notification"


# ── 7. /workspace rejects an unknown target ─────────────────────────────────


def test_workspace_command_rejects_unknown_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, app_cls, _uc = _install_stub_deepagents_code(monkeypatch, version="0.1.8")
    overlay = _fresh_overlay(monkeypatch)
    overlay.apply_olav_overlay()
    monkeypatch.setattr(overlay, "_discover_workspaces", lambda: {"ops", "core"})

    class _FakeApp:
        def __init__(self) -> None:
            self._assistant_id = "core"
            self.exited = False
            self.notices: list[tuple[str, str]] = []

        def notify(self, message: str, *, severity: str = "information", markup: bool = True) -> None:  # noqa: ARG002
            self.notices.append((severity, message))

        def exit(self) -> None:  # pragma: no cover
            self.exited = True

    fake = _FakeApp()

    import asyncio

    asyncio.run(app_cls._handle_command(fake, "/workspace bogus"))

    assert overlay.consume_pending_workspace() is None
    assert fake.exited is False
    assert any(sev == "warning" for sev, _ in fake.notices)


# ── 8. non-/workspace commands flow through to the original handler ─────────


def test_other_commands_delegate_to_original(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, app_cls, _uc = _install_stub_deepagents_code(monkeypatch, version="0.1.8")
    overlay = _fresh_overlay(monkeypatch)
    overlay.apply_olav_overlay()

    class _FakeApp:
        def __init__(self) -> None:
            self.last_original_command: str | None = None

        def notify(self, message: str, *, severity: str = "information", markup: bool = True) -> None:  # noqa: ARG002
            pass

        def exit(self) -> None:  # pragma: no cover
            pass

    fake = _FakeApp()

    import asyncio

    asyncio.run(app_cls._handle_command(fake, "/help"))

    # The stubbed original records the command on the instance.
    assert fake.last_original_command == "/help"
    assert overlay.consume_pending_workspace() is None


# ── 9. /update typed by hand is intercepted, not forwarded ──────────────────


def test_update_command_is_blocked_by_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, app_cls, _uc = _install_stub_deepagents_code(monkeypatch, version="0.1.8")
    overlay = _fresh_overlay(monkeypatch)
    overlay.apply_olav_overlay()

    class _FakeApp:
        def __init__(self) -> None:
            self.last_original_command: str | None = None
            self.notices: list[tuple[str, str]] = []

        def notify(self, message: str, *, severity: str = "information", markup: bool = True) -> None:  # noqa: ARG002
            self.notices.append((severity, message))

        def exit(self) -> None:  # pragma: no cover
            pass

    fake = _FakeApp()

    import asyncio

    # Both the bare command and the "toggle"-style auto-update must be
    # intercepted (they're in _BLOCKED_COMMANDS).
    for command in ("/update", "/auto-update", "/auto-update on"):
        fake.notices.clear()
        fake.last_original_command = None
        asyncio.run(app_cls._handle_command(fake, command))

        # Original handler NOT called.
        assert fake.last_original_command is None, (
            f"handler unexpectedly forwarded {command!r}"
        )
        # Warning notification issued.
        assert any(
            sev == "warning" and "pinned" in msg for sev, msg in fake.notices
        ), f"expected pin-block warning for {command!r}, got {fake.notices}"


# ── 10. /<workspace> aliases registered and dispatched ──────────────────────


def test_workspace_aliases_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, cr, _, _uc = _install_stub_deepagents_code(monkeypatch, version="0.1.8")
    overlay = _fresh_overlay(monkeypatch)
    monkeypatch.setattr(overlay, "_discover_workspaces", lambda: {"ops", "audit"})

    assert overlay.apply_olav_overlay() is True

    names = [c.name for c in cr.COMMANDS]
    assert "/ops" in names
    assert "/audit" in names
    entries = [e.name for e in cr.SLASH_COMMANDS]
    assert "/ops" in entries
    assert "/audit" in entries


def test_alias_collision_with_builtin_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, cr, _, _uc = _install_stub_deepagents_code(monkeypatch, version="0.1.8")
    overlay = _fresh_overlay(monkeypatch)
    # A workspace literally called "help" must not clobber the /help command.
    monkeypatch.setattr(overlay, "_discover_workspaces", lambda: {"help", "ops"})

    assert overlay.apply_olav_overlay() is True

    names = [c.name for c in cr.COMMANDS]
    # /help stays exactly once — not replaced by a workspace alias.
    assert names.count("/help") == 1
    # /ops still registered as an alias.
    assert "/ops" in names


def test_alias_dispatches_to_workspace_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, app_cls, _uc = _install_stub_deepagents_code(monkeypatch, version="0.1.8")
    overlay = _fresh_overlay(monkeypatch)
    monkeypatch.setattr(overlay, "_discover_workspaces", lambda: {"ops", "core"})
    overlay.apply_olav_overlay()

    class _FakeApp:
        def __init__(self) -> None:
            self._assistant_id = "core"
            self.exited = False
            self.notices: list[tuple[str, str]] = []

        def notify(self, message: str, *, severity: str = "information", markup: bool = True) -> None:  # noqa: ARG002
            self.notices.append((severity, message))

        def exit(self) -> None:
            self.exited = True

    fake = _FakeApp()

    import asyncio

    asyncio.run(app_cls._handle_command(fake, "/ops"))

    # Bare /ops → workspace swap scheduled, app exited.
    assert overlay.consume_pending_workspace() == "ops"
    assert fake.exited is True


def test_alias_with_extra_args_falls_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, app_cls, _uc = _install_stub_deepagents_code(monkeypatch, version="0.1.8")
    overlay = _fresh_overlay(monkeypatch)
    monkeypatch.setattr(overlay, "_discover_workspaces", lambda: {"ops"})
    overlay.apply_olav_overlay()

    class _FakeApp:
        def __init__(self) -> None:
            self._assistant_id = "core"
            self.exited = False
            self.last_original_command: str | None = None
            self.notices: list[tuple[str, str]] = []

        def notify(self, message: str, *, severity: str = "information", markup: bool = True) -> None:  # noqa: ARG002
            self.notices.append((severity, message))

        def exit(self) -> None:  # pragma: no cover
            self.exited = True

    fake = _FakeApp()

    import asyncio

    # `/ops something` is NOT a workspace switch — fall through to the
    # original handler so it can be treated as free-form input.
    asyncio.run(app_cls._handle_command(fake, "/ops show devices"))

    assert overlay.consume_pending_workspace() is None
    assert fake.exited is False
    assert fake.last_original_command == "/ops show devices"


# ── 13. /workspace rejects switching to the *current* agent ─────────────────


def test_workspace_command_rejects_same_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, app_cls, _uc = _install_stub_deepagents_code(monkeypatch, version="0.1.8")
    overlay = _fresh_overlay(monkeypatch)
    overlay.apply_olav_overlay()
    monkeypatch.setattr(overlay, "_discover_workspaces", lambda: {"ops", "core"})

    class _FakeApp:
        def __init__(self) -> None:
            self._assistant_id = "core"
            self.exited = False
            self.notices: list[tuple[str, str]] = []

        def notify(self, message: str, *, severity: str = "information", markup: bool = True) -> None:  # noqa: ARG002
            self.notices.append((severity, message))

        def exit(self) -> None:  # pragma: no cover
            self.exited = True

    fake = _FakeApp()

    import asyncio

    asyncio.run(app_cls._handle_command(fake, "/workspace core"))

    assert overlay.consume_pending_workspace() is None, "flag must NOT be set"
    assert fake.exited is False, "app must NOT exit"
    assert any(sev == "warning" for sev, _ in fake.notices), (
        "expected a warning about already-on-this-workspace"
    )


# ── 14. run_interactive agent-swap loop ──────────────────────────────────────


def test_run_interactive_swap_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_interactive restarts with the new agent_id on workspace swap,
    then exits cleanly when the second simple_cli call returns no pending swap.
    """
    import asyncio
    import sys
    from unittest.mock import MagicMock

    monkeypatch.setenv("OLAV_AUTH_MODE", "none")
    monkeypatch.delitem(sys.modules, "olav.cli.main", raising=False)
    from olav.cli import main as cli_main

    # Track which agent IDs were used across loop iterations.
    created_ids: list[str] = []

    def _fake_create(agent_id, *, session_id=None, workspace=None):
        created_ids.append(agent_id)
        return MagicMock(), MagicMock()

    monkeypatch.setattr(cli_main, "create_olav_agent_with_backend", _fake_create)

    # simple_cli: no-op; the pending flag is controlled via the mock below.
    async def _fake_simple_cli(agent, assistant_id, session_state, backend, **kw):
        pass

    monkeypatch.setattr(cli_main, "simple_cli", _fake_simple_cli)

    # consume_pending_workspace: first call returns "netops" (simulating a
    # /workspace command), second call returns None (user exited normally).
    # Use unittest.mock.patch so the patch targets sys.modules["olav.cli.tui_overlay"]
    # at the time run_interactive executes its `from … import` statement,
    # regardless of which module object the test imported at setup time.
    from unittest.mock import patch

    session_state = MagicMock()
    session_state.no_splash = True
    session_state.auto_approve = False

    pending_returns = iter(["netops", None])
    with patch(
        "olav.cli.tui_overlay.consume_pending_workspace",
        side_effect=pending_returns,
    ):
        asyncio.run(
            cli_main.run_interactive(
                assistant_id="core",
                session_state=session_state,
            )
        )

    assert created_ids == ["core", "netops"], (
        f"agents created in wrong order or wrong count: {created_ids}"
    )


# ── 15. stdin pipe → run_single_query (non-TTY fix) ─────────────────────────


def test_piped_stdin_routes_to_single_query(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """When stdin is not a TTY, the CLI must run the piped text as a
    single query rather than launching the interactive TUI.
    """
    import asyncio
    import io
    import sys

    monkeypatch.setenv("OLAV_AUTH_MODE", "none")
    monkeypatch.delitem(sys.modules, "olav.cli.main", raising=False)
    from olav.cli import main as cli_main

    executed_queries: list[str] = []

    async def _fake_run_single_query(query, agent_id, **kw):
        executed_queries.append(query)

    monkeypatch.setattr(cli_main, "run_single_query", _fake_run_single_query)

    interactive_calls: list[str] = []

    async def _fake_run_interactive(assistant_id, session_state, **kw):
        interactive_calls.append(assistant_id)  # pragma: no cover

    monkeypatch.setattr(cli_main, "run_interactive", _fake_run_interactive)

    # Simulate non-TTY stdin with piped content.
    fake_stdin = io.StringIO("!echo hello from pipe\n")
    monkeypatch.setattr(sys, "stdin", fake_stdin)

    # Minimal args namespace that the else-branch reads.
    import argparse
    args = argparse.Namespace(
        query=None,
        agent="core",
        session=None,
        auto_approve=False,
        no_splash=True,
        sandbox="none",
        sandbox_id=None,
        sandbox_setup=None,
        workspace=None,
        repeat=1,
    )

    async def _run():
        if not sys.stdin.isatty():
            _piped = sys.stdin.read().strip()
            if _piped:
                await cli_main.run_single_query(
                    _piped, args.agent, session_id=args.session, workspace=None
                )
            return
        await cli_main.run_interactive(
            assistant_id=args.agent,
            session_state=MagicMock(),
        )

    from unittest.mock import MagicMock
    asyncio.run(_run())

    assert executed_queries == ["!echo hello from pipe"], (
        f"single_query not called with piped text: {executed_queries}"
    )
    assert not interactive_calls, "run_interactive must NOT be called for piped stdin"
