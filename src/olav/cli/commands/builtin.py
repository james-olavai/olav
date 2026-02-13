"""Built-in slash commands for OLAV CLI - Unified command framework.

Provides fast, dedicated commands for common operations.
Commands are prefixed with '/' (e.g., /devices, /help).

Consolidated from:
  - commands.py (command registry and basic commands)
  - cli_enhancements.py (advanced command implementations)
"""

from collections.abc import Callable

# Registry for slash commands
SLASH_COMMANDS: dict[str, Callable] = {}


def register_command(name: str) -> Callable:
    """Decorator to register a slash command.

    Args:
        name: Command name (without / prefix)

    Returns:
        Decorator function

    Example:
        @register_command("devices")
        def cmd_devices(args: str) -> str:
            return "Device list..."
    """

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
        full_command: Full command string (e.g., "/devices core")
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

        if inspect.iscoroutinefunction(func):
            # Call async function directly (we're already in async context)
            result: str | None = await func(args)
        else:
            result: str | None = func(args)
        return result
    except EOFError:
        raise
    except Exception as e:
        return f"Error executing /{cmd_name}: {str(e)}"


# =============================================================================
# Built-in Command Implementations
# =============================================================================


@register_command("devices")
async def cmd_devices(args: str) -> str:
    """List devices or filter devices.

    Usage:
        /devices [filter]

    Examples:
        /devices              - List all devices
        /devices role:core    - List core devices
        /devices site:DC1     - List devices in DC1
    """
    from olav.api.v1.devices import list_devices
    import json

    try:
        # Call function directly (not a LangChain tool)
        result = list_devices()
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"❌ Error listing devices: {str(e)}"


@register_command("skills")
async def cmd_skills(args: str) -> str:
    """List skills or view skill details.

    Usage:
        /skills [name]

    Examples:
        /skills             - List all skills
        /skills deep        - Show deep-analysis skill details
    """
    from olav.core.skill_loader import get_skill_loader

    loader = get_skill_loader()

    if args:
        # Show specific skill
        skill_name = args.strip()
        skill = loader.get_skill(skill_name)
        if skill:
            return f"Skill: {skill.id}\n\n{skill.content}"
        else:
            return f"Skill '{skill_name}' not found"
    else:
        # List all skills
        skills = loader.load_all()
        output = []
        for skill_name, skill in skills.items():
            status = "✅" if skill_name.startswith("_") is False else "❌"
            output.append(f"{status} {skill_name}: {skill.description}")
        return "\n".join(output)


@register_command("reload")
async def cmd_reload(args: str) -> str:
    """Reload skills and capabilities.

    Usage:
        /reload
    """
    try:
        from olav.core.skill_loader import get_skill_loader

        loader = get_skill_loader()
        loader.load_all()  # Reload skills by re-running load_all
        return "✅ Skills and capabilities reloaded successfully"
    except Exception as e:
        return f"Error reloading: {str(e)}"


@register_command("clear")
async def cmd_clear(args: str) -> str:
    """Clear conversation memory.

    Usage:
        /clear
    """
    try:
        # Memory will be cleared by the caller
        return "Conversation memory cleared."
    except Exception as e:
        return f"Error clearing memory: {str(e)}"


@register_command("history")
async def cmd_history(args: str) -> str:
    """Show command history statistics.

    Usage:
        /history
    """
    try:
        # History now managed by LangGraph checkpointer
        return """Session History Info:
  History is now managed by LangGraph checkpointer.
  Use `uv run olav query "what did we discuss?"` to review context.
  Checkpoint database: ~/.olav/checkpoints/<username>.duckdb"""
    except Exception as e:
        return f"Error showing history: {str(e)}"


@register_command("help")
async def cmd_help(args: str) -> str:
    """Show help information.

    Usage:
        /help [command]
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
        # Show general help
        return """OLAV CLI Commands:

  Workflow Commands:
    /analyze [device|all] [--error "desc"]  - Fault diagnosis & health analysis
    /search <query>                          - Search knowledge base

  Device Commands:
    /devices [filter]   - List devices (e.g., /devices role:core)
    /skills [name]      - List skills or view skill details

  Session Commands:
    /reload             - Reload skills and capabilities
    /clear              - Clear session memory
    /history            - Show session statistics
    /help [command]     - Show this help or command-specific help
    /quit, /exit        - Exit OLAV

  Natural Language Queries (no command needed):
    "10.1.12.1在哪个设备?"      - IP location lookup
    "R1的健康状态"            - Device health check
    "网络概览"                  - Network summary
    "显示拓扑"                  - Topology view

  Input Features:
    @file.txt           - Include file content in your query
    !command            - Execute shell command
    Multi-line          - Press Enter twice to submit

  Examples:
    olav> /analyze R1 --error "BGP neighbor down"
    olav> /analyze all
    olav> 10.1.12.1在哪个设备?
    olav> R1的BGP邻居状态
    olav> @config.txt analyze this configuration
"""


@register_command("analyze")
async def cmd_analyze(args: str) -> str:
    """Fault diagnosis and health analysis (Analyzer Agent).

    Usage:
        /analyze [query]

    Examples:
        /analyze show interface errors       - Query interface errors
        /analyze diagnose slow network       - Complex network diagnosis
        /analyze check BGP status           - Real-time BGP verification
        /analyze find anomalies            - Anomaly detection

    This command triggers the Analyzer Agent directly with Data Fusion logic:
        - Phase 1: Query DuckDB snapshot (Instant, 60% confidence)
        - Phase 2: Real-time CLI verification (if anomaly or stale data)
        - Phase 3: Fusion analysis with recommendations

    Task 9.1: Direct integration bypasses generic agent loop.
    """
    # Import here to avoid circular dependency
    from olav.agents.analyzer import analyze_network

    if not args.strip():
        args = "network health check"

    try:
        # Call Analyzer Agent directly
        result = await analyze_network(args)

        if result["status"] == "success":
            path_icon = "⚡" if result["routing_decision"] == "static_only" else "🔍"
            output = [
                f"{path_icon} Analysis complete",
                f"Routing: {result['routing_decision']}",
                f"DB rows: {result.get('db_rows', 0)}",
                "",
                result["analysis"],
            ]

            if result.get("recommendations"):
                output.extend(
                    [
                        "",
                        "## Recommendations:",
                    ]
                )
                for rec in result["recommendations"]:
                    output.append(f"  • {rec}")

            return "\n".join(output)
        else:
            return f"❌ Analysis failed: {result.get('error', 'Unknown error')}"

    except Exception as e:
        return f"❌ Analysis error: {e}"


@register_command("search")
async def cmd_search(args: str) -> str:
    """Search the web for troubleshooting information.

    Usage:
        /search <query>
        /search bgp flapping cisco
        /search "ospf neighbor stuck in exstart"

    Examples:
        /search cisco ios xr bgp community filtering
        /search juniper mx series interface crc errors
        /search arista eos vxlan troubleshooting
    """
    if not args.strip():
        return "Usage: /search <query>\nExample: /search bgp flapping cisco"

    query = args.strip()

    try:
        from langchain_community.tools import DuckDuckGoSearchResults

        search = DuckDuckGoSearchResults(num_results=5)  # type: ignore[call-arg]
        results = search.invoke(query)

        if not results:
            return f"No results found for: {query}"

        return f"🔍 Search results for: {query}\n\n{results}"

    except ImportError:
        return "Error: DuckDuckGo search not available.\nInstall with: uv add duckduckgo-search"
    except Exception as e:
        return f"Search error: {str(e)}"


@register_command("quit")
async def cmd_quit(args: str) -> str:
    """Exit OLAV.

    Usage:
        /quit
    """
    raise EOFError


@register_command("exit")
async def cmd_exit(args: str) -> str:
    """Exit OLAV (alias for /quit).

    Usage:
        /exit
    """
    raise EOFError


@register_command("lib")
async def cmd_lib(args: str) -> str:
    """Browse command library and templates.

    Usage:
        /lib [search_term]

    Examples:
        /lib              - List all available commands
        /lib bgp          - Search for BGP commands
        /lib interface    - Search for interface commands
    """
    from olav.core.command_registry import get_command_registry

    registry = get_command_registry()

    # Parse search term
    search_term = args.strip() if args else None

    if search_term:
        # Search for commands
        results = registry.search_commands(search_term)
        if not results:
            return f"No commands found matching '{search_term}'"

        # Format results
        output = [f"Commands matching '{search_term}':", ""]
        for meta in results:
            inspection = "✅" if meta.has_inspection_rules else "❌"
            output.append(f"{inspection} {meta.display_name}")
            output.append(f"   Devices: {', '.join(meta.devices[:5])}")
            if meta.sample_fields:
                output.append(f"   Fields: {', '.join(meta.sample_fields[:5])}")
            output.append("")
        return "\n".join(output)
    else:
        # List all commands
        return registry.format_command_list()


@register_command("learn_cmd")
async def cmd_learn(args: str) -> str:
    """Learn a new command and generate TextFSM template interactively.

    Usage:
        /learn_cmd <host:group> <platform> <command>

    This runs the Command Learner interactive workflow:
    1. Execute command on target host
    2. Analyze output fields (LLM)
    3. User approval/modification
    4. Fetch NTC references
    5. Generate template via ReAct
    6. Save to custom templates

    Examples:
        /learn_cmd R1:core cisco_ios "show ip custom"
        /learn_cmd R2:access arista_eos "show interfaces detail"

    Note: This command requires approval from user during workflow.
    """
    # Parse arguments
    parts = args.strip().split(maxsplit=2)
    if len(parts) < 3:
        return """Usage: /learn_cmd <host:group> <platform> <command>

Example:
    /learn_cmd R1:core cisco_ios "show running-config"

This will start the interactive TextFSM template learning workflow."""

    return "⚠️  Command learner workflow not yet implemented"


@register_command("cache")
async def cmd_cache(args: str) -> str:
    """Manage command template cache.

    Usage:
        /cache stats                    - Show cache statistics
        /cache clear                    - Clear cache entries
        /cache cleanup [days]           - Remove old templates

    Examples:
        /cache stats                    - Show all cache stats
        /cache clear                    - Clear all cache
        /cache cleanup 60               - Remove templates>60 days old
    """
    return "⚠️  Cache management not yet implemented"
