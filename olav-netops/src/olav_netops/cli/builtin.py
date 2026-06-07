"""NetOps-specific slash commands for the OLAV CLI.

Commands provided by this module (registered into the platform's SLASH_COMMANDS
registry when olav-netops is installed):

  - /learn_cmd   — Learn a network command and generate a TextFSM template.
  - /learn, /lc  — Aliases for /learn_cmd.
  - /netops_init — Initialize netops workspace and bootstrap inventory.

All commands are registered declaratively via the workspace MANIFEST.yaml
(`slash_commands:` section in `.olav/workspace/netops/MANIFEST.yaml`) and
via the ``olav.slash_commands`` entry point group in ``pyproject.toml``.

Async/sync convention:
  - Agent-facing tools (e.g. ``cmd_learn``) are ``async def`` — they delegate
    to an ``OLAVAgent.ainvoke()`` coroutine and must be awaited by the caller.
  - CLI entry-points that run synchronous scripts (e.g. ``netops_init_main``)
    are plain ``def`` — they may block and are invoked from a sync context.
"""

import shlex


async def cmd_learn(args: str, _get_or_create_agent=None) -> str:
    """Learn a parser for a CLI command on a device.

    Usage:
        /learn_cmd "<command>" --device <device> [--platform <platform>]

    Workflow (R71c direct call — no agent delegation):
        1. SSH to the device and capture fresh raw output
        2. Hand the sample to the command_learner skill
        3. LLM picks TextFSM or Python DSL, drafts a parser, validates
        4. Freeze to `.olav/templates/` on success, cache failure on fail

    Examples:
        /learn_cmd "show ip bgp summary" --device R1
        /learn_cmd "show version" --device R1 --platform cisco_ios
        /learn_cmd "show ip route" -d core1

    Options:
        --device, -d    Target device (REQUIRED)
        --platform, -p  Override platform (optional; Nornir default used otherwise)
        --timeout, -t   Command timeout in seconds (default: 60)

    ``_get_or_create_agent`` is accepted for test injection but no longer
    used — the function calls command_learner's ``learn_commands`` API
    directly.
    """
    del _get_or_create_agent  # R71c: no longer routed through agent

    try:
        args_list = shlex.split(args)
    except ValueError:
        return "❌ Error parsing arguments. Use quotes for commands with spaces."

    if not args_list:
        return """Usage: /learn_cmd "<command>" --device <device>

Example:
    /learn_cmd "show ip bgp summary" --device R1"""

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

    if not command:
        return "❌ Command is required"
    if not device:
        return "❌ Device is required (--device)"

    # Direct call to command_learner — no agent round-trip, no NL parse.
    try:
        import sys
        from pathlib import Path
        # Locate workspace (walk up from installed olav-netops back into project)
        from olav.core.config import get_paths_config
        workspace = Path(get_paths_config().agent_dir) / "workspace"
        learner_tools = workspace / "command_learner" / "tools"
        if learner_tools.exists() and str(learner_tools) not in sys.path:
            sys.path.insert(0, str(learner_tools))
        netops_tools = workspace / "netops" / "tools"
        if netops_tools.exists() and str(netops_tools) not in sys.path:
            sys.path.insert(0, str(netops_tools))

        # 1. Capture raw output via take_snapshot._run_one
        from take_snapshot import _run_one  # type: ignore
        print(f"🎓 Capturing output: {command} @ {device}")
        cap = _run_one(device, command, timeout, platform)
        raw = cap.get("raw") or ""
        resolved_platform = platform or cap.get("platform") or "unknown"
        if not raw:
            return f"❌ No output captured from {device} (SSH failed?)"

        # 2. Invoke the batch API with a single-sample list
        from learn_commands import learn_commands  # type: ignore
        result = learn_commands(
            samples=[{
                "device": device,
                "platform": resolved_platform,
                "command": command,
                "raw_output": raw,
            }],
            budget_seconds=max(60, timeout + 30),
            max_workers=1,
            max_retries=2,
            allow_llm=True,
        )

        # 3. Format response
        if result.newly_parsed:
            row = result.newly_parsed[0]
            rows = len(row.get("parsed_data") or [])
            frozen = result.frozen[0] if result.frozen else {}
            return (
                f"✅ Learned {resolved_platform}/{command} "
                f"({frozen.get('dsl', '?')} DSL, {rows} row(s), "
                f"{result.elapsed_seconds:.1f}s)\n"
                f"   Frozen: {frozen.get('path', '(path not reported)')}"
            )
        if result.skipped:
            reason = result.skipped[0].get("reason", "skipped")
            return f"⏭  Skipped {resolved_platform}/{command}: {reason}"
        reason = result.failed[0].get("reason") if result.failed else "no parser produced"
        return f"❌ Failed {resolved_platform}/{command}: {reason}"

    except (ImportError, RuntimeError, ValueError, ConnectionError, TimeoutError, OSError) as e:
        import traceback
        return f"❌ Error: {e}\n\n{traceback.format_exc()}"
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


def netops_snapshot_main(args: str = "") -> str:
    """Slash-command entry point for /netops_snapshot.

    Invoked by the platform's slash-command registry when the user runs
    ``/netops_snapshot`` (or ``/netops_snapshot --repair``).

    Delegates to ``olav-netops/scripts/netops_snapshot.py::run_snapshot()``.
    """
    import importlib.util
    import sys
    from pathlib import Path

    pkg_root = Path(__file__).resolve().parents[3]  # olav-netops/
    script = pkg_root / "scripts" / "netops_snapshot.py"

    if not script.exists():
        return (
            f"❌ netops_snapshot.py not found at {script}.\n"
            "Ensure you have checked out the olav-netops source tree."
        )

    spec = importlib.util.spec_from_file_location("_netops_snapshot_script", script)
    if spec is None or spec.loader is None:
        return "❌ Could not load netops_snapshot.py"
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("_netops_snapshot_script", mod)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]

    repair = "--repair" in args
    rc: int = mod.run_snapshot(repair=repair)
    if rc == 0:
        return "✅ netops_snapshot completed successfully."
    return f"❌ netops_snapshot exited with code {rc}."


# /netops_migrate removed (R70): the v0.12 schema-split migration is 8
# versions behind current (we're at v0.19). Anyone upgrading from pre-v0.12
# should fresh-install into a new project directory and re-run
# /netops_init; the in-place migration path has not been maintained for
# the R66-R70 schema changes.
