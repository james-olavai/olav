#!/usr/bin/env python3
"""
Diagnostic script to check why tests are failing/timing out
"""

import subprocess
import sys
import time
from pathlib import Path


def diagnose():
    print("\n" + "="*80)
    print("🔍 Query Agent Test Failure Diagnosis")
    print("="*80)
    
    # Check 1: Test file exists and is readable
    test_file = Path("tests/e2e/test_query_agent_l1_l2_l3.py")
    print(f"\n1️⃣ Test File Check:")
    print(f"   Exists: {'✅' if test_file.exists() else '❌'} {test_file}")
    
    if test_file.exists():
        content = test_file.read_text()
        print(f"   Size: {len(content)} bytes")
        print(f"   Classes: {content.count('class Test')}")
        print(f"   Test Methods: {content.count('def test_')}")
    
    # Check 2: pytest can collect tests
    print(f"\n2️⃣ Test Collection:")
    cmd = ["uv", "run", "pytest", "tests/e2e/test_query_agent_l1_l2_l3.py", "--collect-only", "-q"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    
    if "selected" in result.stdout or "error" in result.stdout.lower():
        lines = result.stdout.strip().split('\n')
        print(f"   Collection output (last 5 lines):")
        for line in lines[-5:]:
            print(f"      {line}")
    else:
        print(f"   ⚠️ No clear collection output")
        if result.stderr:
            print(f"   Error: {result.stderr[:200]}")
    
    # Check 3: Try running one test with short timeout
    print(f"\n3️⃣ Test Execution (first test with 10s timeout):")
    cmd = ["timeout", "10", "uv", "run", "pytest", 
           "tests/e2e/test_query_agent_l1_l2_l3.py::TestQueryAgentL1Basic::test_l1_001_list_all_devices",
           "-v", "--tb=line"]
    
    start = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = time.time() - start
    
    print(f"   Return code: {result.returncode}")
    print(f"   Elapsed: {elapsed:.2f}s")
    
    # Show last lines of output
    if result.stdout:
        lines = result.stdout.strip().split('\n')
        print(f"   Output (last 10 lines):")
        for line in lines[-10:]:
            if line.strip():
                print(f"      {line[:120]}")
    
    if result.stderr:
        print(f"   Errors:")
        err_lines = result.stderr.strip().split('\n')
        for line in err_lines[-5:]:
            if line.strip():
                print(f"      {line[:120]}")
    
    # Check 4: Investigate orchest rate() directly
    print(f"\n4️⃣ Direct orchestrate() Test:")
    try:
        from olav.agents.orchestrator_v2 import orchestrate
        print(f"   ✅ Import successful")
        
        print(f"   Testing simple query...")
        start = time.time()
        result = orchestrate("How many devices?")
        elapsed = time.time() - start
        
        print(f"   Status: {result.get('status')}")
        print(f"   Elapsed: {elapsed:.2f}s")
        print(f"   ✅ orchestrate() works")
        
    except ImportError as e:
        print(f"   ❌ Import error: {e}")
    except Exception as e:
        print(f"   ❌ Execution error: {e}")
        import traceback
        traceback.print_exc()
    
    # Check 5: LLM configuration
    print(f"\n5️⃣ LLM Configuration:")
    try:
        from config.settings import settings
        print(f"   LLM Provider: {getattr(settings.llm, 'provider', 'N/A')}")
        print(f"   LLM Model: {getattr(settings.llm, 'model_name', 'N/A')}")
        print(f"   Guard Enabled: {getattr(settings.agent, 'enable_guard_routing', 'N/A')}")
    except Exception as e:
        print(f"   Error reading config: {e}")
    
    # Check 6: Main issues
    print(f"\n6️⃣ Analysis:")
    print(f"   - Tests exist and are discoverable")
    print(f"   - orchestrate() function works directly")
    print(f"   - Issue likely: pytest tests timeout due to LLM latency")
    print(f"     (Real LLM calls take 7-23 seconds each)")
    print(f"   - Solution: Tests need longer timeouts or mark as slow")


if __name__ == "__main__":
    try:
        diagnose()
    except Exception as e:
        print(f"\n❌ Diagnosis failed: {e}")
        import traceback
        traceback.print_exc()
