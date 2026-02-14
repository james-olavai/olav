#!/usr/bin/env python3
"""Debug script to analyze query performance and data sources."""

import time
import asyncio
from rich.console import Console
from rich.table import Table

console = Console()

def measure_time(func):
    """Decorator to measure execution time."""
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        elapsed = (time.perf_counter() - start) * 1000  # Convert to ms
        return result, elapsed
    return wrapper

@measure_time
def test_database_query():
    """Test direct database query."""
    import duckdb
    conn = duckdb.connect('.olav/db/olav.duckdb')
    result = conn.execute("SELECT * FROM devices").fetchall()
    conn.close()
    return result

@measure_time
def test_guard_classify():
    """Test Guard classification."""
    from olav.agents.guard import get_guard
    guard = get_guard()
    result = guard.classify("list all devices")
    return result

@measure_time
def test_orchestrator_sync():
    """Test synchronous orchestrator."""
    from olav.agents.orchestrator import orchestrate_query_sync
    result = orchestrate_query_sync("list all devices")
    return result

@measure_time
def test_guard_route_and_execute():
    """Test Guard.route_and_execute()."""
    from olav.agents.guard import get_guard
    guard = get_guard()
    result = guard.route_and_execute("list all devices")
    return result

def main():
    console.print("[bold cyan]🔍 Performance Analysis: 'list all devices'[/bold cyan]\n")
    
    # Create results table
    table = Table(title="Execution Time Breakdown")
    table.add_column("Step", style="cyan", no_wrap=True)
    table.add_column("Time (ms)", justify="right", style="green")
    table.add_column("Status", style="yellow")
    
    # Test 1: Direct database query
    console.print("1️⃣ Testing direct database query...")
    try:
        result, elapsed = test_database_query()
        table.add_row("Database Query", f"{elapsed:.1f}", f"✅ {len(result)} devices")
        console.print(f"   Devices: {[row[1] for row in result]}")  # name column
    except Exception as e:
        table.add_row("Database Query", "N/A", f"❌ {str(e)[:50]}")
    
    console.print()
    
    # Test 2: Guard classification
    console.print("2️⃣ Testing Guard classification...")
    try:
        result, elapsed = test_guard_classify()
        table.add_row("Guard Classify", f"{elapsed:.1f}", f"✅ Route: {result.route}")
        console.print(f"   Route: {result.route}, Confidence: {result.confidence:.2f}")
    except Exception as e:
        table.add_row("Guard Classify", "N/A", f"❌ {str(e)[:50]}")
    
    console.print()
    
    # Test 3: Orchestrator sync
    console.print("3️⃣ Testing Orchestrator sync...")
    try:
        result, elapsed = test_orchestrator_sync()
        table.add_row("Orchestrator Sync", f"{elapsed:.1f}", f"✅ Status: {result.get('status', 'unknown')}")
        console.print(f"   Result keys: {list(result.keys())}")
        if 'data' in result:
            console.print(f"   Data type: {type(result['data'])}")
            if isinstance(result['data'], list):
                console.print(f"   Data count: {len(result['data'])}")
    except Exception as e:
        table.add_row("Orchestrator Sync", "N/A", f"❌ {str(e)[:50]}")
    
    console.print()
    
    # Test 4: Guard route_and_execute (full flow)
    console.print("4️⃣ Testing Guard.route_and_execute() (full flow)...")
    try:
        result, elapsed = test_guard_route_and_execute()
        table.add_row("Guard Full Flow", f"{elapsed:.1f}", f"✅ Status: {result.get('status', 'unknown')}")
        console.print(f"   Result keys: {list(result.keys())}")
        
        # Check if final_answer contains device info
        if 'final_answer' in result:
            answer = result['final_answer']
            console.print(f"   Answer preview: {answer[:200]}...")
            
            # Check for specific device names
            devices = ['R1', 'R2', 'R3', 'R4', 'SW1', 'SW2']
            found_devices = [d for d in devices if d in answer]
            console.print(f"   Found devices in answer: {found_devices}")
            
            # Check for model info
            if 'ISR4321' in answer or 'Catalyst' in answer:
                console.print("   ⚠️  Found model info in answer (ISR4321/Catalyst)")
                console.print("   ⚠️  But database has Model=None!")
    except Exception as e:
        table.add_row("Guard Full Flow", "N/A", f"❌ {str(e)[:50]}")
    
    console.print()
    console.print(table)
    
    # Additional analysis
    console.print("\n[bold yellow]📊 Data Source Analysis:[/bold yellow]")
    console.print("Database: Model=None, Vendor=None (all devices)")
    console.print("CLI Output: Shows ISR4321, Catalyst 3750 (specific models)")
    console.print("❓ Question: Where does model/version data come from?")

if __name__ == "__main__":
    main()
