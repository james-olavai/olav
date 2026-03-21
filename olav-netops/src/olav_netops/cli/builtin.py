"""NetOps-specific slash commands for the OLAV CLI.

Commands provided by this module (registered into the platform's SLASH_COMMANDS
registry when olav-netops is installed):

  - /learn_cmd   — Learn a network command and generate a TextFSM template.
  - /learn, /lc  — Aliases for /learn_cmd.
  - /netops_init — Initialize netops workspace and bootstrap inventory.

All commands are registered declaratively via the workspace MANIFEST.yaml
(`slash_commands:` section in `.olav/workspace/ops/MANIFEST.yaml`) and
via the ``olav.slash_commands`` entry point group in ``pyproject.toml``.
"""

import shlex


async def cmd_learn(args: str, _get_or_create_agent=None) -> str:
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
    try:
        import uuid

        if _get_or_create_agent is None:
            # Fallback: import from platform builtin helpers
            from olav.cli.commands.builtin import (
                _get_or_create_agent as _factory,  # type: ignore[import]
            )

            _get_or_create_agent = _factory

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
def netops_init_main(args: str = "") -> str:
    """Slash-command entry point for /netops_init.

    Invoked by the platform's slash-command registry when the user runs
    ``/netops_init`` (or ``/netops_init --dry-run``).

    Delegates to ``olav-netops/scripts/netops_init.py::run_init()``.
    """
    import importlib.util
    import sys
    from pathlib import Path

    # Locate netops_init.py relative to this package file.
    # __file__ = olav-netops/src/olav_netops/cli/builtin.py
    # parents[0] = cli/  parents[1] = olav_netops/  parents[2] = src/  parents[3] = olav-netops/
    pkg_root = Path(__file__).resolve().parents[3]  # olav-netops/
    scripts_dir = pkg_root / "scripts"
    init_script = scripts_dir / "netops_init.py"

    if not init_script.exists():
        return (
            f"❌ netops_init.py not found at {init_script}.\n"
            "Ensure you have checked out the olav-netops source tree."
        )

    # Dynamically load the script module (avoids circular imports)
    spec = importlib.util.spec_from_file_location("_netops_init_script", init_script)
    if spec is None or spec.loader is None:
        return "❌ Could not load netops_init.py"
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("_netops_init_script", mod)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]

    dry_run = "--dry-run" in args
    rc: int = mod.run_init(dry_run=dry_run)
    if rc == 0:
        return "✅ netops_init completed successfully."
    return f"❌ netops_init exited with code {rc}."
