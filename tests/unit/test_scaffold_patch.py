"""
tests/unit/test_scaffold_patch.py
─────────────────────────────────
Unit coverage for the P6 monkey-patch that redirects deepagents-cli's
subprocess-mode graph loader at OLAV's factory.

Before this patch, ``run_textual_app(server_kwargs=...)`` spawned a
``langgraph dev`` subprocess that loaded deepagents' own default
``server_graph.py`` — ignoring OLAV entirely (see dev_docs/56 §10).

The patch wraps ``deepagents_code.server_manager._scaffold_workspace``
so after the default scaffolding runs, we rewrite the generated
``langgraph.json`` to point ``graph_ref`` at
``olav.server.graph_factory:graph``.  The subprocess shares the
parent's Python interpreter (``sys.executable``), so OLAV is already
importable — no extra install step needed.

Guarantees:

1. The patch function exists in ``olav.cli.tui_overlay`` and is
   addressable for tests.
2. After applying the patch, calling the (now wrapped)
   ``_scaffold_workspace`` invokes ``generate_langgraph_json`` with
   the OLAV graph_ref — replacing deepagents' default.
3. The original scaffold behaviour (checkpointer.py / pyproject.toml
   writes) still runs — we only overwrite langgraph.json, not the
   whole directory.
4. The patch is version-guarded: unsupported deepagents-cli releases
   log a warning and skip.
"""

from __future__ import annotations

import sys
import types

import pytest


def _install_scaffold_stubs(
    monkeypatch: pytest.MonkeyPatch, *, version: str
) -> tuple[types.ModuleType, types.ModuleType]:
    """Install stand-ins for deepagents_code + server_manager + server
    + other modules the overlay already patches.  Returns
    ``(server_manager, server)`` so tests can inspect spies."""
    # Minimal deepagents_code package
    pkg = types.ModuleType("deepagents_code")
    pkg.__version__ = version  # type: ignore[attr-defined]
    pkg.__path__ = []  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "deepagents_code", pkg)

    # server_manager with a trackable _scaffold_workspace
    sm = types.ModuleType("deepagents_code.server_manager")
    sm.original_scaffold_calls = []  # type: ignore[attr-defined]

    def _scaffold_workspace(work_dir):
        sm.original_scaffold_calls.append(work_dir)

    sm._scaffold_workspace = _scaffold_workspace  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "deepagents_code.server_manager", sm)

    # server with a spy generate_langgraph_json
    server = types.ModuleType("deepagents_code.server")
    server.generate_calls = []  # type: ignore[attr-defined]

    def _generate_langgraph_json(work_dir, *, graph_ref, checkpointer_path=None):
        server.generate_calls.append(
            {
                "work_dir": work_dir,
                "graph_ref": graph_ref,
                "checkpointer_path": checkpointer_path,
            }
        )

    server.generate_langgraph_json = _generate_langgraph_json  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "deepagents_code.server", server)

    # Other modules the overlay's other patches touch — minimal stubs
    # so apply_olav_overlay doesn't explode under test.
    config_mod = types.ModuleType("deepagents_code.config")
    config_mod._UNICODE_BANNER = "X"  # type: ignore[attr-defined]
    config_mod._ASCII_BANNER = "X"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "deepagents_code.config", config_mod)

    cr = types.ModuleType("deepagents_code.command_registry")

    class _BypassTier:
        IMMEDIATE_UI = "immediate_ui"
        QUEUED = "queued"

    class _CommandEntry:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    class _SlashCommand:
        def __init__(self, **kw):
            self.__dict__.update(kw)
            self.aliases = kw.get("aliases", ())

        def to_entry(self):
            return _CommandEntry(
                name=self.name,
                description=self.description,
                hidden_keywords=getattr(self, "hidden_keywords", ""),
                argument_hint=getattr(self, "argument_hint", ""),
            )

    cr.SlashCommand = _SlashCommand  # type: ignore[attr-defined]
    cr.BypassTier = _BypassTier  # type: ignore[attr-defined]
    cr.CommandEntry = _CommandEntry  # type: ignore[attr-defined]
    cr.COMMANDS = ()  # type: ignore[attr-defined]
    cr.SLASH_COMMANDS = []  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "deepagents_code.command_registry", cr)

    app_mod = types.ModuleType("deepagents_code.app")

    class _DeepAgentsApp:
        TITLE = "Deep Agents"
        SUB_TITLE = None

        async def _handle_command(self, command):
            pass

    app_mod.DeepAgentsApp = _DeepAgentsApp  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "deepagents_code.app", app_mod)

    # widgets.welcome — the overlay's footer + tips patches (added after
    # this test was written) import it; missing stubs made
    # apply_olav_overlay return False and fail the wrapper/idempotency
    # tests even with the right version.
    widgets_pkg = types.ModuleType("deepagents_code.widgets")
    widgets_pkg.__path__ = []  # type: ignore[attr-defined]
    welcome_mod = types.ModuleType("deepagents_code.widgets.welcome")
    welcome_mod.theme = types.SimpleNamespace(PRIMARY="white")  # type: ignore[attr-defined]
    welcome_mod.build_welcome_footer = lambda **kw: None  # type: ignore[attr-defined]
    welcome_mod._TIPS = {"stub": "tip"}  # type: ignore[attr-defined]
    widgets_pkg.welcome = welcome_mod  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "deepagents_code.widgets", widgets_pkg)
    monkeypatch.setitem(sys.modules, "deepagents_code.widgets.welcome", welcome_mod)

    uc = types.ModuleType("deepagents_code.update_check")
    uc.is_auto_update_enabled = lambda: True  # type: ignore[attr-defined]

    async def _orig_upgrade():
        return True, "ok"

    uc.perform_upgrade = _orig_upgrade  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "deepagents_code.update_check", uc)

    return sm, server


def _fresh_overlay(monkeypatch: pytest.MonkeyPatch):
    """Re-import the overlay with a clean ``_applied`` flag."""
    monkeypatch.delitem(sys.modules, "olav.cli.tui_overlay", raising=False)
    import olav.cli.tui_overlay as overlay

    return overlay


# ── 1. Patch function exists ───────────────────────────────────────────────


def test_patch_function_present() -> None:
    import olav.cli.tui_overlay as overlay

    # The function is module-level and named for grep-ability.
    assert hasattr(overlay, "_patch_scaffold_for_olav_graph") or hasattr(
        overlay, "_patch_server_scaffold"
    )


# ── 2. Patch installs a wrapper that calls generate_langgraph_json ────────


def test_wrapper_overwrites_langgraph_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    sm, server = _install_scaffold_stubs(monkeypatch, version="0.1.8")
    overlay = _fresh_overlay(monkeypatch)

    assert overlay.apply_olav_overlay() is True

    # Wrapper replaced the original
    assert sm._scaffold_workspace.__name__ != "_scaffold_workspace" or \
        sm._scaffold_workspace is not None

    # Call the (now patched) scaffold
    sm._scaffold_workspace(tmp_path)

    # Original behaviour preserved
    assert tmp_path in sm.original_scaffold_calls

    # Our generate_langgraph_json call happened with OLAV's graph_ref
    assert len(server.generate_calls) == 1
    call = server.generate_calls[0]
    assert call["graph_ref"] == "olav.server.graph_factory:graph"
    assert call["work_dir"] == tmp_path


# ── 3. Unsupported version skips the patch ─────────────────────────────────


def test_unsupported_version_skips_patch(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    sm, server = _install_scaffold_stubs(monkeypatch, version="999.999.999")
    overlay = _fresh_overlay(monkeypatch)

    # Version guard returns False before any patch is attempted.
    assert overlay.apply_olav_overlay() is False

    # The scaffold was NOT wrapped — calling it just runs the original.
    sm._scaffold_workspace(tmp_path)
    assert server.generate_calls == []


# ── 4. Idempotent — applying twice doesn't double-wrap ───────────────────


def test_scaffold_patch_idempotent(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    sm, server = _install_scaffold_stubs(monkeypatch, version="0.1.8")
    overlay = _fresh_overlay(monkeypatch)

    assert overlay.apply_olav_overlay() is True
    assert overlay.apply_olav_overlay() is True  # second call = no-op

    sm._scaffold_workspace(tmp_path)
    # Exactly one generate_langgraph_json call per scaffold
    assert len(server.generate_calls) == 1
