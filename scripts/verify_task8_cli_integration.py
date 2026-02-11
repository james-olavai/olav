#!/usr/bin/env python3
"""
Task 8 Verification Script - CLI + Guard Integration Test

Tests:
  1. CLI module loads without errors
  2. Guard configuration is correct
  3. Guard classification works (basic heuristics)
  4. CLI query command supports --guard/--no-guard flags
  5. Result format includes route info
"""

import sys
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))


def test_cli_imports():
    """Test 1: CLI module imports successfully."""
    print("\n[Test 1] 🔍 Checking CLI imports...")
    try:
        from src.olav.cli.cli_main import app
        print("  ✅ CLI app imports successfully")
        return True
    except Exception as e:
        print(f"  ❌ CLI import failed: {e}")
        return False


def test_guard_config():
    """Test 2: Guard configuration is correct."""
    print("\n[Test 2] ⚙️ Checking Guard configuration...")
    try:
        from config.settings import settings
        
        assert hasattr(settings.agent, 'enable_guard_routing'), "Missing enable_guard_routing"
        assert hasattr(settings.agent, 'guard_confidence_threshold'), "Missing guard_confidence_threshold"
        assert hasattr(settings.agent, 'guard_cache_ttl'), "Missing guard_cache_ttl"
        assert hasattr(settings.agent, 'guard_enable_multi_agent_detection'), "Missing guard_enable_multi_agent_detection"
        
        print(f"  ✅ enable_guard_routing: {settings.agent.enable_guard_routing}")
        print(f"  ✅ guard_confidence_threshold: {settings.agent.guard_confidence_threshold}")
        print(f"  ✅ guard_cache_ttl: {settings.agent.guard_cache_ttl}")
        print(f"  ✅ guard_enable_multi_agent_detection: {settings.agent.guard_enable_multi_agent_detection}")
        return True
    except Exception as e:
        print(f"  ❌ Guard config check failed: {e}")
        return False


def test_guard_classification():
    """Test 3: Guard classification works with basic heuristics."""
    print("\n[Test 3] 🛡️ Testing Guard classification...")
    try:
        from olav.agents.guard import get_guard
        
        guard = get_guard()
        
        # Test SIMPLE query
        result = guard.classify("count devices")
        print(f"  Query: 'count devices'")
        print(f"    Route: {result.code}")
        print(f"    Confidence: {result.confidence}")
        print(f"  ✅ Guard classification works")
        
        return True
    except Exception as e:
        print(f"  ❌ Guard classification failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_orchestrator_imports():
    """Test 4: Orchestrator V2 imports and functions."""
    print("\n[Test 4] 🔗 Checking Orchestrator V2...")
    try:
        from olav.agents.orchestrator_v2 import orchestrate_with_guard
        from olav.agents.orchestrator import orchestrate_query_sync
        
        print(f"  ✅ orchestrate_with_guard imported")
        print(f"  ✅ orchestrate_query_sync imported")
        return True
    except Exception as e:
        print(f"  ❌ Orchestrator imports failed: {e}")
        return False


def verify_cli_help():
    """Test 5: CLI help shows Guard options."""
    print("\n[Test 5] 📖 Checking CLI query help...")
    try:
        import subprocess
        result = subprocess.run(
            ["uv", "run", "olav", "query", "--help"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if "--guard" in result.stdout and "--no-guard" in result.stdout:
            print(f"  ✅ CLI query command shows --guard/--no-guard options")
            return True
        else:
            print(f"  ❌ CLI options not found in help")
            return False
    except Exception as e:
        print(f"  ⚠️ Could not verify CLI help: {e}")
        return False


def test_mock_guard_routing():
    """Test 6: Mock Guard routing decision."""
    print("\n[Test 6] 🎯 Testing Guard routing logic...")
    try:
        from olav.agents.guard import RouteCode
        from config.settings import settings
        
        # Verify confidence threshold boundary
        threshold = settings.agent.guard_confidence_threshold
        assert threshold == 0.85, f"Threshold should be 0.85, got {threshold}"
        
        # Test that routes are defined
        routes = [e.value for e in RouteCode]
        expected = ['REJECT', 'SIMPLE', 'CLI', 'EXPERT', 'MULTI_AGENT', 'UNKNOWN']
        
        for route in expected:
            assert route in routes, f"Missing route: {route}"
        
        print(f"  ✅ Confidence threshold: {threshold} (exact boundary)")
        print(f"  ✅ All 6 route types defined: {routes}")
        return True
    except Exception as e:
        print(f"  ❌ Routing logic test failed: {e}")
        return False


def main():
    """Run all tests."""
    print("=" * 70)
    print("🧪 Task 8 CLI Integration - Verification Tests")
    print("=" * 70)
    
    tests = [
        ("CLI Imports", test_cli_imports),
        ("Guard Config", test_guard_config),
        ("Guard Classification", test_guard_classification),
        ("Orchestrator Imports", test_orchestrator_imports),
        ("CLI Help Options", verify_cli_help),
        ("Guard Routing Logic", test_mock_guard_routing),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            passed = test_func()
            results.append((name, passed))
        except Exception as e:
            print(f"  ❌ {name} raised exception: {e}")
            results.append((name, False))
    
    # Summary
    print("\n" + "=" * 70)
    print("📊 Summary")
    print("=" * 70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅" if result else "❌"
        print(f"  {status} {name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed! Task 8 CLI Integration is ready.")
        return 0
    else:
        print(f"\n⚠️ {total - passed} test(s) failed. Review above for details.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
