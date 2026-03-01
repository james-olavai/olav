"""Built-in slash commands for OLAV CLI - Simplified to 6 core commands.

Commands registered:
  - /help, /?           - Show help information
  - /clear              - Clear conversation memory
  - /history            - Show session statistics
  - /quit, /exit        - Exit OLAV
  - /learn_cmd          - Learn network commands (TextFSM templates)
  - /learn, /lc         - Aliases for /learn_cmd
"""

from collections.abc import Callable

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
) -> str | None:
    """Execute a slash command.

    Args:
        full_command: Full command string (e.g., "/help")
        agent: OLAV agent instance (optional)

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

    # Look up command
    if cmd_name not in SLASH_COMMANDS:
        return f"Unknown command: /{cmd_name}. Type /help for available commands."

    # Execute command
    try:
        func = SLASH_COMMANDS[cmd_name]

        # Check if function is async
        import inspect

        # Log the slash command for auditing
        from olav.core.audit_logger import log_command

        log_command(full_command, agent_id=cmd_name)

        if inspect.iscoroutinefunction(func):
            result: str | None = await func(args)
        else:
            result: str | None = func(args)
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
    if args:
        # Show specific command help
        cmd_name = args.strip().lstrip("/")
        if cmd_name in SLASH_COMMANDS:
            func = SLASH_COMMANDS[cmd_name]
            doc = func.__doc__ or "No documentation available"
            return f"Help for /{cmd_name}:\n\n{doc}"
        else:
            return f"Unknown command: /{cmd_name}"
    else:
        # Show all available commands
        return """OLAV CLI - Available Commands:

Session Commands:
  /help [cmd]      - Show this help or command details
  /clear           - Clear conversation memory
  /history         - Show session statistics
  /quit, /exit     - Exit OLAV

Learning Commands:
  /learn_cmd "<cmd>" --device <dev>  - Learn command template (TextFSM)
  /learn, /lc      - Aliases for /learn_cmd

Natural Language Queries (type without / prefix):
  "10.1.12.1在哪个设备?"    - IP location lookup
  "R1的健康状态"          - Device health check
  "网络概览"                - Network summary

Input Features:
  @file.txt               - Include file content
  !shell_command          - Execute shell command
  Press Enter twice       - Submit multi-line input

Examples:
  olav> How are BGP neighbors on R1?
  olav> /learn_cmd "show ip bgp summary" --device R1
  olav> @config.txt analyze this
"""


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
    from olav.core.config import USER_HISTORY_PATH, USER_SESSION_DIR

    # Try to show audit log if available
    try:
        from olav.core.audit_logger import get_command_history

        limit = 20
        if args.strip() == "--audit":
            limit = 50

        history = get_command_history(limit=limit)

        if history:
            lines = ["Recent Command History:"]
            # Show last 10 entries
            for entry in history[-10:]:
                ts = entry.get("timestamp", "")
                cmd = entry.get("command", entry.get("raw", ""))
                lines.append(f"  [{ts[:19]}] {cmd}")

            if args.strip() == "--audit":
                lines.append(f"\nFull audit log: {USER_HISTORY_PATH}")

            return "\n".join(lines)
    except Exception:
        # Fallback if audit log fails
        pass

    return f"""Session History Info:
  History managed by LangGraph checkpointer.
  Checkpoint directory: {USER_SESSION_DIR}

Centralized audit log: {USER_HISTORY_PATH}

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


@register_command("learn_cmd")
async def cmd_learn(args: str) -> str:
    """Learn a new command and generate TextFSM template.

    Usage:
        /learn_cmd "<command>" --device <device> [--platform <platform>]

    Workflow:
        1. Execute command on target device
        2. Analyze output fields
        3. Generate TextFSM template
        4. Save to custom templates

    Examples:
        /learn_cmd "show ip bgp summary" --device R1
        /learn_cmd "show version" --device R1 --platform cisco_ios
        /learn_cmd "show ip route" -d core1

    Options:
        --device, -d    Target device (REQUIRED)
        --platform, -p  Override platform (optional)
        --timeout, -t   Command timeout in seconds (default: 60)

    Note: Command Learner Agent will guide you through the workflow.
    """
    import shlex

    try:
        args_list = shlex.split(args)
    except ValueError:
        return "❌ Error parsing arguments. Use quotes for commands with spaces."

    if not args_list:
        return """Usage: /learn_cmd "<command>" --device <device>

Example:
    /learn_cmd "show ip bgp summary" --device R1"""

    # Parse arguments
    command = None
    device = None
    platform = None
    timeout = 60

    i = 0
    while i < len(args_list):
        arg = args_list[i]

        if arg in ["--device", "-d"]:
            if i + 1 < len(args_list):
                device = args_list[i + 1]
                i += 2
            else:
                return "❌ --device requires a value"
        elif arg in ["--platform", "-p"]:
            if i + 1 < len(args_list):
                platform = args_list[i + 1]
                i += 2
            else:
                return "❌ --platform requires a value"
        elif arg in ["--timeout", "-t"]:
            if i + 1 < len(args_list):
                try:
                    timeout = int(args_list[i + 1])
                    i += 2
                except ValueError:
                    return "❌ --timeout must be an integer"
            else:
                return "❌ --timeout requires a value"
        else:
            if command is None:
                command = arg
            i += 1

    # Validate
    if not command:
        return "❌ Command is required"
    if not device:
        return "❌ Device is required (--device)"

    # Route through OLAVAgent (command_learner skill tools are loaded automatically)
    # Use cached agent to avoid heavy re-initialization
    try:
        import uuid

        agent = _get_or_create_agent(agent_id="ops")
        thread_id = str(uuid.uuid4())

        print("🎓 Starting Command Learner workflow...")
        print(f"   Command: {command}")
        print(f"   Device: {device}")
        if platform:
            print(f"   Platform: {platform}")
        print()

        query = f"Learn command: {command}\nDevice: {device}"
        if platform:
            query += f"\nPlatform: {platform}"
        query += f"\nTimeout: {timeout}s"

        result = await agent.ainvoke(query, thread_id=thread_id)
        return result

    except Exception as e:
        import traceback

        return f"❌ Error: {str(e)}\n\n{traceback.format_exc()}"


# Aliases for /learn_cmd
register_command("learn")(cmd_learn)
register_command("lc")(cmd_learn)


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
