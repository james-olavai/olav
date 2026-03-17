"""Built-in slash commands for OLAV CLI.

Platform builtins (always available):
  - /help, /?           - Show help information
  - /clear              - Clear conversation memory
  - /history            - Show session statistics
  - /quit, /exit        - Exit OLAV
  - /config             - Admin configuration tasks
  - /model              - Switch LLM model at runtime

Additional commands are discovered dynamically from workspace MANIFEST.yaml
declarations and ``olav.slash_commands`` entry points at runtime.
"""

from collections.abc import Callable
from pathlib import Path

from olav.cli.commands.registry import SlashCommandSpec, build_slash_command_registry

# Registry for slash commands
SLASH_COMMANDS: dict[str, Callable] = {}

# Module-level agent cache to avoid heavy re-initialization
_cached_agent = None
_cached_agent_params = {}


def _get_or_create_agent(agent_id: str = "quick", **kwargs: object) -> object:
    """Get cached agent or create new one with given params."""
    global _cached_agent, _cached_agent_params

    # Inject model override if present
    if "model_name" not in kwargs:
        kwargs["model_name"] = _model_override

    # Ensure agent_id is passed
    kwargs["agent_id"] = agent_id

    # Check if we can reuse existing agent
    if _cached_agent is not None:
        # Verify params match - if different, recreate
        if _cached_agent_params == kwargs:
            return _cached_agent

    # Create new agent and cache it
    from olav.agents.agent import create_olav_agent

    _cached_agent = create_olav_agent(**kwargs)
    _cached_agent_params = kwargs
    return _cached_agent


def clear_cached_agent() -> None:
    """Clear the cached agent (call on session reset)."""
    global _cached_agent, _cached_agent_params
    _cached_agent = None
    _cached_agent_params = {}


def register_command(name: str) -> Callable:
    """Decorator to register a slash command."""

    def decorator(func: Callable) -> Callable:
        SLASH_COMMANDS[name] = func
        return func

    return decorator


async def execute_command(
    full_command: str,
    agent: object | None = None,  # noqa: ANN401
    *,
    workspace_root: Path | None = None,
    project_root: Path | None = None,
    auto_approve: bool = False,
) -> str | None:
    """Execute a slash command.

    Resolves the command through the three-layer merged registry:
      1. platform builtins (highest priority, never overridden)
      2. workspace MANIFEST.yaml slash_commands sections
      3. olav.slash_commands entry points (lowest priority)

    Args:
        full_command: Full command string (e.g., "/help")
        agent: OLAV agent instance (optional)
        workspace_root: Path to .olav/workspace (defaults to CWD/.olav/workspace)
        project_root: Project root for shell command CWD (defaults to CWD)
        auto_approve: Skip HITL approval prompts for shell commands

    Returns:
        Command output string

    Raises:
        EOFError: If /quit or /exit command is executed
    """
    full_command = full_command.strip()

    # Must start with /
    if not full_command.startswith("/"):
        raise ValueError(f"Not a slash command: {full_command}")

    # Parse command and args
    parts = full_command[1:].split(None, 1)
    cmd_name = parts[0]
    args = parts[1] if len(parts) > 1 else ""

    # Build merged registry (builtins + workspace manifest + entry points)
    _ws_root = workspace_root or (Path.cwd() / ".olav" / "workspace")
    merged = build_slash_command_registry(_ws_root, SLASH_COMMANDS)

    # Look up command
    if cmd_name not in merged:
        return f"Unknown command: /{cmd_name}. Type /help for available commands."

    # Execute command
    try:
        handler = merged[cmd_name]

        # ── SlashCommandSpec dispatch ─────────────────────────────────────────
        if isinstance(handler, SlashCommandSpec):
            if handler.kind == "shell":
                from olav.cli.commands.shell_runner import run_shell_command

                _proj_root = project_root or Path.cwd()
                return await run_shell_command(handler, args, _proj_root, auto_approve=auto_approve)
            else:  # python
                import inspect

                fn = handler.resolve_callable()
                if inspect.iscoroutinefunction(fn):
                    return await fn(args)
                return fn(args)

        # ── Legacy callable dispatch (platform builtins) ─────────────────────
        import inspect

        if inspect.iscoroutinefunction(handler):
            result: str | None = await handler(args)
        else:
            result: str | None = handler(args)
        return result
    except EOFError:
        raise
    except Exception as e:
        return f"Error executing /{cmd_name}: {str(e)}"


# =============================================================================
# Core Slash Commands (6 total)
# =============================================================================


@register_command("help")
async def cmd_help(args: str) -> str:
    """Show help information.

    Usage:
        /help              - Show all commands
        /help <command>    - Show specific command help
    """
    merged = build_slash_command_registry(Path.cwd() / ".olav" / "workspace", SLASH_COMMANDS)

    if args:
        cmd_name = args.strip().lstrip("/")
        handler = merged.get(cmd_name)
        if handler is None:
            return f"Unknown command: /{cmd_name}"
        if isinstance(handler, SlashCommandSpec):
            return f"Help for /{cmd_name}:\n\n{handler.help or 'No documentation available.'}"
        doc = getattr(handler, "__doc__", None) or "No documentation available"
        return f"Help for /{cmd_name}:\n\n{doc}"

    # ── Build dynamic command listing ─────────────────────────────────
    seen_specs: set[str] = set()
    builtin_lines: list[str] = []
    discovered_lines: list[str] = []

    for name, handler in sorted(merged.items()):
        if isinstance(handler, SlashCommandSpec):
            if name != handler.name:
                continue
            if handler.name in seen_specs:
                continue
            seen_specs.add(handler.name)
            alias_str = ", ".join(f"/{a}" for a in handler.aliases) if handler.aliases else ""
            desc = handler.help or "(no description)"
            if alias_str:
                discovered_lines.append(f"  /{handler.name:<16s} - {desc}  (aliases: {alias_str})")
            else:
                discovered_lines.append(f"  /{handler.name:<16s} - {desc}")
        else:
            doc_line = ""
            if handler.__doc__:
                doc_line = handler.__doc__.strip().split("\n")[0]
            builtin_lines.append(f"  /{name:<16s} - {doc_line}")

    sections: list[str] = ["OLAV CLI - Available Commands:", ""]

    if builtin_lines:
        sections.append("Platform Commands:")
        sections.extend(builtin_lines)
        sections.append("")

    if discovered_lines:
        sections.append("Discovered Commands:")
        sections.extend(discovered_lines)
        sections.append("")

    sections.append("Input Features:")
    sections.append("  @file.txt               - Include file content")
    sections.append("  !shell_command          - Execute shell command")
    sections.append("  Press Enter twice       - Submit multi-line input")
    sections.append("")

    return "\n".join(sections)


@register_command("clear")
async def cmd_clear(args: str) -> str:
    """Clear conversation memory.

    Usage:
        /clear
    """
    # Clear the cached agent to release memory and checkpoints
    clear_cached_agent()
    return "✓ Conversation memory cleared."


@register_command("history")
async def cmd_history(args: str) -> str:
    """Show session statistics and command history.

    Usage:
        /history
        /history --audit
    """
    from olav.core.config import AUDIT_DB_PATH, USER_SESSION_DIR

    limit = 50 if args.strip() == "--audit" else 20

    if AUDIT_DB_PATH.exists():
        try:
            import duckdb

            con = duckdb.connect(str(AUDIT_DB_PATH), read_only=True)
            rows = con.execute(
                """
                SELECT timestamp, json_extract_string(payload, '$.content') AS cmd
                FROM audit_events
                WHERE event_type = 'user_input_received'
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                [limit],
            ).fetchall()
            con.close()
            if rows:
                lines = ["Recent Command History:"]
                for ts, cmd in reversed(rows):
                    lines.append(f"  [{str(ts)[:19]}] {cmd}")
                lines.append(f"\nFull audit log: {AUDIT_DB_PATH} (use 'olav log' to query)")
                return "\n".join(lines)
        except Exception:
            pass

    return f"""Session History Info:
  History managed by LangGraph checkpointer.
  Checkpoint directory: {USER_SESSION_DIR}

Centralized audit log: {AUDIT_DB_PATH} (use 'olav log' to query)

To view full history: /history --audit
To review context: ask "what did we discuss earlier?"
"""


@register_command("quit")
async def cmd_quit(args: str) -> str:
    """Exit OLAV.

    Usage:
        /quit
    """
    raise EOFError


@register_command("exit")
async def cmd_exit(args: str) -> str:
    """Exit OLAV.

    Usage:
        /exit
    """
    raise EOFError


@register_command("config")
async def cmd_config(args: str) -> str:
    """Execute admin tasks in OLAV system.

    Usage:
        /config "<task>"

    Available Admin Tasks:
        - File operations (read, write)
        - Shell command execution
        - OLAV system commands

    Examples:
        /config "show system status"
        /config "backup database"
        /config "list running services"

    Note: Config Agent handles configuration writes and scheduling directives your task with system privileges context.
    """
    if not args:
        return """Usage: /config "<task>"

Examples:
    /config "show system status"
    /config "backup database"
    /config "list running processes"

For detailed admin operations, use OLAV admin CLI: uv run olav config"""

    # Delegate to OLAVAgent (olav-config SubAgent handles writes/scheduling with HITL)
    # Use cached agent to avoid heavy re-initialization
    try:
        import uuid

        agent = _get_or_create_agent(agent_id="config")
        thread_id = str(uuid.uuid4())

        print("⚙️  Config SubAgent processing task (HITL enabled for write operations)...")
        print(f"   Task: {args}")
        print()

        result = await agent.ainvoke(args, thread_id=thread_id)
        return result

    except Exception as e:
        import traceback

        return f"❌ Config Error: {str(e)}\n\n{traceback.format_exc()}"


# Model switching command
_model_override: str | None = None


@register_command("model")
async def cmd_model(args: str) -> str:
    """Switch LLM model at runtime.

    Usage:
        /model <model_name>
        /model list
        /model reset

    Examples:
        /model gpt-4o
        /model groq/llama-3.1-70b-versatile
        /model reset

    Note: Changes the model for the current session only.
    """
    global _model_override

    args = args.strip()

    if not args or args == "list":
        return """Available models:
  - gpt-4o (OpenAI)
  - groq/llama-3.1-70b-versatile (Groq)
  - x-ai/grok-4.1-fast (OpenRouter)

Usage: /model <model_name>
To use a different provider, configure in .olav/config/api.json"""

    if args == "reset":
        _model_override = None
        clear_cached_agent()
        return "✅ Model reset to default."

    _model_override = args
    clear_cached_agent()
    return f"✅ Model set to: {args}. Agent will use this model for next request."


def get_model_override() -> str | None:
    """Get the current model override."""
    return _model_override
