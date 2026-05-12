#!/usr/bin/env python3
"""OLAV v0.14.0 CLI - Full deepagents-cli integration.

This is a thin wrapper around deepagents-cli for domain operations.
All domain functionality is exposed through workspace agents and tools, not CLI commands.

Usage:
    olav                                    # Interactive mode
    olav "How many devices?"               # Single query
    olav --agent ops "Check network"       # Multi-agent
    olav --sandbox modal "Deploy config"   # Remote execution
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import re
import signal
import sys
import uuid as _uuid_mod
import warnings
from importlib.metadata import entry_points
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console

from olav.core.audit_recorder import AuditEventRecorder
from olav.core.version import (
    VERSION,
    format_version_banner,
)

from .banner import print_olav_banner

if TYPE_CHECKING:
    from olav.core.auth import UserIdentity

console = Console()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SIGTERM / atexit guard — mark active run as "interrupted" on unexpected exit
# ---------------------------------------------------------------------------
_active_audit: AuditEventRecorder | None = None
_active_run_id: str | None = None


def _mark_run_interrupted() -> None:
    """Best-effort: mark the current active run as interrupted."""
    global _active_audit, _active_run_id
    if _active_run_id and _active_audit:
        try:
            _active_audit.record_run_end(run_id=_active_run_id, status="interrupted")
            _active_audit.close()
        except Exception:
            pass
        finally:
            _active_audit = None
            _active_run_id = None


def _sigterm_handler(signum: int, frame: object) -> None:
    """Cancel active asyncio tasks + mark run interrupted + exit non-zero.

    Rev 268: closes ISSUE-CLI-TIMEOUT-NO-PROCESS-KILL (P2, rev 242). The
    previous handler called `sys.exit(0)` from the main thread, but
    when OLAV was inside an `await self.graph.ainvoke(...)` the asyncio
    loop and ThreadPoolExecutor kept running in their own contexts and
    ignored the SystemExit — so `bash timeout` would SIGTERM the wrapper
    but the Python child stayed alive minutes longer (rev 242 A5: 22-min
    drag).

    Fix: explicitly walk every asyncio task and call `.cancel()`, then
    exit with code 130 (standard "killed by SIGINT/SIGTERM" convention)
    so callers see a clear non-zero status instead of a misleading 0.
    """
    import asyncio
    _mark_run_interrupted()
    try:
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = None
        if loop is not None and loop.is_running():
            for task in asyncio.all_tasks(loop):
                task.cancel()
    except Exception:
        pass
    # Use code 130 (128 + SIGINT/SIGTERM) so wrappers can detect a
    # terminate vs a real exit. bash's `timeout` itself returns 124
    # / 137; this lets us distinguish the timeout sender from the
    # signal recipient.
    sys.exit(130)


def _sigint_handler(signum: int, frame: object) -> None:
    """Handle Ctrl-C identically — same cancellation path."""
    _sigterm_handler(signum, frame)


signal.signal(signal.SIGTERM, _sigterm_handler)
signal.signal(signal.SIGINT, _sigint_handler)

_GENERIC_DOMAIN_PROMPT = "You are an AI Operations Assistant."


def get_domain_prompt() -> str:
    """Discover domain prompt from installed plugins via entry_points.

    Checks the ``olav.domain_prompts`` entry point group. Returns the prompt
    from the first registered entry point, or a generic fallback if none exist.
    """
    eps = entry_points(group="olav.domain_prompts")
    for ep in eps:
        try:
            return ep.load()
        except Exception:
            logger.warning("Failed to load domain prompt entry point %r", ep.name)
    return _GENERIC_DOMAIN_PROMPT


_KNOWN_COMMANDS: frozenset[str] = frozenset(
    {
        "list",
        "help",
        "version",
        "admin",
        "config",
        "service",
        "reset",
        "skills",
        "skill",   # v0.21.0-rc4 deprecation shim → forwards to `olav agent`.
                   # See gitea #11; without this entry the dispatcher hits
                   # the natural-language query path instead of our shim.
        "log",
        "init",
        "refresh",
        "sessions",
        "workspace",
        "export",
        # "skill" singular: shim re-added v0.21.0-rc4 above; the v0.20.3
        # deletion stripped the ARG dispatcher but kept the SkillCommand
        # class for internal use by agent_install.
        "agent",
        "migrate",
        "registry",
        "kb",
        # ARCH-12 / ARCH-11 / ARCH-13 CLI shortcuts added across Rounds 25/45/47.
        # Missing from the NL-query escape hatch below, these subcommands
        # would misroute through the auth-gated single-query fast-path and
        # refuse to serve even ``--help`` on non-authenticated machines.
        "catalog",
        "explain",
        "diff",
    }
)
"""Subcommand tokens the CLI recognises.  Anything else is treated as
natural-language query text so ``olav show log statistics`` and
``olav "show log statistics"`` behave the same way."""


def _get_known_commands() -> frozenset[str]:
    """Return the frozenset of known CLI subcommand names.

    Exposed for tests that assert on which verbs are wired without
    instantiating the full argparse structure.
    """
    return _KNOWN_COMMANDS


def parse_args():
    """Parse command line arguments - deepagents-cli compatible."""
    import types as _types

    # Known subcommands – if the first non-flag positional arg is NOT one of
    # these, treat all remaining positionals as a natural-language query so
    # that both `olav "show log statistics"` and `olav show log counts` work.
    known_commands = _KNOWN_COMMANDS

    # Flags that consume the immediately following token as their value.
    # We must skip those tokens when searching for the first true positional.
    flags_with_value = {
        "--agent",
        "-a",
        "--sandbox",
        "--sandbox-id",
        "--sandbox-setup",
        "--session",
        "--repeat",
    }

    raw_argv = sys.argv[1:]

    def _first_positional(argv: list[str]) -> str | None:
        skip_next = False
        for tok in argv:
            if skip_next:
                skip_next = False
                continue
            if tok in flags_with_value:
                skip_next = True
                continue
            if tok.startswith("-"):
                continue
            return tok
        return None

    first_positional = _first_positional(raw_argv)

    if first_positional and first_positional not in known_commands:
        # ── Fast path: natural-language single-query mode ──────────────────
        # Use a lightweight pre-parser to extract flags while leaving the
        # query tokens untouched.
        pre = argparse.ArgumentParser(add_help=False)
        pre.add_argument("--agent", "-a", default=None)
        pre.add_argument("--workspace", "-w", default=None)
        pre.add_argument("--auto-approve", dest="auto_approve", action="store_true")
        pre.add_argument(
            "--dangerously-skip-permissions",
            dest="dangerously_skip_permissions",
            action="store_true",
            help="Skip all approval gates (for testing only — not for production use)",
        )
        pre.add_argument(
            "--sandbox", default="none", choices=["none", "modal", "daytona", "runloop"]
        )
        pre.add_argument("--sandbox-id", dest="sandbox_id", default=None)
        pre.add_argument("--sandbox-setup", dest="sandbox_setup", default=None)
        pre.add_argument("--session", default=None)
        pre.add_argument("--no-splash", dest="no_splash", action="store_true")
        pre.add_argument("--verbose", "-v", action="store_true")
        pre.add_argument("--profile", default=None)  # ISSUE-004: audit profile shorthand
        pre.add_argument(
            "--enable-api-write",
            dest="enable_api_write",
            action="store_true",
            help="Unlock API write operations (POST/PUT/PATCH/DELETE). Writes still require dry-run + approval.",
        )
        pre.add_argument(
            "--repeat",
            dest="repeat",
            type=int,
            default=1,
            help="Run the same query N times in one process (default 1). "
                 "Used to measure SemanticCache amortisation in bench harnesses; "
                 "each iteration emits ``=== run K/N elapsed Xs ===`` markers.",
        )

        pre_args, query_tokens = pre.parse_known_args()
        query = " ".join(query_tokens).strip()
        # ISSUE-004: --profile builds a deterministic run-audit query
        if pre_args.profile and not query:
            profile_name = pre_args.profile
            if not profile_name.endswith(".md") and "/" not in profile_name:
                from olav.core.workspace import resolve_workspace_path
                profile_path = str(
                    resolve_workspace_path("audit", "profiles", workspace=pre_args.workspace)
                    / f"{profile_name}.md"
                )
            else:
                profile_path = profile_name
            query = f"Run audit using profile {profile_path}"
        # Resolve agent default: use active workspace default if not specified
        agent = pre_args.agent
        if agent is None:
            from olav.core.workspace import get_active_workspace
            ws = pre_args.workspace or get_active_workspace()
            agent = ws  # core is the default agent (v0.15+)
        # Build a Namespace that matches what the rest of main() expects
        return _types.SimpleNamespace(
            command=None,
            query=query,
            agent=agent,
            workspace=pre_args.workspace,
            auto_approve=pre_args.auto_approve,
            dangerously_skip_permissions=pre_args.dangerously_skip_permissions,
            sandbox=pre_args.sandbox,
            sandbox_id=pre_args.sandbox_id,
            sandbox_setup=pre_args.sandbox_setup,
            session=pre_args.session,
            no_splash=pre_args.no_splash,
            verbose=pre_args.verbose,
            repeat=pre_args.repeat,
        )

    # ── Normal subcommand / interactive path ──────────────────────────────
    parser = argparse.ArgumentParser(
        prog="olav",
        description=f"OLAV v{VERSION} - AI Operations Assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Version command
    subparsers.add_parser("version", help="Show version and system information")

    # List agents command
    subparsers.add_parser("list", help="List all available agents")

    # Help command
    subparsers.add_parser("help", help="Show help information")

    # Admin command
    admin_parser = subparsers.add_parser("admin", help="Admin commands (status, backup, etc.)")
    admin_parser.add_argument("args", nargs=argparse.REMAINDER, help="Admin command arguments")

    # Config command
    config_parser = subparsers.add_parser(
        "config",
        help="Configuration commands (evolve, or natural language query)",
    )
    config_parser.add_argument(
        "args",
        nargs=argparse.REMAINDER,
        help="'evolve --list', 'evolve --approve <id>', or natural language config query",
    )

    # Init command
    subparsers.add_parser("init", help="Initialize platform scaffolding")

    # Refresh command — rebuild global agent registry (deterministic, no LLM)
    subparsers.add_parser(
        "refresh", help="Rebuild global agent registry (PLATFORM.md + routing table)"
    )

    # Sessions command — list conversation sessions across interfaces (M4)
    sessions_parser = subparsers.add_parser(
        "sessions", help="List conversation sessions across CLI/TUI/Web interfaces"
    )
    sessions_parser.add_argument(
        "--all", action="store_true", help="Include inactive sessions"
    )
    sessions_parser.add_argument(
        "--user", metavar="NAME", help="Admin: list sessions for a specific user"
    )

    # Workspace command
    workspace_parser = subparsers.add_parser("workspace", help="Manage workspace lifecycle")
    workspace_parser.add_argument(
        "args", nargs=argparse.REMAINDER, help="Workspace lifecycle arguments"
    )

    # Export command
    export_parser = subparsers.add_parser("export", help="Export Claude-compatible artifacts")
    export_parser.add_argument("args", nargs=argparse.REMAINDER, help="Export command arguments")

    # Service command (logs, web, daemon, etc.)
    service_parser = subparsers.add_parser("service", help="Manage background services")
    service_parser.add_argument(
        "args", nargs=argparse.REMAINDER, help="Service management arguments"
    )

    registry_parser = subparsers.add_parser(
        "registry", help="Register and manage external service integrations"
    )
    registry_parser.add_argument(
        "args", nargs=argparse.REMAINDER, help="Registry subcommand arguments"
    )

    # `skill` verb (singular) — deprecation shim, forwards to `olav agent`.
    # The full singular-skill dispatcher was deleted in v0.20.3 (P7 cycle 2),
    # but every dev_docs reference and external doc still uses `olav skill
    # install <path>` from the v0.19.x era.  Without a shim, users hit the
    # outer parser's "unknown command" error.  See gitea #11.
    skill_parser = subparsers.add_parser(
        "skill",
        help="DEPRECATED: use `olav agent install` instead.",
    )
    skill_parser.add_argument(
        "args",
        nargs=argparse.REMAINDER,
        help="Forwarded verbatim to `olav agent` after a deprecation warning.",
    )

    # v0.20.0 — new `olav agent install` verb (P5 scaffold; full takeover in P1)
    agent_parser = subparsers.add_parser(
        "agent",
        help="Install and manage OLAV agent packages (git URL, archive, local path)",
    )
    agent_parser.add_argument(
        "args",
        nargs=argparse.REMAINDER,
        help="Agent subcommand and arguments (install / ...)",
    )

    # v0.20.2 P1 — workspace layout migration.  Uses first-class
    # argparse flags (NOT REMAINDER) so top-level argparse doesn't
    # capture `--dry-run` before we see it.
    migrate_parser = subparsers.add_parser(
        "migrate",
        help="Migrate workspace from v0.19.x to v0.20.2+ layout",
    )
    migrate_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would change; do not touch disk",
    )
    migrate_parser.add_argument(
        "--json",
        action="store_true",
        help="(with --dry-run) emit plan as JSON",
    )
    migrate_parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip .olav.bak/ tarball (NOT recommended)",
    )
    migrate_parser.add_argument(
        "--root",
        default=None,
        help="OLAV install root (default: current dir)",
    )

    # Reset command - clear agent conversation/checkpoint history
    reset_parser = subparsers.add_parser("reset", help="Reset agent conversation history")
    reset_parser.add_argument("--agent", "-a", required=True, help="Agent identifier to reset")
    reset_parser.add_argument(
        "--target", default=None, help="Copy initial prompt from this agent (optional)"
    )

    # Skills command - manage agent skills/tools in .olav/workspace/
    skills_parser = subparsers.add_parser("skills", help="Manage agent skills")
    skills_sub = skills_parser.add_subparsers(dest="skills_command", help="Skills action")

    # skills list
    skills_list = skills_sub.add_parser("list", help="List skills for an agent")
    skills_list.add_argument("--agent", "-a", default=None, help="Filter by agent")

    # skills create <name>
    skills_create = skills_sub.add_parser("create", help="Create a new skill template")
    skills_create.add_argument("name", help="Skill name")
    skills_create.add_argument("--agent", "-a", required=True, help="Agent to add skill to")

    # skills info <name>
    skills_info = skills_sub.add_parser("info", help="Show skill details")
    skills_info.add_argument("name", help="Skill name")
    skills_info.add_argument("--agent", "-a", default=None, help="Agent to search in")

    # Log command — query audit.duckdb
    log_parser = subparsers.add_parser("log", help="Query audit log (audit.duckdb)")
    log_sub = log_parser.add_subparsers(dest="log_command", help="Log action")
    log_sub.add_parser("list", help="List recent runs (default, last 24 h)")
    log_show_p = log_sub.add_parser("show", help="Show all events for a run")
    log_show_p.add_argument("run_id", help="Run ID to show")
    log_errors_p = log_sub.add_parser("errors", help="Show error events")
    log_errors_p.add_argument("--hours", type=int, default=24, help="Look-back window in hours")

    # log export sft — export audit data as SFT chat JSONL
    log_export_p = log_sub.add_parser("export", help="Export audit data for training")
    log_export_sub = log_export_p.add_subparsers(dest="export_format", help="Export format")
    # raw — basic AAA export (no olav-ent required)
    log_export_raw_p = log_export_sub.add_parser("raw", help="Export raw audit runs+events as JSONL (no olav-ent required)")
    log_export_raw_p.add_argument("--hours", type=int, default=24, help="Look-back window in hours")
    log_export_raw_p.add_argument("--output", default=None, help="Output directory")
    log_export_sft = log_export_sub.add_parser("sft", help="Export SFT chat JSONL (requires olav-ent)")
    log_export_sft.add_argument("--hours", type=int, default=24, help="Look-back window in hours")
    log_export_sft.add_argument("--output", default=None, help="Output directory")
    log_export_sft.add_argument(
        "--min-score", type=float, default=0.0, help="Minimum rule score threshold (0.0-1.0)"
    )
    log_export_sft.add_argument(
        "--encrypt", action="store_true", default=None, help="Force encryption"
    )
    log_export_sft.add_argument(
        "--no-encrypt", dest="encrypt", action="store_false", help="Force plaintext"
    )
    log_export_sft.add_argument("--key-ref", default=None, help="Keyset reference name")
    log_export_traj = log_export_sub.add_parser(
        "trajectory", help="Export tool-use trajectory JSONL (requires olav-ent)"
    )
    log_export_traj.add_argument("--hours", type=int, default=24, help="Look-back window in hours")
    log_export_traj.add_argument("--output", default=None, help="Output directory")
    log_export_traj.add_argument(
        "--min-score", type=float, default=0.0, help="Minimum rule score threshold (0.0-1.0)"
    )
    log_export_traj.add_argument(
        "--encrypt", action="store_true", default=None, help="Force encryption"
    )
    log_export_traj.add_argument(
        "--no-encrypt", dest="encrypt", action="store_false", help="Force plaintext"
    )
    log_export_traj.add_argument("--key-ref", default=None, help="Keyset reference name")
    log_export_atif = log_export_sub.add_parser("atif", help="Export ATIF trace JSONL")
    log_export_atif.add_argument("--hours", type=int, default=24, help="Look-back window in hours")
    log_export_atif.add_argument("--output", default=None, help="Output directory")
    log_export_atif.add_argument(
        "--min-score", type=float, default=0.0, help="Minimum rule score threshold (0.0-1.0)"
    )
    log_export_atif.add_argument(
        "--encrypt", action="store_true", default=None, help="Force encryption"
    )
    log_export_atif.add_argument(
        "--no-encrypt", dest="encrypt", action="store_false", help="Force plaintext"
    )
    log_export_atif.add_argument("--key-ref", default=None, help="Keyset reference name")
    log_export_grant = log_export_sub.add_parser(
        "grant-local-train", help="Issue one-time token for local training access"
    )
    log_export_grant.add_argument(
        "--export-id", required=True, help="Export ID to bind the token to"
    )
    log_export_grant.add_argument(
        "--ttl-minutes", type=int, default=10, help="Token TTL in minutes (default: 10)"
    )

    # KB (Unified Knowledge Store) command group
    from olav.cli.commands.kb import build_kb_parser
    build_kb_parser(subparsers)

    # Catalog — three-level data model drill-down (ARCH-12)
    from olav.cli.commands.catalog import build_catalog_parser
    build_catalog_parser(subparsers)

    # Explain — resolve an audit-report [src: ...] citation token (ARCH-11 Round 45)
    from olav.cli.commands.explain import build_explain_parser
    build_explain_parser(subparsers)

    # Diff — cross-snapshot diff CLI shortcut (ARCH-13 Round 47)
    from olav.cli.commands.diff import build_diff_parser
    build_diff_parser(subparsers)

    # Default interactive mode flags
    parser.add_argument(
        "--agent",
        "-a",
        default="core",
        help="Agent identifier for separate memory stores (default: core)",
    )
    parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="Auto-approve tool usage without prompting (disables HITL)",
    )
    parser.add_argument(
        "--dangerously-skip-permissions",
        dest="dangerously_skip_permissions",
        action="store_true",
        help="Skip all approval gates — check_approval, sandbox_guard, service_call write gate (for testing only)",
    )
    parser.add_argument(
        "--enable-api-write",
        dest="enable_api_write",
        action="store_true",
        help="Unlock API write operations. Writes still require dry-run + mandatory approval.",
    )
    parser.add_argument(
        "--sandbox",
        choices=["none", "modal", "daytona", "runloop"],
        default="none",
        help="Remote sandbox for code execution (default: none - local only)",
    )
    parser.add_argument(
        "--sandbox-id",
        help="Existing sandbox ID to reuse (skips creation and cleanup)",
    )
    parser.add_argument(
        "--sandbox-setup",
        help="Path to setup script to run in sandbox after creation",
    )
    parser.add_argument(
        "--session",
        help="Session ID for session recovery (stored in ~/.olav/sessions/)",
    )
    parser.add_argument(
        "--no-splash",
        action="store_true",
        help="Disable the startup splash screen",
    )
    parser.add_argument("--version", "-V", action="version", version=f"OLAV v{VERSION}")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose output")
    parser.add_argument("-h", "--help", action="help", help="Show this help message and exit")

    # Single positional argument for query
    parser.add_argument(
        "query",
        nargs="?",
        help="Natural language query (starts interactive mode if omitted)",
    )

    return parser.parse_args()


def check_dependencies() -> None:
    """Check if required dependencies are installed."""
    missing = []

    try:
        import rich
    except ImportError:
        missing.append("rich")

    try:
        import prompt_toolkit
    except ImportError:
        missing.append("prompt-toolkit")

    if missing:
        console.print("\n[bold red]Missing required dependencies![/bold red]")
        console.print("\nThe following packages are required:")
        for pkg in missing:
            console.print(f"  - {pkg}")
        console.print("\nInstall with: [bold]uv sync[/bold]")
        sys.exit(1)


def _resolve_agent_id(agent_id: str, workspace: str | None) -> str:
    """Resolve effective agent_id for OLAVAgent given an optional workspace name.

    Strategy (flat→nested, §11.6):
    1. If workspace is None: return agent_id as-is (flat compat)
    2. If flat .olav/workspace/<agent_id>/ exists: return agent_id (backward compat)
    3. Otherwise: return "<workspace>/<agent_id>" for nested structure
    """
    from olav.core.workspace import resolve_workspace_path

    resolved = resolve_workspace_path(agent_id, workspace=workspace)
    workspace_root = (Path(".olav") / "workspace").resolve()
    try:
        return str(resolved.relative_to(workspace_root))
    except ValueError:
        return agent_id


def create_olav_agent_with_backend(
    assistant_id: str,
    session_id: str | None = None,
    sandbox=None,
    sandbox_type: str | None = None,
    workspace: str | None = None,
):
    """Create OLAV agent with CompositeBackend.

    This integrates OLAV's domain-specific agent with deepagents infrastructure.

    Args:
        assistant_id: Agent identifier for memory storage
        session_id: Optional session ID for recovery
        sandbox: Optional sandbox backend for remote execution
        sandbox_type: Type of sandbox ("modal", "runloop", "daytona")

    Returns:
        Tuple of (agent graph, composite backend)
    """
    from deepagents.backends import CompositeBackend
    from deepagents.backends.filesystem import FilesystemBackend

    from olav.agents.agent import OLAVAgent

    # Resolve agent_id through workspace routing (§4, §11.6)
    effective_id = _resolve_agent_id(assistant_id, workspace)

    # Create OLAV agent (which uses create_deep_agent internally)
    olav_agent = OLAVAgent(
        agent_id=effective_id,
        session_id=session_id,
        enable_checkpointer=True,
    )

    # Create backend
    if sandbox is None:
        # Local mode — use LocalShellBackend directly (NOT wrapped in CompositeBackend).
        # CompositeBackend does not inherit SandboxBackendProtocol, so wrapping it
        # would prevent deepagents from injecting the `execute` shell tool.
        # LocalShellBackend inherits SandboxBackendProtocol → agent gets `execute`.
        from olav.agents._deepagents_bridge import HAS_LOCAL_SHELL_BACKEND, LocalShellBackend

        if HAS_LOCAL_SHELL_BACKEND and LocalShellBackend is not None:
            composite_backend = LocalShellBackend(root_dir=str(Path.cwd()), inherit_env=True)
        else:
            composite_backend = CompositeBackend(
                default=FilesystemBackend(),
                routes={},
            )
    else:
        # Remote sandbox mode
        composite_backend = CompositeBackend(
            default=sandbox,
            routes={},
        )

    # Bake plugin callbacks into the graph so they fire even when callers
    # (e.g. deepagents_cli.execute_task) build their own config without callbacks.
    graph = olav_agent.graph
    cbs = olav_agent.plugin_registry.get_callback_plugins()
    if cbs:
        graph = graph.with_config({"callbacks": cbs})  # type: ignore[assignment]
    # Attach plugin_registry to the graph so CLI/API code can access it for
    # binding the top-level run context to callback plugins (e.g. audit).
    graph.plugin_registry = olav_agent.plugin_registry  # type: ignore[attr-defined]
    return graph, composite_backend


@contextlib.contextmanager
def _hitl_audit_scope(recorder: AuditEventRecorder, run_id: str, agent_id: str):
    """Context manager that patches *prompt_for_tool_approval* to emit HITL
    audit events (``hitl_requested`` / ``hitl_decision``) for every interrupt.

    The patch is thread-local to this invocation: the original function is
    restored in the ``finally`` block even if an exception occurs.
    """
    try:
        import deepagents_cli.execution as _dce  # type: ignore[import]

        _original = _dce.prompt_for_tool_approval
    except Exception as _e:
        logger.debug("_hitl_audit_scope: deepagents_cli not available (%s) — HITL events disabled", _e)
        yield
        return

    def _audited(action_request, assistant_id_arg):
        interrupt_id = str(_uuid_mod.uuid4())
        recorder.record_hitl_requested(
            run_id=run_id,
            interrupt_id=interrupt_id,
            action_requests=[action_request]
            if not isinstance(action_request, list)
            else action_request,
            agent_id=agent_id,
        )
        decision = _original(action_request, assistant_id_arg)
        decision_type = (
            decision.get("type")
            if isinstance(decision, dict)
            else getattr(decision, "type", str(decision))
        )
        recorder.record_hitl_decision(
            run_id=run_id,
            interrupt_id=interrupt_id,
            decision=str(decision_type),
            agent_id=agent_id,
        )
        return decision

    _dce.prompt_for_tool_approval = _audited
    try:
        yield
    finally:
        _dce.prompt_for_tool_approval = _original


async def simple_cli(
    agent,
    assistant_id: str,
    session_state,
    backend,
    sandbox_type: str | None = None,
    no_splash: bool = False,
) -> None:
    """Main CLI loop using deepagents-cli Textual TUI with OLAV overlay."""
    try:
        from deepagents_cli.app import run_textual_app
    except ImportError as _e:
        console.print(
            f"[red]Error:[/red] Interactive TUI requires deepagents-cli: {_e}\n"
            "Use single-query mode: [cyan]olav \"your question\"[/cyan]"
        )
        return

    # Apply OLAV branding (banner, title) and /workspace command BEFORE the
    # Textual app is constructed.  Version-guarded — a mismatch falls back to
    # vanilla deepagents-cli so the TUI still works.
    from olav.cli.tui_overlay import apply_olav_overlay

    apply_olav_overlay()

    # Banner is owned by the overlay's WelcomeBanner replacement; the legacy
    # pre-TUI ANSI splash would just flash and be wiped by Textual's alternate
    # screen anyway.  Keep it as an opt-in for users who pass --no-splash=false
    # and have the old muscle memory.
    _ = no_splash  # retained for API compatibility

    # P6 dispatch: native mode spawns a langgraph subprocess (deepagents-cli
    # owns the lifecycle; our scaffold patch redirects it at OLAV's graph
    # factory).  Overlay mode keeps the v0.19.x in-process path.  Auto-detect
    # picks native when the new workspace layout is in play or no workspace
    # exists yet; legacy layout stays on overlay for compatibility.
    from olav.cli.tui_overlay import resolve_tui_mode

    mode = resolve_tui_mode()
    mode_explicit = bool((os.environ.get("OLAV_TUI_MODE") or "").strip())

    if mode == "native":
        try:
            await run_textual_app(
                assistant_id=assistant_id,
                auto_approve=getattr(session_state, "auto_approve", False),
                server_kwargs={
                    "assistant_id": assistant_id,
                    "auto_approve": getattr(session_state, "auto_approve", False),
                    "no_mcp": True,
                    "interactive": True,
                },
            )
            return
        except Exception as exc:  # noqa: BLE001
            if mode_explicit:
                # User explicitly asked for native; don't silently fall back —
                # that would hide a real configuration problem.
                logger.error("native TUI failed (%s)", exc, exc_info=True)
                raise
            logger.warning(
                "native TUI launch failed (%s); falling back to overlay mode. "
                "Set OLAV_TUI_MODE=overlay to silence this warning.",
                exc,
            )
            # Fall through to overlay path

    # Overlay mode — v0.19.x in-process path.
    _graph = agent.graph if hasattr(agent, "graph") else agent
    await run_textual_app(
        agent=_graph,
        assistant_id=assistant_id,
        backend=backend,
        auto_approve=getattr(session_state, "auto_approve", False),
    )
    return



# ---------------------------------------------------------------------------
# Auth helpers (P1: inline login gate + single-query silent auth)
# ---------------------------------------------------------------------------


def _get_auth_mode() -> str:
    """Read auth.mode from ConfigLoader (api.json). Default: 'none'."""
    try:
        from olav.core.config import ConfigLoader

        return ConfigLoader().auth.mode
    except Exception:
        return "none"


async def _inline_login_gate() -> UserIdentity | None:
    """Inline login gate for interactive mode when auth.mode != 'none'.

    Tries three auth paths, in order:

    1. Silent — resolve the token via
       :func:`olav.core.auth.keyring_store.load_token` (``OLAV_TOKEN``
       env → OS keyring → legacy ``~/.olav/token``).  A hit means the
       TUI launches without any prompt, matching single-query mode's
       UX — no more paste-the-token-every-time-you-open-the-TUI friction.
    2. Prompted — prompt_toolkit masked input, 3 attempts.
    3. ``getpass`` fallback when prompt_toolkit isn't importable.

    Returns:
        UserIdentity on success, ``None`` when the user aborts (Ctrl-C)
        or exhausts the attempt budget.  ``None`` immediately for
        ``mode == "none"`` (OS identity).
    """
    from olav.core.auth import UserIdentity, get_auth_provider

    mode = _get_auth_mode()
    if mode == "none":
        return get_auth_provider("none").authenticate()

    # 1. Silent-first — reuse the single-query resolver so the keyring,
    # per-env file, legacy file, and OLAV_TOKEN paths all apply to the TUI.
    silent = _silent_auth()
    if silent is not None and silent.source == "token":
        console.print(
            f"  [green]✓ Authenticated as [bold]{silent.username}[/bold] "
            f"[{silent.role}] (stored token)[/green]"
        )
        return silent

    try:
        from prompt_toolkit import prompt as pt_prompt
        from prompt_toolkit.formatted_text import ANSI
    except ImportError:
        # Fallback without prompt_toolkit masking
        import getpass

        token = getpass.getpass("Token: ")
        return get_auth_provider(mode).authenticate(token=token, source_channel="cli_interactive")

    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            token = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: pt_prompt("Token: ", is_password=True),
            )
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Login cancelled.[/yellow]")
            return None
        token = token.strip()
        if not token:
            continue
        identity = get_auth_provider(mode).authenticate(
            token=token, source_channel="cli_interactive"
        )
        if identity.source == "token":
            # Persist to the OS keyring so the next TUI launch takes the
            # silent path.  Failures here are non-fatal — the token file
            # fallback or another prompt on next launch are both fine.
            try:
                from olav.core.auth.keyring_store import save_token

                where = save_token(token)
                storage_hint = (
                    " · saved to keyring"
                    if where == "keyring"
                    else " · saved to ~/.olav/token"
                )
            except Exception:  # noqa: BLE001
                storage_hint = ""
            console.print(
                f"  [green]✓ Authenticated as [bold]{identity.username}[/bold] "
                f"[{identity.role}][/green][dim]{storage_hint}[/dim]"
            )
            return identity
        console.print(f"  [red]✗ Authentication failed (attempt {attempt}/{max_attempts})[/red]")
    console.print("[red]Too many failed attempts. Exiting.[/red]")
    return None


def _silent_auth() -> UserIdentity | None:
    """Silent token auth for single-query mode (D6) and for the TUI's
    silent-first path.

    Resolves the bearer token via
    :func:`olav.core.auth.keyring_store.load_token` — which honours
    ``OLAV_TOKEN`` env → OS keyring → legacy ``~/.olav/token`` — and
    validates it against the current workspace's ``users.duckdb``.

    Returns ``None`` when no valid token is available so the caller can
    choose between an interactive prompt (TUI) and a hard error
    (single-query mode).
    """
    mode = _get_auth_mode()
    if mode == "none":
        from olav.core.auth import get_auth_provider

        return get_auth_provider("none").authenticate()

    from olav.core.auth.keyring_store import load_token

    token = load_token()
    if not token:
        return None  # caller prints error

    from olav.core.auth import get_auth_provider

    identity = get_auth_provider(mode).authenticate(token=token, source_channel="cli_token")
    if identity.source == "token":
        return identity
    return None  # invalid token


async def run_interactive(
    assistant_id: str,
    session_state,
    sandbox_type: str = "none",
    session_id: str | None = None,
    workspace: str | None = None,
) -> None:
    """Run interactive mode.

    Wraps :func:`simple_cli` in a swap-aware loop: when the in-TUI
    ``/workspace <name>`` command fires, the overlay stores the target
    in ``tui_overlay._PENDING_WORKSPACE`` and exits the Textual app.
    We read that flag here, rebuild the agent+backend for the new
    workspace, and re-enter — giving the user a one-shot restart.
    """
    from olav.cli.tui_overlay import consume_pending_workspace

    # P1: inline login gate (skipped in mode=none).  Run once; token survives
    # across swaps.
    if _get_auth_mode() != "none":
        identity = await _inline_login_gate()
        if identity is None:
            return  # aborted or too many failures

    current_id = assistant_id
    while True:
        agent, backend = create_olav_agent_with_backend(
            current_id, session_id=session_id, workspace=workspace
        )
        await simple_cli(
            agent,
            current_id,
            session_state,
            backend,
            sandbox_type=sandbox_type if sandbox_type != "none" else None,
            no_splash=session_state.no_splash,
        )

        pending = consume_pending_workspace()
        if not pending:
            return
        current_id = pending
        # A workspace swap starts a fresh agent — detach the previous
        # session_id so the new agent doesn't inherit the wrong thread.
        session_id = None


async def run_single_query(
    query: str,
    assistant_id: str,
    session_id: str | None = None,
    workspace: str | None = None,
) -> None:
    """Run a single query and exit."""
    import uuid

    # Intercept slash commands before sending to LLM — workspace MANIFEST.yaml
    # slash_commands (kind=shell) run scripts directly without LLM overhead.
    if query.strip().startswith("/"):
        from olav.cli.commands.builtin import execute_command

        _slash_result = await execute_command(query.strip(), auto_approve=True)
        if _slash_result is not None and not (
            isinstance(_slash_result, str) and _slash_result.startswith("Unknown command:")
        ):
            if _slash_result:
                console.print(_slash_result)
            return

    # Apply input_parser: expand @file references and handle !cmd shell commands
    try:
        from olav.cli.input_parser import parse_input as _parse_input
        import subprocess as _subprocess
        query, _is_shell_cmd, _shell_cmd = _parse_input(query)
        if _is_shell_cmd and _shell_cmd:
            _proc = _subprocess.run(_shell_cmd, shell=True, capture_output=True, text=True)
            if _proc.stdout:
                console.print(_proc.stdout, end="")
            if _proc.stderr:
                console.print(_proc.stderr, end="", style="red")
            return
    except Exception:
        pass

    # deepagents-cli is used for TUI mode; single-query uses langgraph native API

    # P1: silent auth check (D6) — no interactive prompt in single-query mode
    if _get_auth_mode() != "none":
        identity = _silent_auth()
        if identity is None:
            print(
                "Not authenticated. Run `olav` to log in or set OLAV_TOKEN env var.",
                file=sys.stderr,
            )
            sys.exit(1)
        user_id = identity.username
    else:
        user_id = os.environ.get("USER", "anonymous")

    # Top-level agent selection is explicit (--agent ops/audit).
    # Core is always the default. Semantic routing is used WITHIN an agent
    # to select subagents, not to switch between top-level agents.
    # If core can't handle the query, it should suggest "--agent ops" in its response.

    # ── Semantic cache: check for cached answer ──
    try:
        from olav.core.memory import SemanticCache, get_store
        from olav.core.embedder import embed_text as _embed
        _cstore = get_store()
        if _cstore:
            try:
                from olav.core.config import ConfigLoader
                _mcfg = ConfigLoader().memory
                _sc = SemanticCache(
                    _cstore,
                    threshold=_mcfg.cache_similarity_threshold,
                    ttl_hours=_mcfg.cache_ttl_hours,
                    max_entries=_mcfg.cache_max_entries,
                )
            except Exception:
                _sc = SemanticCache(_cstore)
            _qv = _embed(query)
            if _qv:
                _hit = _sc.get(_qv)
                if _hit and isinstance(_hit, list) and _hit:
                    _answer = _hit[0].get("answer", "")
                    if _answer:
                        console.print(_answer)
                        return
    except Exception:
        pass

    agent, backend = create_olav_agent_with_backend(
        assistant_id, session_id=session_id, workspace=workspace
    )

    run_id = str(uuid.uuid4())
    recorder = AuditEventRecorder()
    global _active_audit, _active_run_id
    _active_audit, _active_run_id = recorder, run_id
    recorder.record_run_start(
        run_id=run_id,
        agent_id=assistant_id,
        user_id=user_id,
        source_channel="cli",
    )
    recorder.record(
        event_type="user_input_received",
        run_id=run_id,
        agent_id=assistant_id,
        payload={"content": query},
    )
    # Record the user turn in audit_messages for dataset export
    recorder.record_message(run_id=run_id, role="user", content=query)

    # Bind the top-level run context to AuditCallbackPlugin
    from olav.plugins.callbacks.audit import AuditCallbackPlugin as _AuditCBPlugin
    _audit_cbs = [
        _cb for _cb in (
            agent.plugin_registry.get_callback_plugins()
            if hasattr(agent, "plugin_registry") else []
        )
        if isinstance(_cb, _AuditCBPlugin)
    ]
    for _cb in _audit_cbs:
        _cb.bind_run(run_id, recorder)

    # Routing audit: record which agent handles this query (informational only)
    recorder.record(
        event_type="routing_decision",
        run_id=run_id,
        payload={"agent": assistant_id, "method": "explicit"},
    )

    try:
        # Stream agent execution using native langgraph API
        # recursion_limit: deepagents stacks 5+ middleware (AutoRecall +
        # Skills + SubAgent + Filesystem + Summarization + TodoList) each
        # of which is its own graph node, so a single agent turn that
        # makes 1 tool call can consume 6-8 recursion units.  75 was the
        # langgraph default and proved tight for layered diagnostic flows
        # that exceed ~10 tool calls.  Default raised to 200; override
        # with ``OLAV_RECURSION_LIMIT`` env for unusually deep tasks
        # (e.g. multi-stage TCF lab validation).
        _rec_limit = int(os.environ.get("OLAV_RECURSION_LIMIT", "200"))
        config = {"configurable": {"thread_id": session_id or run_id}, "recursion_limit": _rec_limit}
        input_msg = {"messages": [{"role": "human", "content": query}]}
        _chunks: list[str] = []
        _tool_results: list[dict] = []  # capture tool outputs for post-processing
        _pending_tool_args: dict[str, tuple] = {}  # run_id → (tool_name, args), drained by on_tool_end

        _graph = agent.graph if hasattr(agent, "graph") else agent
        # WRITER-01 (a) Round 39: tag 🔧 output with origin — "orch" for tools
        # the top-level orchestrator invokes, "sub" for tools the subagent
        # invokes after an olav_delegate / task call. Tier2 CI can filter
        # by orch-only to tighten the T2-14 threshold away from the current
        # loose ≤8 (which had to account for delegate-internal bloat).
        _DELEGATE_TOOLS = {"olav_delegate", "task"}
        _delegate_depth = 0

        async for event in _graph.astream_events(input_msg, config=config, version="v2"):
            kind = event.get("event", "")
            data = event.get("data", {})

            if kind == "on_chat_model_stream":
                chunk = data.get("chunk")
                if chunk:
                    text = getattr(chunk, "content", "")
                    if text:
                        console.print(text, end="")
                        _chunks.append(text)

            elif kind == "on_chat_model_end":
                # Non-streaming mode: full response arrives here
                output = data.get("output")
                if output:
                    text = getattr(output, "content", "")
                    if text and not _chunks:  # only if not already streamed
                        console.print(text)
                        _chunks.append(text)

            elif kind == "on_tool_start":
                tool_name = event.get("name", "")
                tool_input = data.get("input", {})
                _input_preview = str(tool_input)[:60]
                _origin = "sub" if _delegate_depth > 0 else "orch"
                console.print(f"  🔧[{_origin}] {tool_name}({_input_preview}...)")
                if tool_name in _DELEGATE_TOOLS:
                    _delegate_depth += 1
                # Pair (args → result) for memory capture: stash by run_id from
                # event so concurrent calls don't clobber each other.
                _run_id = event.get("run_id") or event.get("id") or ""
                _pending_tool_args[_run_id] = (tool_name, tool_input)

            elif kind == "on_tool_end":
                tool_name = event.get("name", "")
                output = data.get("output", "")
                if tool_name in _DELEGATE_TOOLS and _delegate_depth > 0:
                    _delegate_depth -= 1
                _run_id = event.get("run_id") or event.get("id") or ""
                _, _args = _pending_tool_args.pop(_run_id, (tool_name, {}))
                _tool_results.append({
                    "name": tool_name,
                    "args": _args,
                    "content": str(output)[:4096],
                })

        final_content = "".join(_chunks)

        # NL-CLI-TERMINAL-TOOL (2026-05-12): if any tool returned a
        # "Report saved: <path>" payload (render_report and friends —
        # tools marked return_direct=True so the orchestrator exits
        # without a "format the response" LLM turn), surface that line
        # at the end. Without this the user sees streamed per-section
        # content from render_report's internal LLM calls but loses the
        # report path + executive summary the tool returned.
        _terminal_tool_lines: list[str] = []
        for tr in _tool_results:
            content = tr.get("content") or ""
            # Tool result strings carry payloads in two shapes:
            #   (a) raw return string from a `@tool`-decorated function
            #   (b) `str(ToolMessage(content='...', name='...', ...))` —
            #       newlines inside the content appear as the literal
            #       two-char sequence `\n` (backslash-n).
            # Normalise (b) → (a) so a single regex covers both.
            if content.startswith("content='") or "ToolMessage(content='" in content:
                _inner = re.search(r"content='(.*?)'\s+name=", content, re.DOTALL)
                if _inner:
                    payload = _inner.group(1).replace("\\n", "\n")
                else:
                    payload = content
            else:
                payload = content
            # Path: stop at whitespace/newline — never crosses lines.
            m = re.search(r"Report saved:\s+([^\s]+)", payload)
            if not m:
                continue
            _path_line = f"Report saved: {m.group(1)}"
            if _path_line in final_content:
                continue  # already in stream
            # ISSUE-AUDIT-FRESHNESS-GATE-MISSING (P1, 2026-05-12): if a
            # deterministic warning banner (`> 🔴 **...**: ...`) is in
            # the payload, surface it FIRST so the qualifier is seen
            # before the path / summary.
            _banner_m = re.search(
                r"^(>\s+(?:🔴|⚠️)\s*\*\*[^*]+\*\*[^\n]*)",
                payload, re.MULTILINE,
            )
            if _banner_m and _banner_m.group(1) not in final_content:
                _terminal_tool_lines.append("\n" + _banner_m.group(1))
            _terminal_tool_lines.append(f"\n📄 {_path_line}")
            # Executive summary: between heading and next heading / EOF.
            _exec_m = re.search(
                r"##\s*Executive\s+Summary\s*\n+(.*?)(?=\n##|\Z)",
                payload, re.DOTALL | re.IGNORECASE,
            )
            if _exec_m and "## Executive Summary" not in final_content:
                _terminal_tool_lines.append(
                    "\n## Executive Summary\n" + _exec_m.group(1).rstrip()
                )
            break  # surface only the first terminal tool result
        if _terminal_tool_lines:
            for line in _terminal_tool_lines:
                console.print(line)
            final_content = final_content + "\n" + "\n".join(_terminal_tool_lines)

        # NL-CLI-SILENT-FINAL (R82): some models (small ones especially)
        # finish a run with only tool calls — they consider the work
        # "delegated and done" and emit no final assistant text.  The
        # user then sees only `🔧` indicators with no result.  Surface
        # the most recent informative tool result(s) as a fallback so
        # the CLI never goes silent after running tools.
        if not final_content and _tool_results:
            _SILENT_DELEGATE = {"olav_delegate", "task"}
            _PATH_KEYS = ("path", "absolute_path", "saved_to", "file")
            _fallback_lines: list[str] = []
            for tr in _tool_results:
                name = tr["name"]
                if name in _SILENT_DELEGATE:
                    continue  # the inner subagent's tools are what produced output
                content = tr["content"]
                # Try to extract a file path / saved-to indicator from the
                # tool's structured output (format_and_export, render_report,
                # take_snapshot all return path-bearing dicts).
                preview = content
                for key in _PATH_KEYS:
                    m = re.search(rf"['\"]?{key}['\"]?\s*[:=]\s*['\"]([^'\"]+)['\"]", content)
                    if m:
                        preview = f"{key}: {m.group(1)}"
                        break
                _fallback_lines.append(f"📁 {name} → {preview[:200]}")
            if _fallback_lines:
                console.print("")
                for line in _fallback_lines:
                    console.print(line)
                final_content = "\n".join(_fallback_lines)

        recorder.record(
            event_type="assistant_output_final",
            run_id=run_id,
            agent_id=assistant_id,
            payload={"content": final_content},
        )
        # Record assistant response in audit_messages for dataset export
        if final_content:
            recorder.record_message(run_id=run_id, role="assistant", content=final_content)
        recorder.record_run_end(run_id=run_id, status="completed")

        # ── OLAV middleware hooks (workaround: deepagents doesn't mount them) ──
        if hasattr(agent, "_olav_middleware"):
            # Build a synthetic message log middleware can scan.  Tool
            # messages carry both ``args`` (request payload — e.g. the
            # SQL string for ``execute_sql``) and ``content`` (response
            # payload — e.g. the row JSON).  Plugins like
            # query_pattern_capture pair them by sequence to learn
            # successful (intent → SQL) tuples.
            _state = {
                "messages": [
                    {"role": "human", "content": query},
                ] + [
                    {
                        "role": "tool",
                        "name": tr["name"],
                        "args": tr.get("args", {}),
                        "content": tr["content"],
                    }
                    for tr in _tool_results
                ] + [
                    {"role": "assistant", "content": final_content},
                ]
            }
            for _mw in agent._olav_middleware:
                try:
                    _hook = getattr(_mw, "aafter_agent", None)
                    if _hook:
                        result = await _hook(_state, None)
                        # OutputFormatterPlugin may append supplements
                        if result and "_output_supplements" in result:
                            for s in result["_output_supplements"]:
                                console.print(s)
                except Exception as _mw_err:
                    logging.debug("Middleware hook %s failed: %s", type(_mw).__name__, _mw_err)

        # ── Semantic cache: store result for future queries ──
        # execute_task prints to console, returns None. Read the assistant
        # message from audit DB (written by AuditCallbackPlugin during run).
        _cached_content = final_content
        if not _cached_content:
            try:
                import duckdb
                from olav.core.config import AUDIT_DB_PATH
                with duckdb.connect(str(AUDIT_DB_PATH), read_only=True) as _adb:
                    _row = _adb.execute(
                        "SELECT content FROM audit_messages WHERE run_id=? AND role='assistant' ORDER BY id DESC LIMIT 1",
                        [run_id],
                    ).fetchone()
                    if _row and _row[0]:
                        _cached_content = _row[0]
            except Exception:
                pass
        if _cached_content:
            # 2026-05-10 INVIVO-T15-NON-DETERMINISTIC root cause:
            # gemma4 nothink occasionally produces an empty response
            # (just "[]" — no content, no tool result fallback). If
            # that empty answer gets cached, every subsequent identical
            # prompt returns the cached "[]" in ~10s instead of running
            # the model — turning a 1/3 flaky failure into a 100%
            # deterministic failure. Filter junk responses before cache
            # write: empty, just punctuation, or shorter than ~30
            # chars without any letters.
            _stripped = _cached_content.strip()
            _has_real = (
                len(_stripped) >= 30
                and any(c.isalnum() for c in _stripped)
                and _stripped not in ("[]", "{}", "()", "null", "None")
            )
            if not _has_real:
                logging.debug(
                    "Semantic cache: skip put — content looks empty/junk: %r",
                    _stripped[:60],
                )
            else:
                try:
                    from olav.core.memory import SemanticCache, get_store
                    from olav.core.embedder import embed_text as _embed
                    _cstore = get_store()
                    if _cstore:
                        _sc = SemanticCache(_cstore)
                        _qv = _embed(query)
                        if _qv:
                            _sc.put(_qv, [{"query": query, "answer": _cached_content[:2000]}])
                except Exception:
                    pass
    except KeyboardInterrupt:
        recorder.record(
            event_type="run_cancelled",
            run_id=run_id,
            agent_id=assistant_id,
            payload={"reason": "KeyboardInterrupt"},
        )
        recorder.record_run_end(run_id=run_id, status="cancelled")
        raise
    except Exception:
        recorder.record(
            event_type="run_error",
            run_id=run_id,
            agent_id=assistant_id,
            payload={},
        )
        recorder.record_run_end(run_id=run_id, status="error")
        raise
    finally:
        for _cb in _audit_cbs:
            _cb.unbind_run()
        recorder.close()
        _active_audit = None
        _active_run_id = None


def cli_main_async() -> None:
    """Main entry point for console script (async wrapper)."""
    # Suppress LangChain Pydantic V1 deprecation warning on Python 3.14+.
    # LangChain internally uses pydantic.v1 compatibility shim; the warning is
    # cosmetic — it does not affect runtime behaviour on Python 3.11–3.14.
    warnings.filterwarnings(
        "ignore",
        message="Core Pydantic V1 functionality",
        category=UserWarning,
    )
    # Suppress noisy HuggingFace / transformers / sentence-transformers warnings
    warnings.filterwarnings("ignore", category=FutureWarning, module="transformers")
    warnings.filterwarnings("ignore", category=FutureWarning, module="olav.core.memory")
    warnings.filterwarnings("ignore", message=".*get_sentence_embedding_dimension.*")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("SAFETENSORS_FAST_GPU", "0")
    os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
    # Suppress BertModel LOAD REPORT, HF Hub auth, and safetensors shard reports
    for _noisy_logger in ("sentence_transformers", "transformers", "transformers.modeling_utils",
                          "huggingface_hub", "huggingface_hub.utils", "safetensors"):
        logging.getLogger(_noisy_logger).setLevel(logging.ERROR)
    # Suppress HF Hub "unauthenticated requests" stderr warning
    warnings.filterwarnings("ignore", message=".*unauthenticated.*HF Hub.*")
    warnings.filterwarnings("ignore", message=".*Sending unauthenticated.*")

    # Fix for gRPC fork issue on macOS
    if sys.platform == "darwin":
        os.environ["GRPC_ENABLE_FORK_SUPPORT"] = "0"

    check_dependencies()
    asyncio.run(cli_main_impl())


async def cli_main_impl() -> None:
    """Async implementation of cli_main."""
    try:
        args = parse_args()

        if args.verbose:
            logging.basicConfig(level=logging.DEBUG)

        # Handle version command
        if args.command == "version":
            import platform

            # Use the formatted banner from version module
            console.print(format_version_banner())

            # System information
            try:
                console.print("[bold dim]System Information:[/bold dim]")
                console.print(f"  Python: {platform.python_version()}")
                console.print(f"  Platform: {platform.system()} {platform.release()}")
                console.print(f"  Machine: {platform.machine()}")
            except Exception:
                pass

            # Installation path
            try:
                olav_module = Path(__file__).parent.parent
                console.print(f"  Installation: {olav_module}")
            except Exception:
                pass

            console.print()
            return

        # Handle list command
        if args.command == "list":
            import yaml
            from olav.core.workspace import resolve_workspace_root

            workspace_root = resolve_workspace_root()
            console.print("\n[bold]Available Agents:[/bold]\n")
            found = []
            if workspace_root.exists():
                for agent_md in sorted(workspace_root.glob("*/AGENT.md")):
                    agent_dir = agent_md.parent
                    try:
                        raw = agent_md.read_text()
                        if raw.startswith("---"):
                            parts = raw.split("---", 2)
                            meta = yaml.safe_load(parts[1]) if len(parts) >= 2 else {}
                        else:
                            meta = {}
                        name = meta.get("name") or agent_dir.name
                        desc = " ".join(str(meta.get("description", "")).split())
                        found.append((agent_dir.name, name, desc))
                    except Exception:
                        found.append((agent_dir.name, agent_dir.name, ""))
            if found:
                for flag, _name, desc in found:
                    default_tag = " [dim](default)[/dim]" if flag == "olav" else ""
                    console.print(f"  • [bold]{flag}[/bold]{default_tag}")
                    if desc:
                        console.print(f"    [dim]{desc}[/dim]")
                    console.print(f"    Location: .olav/workspace/{flag}/")
                    console.print()
            else:
                console.print("  [yellow]No agents found in .olav/workspace/[/yellow]\n")
            return

        # Handle help command
        if args.command == "help":
            console.print()
            console.print(f"[bold cyan]OLAV v{VERSION} - AI Operations Assistant[/bold cyan]\n")
            console.print("[bold]Usage:[/bold]")
            console.print("  [cyan]olav[/cyan]                                    Interactive mode")
            console.print(
                '  [cyan]olav[/cyan] [green]"query"[/green]                           Single query'
            )
            console.print(
                '  [cyan]olav[/cyan] [yellow]--agent ops[/yellow] [green]"Check network"[/green]      Multi-agent'
            )
            console.print(
                '  [cyan]olav[/cyan] [yellow]--sandbox modal[/yellow] [green]"Deploy config"[/green]  Remote execution'
            )
            console.print()
            console.print("[bold]Commands:[/bold]")
            console.print("  [cyan]version[/cyan]              Show version and system information")
            console.print("  [cyan]list[/cyan]                 List all available agents")
            console.print("  [cyan]help[/cyan]                 Show this help message")
            console.print(
                "  [cyan]reset[/cyan] --agent ID     Reset agent conversation/session history"
            )
            console.print(
                "  [cyan]skills[/cyan] list          List all skills          (alias: [dim]skills[/dim])"
            )
            console.print(
                "  [cyan]skills[/cyan] create NAME   Create new skill template  --agent required"
            )
            console.print("  [cyan]skills[/cyan] info NAME     Show skill details")
            console.print(
                "  [cyan]admin[/cyan]               Admin commands (status, backup, etc.)"
            )
            console.print("  [cyan]config[/cyan]              Configuration management")
            console.print("  [cyan]init[/cyan]                Initialize platform scaffolding")
            console.print(
                "  [cyan]workspace[/cyan]           Manage workspace lifecycle (status/diff/upgrade/disable/remove/prune/rollback)"
            )
            console.print(
                "  [cyan]workspace[/cyan]           Manage workspace lifecycle (status/diff/upgrade/disable/remove/prune/rollback)"
            )
            console.print(
                "  [cyan]export[/cyan]              Export Claude skills or plugin layout"
            )
            console.print(
                "  [cyan]service[/cyan]             Manage background services (daemon, logs, web)"
            )
            console.print()
            console.print("[bold]Interactive Slash Commands:[/bold]")
            console.print("  [cyan]/help[/cyan]                Show interactive commands")
            console.print("  [cyan]/clear[/cyan]               Reset conversation and clear screen")
            console.print("  [cyan]/tokens[/cyan]              Show token usage statistics")
            console.print(
                "  [cyan]/trace-review[/cyan]        Analyze agent failures → learn constraints"
            )
            console.print(
                "  [cyan]/quit[/cyan]  [cyan]/exit[/cyan]  [cyan]/q[/cyan]   Exit the CLI"
            )
            console.print()
            console.print("[bold]Special Input Prefixes:[/bold]")
            console.print(
                "  [cyan]!<cmd>[/cyan]               Run a bash command (e.g., [dim]!ls -la[/dim], [dim]!git status[/dim])"
            )
            console.print(
                "  [cyan]@<file>[/cyan]              Inject file contents into the prompt"
            )
            console.print()
            console.print("[bold]Global Options:[/bold]")
            console.print(
                "  [yellow]-a, --agent[/yellow] AGENT       Set active agent (core, ops, audit, config)"
            )
            console.print(
                "  [yellow]--sandbox[/yellow] TYPE          Remote sandbox (none, modal, daytona, runloop)"
            )
            console.print("  [yellow]--sandbox-id[/yellow] ID         Reuse existing sandbox ID")
            console.print(
                "  [yellow]--auto-approve[/yellow]          Auto-approve tool usage without prompting"
            )
            console.print(
                "  [yellow]--session[/yellow] ID            Session ID for recovery (in ~/.olav/sessions/)"
            )
            console.print("  [yellow]--no-splash[/yellow]            Disable startup banner")
            console.print("  [yellow]-v, --verbose[/yellow]         Enable verbose/debug output")
            console.print("  [yellow]-V, --version[/yellow]         Show version information")
            console.print("  [yellow]-h, --help[/yellow]            Show this help message")
            console.print()
            console.print("[bold]Examples:[/bold]")
            console.print("  [dim]# Start interactive mode[/dim]")
            console.print("  [cyan]$ olav[/cyan]")
            console.print()
            console.print("  [dim]# Ask a quick question[/dim]")
            console.print('  [cyan]$ olav "How many records are in the database?"[/cyan]')
            console.print()
            console.print("  [dim]# Use a specific agent for deep analysis[/dim]")
            console.print('  [cyan]$ olav --agent ops "Analyze recent audit logs"[/cyan]')
            console.print()
            console.print("  [dim]# Run in a remote sandbox[/dim]")
            console.print('  [cyan]$ olav --sandbox modal "Deploy configuration"[/cyan]')
            console.print()
            console.print("[bold]Documentation:[/bold]")
            console.print("  README:           ./README.md")
            console.print("  User Guide:       ./docs/")
            console.print("  Configuration:    ~/.olav/config/")
            console.print()
            return

        # Handle admin command
        if args.command == "admin":
            cmd_args = " ".join(args.args) if args.args else "status"

            # User management sub-commands → AdminUsersCommand
            _user_mgmt_cmds = {"add-user", "list-users", "revoke-token", "rotate-token"}
            _first_token = cmd_args.split()[0] if cmd_args.strip() else ""
            if _first_token in _user_mgmt_cmds:
                from olav.cli.commands.admin_users import AdminUsersCommand

                _admin_users = AdminUsersCommand()
                _result_str = await _admin_users.execute(cmd_args)
                console.print(_result_str)
                if _result_str.startswith("error:"):
                    raise SystemExit(1)
                return

            # LEGACY-KEEP: admin_handler is the pre-v0.15 system admin entry
            # retained for /admin … subcommands not yet migrated to refresh/skill.
            from olav.cli.admin import admin_handler

            result = await admin_handler(f"/admin {cmd_args}")
            if result.get("status") == "error":
                console.print(f"[red]Error:[/red] {result.get('message')}")
            else:
                console.print(result.get("message", result))
            return

        # Handle config command
        if args.command == "config":
            # If args provided, check for 'evolve' subcommand first
            if args.args and args.args[0] == "evolve":
                from olav.cli.commands.config_evolve import run_evolve_command
                from olav.core.config import DOMAIN_DB_PATH

                output = run_evolve_command(
                    args=args.args[1:],
                    domain_db_path=DOMAIN_DB_PATH,
                )
                console.print(output)
            elif args.args:
                query = " ".join(args.args)
                await run_single_query(query, args.agent, session_id=args.session)
            else:
                # Otherwise show configuration
                from olav.core.config import settings

                console.print("\n[bold]OLAV Configuration:[/bold]\n")
                console.print(f"  LLM Provider: {settings.llm_provider}")
                console.print(f"  LLM Model: {settings.llm_model_name}")
                console.print(f"  Temperature: {settings.llm_temperature}")
                console.print()
            return

        # Handle init command
        if args.command == "init":
            from olav.cli.commands.init import InitCommand

            cmd = InitCommand()
            result = await cmd.execute()
            console.print(result)
            return

        # Handle refresh command — rebuild global agent registry
        if args.command == "refresh":
            from olav.cli.commands.refresh import RefreshCommand

            cmd = RefreshCommand()
            result = await cmd.execute()
            console.print(result)
            return

        # Handle sessions command (M4: session listing across interfaces)
        if args.command == "sessions":
            from olav.cli.commands.sessions import SessionsCommand

            cmd = SessionsCommand()
            # Build args string from the proper argparse attributes
            _sessions_parts = []
            if getattr(args, "all", False):
                _sessions_parts.append("--all")
            if getattr(args, "user", None):
                _sessions_parts.extend(["--user", args.user])
            result = await cmd.execute(" ".join(_sessions_parts))
            console.print(result)
            return

        # Handle service command
        if args.command == "service":
            from olav.cli.commands.service import ServiceCommand

            cmd = ServiceCommand()
            service_args = " ".join(args.args) if args.args else ""
            result = await cmd.execute(service_args)
            if result and result != "success":
                console.print(result)
            return

        # Handle registry command (external service registration)
        if args.command == "registry":
            from olav.cli.commands.service_registry import ServiceRegistryCommand

            cmd = ServiceRegistryCommand()
            registry_args = " ".join(args.args) if args.args else ""
            result = await cmd.execute(registry_args)
            if result and result not in ("success", ""):
                console.print(result)
            return

        # `skill` verb — deprecation shim added back in v0.21.0-rc4 (gitea
        # #11).  v0.20.3 deleted the dispatcher entirely, but every
        # historical demo doc still uses ``olav skill install <path>``.
        # The earlier behaviour (falling through to the natural-language
        # query path) silently routed install requests to the LLM, which
        # then printed "Please run the CLI command directly" without
        # actually doing anything — confusing and visibly broken on demos.
        # Now we forward verbatim to the agent dispatcher and warn once.
        if args.command == "skill":
            from olav.cli.commands.agent_install import AgentInstallCommand

            console.print(
                "[yellow]warning:[/yellow] `olav skill` is deprecated; "
                "use [cyan]`olav agent`[/cyan] instead.  Forwarding…"
            )
            agent_cmd = AgentInstallCommand()
            agent_args = " ".join(args.args) if args.args else ""
            result = await agent_cmd.execute(agent_args)
            console.print(result)
            return

        if args.command == "agent":
            # v0.20.0 scaffold: new public verb, dispatches via the
            # AgentInstallCommand shim until P1 (v0.20.2) fully moves
            # the install implementation out of SkillCommand.
            from olav.cli.commands.agent_install import AgentInstallCommand

            agent_cmd = AgentInstallCommand()
            agent_args = " ".join(args.args) if args.args else ""
            result = await agent_cmd.execute(agent_args)
            console.print(result)
            return

        if args.command == "migrate":
            # v0.20.2 P1 — olav migrate [--dry-run] [--json]
            #              [--no-backup] [--root PATH]
            from olav.cli.commands.migrate import MigrateCommand

            migrate_cmd = MigrateCommand()
            # Reconstruct the flag string from the parsed args so the
            # command module stays self-contained and testable.
            migrate_flags: list[str] = []
            if args.dry_run:
                migrate_flags.append("--dry-run")
            if args.json:
                migrate_flags.append("--json")
            if args.no_backup:
                migrate_flags.append("--no-backup")
            if args.root:
                migrate_flags.extend(["--root", args.root])
            result = await migrate_cmd.execute(" ".join(migrate_flags))
            console.print(result)
            return

        # Handle workspace command
        if args.command == "workspace":
            from olav.cli.commands.workspace import WorkspaceCommand

            cmd = WorkspaceCommand()
            workspace_args = " ".join(args.args) if args.args else ""
            result = await cmd.execute(workspace_args)
            if result:
                console.print(result)
            return

        # Handle export command
        if args.command == "export":
            from olav.cli.commands.export import ExportCommand

            cmd = ExportCommand()
            export_args = " ".join(args.args) if args.args else ""
            result = await cmd.execute(export_args)
            if result:
                console.print(result)
            return

        # Handle reset command - clear checkpoint/session data for an agent
        if args.command == "reset":
            import shutil

            agent_id = args.agent
            source = getattr(args, "target", None)
            sessions_dir = Path.home() / ".olav" / "sessions"
            removed = 0
            if sessions_dir.exists():
                for f in sessions_dir.iterdir():
                    if agent_id in f.name:
                        f.unlink()
                        removed += 1
            if source:
                console.print(
                    "[yellow]--target copy not supported in OLAV (agents live in "
                    ".olav/workspace/). Cleared session data only.[/yellow]"
                )
            console.print(
                f"[bold green]✓[/bold green] Agent [bold]{agent_id}[/bold] reset "
                f"({removed} session file(s) removed)."
            )
            console.print(f"  [dim]Sessions dir: {sessions_dir}[/dim]")
            return

        # Handle log command — query audit.duckdb
        if args.command == "log":
            from olav.cli.log_cmd import log_errors, log_list, log_show

            log_sub_cmd = getattr(args, "log_command", None)
            if log_sub_cmd == "show":
                events = log_show(args.run_id)
                if not events:
                    console.print(f"[yellow]No events found for run_id: {args.run_id}[/yellow]")
                else:
                    for ev in events:
                        ts = str(ev.get("timestamp", ""))[:19]
                        console.print(f"  [{ts}] {ev['event_type']:30s} {ev.get('agent_id') or ''}")
            elif log_sub_cmd == "errors":
                hours = getattr(args, "hours", 24)
                events = log_errors(since_hours=hours)
                if not events:
                    console.print(f"[green]No errors in the last {hours}h[/green]")
                else:
                    for ev in events:
                        ts = str(ev.get("timestamp", ""))[:19]
                        console.print(
                            f"  [{ts}] [red]{ev['event_type']}[/red]  run={ev.get('run_id', '')[:8]}"
                        )
            elif log_sub_cmd == "export":
                export_fmt = getattr(args, "export_format", None)
                # raw export — base package, no olav-ent required
                if export_fmt == "raw":
                    from olav.cli.log_cmd import log_export_raw
                    hours = getattr(args, "hours", 24)
                    output_dir = getattr(args, "output", None)
                    result = log_export_raw(output_dir=output_dir, hours=hours)
                    if result["runs_exported"] == 0:
                        console.print("[yellow]No audit runs in the last %dh[/yellow]" % hours)
                    else:
                        console.print(f"[bold green]✓[/bold green] Raw export complete → {result['output_dir']}")
                        console.print(f"  Runs exported:   {result['runs_exported']}")
                        console.print(f"  Events exported: {result['events_exported']}")
                    return
                # enterprise formats — require olav-ent
                try:
                    from olav.enterprise.cli_bridge import dispatch_log_export
                except ImportError:
                    print(
                        "Error: olav-ent package not installed. "
                        "Install with: pip install olav-ent",
                        file=sys.stderr,
                    )
                    return
                dispatch_log_export(export_fmt, args, console)
            else:
                runs = log_list()
                if not runs:
                    console.print("[yellow]No audit runs in the last 24h[/yellow]")
                else:
                    console.print("\n[bold]Recent Audit Runs (last 24h):[/bold]\n")
                    for r in runs:
                        ts = str(r.get("start_time", ""))[:19]
                        rid = str(r.get("run_id", ""))[:8]
                        status = r.get("status", "")
                        agent = r.get("agent_id", "")
                        console.print(f"  [{ts}] {rid}  {status:12s}  agent={agent}")
            return

        # Handle skills command - manage SKILL.md files in .olav/workspace/
        if args.command == "skills":
            from olav.core.workspace import resolve_workspace_root
            workspace = resolve_workspace_root()
            skills_cmd = getattr(args, "skills_command", None)

            if skills_cmd is None or skills_cmd == "list":
                agent_filter = getattr(args, "agent", None)
                console.print("\n[bold]Agent Skills:[/bold]\n")
                found_any = False
                search_dirs = (
                    ([workspace / agent_filter] if agent_filter else sorted(workspace.iterdir()))
                    if workspace.exists()
                    else []
                )
                for agent_dir in search_dirs:
                    if not agent_dir.is_dir():
                        continue
                    tools_dir = agent_dir / "tools"
                    if not tools_dir.exists():
                        continue
                    for skill_dir in sorted(tools_dir.iterdir()):
                        skill_md = skill_dir / "SKILL.md"
                        if skill_md.exists():
                            found_any = True
                            console.print(
                                f"  [cyan]{agent_dir.name}[/cyan] / [bold]{skill_dir.name}[/bold]"
                            )
                            console.print(f"    [dim]{skill_md}[/dim]")
                if not found_any:
                    console.print("  [yellow]No skills found in .olav/workspace/[/yellow]")
                console.print()

            elif skills_cmd == "create":
                skill_name = args.name
                agent_id = args.agent
                skill_dir = workspace / agent_id / "tools" / skill_name
                skill_dir.mkdir(parents=True, exist_ok=True)
                skill_md = skill_dir / "SKILL.md"
                if skill_md.exists():
                    console.print(
                        f"[yellow]Skill '{skill_name}' already exists at {skill_md}[/yellow]"
                    )
                else:
                    template = f"""---
name: {skill_name}
description: |
  Describe what this skill does in one sentence.
  What domain does it cover? What agent does it enable?
version: "1.0"
---

# {skill_name}

## Instructions

Describe the agent's role, capabilities, and operating constraints here.
What should the agent do? What should it avoid?
What tools are available and when should each be used?

## Examples

- "Show me all interfaces on router-01"
- "Compare running config vs last snapshot"
- "Deploy the lab topology from topology.yaml"
"""
                    skill_md.write_text(template)
                    console.print(
                        f"[bold green]✓[/bold green] Skill '[bold]{skill_name}[/bold]' created at {skill_md}"
                    )
                    console.print(f"  [dim]Edit with: nano {skill_md}[/dim]")

            elif skills_cmd == "info":
                skill_name = args.name
                agent_filter = getattr(args, "agent", None)
                found = False
                search_dirs = (
                    ([workspace / agent_filter] if agent_filter else sorted(workspace.iterdir()))
                    if workspace.exists()
                    else []
                )
                for agent_dir in search_dirs:
                    skill_md = agent_dir / "tools" / skill_name / "SKILL.md"
                    if skill_md.exists():
                        found = True
                        console.print(
                            f"\n[bold]Skill:[/bold] {skill_name}  [dim](agent: {agent_dir.name})[/dim]\n"
                        )
                        console.print(skill_md.read_text())
                        break
                if not found:
                    console.print(f"[red]Skill '{skill_name}' not found.[/red]")
                    console.print("[dim]Use 'olav skills list' to see available skills.[/dim]")
            return

        # Handle kb command group (Unified Knowledge Store)
        if args.command == "kb":
            from olav.cli.commands.kb import handle_kb_command
            sys.exit(handle_kb_command(args))
            return

        # Handle catalog command group (data model drill-down, ARCH-12)
        if args.command == "catalog":
            from olav.cli.commands.catalog import handle_catalog_command
            sys.exit(handle_catalog_command(args))
            return

        # Handle explain — resolve [src: ...] citation tokens (ARCH-11 Round 45)
        if args.command == "explain":
            from olav.cli.commands.explain import handle_explain_command
            sys.exit(handle_explain_command(args))
            return

        # Handle diff — cross-snapshot diff (ARCH-13 Round 47)
        if args.command == "diff":
            from olav.cli.commands.diff import handle_diff_command
            sys.exit(handle_diff_command(args))
            return

        # Activate bypass mode before creating session (sets env var for all gates)
        if getattr(args, "dangerously_skip_permissions", False):
            from olav.platform.safety.permissions import set_bypass
            set_bypass(True)
            console.print(
                "  [bold red]⚠ --dangerously-skip-permissions: ON[/bold red] "
                "[dim](all approval gates disabled — for testing only)[/dim]"
            )
            console.print()

        # Activate API write mode (separate from skip-permissions)
        if getattr(args, "enable_api_write", False):
            import os as _os
            _os.environ["OLAV_ENABLE_API_WRITE"] = "1"
            console.print(
                "  [bold yellow]⚠ API WRITE MODE ENABLED[/bold yellow]"
            )
            console.print(
                "  [dim]• Backup your data before proceeding[/dim]\n"
                "  [dim]• All writes require dry-run verification + manual approval[/dim]\n"
                "  [dim]• --dangerously-skip-permissions does NOT bypass write approval[/dim]"
            )
            console.print()

        # Create session state
        try:
            from deepagents_cli.config import SessionState
        except ImportError as _e:
            console.print(
                f"[red]Error:[/red] Interactive mode requires deepagents-cli: {_e}\n"
                "Install with: [cyan]pip install 'deepagents-cli>=0.0.37'[/cyan]"
            )
            sys.exit(1)

        session_state = SessionState(
            auto_approve=args.auto_approve,
            no_splash=args.no_splash,
        )

        _workspace = getattr(args, "workspace", None)
        _repeat = max(1, int(getattr(args, "repeat", 1) or 1))
        if args.query:
            # Single query mode.  When ``--repeat N`` is set, run the
            # query N times in this same Python process — the
            # ``SemanticCache._entries`` list is class-level so cache
            # state persists across run_single_query calls.  This is
            # how the bench harness measures cache amortisation
            # (per dev_docs/62 Phase 1.5 step b).  Each iteration
            # prints ``=== run K/N elapsed Xs ===`` markers that the
            # harness greps for timing extraction.
            import time as _time
            for _i in range(1, _repeat + 1):
                if _repeat > 1:
                    console.print(f"\n=== run {_i}/{_repeat} ===")
                _start = _time.time()
                await run_single_query(
                    args.query, args.agent, session_id=args.session,
                    workspace=_workspace,
                )
                if _repeat > 1:
                    console.print(
                        f"=== run {_i} elapsed {_time.time() - _start:.1f}s ==="
                    )
        else:
            # Interactive mode
            await run_interactive(
                assistant_id=args.agent,
                session_state=session_state,
                sandbox_type=args.sandbox,
                session_id=args.session,
                workspace=_workspace,
            )

    except KeyboardInterrupt:
        console.print("\n\n[yellow]Interrupted[/yellow]")
        sys.exit(0)
    except Exception as e:
        console.print(f"\n[bold red]Error:[/bold red] {e}")
        import traceback

        # Only print full traceback in debug mode; suppress for known API errors
        # (e.g., 402 Payment Required, 429 Rate Limit) to avoid noisy stderr.
        _is_api_error = any(
            marker in str(type(e).__name__) or marker in str(e)
            for marker in ("APIStatusError", "APIError", "RateLimitError", "AuthenticationError")
        )
        if logging.getLogger().level == logging.DEBUG or not _is_api_error:
            traceback.print_exc()
        if logging.getLogger().level == logging.DEBUG:
            console.print_exception()
        sys.exit(1)


def cli_main() -> None:
    """Main entry point for console script."""
    cli_main_async()


if __name__ == "__main__":
    cli_main()
