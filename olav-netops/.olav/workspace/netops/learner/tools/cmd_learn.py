"""cmd_learn — LangChain @tool wrapper around learn_commands.

This is the agent-side interactive entry point. The slash command
`/learn_cmd` (R71c) calls ``learn_commands`` directly without going
through an agent — this wrapper exists for cases where ops agent
or other agents want to expose learning as a tool in their own
workflow.

The implementation is deliberately thin: capture raw output via
`take_snapshot._run_one`, then forward to `learn_commands` with a
single-sample list.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _tool_decorator():
    """Return LangChain ``@tool`` if available; else an identity decorator."""
    try:
        from langchain_core.tools import tool
        return tool
    except Exception:
        def _identity(fn):
            return fn
        return _identity


_tool = _tool_decorator()


@_tool
def cmd_learn(
    command: str,
    device: str,
    platform: str | None = None,
    timeout: int = 60,
) -> dict[str, Any]:
    """Capture fresh output from a device and learn a parser for it.

    Args:
        command: CLI command to run (e.g. ``show bgp summary``).
        device: Nornir inventory host name.
        platform: Netmiko platform override — defaults to Nornir's declared value.
        timeout: Per-command SSH timeout in seconds.

    Returns:
        dict with keys:
          * ``status``: ``learned`` / ``failed`` / ``skipped``
          * ``parsed_rows``: count of records produced (0 on failure)
          * ``dsl``: ``textfsm`` / ``python`` / ``None``
          * ``frozen_path``: absolute path of the saved parser (if learned)
          * ``reason``: short explanation
          * ``elapsed_seconds``: wall-clock time
    """
    import sys
    from pathlib import Path as _P

    # Bootstrap paths so this works from any cwd
    _here = _P(__file__).resolve()
    for up in [_here.parent.parent, _here.parent.parent.parent]:
        if (up / "SKILL.md").exists() or (up / "netops_init").exists():
            sys.path.insert(0, str(up.parent))
            break

    # 1. Capture raw output.
    try:
        from olav_netops.tools.take_snapshot import _run_one  # type: ignore
    except Exception:
        # Fall back to workspace copy.
        ops_tools = _P(__file__).resolve().parent.parent.parent / "ops" / "tools"
        sys.path.insert(0, str(ops_tools))
        from take_snapshot import _run_one  # type: ignore

    capture = _run_one(device, command, timeout, platform)
    raw_output = capture.get("raw") or ""
    resolved_platform = platform or capture.get("platform") or "unknown"

    if not raw_output:
        return {
            "status": "failed",
            "parsed_rows": 0,
            "dsl": None,
            "frozen_path": None,
            "reason": "no raw output (SSH failed?)",
            "elapsed_seconds": 0.0,
        }

    # 2. Invoke the batch API with a single-sample list.
    sys.path.insert(0, str(_P(__file__).resolve().parent))
    from learn_commands import learn_commands  # type: ignore

    result = learn_commands(
        samples=[{
            "device": device,
            "platform": resolved_platform,
            "command": command,
            "raw_output": raw_output,
        }],
        budget_seconds=max(60, timeout + 30),
        max_workers=1,
        max_retries=2,
        allow_llm=True,
    )

    # 3. Shape the response.
    if result.newly_parsed:
        row = result.newly_parsed[0]
        frozen = result.frozen[0] if result.frozen else {}
        return {
            "status": "learned",
            "parsed_rows": len(row.get("parsed_data") or []),
            "dsl": frozen.get("dsl"),
            "frozen_path": None,  # registry decides path; leave to logs
            "reason": row.get("source", "learned"),
            "elapsed_seconds": result.elapsed_seconds,
        }
    if result.skipped:
        return {
            "status": "skipped",
            "parsed_rows": 0,
            "dsl": None,
            "frozen_path": None,
            "reason": result.skipped[0].get("reason", "skipped"),
            "elapsed_seconds": result.elapsed_seconds,
        }
    return {
        "status": "failed",
        "parsed_rows": 0,
        "dsl": None,
        "frozen_path": None,
        "reason": (result.failed[0].get("reason") if result.failed else "no parser produced"),
        "elapsed_seconds": result.elapsed_seconds,
    }
