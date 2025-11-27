#!/usr/bin/env python
"""Test script for HITL (Human-in-the-Loop) workflow interruption.

This script verifies that:
1. DeepDive workflow triggers HITL interrupt after schema investigation
2. The interrupted state is properly returned to the client
3. The resume() method correctly continues the workflow
"""
import asyncio
import sys

# Windows async compatibility
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


async def test_deepdive_hitl():
    """Test DeepDive HITL interrupt and resume flow."""
    from rich.console import Console
    from olav.agents.root_agent_orchestrator import create_workflow_orchestrator
    
    console = Console()
    console.print("[bold cyan]Testing DeepDive HITL Flow[/bold cyan]\n")
    
    # Initialize orchestrator in expert mode
    console.print("1. Initializing orchestrator (expert_mode=True)...")
    orchestrator, stateful_graph, stateless_graph, checkpointer_mgr = await create_workflow_orchestrator(
        expert_mode=True
    )
    console.print("[green]✅ Orchestrator initialized[/green]\n")
    
    # Test query
    query = "分析为什么R1到R2(10.1.12.2)的eBGP邻居建立失败"
    # Use unique thread_id to avoid state persistence issues
    import time
    thread_id = f"test-hitl-deepdive-{int(time.time())}"
    
    console.print(f"2. Executing query: {query}")
    console.print(f"   Thread ID: {thread_id}\n")
    
    # Route to workflow (this should trigger DeepDive with HITL)
    result = await orchestrator.route(query, thread_id)
    
    console.print("[bold]Workflow Result:[/bold]")
    console.print(f"   - workflow_type: {result.get('workflow_type')}")
    console.print(f"   - interrupted: {result.get('interrupted')}")
    console.print(f"   - next_node: {result.get('next_node')}")
    console.print(f"   - execution_plan keys: {list(result.get('execution_plan', {}).keys()) if result.get('execution_plan') else 'None'}")
    console.print(f"   - todos count: {len(result.get('todos', []))}")
    
    if result.get("interrupted"):
        console.print("\n[yellow]⏸️ Workflow interrupted for HITL approval![/yellow]")
        
        # Show execution plan
        plan = result.get("execution_plan", {})
        todos = result.get("todos", [])
        
        console.print(f"\n   Feasible tasks: {len(plan.get('feasible_tasks', []))}")
        console.print(f"   Uncertain tasks: {len(plan.get('uncertain_tasks', []))}")
        console.print(f"   Infeasible tasks: {len(plan.get('infeasible_tasks', []))}")
        
        # Test resume with "Y" approval
        console.print("\n3. Testing resume with 'Y' approval...")
        from olav.workflows.base import WorkflowType
        
        resume_result = await orchestrator.resume(
            thread_id=thread_id,
            user_input="Y",
            workflow_type=WorkflowType.DEEP_DIVE,
        )
        
        console.print("[bold]Resume Result:[/bold]")
        console.print(f"   - interrupted: {resume_result.get('interrupted')}")
        console.print(f"   - aborted: {resume_result.get('aborted')}")
        console.print(f"   - final_message: {resume_result.get('final_message', 'None')[:200] if resume_result.get('final_message') else 'None'}...")
        
        if not resume_result.get("interrupted") and not resume_result.get("aborted"):
            console.print("\n[green]✅ HITL test PASSED! Workflow completed after approval.[/green]")
        elif resume_result.get("aborted"):
            console.print("\n[red]❌ HITL test FAILED: Workflow aborted unexpectedly.[/red]")
        else:
            console.print("\n[yellow]⚠️ Workflow still interrupted (may need more approvals).[/yellow]")
    else:
        console.print("\n[red]❌ HITL test FAILED: Workflow was NOT interrupted![/red]")
        console.print("   Check if DeepDive is using checkpointer for HITL support.")
    
    # Cleanup
    if hasattr(checkpointer_mgr, '__aexit__'):
        await checkpointer_mgr.__aexit__(None, None, None)
    elif hasattr(checkpointer_mgr, '__exit__'):
        checkpointer_mgr.__exit__(None, None, None)
    
    console.print("\n[dim]Test completed.[/dim]")


if __name__ == "__main__":
    asyncio.run(test_deepdive_hitl())
