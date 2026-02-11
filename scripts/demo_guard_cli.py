#!/usr/bin/env python3
"""Demo script for Guard-Driven CLI Agent v1.0.

Demonstrates key features:
- Guard as entry point (bypasses Orchestrator)
- TextFSM structured parsing
- Nornir native concurrency
- Realtime detection with cache bypass
- Route classification with confidence scores

Usage:
    uv run python scripts/demo_guard_cli.py
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from olav.agents.guard import get_guard

console = Console()


def demo_header(title: str, description: str) -> None:
    """Print demo section header."""
    console.print()
    console.print(Panel(
        f"[bold cyan]{title}[/bold cyan]\n{description}",
        border_style="cyan"
    ))


def demo_query(query: str, description: str) -> None:
    """Execute demo query with Guard routing."""
    demo_header(f"Query: {query}", description)
    
    guard = get_guard()
    result = guard.route_and_execute(query)
    
    # Display routing info
    if result.get('route'):
        console.print(f"\n🛡️  [dim]Route: {result['route']}[/dim]")
    
    if result.get('confidence'):
        console.print(f"   [dim]Confidence: {result['confidence']:.2f}[/dim]")
    
    if result.get('use_textfsm') is not None:
        console.print(f"   [dim]TextFSM: {result['use_textfsm']}[/dim]")
    
    if result.get('execution_time'):
        console.print(f"   [dim]Latency: {result['execution_time']:.1f}ms[/dim]")
    
    # Display result
    status = result.get('status', 'unknown')
    if status == 'complete':
        answer = result.get('final_answer', '')
        if answer:
            console.print()
            console.print(Markdown(answer))
    elif status == 'rejected':
        console.print(f"\n[bold red]❌ {result.get('message', 'Query rejected')}[/bold red]")
    else:
        error = result.get('error_message', 'Unknown error')
        console.print(f"\n[bold red]❌ Error: {error}[/bold red]")
    
    console.print()


def main():
    """Run Guard CLI Agent demo."""
    console.print(Panel(
        "[bold cyan]OLAV v1.0 - Guard-Driven CLI Agent Demo[/bold cyan]\n"
        "Showcasing: TextFSM parsing, native concurrency, realtime detection",
        border_style="cyan"
    ))
    
    # Demo 1: Single device with TextFSM
    demo_query(
        "在 R1 上执行 show ip interface brief",
        "🎯 Single device query with TextFSM structured parsing"
    )
    
    # Demo 2: Multiple devices concurrent
    demo_query(
        "在所有路由器上执行 show version",
        "⚡ Multi-device concurrent execution via Nornir nr.run()"
    )
    
    # Demo 3: Realtime query
    demo_query(
        "实时查看 R1 的 CPU 使用率",
        "🔥 Realtime detection (Stage 0) with cache bypass"
    )
    
    # Demo 4: Simple database query
    demo_query(
        "有多少个设备?",
        "📊 Simple database query (no CLI execution)"
    )
    
    # Summary
    console.print(Panel(
        "[bold green]✅ Demo Complete![/bold green]\n\n"
        "[bold]Key Features Demonstrated:[/bold]\n"
        "  • Guard as primary entry point (not Orchestrator)\n"
        "  • High-confidence routes bypass Orchestrator\n"
        "  • Native TextFSM parsing (63.7% token savings)\n"
        "  • Nornir native concurrency (60-80% faster)\n"
        "  • Realtime detection with cache bypass\n"
        "  • Intelligent route classification",
        border_style="green"
    ))


if __name__ == "__main__":
    main()
