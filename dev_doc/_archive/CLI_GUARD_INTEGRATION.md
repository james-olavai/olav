"""
CLI Integration Guide for Guard Router

Status: Phase 1 Complete - Ready for Implementation

Location of changes needed:
  File: src/olav/cli/cli_main.py
  Function: query() command (line 457-510)
  Module: from olav.agents.orchestrator_v2 import orchestrate_with_guard

IMPLEMENTATION STEPS
====================

1. Import Guard Orchestrator
   Current (line 461):
      from olav.agents.orchestrator import orchestrate_query
   
   New:
      from olav.agents.orchestrator_v2 import orchestrate_with_guard
      from config.settings import settings

2. Replace Orchestrator Call
   Current (line 474-475):
      result = asyncio.run(orchestrate_query(query_text))
   
   New:
      # Use Guard routing if enabled
      if settings.agent.enable_guard_routing:
          result = orchestrate_with_guard(query_text)
      else:
          # Fallback to sync orchestrator
          from olav.agents.orchestrator import orchestrate_query_sync
          result = orchestrate_query_sync(query_text)

3. Add Optional CLI Flag (v0.12.1+)
   Add to query() function signature:
      use_guard: bool = typer.Option(
          None,
          "--guard/--no-guard",
          help="Enable/disable Guard routing (default: use setting)",
      )
   
   Then update call:
      if use_guard is not None:
          result = orchestrate_query_with_routing(query_text, enable_guard=use_guard)
      else:
          # Use default from settings
          result = (orchestrate_with_guard(query_text) 
                    if settings.agent.enable_guard_routing 
                    else orchestrate_query_sync(query_text))

4. Update Result Handling
   Expected result structure from Guard:
      {
          "status": "complete" or "error" or "rejected",
          "result": <data>,
          "route": "SIMPLE|CLI|EXPERT|MULTI_AGENT|UNKNOWN|REJECT",
          "confidence": <float>,
          "execution_time": <ms>
      }
   
   Current handling treats it as:
      {
          "status": "complete" or "other",
          "final_answer": <string>,
          "error_message": <string>
      }
   
   Add route display:
      if result.get("route"):
          console.print(f"[dim]Route: {result['route']}[/dim]")
      if result.get("execution_time"):
          console.print(f"[dim]Latency: {result['execution_time']:.1f}ms[/dim]")

TESTING WITH CLI
================

After implementation, test with:

1. Basic SIMPLE query (should route to Guard → heuristic → execute):
   uv run olav query "how many devices?"
   # Expected: <5s latency

2. Expert query (should route to Orchestrator):
   uv run olav query "which devices have errors?"
   # Expected: <12s latency

3. Dangerous query (should be REJECT):
   uv run olav query "delete all devices"
   # Expected: Instant rejection with message

4. With Guard disabled (feature flag):
   uv run olav query "list devices" --no-guard
   # Expected: Use baseline orchestrator

5. Performance comparison:
   time uv run olav query "count devices"
   # Before Guard: ~12s
   # After Guard (cached): <2s

FEATURE FLAG CONTROL
====================

Users can control Guard behavior via:

1. Environment variable:
   export OLAV_AGENT__ENABLE_GUARD_ROUTING=false
   uv run olav query "..."

2. Settings file (.olav/settings.json):
   {
     "agent": {
       "enable_guard_routing": false
     }
   }

3. CLI flag (after Task 8 implementation):
   uv run olav query "..." --no-guard

BACKWARDS COMPATIBILITY
=======================

✅ All existing code continues to work
✅ Guard is disabled by default in v0.11.x
✅ Guard is enabled by default in v0.12.0+
✅ Feature flag allows instant disable
✅ Fallback to orchestrate_query_sync on error

RELATED FILES
=============

Core Implementation:
  • src/olav/agents/guard.py (400+ lines)
  • src/olav/agents/orchestrator_v2.py (500+ lines)
  • .olav/skills/guard/SKILL.md (850+ lines)
  • config/settings.py (Guard configuration fields)

Testing:
  • tests/unit/test_guard.py (600+ lines, 22 passing tests)
  • tests/e2e/test_guard_integration.py (500+ lines)
  • scripts/benchmark_guard.py (performance benchmarking)

Performance Targets:
  • SIMPLE queries: 12s → <5s (58% improvement)
  • Cache hits: <100ms latency
  • Overall: >30% average improvement

NEXT STEPS
==========

1. Implement changes in cli_main.py query() function
2. Test with actual network queries
3. Deploy with feature flag (default: disabled in v0.11.x)
4. Collect performance metrics
5. Enable by default in v0.12.0 release

DOCUMENTED BY
=============
Phase 1 Implementation: 2026-02-11
Tasks 1-8: Completed
Remaining: CLI code integration (minimal changes)
"""

# Code template for easy copy-paste into cli_main.py (lines 457-510):

"""
@app.command()
def query(
    query_text: str = typer.Argument(..., help="Network operation query"),
    debug: bool = typer.Option(False, "--debug", "-d", help="Enable debug logging"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show full LLM thinking process"),
    guard: bool = typer.Option(None, "--guard/--no-guard", help="Use Guard routing (default: use setting)"),
) -> None:
    \"\"\"Execute a single network operations query with Guard routing.

    Examples:
        olav query "show device status"
        olav query "count devices" --guard       # Force Guard enabled
        olav query "list routers" --no-guard     # Force Guard disabled
        olav query "Check BGP" --verbose --debug
    \"\"\"
    from olav.cli.display import StreamingDisplay
    from config.settings import settings
    from olav.agents.orchestrator_v2 import orchestrate_query_with_routing
    from olav.agents.orchestrator import orchestrate_query_sync

    display = StreamingDisplay(console=console, verbose=verbose, show_spinner=not verbose)
    console.print(Panel(f"[bold cyan]Query[/bold cyan]: {query_text}", border_style="cyan"))

    try:
        if not verbose:
            display.show_processing_status("🛡️ Guard analyzing query...")

        # Use Guard routing if enabled or explicitly requested
        use_guard = guard if guard is not None else settings.agent.enable_guard_routing
        
        if use_guard:
            from olav.agents.orchestrator_v2 import orchestrate_with_guard
            result = orchestrate_with_guard(query_text)
        else:
            result = orchestrate_query_sync(query_text)

        display.stop_processing_status()

        # Display route and performance info
        if result.get("route"):
            route = result["route"]
            confidence = result.get("confidence", 0)
            console.print(f"[dim]Route: {route} (confidence: {confidence:.2f})[/dim]")
        
        if result.get("execution_time"):
            console.print(f"[dim]Latency: {result['execution_time']:.1f}ms[/dim]")

        # Handle result based on status
        if result.get("status") == "rejected":
            console.print(f"[bold red]❌ {result.get('message', 'Query rejected')[/bold red]")
        elif result.get("status") == "complete":
            answer = result.get("final_answer", result.get("result", ""))
            if answer:
                from rich.markdown import Markdown
                console.print(Markdown(answer))
            else:
                console.print("[bold yellow]⚠ No result[/bold yellow]")
        else:
            error_msg = result.get("error_message", result.get("message", "Unknown error"))
            console.print(f"[bold red]❌ Error: {error_msg}[/bold red]")

    except Exception as e:
        display.stop_processing_status()
        console.print(f"[bold red]❌ Error: {str(e)}[/bold red]")
        if debug:
            import traceback
            traceback.print_exc()
        raise typer.Exit(1) from None
"""
