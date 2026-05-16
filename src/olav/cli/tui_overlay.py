"""OLAV overlay on top of ``deepagents-cli``'s Textual TUI.

OLAV delegates the interactive TUI to ``deepagents_cli.app.run_textual_app``
but re-skins the shell and adds a ``/workspace`` slash command that triggers
a restart-style agent swap.

Monkey-patch targets (version-guarded)
--------------------------------------
* ``deepagents_cli.config._UNICODE_BANNER`` / ``_ASCII_BANNER`` —
  welcome banner text consumed by ``WelcomeBanner.__init__``.
* ``deepagents_cli.app.DeepAgentsApp.TITLE`` / ``SUB_TITLE`` — window
  title shown in the Textual header.
* ``deepagents_cli.command_registry.COMMANDS`` /
  ``SLASH_COMMANDS`` — extended with OLAV's ``/workspace`` entry so
  autocomplete discovers it.
* ``DeepAgentsApp._handle_command`` — wrapped to intercept
  ``/workspace <name>`` and request a restart via a module-level flag.

The ``/workspace`` command itself does **not** hot-swap the LangGraph
graph; it sets :data:`_PENDING_WORKSPACE` and asks the app to exit.  The
outer interactive loop in ``olav.cli.main.run_interactive`` reads the
flag via :func:`consume_pending_workspace` and re-enters with the new
``assistant_id``.

Version guard
-------------
Monkey-patching deepagents-cli internals is only safe against pinned
versions.  :data:`_SUPPORTED_VERSIONS` lists the versions we have
smoke-tested; on any other version the overlay logs a warning and
skips every patch so the TUI falls back to vanilla deepagents-cli
branding (no crash).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)


TuiMode = Literal["native", "overlay"]

_TUI_MODE_ENV = "OLAV_TUI_MODE"
"""Env var selecting between native (deepagents server_kwargs) and
overlay (v0.19-style in-process ``agent=`` path).  Phase B (v0.20.2)
ships both; the default depends on workspace layout."""


def resolve_tui_mode(root: Path | None = None) -> TuiMode:
    """Return the effective TUI mode for this invocation.

    Precedence:

    1. ``OLAV_TUI_MODE`` env var — ``"native"`` or ``"overlay"``.
       Unknown values log a warning and fall through to layout-
       driven default.
    2. Auto-detect from filesystem layout:
       * ``.deepagents/agents/`` present → ``"native"``
       * Only ``.olav/workspace/`` present → ``"overlay"``
       * Neither present → ``"native"`` (fresh projects should use
         the new layout).

    Args:
        root: Project root to probe.  Defaults to current working
            directory.

    Returns:
        The effective mode as a string literal.
    """
    raw = (os.environ.get(_TUI_MODE_ENV) or "").strip().lower()
    if raw in ("native", "overlay"):
        return raw  # type: ignore[return-value]
    if raw:
        logger.warning(
            "%s=%r is not a recognised value; auto-detecting from layout. "
            "Valid values: 'native', 'overlay'.",
            _TUI_MODE_ENV,
            raw,
        )

    probe_root = (root or Path.cwd()).resolve()

    new_root = probe_root / ".deepagents" / "agents"
    if new_root.is_dir() and any(p.is_dir() for p in new_root.iterdir()):
        return "native"

    legacy_root = probe_root / ".olav" / "workspace"
    if legacy_root.is_dir():
        return "overlay"

    # No workspace at all → native (new default for fresh projects).
    return "native"

# Suppress deepagents-cli's PyPI auto-update-check on every TUI launch.
# OLAV pins deepagents-cli==0.0.41 (exact) because tui_overlay below
# monkey-patches private internals (WelcomeBanner constants,
# DeepAgentsApp TITLE/_handle_command, command_registry COMMANDS).
# A user-triggered upgrade would silently break those bindings until
# _SUPPORTED_VERSIONS is updated — so the "new version available"
# nag is at best noise and at worst destructive.
#
# Setting the env var at module import time (which runs before the
# Textual app is constructed; see src/olav/cli/main.py:806).
# update_check.is_update_check_enabled() reads it lazily so this works.
os.environ.setdefault("DEEPAGENTS_CLI_NO_UPDATE_CHECK", "1")


_SUPPORTED_VERSIONS: frozenset[str] = frozenset({"0.0.41"})
"""deepagents-cli versions where the overlay has been smoke-tested.

Update this set together with the ``deepagents-cli`` pin in
``pyproject.toml`` after verifying the TUI manually (see
``tests/ci/tier1_functional.sh`` T1-53)."""

_PENDING_WORKSPACE: str | None = None
"""Set by the ``/workspace <name>`` handler when the user asks to swap
agent.  Consumed (and cleared) by :func:`consume_pending_workspace` in
the outer interactive loop."""

_applied: bool = False
"""True once the overlay has been applied in this process so repeated
calls short-circuit."""


OLAV_UNICODE_BANNER = """
  ██████╗  ██╗       █████╗  ██╗   ██╗
 ██╔═══██╗ ██║      ██╔══██╗ ██║   ██║
 ██║   ██║ ██║      ███████║ ██║   ██║
 ██║   ██║ ██║      ██╔══██║ ╚██╗ ██╔╝
 ╚██████╔╝ ███████╗ ██║  ██║  ╚████╔╝
  ╚═════╝  ╚══════╝ ╚═╝  ╚═╝   ╚═══╝

 Online Analytical Vertex for Agentic Operations 🐺
"""

OLAV_ASCII_BANNER = """
  ___  _      ___  __   __
 / _ \\| |    / _ \\ \\ \\ / /
| | | | |   | |_| | \\ V /
| |_| | |___|  _  |  | |
 \\___/|_____|_| |_|  |_|

 Online Analytical Vertex for Agentic Operations
"""


def consume_pending_workspace() -> str | None:
    """Return and clear the pending workspace swap request, if any.

    Called by :func:`olav.cli.main.run_interactive` after the TUI exits
    to decide whether to restart with a new agent.

    Returns:
        The workspace/agent name the user requested, or ``None`` when
        the TUI exited for any other reason.
    """
    global _PENDING_WORKSPACE
    target = _PENDING_WORKSPACE
    _PENDING_WORKSPACE = None
    return target


def apply_olav_overlay() -> bool:
    """Apply the OLAV branding + ``/workspace`` overlay.

    Safe to call repeatedly; only applies patches once per process.  Any
    individual patch failure is swallowed (logged at WARNING) so a
    partial overlay is better than a crashed CLI.

    Returns:
        ``True`` when every patch landed, ``False`` when the overlay was
        skipped (unsupported version) or at least one patch failed.
    """
    global _applied
    if _applied:
        return True

    try:
        import deepagents_cli
    except ImportError:
        logger.warning("deepagents_cli not importable — overlay skipped")
        return False

    version = getattr(deepagents_cli, "__version__", "unknown")
    if version not in _SUPPORTED_VERSIONS:
        logger.warning(
            "deepagents-cli %s is not in the overlay's supported set %s — "
            "falling back to vanilla deepagents TUI (branding and /workspace "
            "command disabled). Update _SUPPORTED_VERSIONS after smoke-testing.",
            version,
            sorted(_SUPPORTED_VERSIONS),
        )
        return False

    ok = True
    ok &= _patch_banner()
    ok &= _patch_title()
    ok &= _patch_workspace_command()
    ok &= _patch_disable_self_upgrade()
    # Scaffold patch is "best effort" for native mode — don't let its
    # absence flip `ok` to False when the core overlay (banner, title,
    # /workspace command) is otherwise healthy.  Native users still
    # get the patch when it succeeds; overlay users don't care.
    _patch_scaffold_for_olav_graph()

    _applied = True
    return ok


_BLOCKED_COMMANDS: frozenset[str] = frozenset({"/update", "/auto-update"})
"""Slash commands hidden from the menu and intercepted by the overlay.

These commands trigger ``deepagents_cli.update_check.perform_upgrade``
which would bump ``deepagents-cli`` past our exact pin and break the
overlay.  We hide them from autocomplete and, as belt-and-braces,
intercept them in ``_handle_command`` with a message pointing users
back to ``pip install --upgrade olav``."""


def _patch_banner() -> bool:
    """Swap the deepagents welcome banner constants for OLAV's."""
    try:
        import deepagents_cli.config as _dc_config

        if not hasattr(_dc_config, "_UNICODE_BANNER") or not hasattr(
            _dc_config, "_ASCII_BANNER"
        ):
            logger.warning(
                "deepagents_cli.config is missing _UNICODE_BANNER/_ASCII_BANNER — "
                "banner overlay skipped"
            )
            return False

        _dc_config._UNICODE_BANNER = OLAV_UNICODE_BANNER
        _dc_config._ASCII_BANNER = OLAV_ASCII_BANNER
        return True
    except Exception:
        logger.warning("Banner patch failed", exc_info=True)
        return False


def _patch_title() -> bool:
    """Set the Textual window TITLE/SUB_TITLE to OLAV's."""
    try:
        from deepagents_cli.app import DeepAgentsApp

        DeepAgentsApp.TITLE = "OLAV"
        DeepAgentsApp.SUB_TITLE = "Online Analytical Vertex for Agentic Operations"
        return True
    except Exception:
        logger.warning("Title patch failed", exc_info=True)
        return False


def _patch_workspace_command() -> bool:
    """Register the ``/workspace`` slash command and its handler.

    Steps:

    1. Build a ``SlashCommand`` for ``/workspace`` and prepend it to
       :data:`deepagents_cli.command_registry.COMMANDS` so autocomplete
       surfaces it.
    2. Extend :data:`deepagents_cli.command_registry.SLASH_COMMANDS`
       (the derived list consumed by the autocomplete UI).
    3. Wrap ``DeepAgentsApp._handle_command`` with a dispatcher that
       intercepts ``/workspace`` and delegates everything else to the
       original.
    """
    try:
        from deepagents_cli import command_registry as _cr
        from deepagents_cli.app import DeepAgentsApp

        if not hasattr(_cr, "COMMANDS") or not hasattr(_cr, "SLASH_COMMANDS"):
            logger.warning(
                "command_registry is missing COMMANDS/SLASH_COMMANDS — "
                "/workspace command skipped"
            )
            return False
        if not hasattr(_cr, "SlashCommand") or not hasattr(_cr, "BypassTier"):
            logger.warning(
                "command_registry is missing SlashCommand/BypassTier — "
                "/workspace command skipped"
            )
            return False
        if not hasattr(DeepAgentsApp, "_handle_command"):
            logger.warning(
                "DeepAgentsApp._handle_command no longer exists — "
                "/workspace command skipped"
            )
            return False

        workspace_cmd = _cr.SlashCommand(
            name="/workspace",
            description="Switch to a different OLAV workspace (restarts TUI)",
            bypass_tier=_cr.BypassTier.IMMEDIATE_UI,
            hidden_keywords="agent swap switch",
            argument_hint="<name>",
        )

        # Filter out deepagents-cli's self-upgrade commands — they'd break
        # our pinned version — and prepend /workspace.
        filtered_commands = tuple(
            c for c in _cr.COMMANDS if c.name not in _BLOCKED_COMMANDS
        )

        # Compute /<workspace> aliases (/ops, /audit, …) that don't shadow
        # any existing built-in command or /workspace itself.  These are a
        # startup-time snapshot — newly installed workspaces still work via
        # /workspace <name> without a restart; the short alias just won't
        # appear until next TUI launch.
        reserved = {c.name for c in filtered_commands} | {"/workspace"}
        workspace_names = _discover_workspaces()
        alias_cmds: list[Any] = []
        aliases_registered: set[str] = set()
        for name in sorted(workspace_names):
            alias = f"/{name}"
            if alias in reserved:
                logger.warning(
                    "Workspace %r collides with existing command %s; "
                    "alias not registered",
                    name,
                    alias,
                )
                continue
            alias_cmds.append(
                _cr.SlashCommand(
                    name=alias,
                    description=f"Switch to the '{name}' workspace",
                    bypass_tier=_cr.BypassTier.IMMEDIATE_UI,
                    hidden_keywords="workspace agent swap switch",
                )
            )
            aliases_registered.add(name)

        _cr.COMMANDS = (workspace_cmd, *filtered_commands, *alias_cmds)
        _cr.SLASH_COMMANDS[:] = [c.to_entry() for c in _cr.COMMANDS]

        _original_handle = DeepAgentsApp._handle_command

        async def _olav_handle_command(self: Any, command: str) -> None:
            cmd_lower = command.lower().strip()
            # Match "/workspace" exactly and any "/workspace <args>" form.
            if cmd_lower == "/workspace" or cmd_lower.startswith("/workspace "):
                await _dispatch_workspace(self, command)
                return
            # Match a registered workspace alias with no extra args —
            # e.g. "/ops" but NOT "/ops some free-form message".
            cmd_token = cmd_lower.split(maxsplit=1)[0] if cmd_lower else ""
            if cmd_lower == cmd_token and cmd_token.startswith("/"):
                alias_name = cmd_token[1:]
                if alias_name in aliases_registered:
                    await _dispatch_workspace(self, f"/workspace {alias_name}")
                    return
            # Intercept upgrade commands so they can't break the pin even if
            # typed manually.  (They no longer appear in autocomplete but a
            # determined user can still type them by hand.)
            if cmd_token in _BLOCKED_COMMANDS:
                _notify(
                    self,
                    "This command is disabled under OLAV — deepagents-cli is "
                    "pinned. Run `pip install --upgrade olav` to update.",
                    severity="warning",
                )
                return
            await _original_handle(self, command)

        DeepAgentsApp._handle_command = _olav_handle_command  # type: ignore[method-assign]
        return True
    except Exception:
        logger.warning("/workspace command patch failed", exc_info=True)
        return False


def _patch_disable_self_upgrade() -> bool:
    """Neutralise deepagents-cli's background auto-update and on-demand
    upgrade helpers.

    ``deepagents-cli`` has two upgrade paths we need to close:

    * ``update_check.is_auto_update_enabled()`` — polled on TUI start and
      in the background; when true and a newer version is live on PyPI,
      the CLI silently runs ``pip install --upgrade deepagents-cli``,
      which would bump past our pin.
    * ``update_check.perform_upgrade()`` — invoked by ``/update`` and by
      the auto-update loop; executes the upgrade directly.

    We replace both with inert versions.  ``is_auto_update_enabled``
    always returns ``False`` and ``perform_upgrade`` returns a
    ``(False, <message>)`` tuple explaining the block.  These functions
    are defensive: the slash commands themselves are already hidden and
    intercepted in :func:`_patch_workspace_command`, but a future
    deepagents-cli release might expose a new entry point that still
    calls these helpers.
    """
    try:
        from deepagents_cli import update_check

        if hasattr(update_check, "is_auto_update_enabled"):
            update_check.is_auto_update_enabled = lambda: False  # type: ignore[assignment]
        else:
            logger.warning(
                "update_check.is_auto_update_enabled missing — auto-update "
                "block skipped"
            )
            return False

        if hasattr(update_check, "perform_upgrade"):
            async def _blocked_upgrade() -> tuple[bool, str]:
                return (
                    False,
                    "deepagents-cli upgrade blocked by OLAV overlay. "
                    "Run `pip install --upgrade olav` to receive a "
                    "compatible deepagents-cli bump.",
                )

            update_check.perform_upgrade = _blocked_upgrade  # type: ignore[assignment]
        else:
            logger.warning(
                "update_check.perform_upgrade missing — upgrade block skipped"
            )
            return False

        return True
    except Exception:
        logger.warning("Self-upgrade disable patch failed", exc_info=True)
        return False


def _patch_scaffold_for_olav_graph() -> bool:
    """Redirect deepagents-cli's subprocess graph loader at OLAV's factory.

    Without this patch, ``run_textual_app(server_kwargs=...)`` spawns
    a ``langgraph dev`` subprocess whose ``langgraph.json`` points at
    ``./server_graph.py:graph`` — deepagents-cli's own default graph.
    The subprocess therefore completely ignores OLAV's agents, tools,
    and plugin registry.

    The patch wraps
    :func:`deepagents_cli.server_manager._scaffold_workspace`.  After
    deepagents' default scaffolding (checkpointer module, pyproject
    template, initial langgraph.json) writes its files, the wrapper
    calls :func:`deepagents_cli.server.generate_langgraph_json` one
    more time with ``graph_ref="olav.server.graph_factory:graph"`` to
    overwrite the config file.

    Why this works
    --------------
    :func:`deepagents_cli.server._build_server_cmd` launches the
    subprocess via ``sys.executable -m langgraph_cli dev`` — same
    Python interpreter, same ``site-packages``.  OLAV is therefore
    already importable in the subprocess, so ``dependencies: ["."]``
    in the generated langgraph.json just re-installs an empty
    ``deepagents-server-runtime`` shell while the real graph is
    loaded by module path.

    Returns:
        ``True`` when the patch was applied, ``False`` when a
        required deepagents-cli symbol is missing (older / newer
        release than the overlay was tested against).
    """
    try:
        from deepagents_cli import server_manager as _sm

        if not hasattr(_sm, "_scaffold_workspace"):
            logger.warning(
                "deepagents_cli.server_manager._scaffold_workspace no longer "
                "exists — native /agents cutover patch skipped"
            )
            return False

        try:
            from deepagents_cli.server import generate_langgraph_json
        except ImportError:
            logger.warning(
                "deepagents_cli.server.generate_langgraph_json not importable "
                "— scaffold patch skipped"
            )
            return False

        original = _sm._scaffold_workspace

        # Idempotence — detect prior wrap via a marker attribute.
        if getattr(original, "_olav_wrapped", False):
            return True

        def _olav_scaffold_workspace(work_dir):
            # Run deepagents' default scaffolding first so checkpointer.py,
            # pyproject.toml, and the initial langgraph.json all exist.
            original(work_dir)
            # Then overwrite langgraph.json with OLAV's graph_ref.  The
            # checkpointer_path must match deepagents' default so the
            # server still finds the checkpointer module it just wrote.
            try:
                generate_langgraph_json(
                    work_dir,
                    graph_ref="olav.server.graph_factory:graph",
                    checkpointer_path="./checkpointer.py:create_checkpointer",
                )
            except Exception:  # noqa: BLE001
                logger.warning(
                    "OLAV scaffold override failed; subprocess will run "
                    "deepagents' default graph",
                    exc_info=True,
                )

        _olav_scaffold_workspace._olav_wrapped = True  # type: ignore[attr-defined]
        _sm._scaffold_workspace = _olav_scaffold_workspace
        return True
    except Exception:
        logger.warning("Scaffold patch failed", exc_info=True)
        return False


async def _dispatch_workspace(app: Any, command: str) -> None:
    """Handle a ``/workspace [<name>]`` submission from inside the TUI.

    Without an argument we list available workspaces.  With one we
    record the target on :data:`_PENDING_WORKSPACE` and ask the app to
    exit so :func:`olav.cli.main.run_interactive` can relaunch.
    """
    global _PENDING_WORKSPACE

    parts = command.strip().split(maxsplit=1)
    target = parts[1].strip() if len(parts) > 1 else ""

    if not target:
        _notify(app, _list_workspaces_message(), severity="information")
        return

    # Reject switching to the current agent.
    current = getattr(app, "_assistant_id", None)
    if current and target == current:
        _notify(app, f"Already on workspace '{target}'.", severity="warning")
        return

    # Validate against discovered workspaces.
    available = _discover_workspaces()
    if available and target not in available:
        _notify(
            app,
            f"Unknown workspace '{target}'. Available: {', '.join(sorted(available))}",
            severity="warning",
        )
        return

    _PENDING_WORKSPACE = target
    _notify(
        app,
        f"Switching to workspace '{target}'…",
        severity="information",
    )
    try:
        app.exit()
    except Exception:
        logger.warning("Failed to exit TUI cleanly for workspace swap", exc_info=True)


def _notify(app: Any, message: str, *, severity: str = "information") -> None:
    """Best-effort Textual notification with a plain-print fallback."""
    try:
        app.notify(message, severity=severity, markup=False)
    except Exception:
        print(message)


def _list_workspaces_message() -> str:
    """Format a human-readable list of discovered workspaces."""
    names = _discover_workspaces()
    if not names:
        return (
            "Usage: /workspace <name>\n"
            "No workspaces discovered in .olav/workspace/"
        )
    return "Usage: /workspace <name>\nAvailable: " + ", ".join(sorted(names))


def _discover_workspaces() -> set[str]:
    """Return the set of agent directory names across both layouts.

    Delegates to :func:`olav.core.workspace_discovery.discover_agent_names`
    so the overlay + CLI + API all share one implementation.  Returns
    an empty set on any failure — overlay must never crash the TUI
    just because workspace discovery hiccuped.
    """
    try:
        from olav.core.workspace_discovery import discover_agent_names

        return set(discover_agent_names())
    except Exception:
        logger.debug("Workspace discovery failed", exc_info=True)
        return set()


__all__ = [
    "OLAV_ASCII_BANNER",
    "OLAV_UNICODE_BANNER",
    "apply_olav_overlay",
    "consume_pending_workspace",
]
