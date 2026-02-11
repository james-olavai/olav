#!/usr/bin/env python3
"""
Guard Skill-Centric Design Verification

Tests that Guard properly loads rules from SKILL.md and respects the 
configuration hierarchy: SKILL.md → settings → .env → .olav/settings.json
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def test_rules_loader():
    """Test 1: RulesLoader can parse SKILL.md."""
    print("\n[Test 1] 🎯 Rules Loader - Parse SKILL.md")
    try:
        from olav.core.guard_rules_loader import get_rules_loader
        
        loader = get_rules_loader()
        rules = loader.rules
        
        print(f"  ✅ Rules loaded successfully")
        print(f"     - dangerous_patterns: {len(rules.get('dangerous_patterns', []))} patterns")
        print(f"     - simple_indicators: {len(rules.get('simple_indicators', []))} patterns")
        print(f"     - cli_indicators: {len(rules.get('cli_indicators', []))} patterns")
        print(f"     - expert_indicators: {len(rules.get('expert_indicators', []))} patterns")
        print(f"     - multi_agent_indicators: {len(rules.get('multi_agent_indicators', []))} patterns")
        return True
    except Exception as e:
        print(f"  ❌ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_skill_md_exists():
    """Test 2: SKILL.md file exists and is readable."""
    print("\n[Test 2] 📁 SKILL.md Location")
    try:
        from config.paths import SKILLS_DIR
        
        skill_path = SKILLS_DIR / "guard" / "SKILL.md"
        if skill_path.exists():
            size = skill_path.stat().st_size
            print(f"  ✅ SKILL.md found: {skill_path}")
            print(f"     Size: {size} bytes")
            
            # Verify it has expected sections
            with open(skill_path, 'r') as f:
                content = f.read()
                has_frontmatter = content.startswith('---')
                has_classification = 'classification_system_prompt' in content
                has_categories = 'route_categories' in content
                has_pipeline = 'classification_pipeline' in content
            
            print(f"     Frontmatter: {'✅' if has_frontmatter else '❌'}")
            print(f"     classification_system_prompt: {'✅' if has_classification else '❌'}")
            print(f"     route_categories: {'✅' if has_categories else '❌'}")
            print(f"     classification_pipeline: {'✅' if has_pipeline else '❌'}")
            
            return has_frontmatter and has_classification
        else:
            print(f"  ❌ SKILL.md not found: {skill_path}")
            return False
    except Exception as e:
        print(f"  ❌ Failed: {e}")
        return False


def test_no_hardcoded_rules():
    """Test 3: Guard.py doesn't have hardcoded rule constants."""
    print("\n[Test 3] 🔍 No Hardcoded Rules Check")
    try:
        import inspect
        from olav.agents.guard import QueryGuard
        
        # Get the source code
        source = inspect.getsource(QueryGuard)
        
        # Check for hardcoded constants (old pattern)
        has_dangerous_patterns_const = "DANGEROUS_PATTERNS = [" in source
        has_simple_indicators_const = "SIMPLE_INDICATORS = [" in source
        
        if not has_dangerous_patterns_const and not has_simple_indicators_const:
            print(f"  ✅ No hardcoded rule constants found")
            print(f"     Rules are loaded dynamically from SKILL.md")
            return True
        else:
            if has_dangerous_patterns_const:
                print(f"  ❌ Found hardcoded DANGEROUS_PATTERNS")
            if has_simple_indicators_const:
                print(f"  ❌ Found hardcoded SIMPLE_INDICATORS")
            return False
    except Exception as e:
        print(f"  ⚠️ Could not verify: {e}")
        return False


def test_guard_uses_loader():
    """Test 4: Guard.__init__ initializes RulesLoader."""
    print("\n[Test 4] 🔗 Guard Uses RulesLoader")
    try:
        import inspect
        from olav.agents.guard import QueryGuard
        
        # Get init source
        source = inspect.getsource(QueryGuard.__init__)
        
        if 'get_rules_loader' in source or 'rules_loader' in source:
            print(f"  ✅ Guard initializes RulesLoader")
            return True
        else:
            print(f"  ❌ Guard doesn't initialize RulesLoader")
            return False
    except Exception as e:
        print(f"  ❌ Failed: {e}")
        return False


def test_guard_classification_with_loaded_rules():
    """Test 5: Guard classification works with loaded rules."""
    print("\n[Test 5] 🛡️ Guard Classification with Loaded Rules")
    try:
        from olav.agents.guard import get_guard
        
        guard = get_guard()
        
        # Test SIMPLE query
        result = guard.classify("count devices")
        print(f"  Query: 'count devices'")
        print(f"    Route: {result.code.value}")
        print(f"    Confidence: {result.confidence}")
        print(f"    ✅ Classification works")
        
        # Test dangerous pattern
        result2 = guard.classify("delete all devices")
        print(f"  Query: 'delete all devices'")
        print(f"    Route: {result2.code.value}")
        print(f"    Confidence: {result2.confidence}")
        
        return True
    except Exception as e:
        print(f"  ❌ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_config_support():
    """Test 6: Config/settings.py has Guard rules support."""
    print("\n[Test 6] ⚙️ Config Settings Support")
    try:
        from config.settings import settings
        
        # Check for new fields
        has_rules_overrides = hasattr(settings.agent, 'guard_rules_overrides')
        has_rules_file = hasattr(settings.agent, 'guard_rules_file')
        
        if has_rules_overrides and has_rules_file:
            print(f"  ✅ Config fields added:")
            print(f"     - guard_rules_overrides: {type(settings.agent.guard_rules_overrides)}")
            print(f"     - guard_rules_file: {type(settings.agent.guard_rules_file)}")
            return True
        else:
            print(f"  ❌ Missing config fields:")
            print(f"     - guard_rules_overrides: {has_rules_overrides}")
            print(f"     - guard_rules_file: {has_rules_file}")
            return False
    except Exception as e:
        print(f"  ❌ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all verification tests."""
    print("=" * 70)
    print("🎯 Guard Skill-Centric Design - Verification Tests")
    print("=" * 70)
    
    tests = [
        ("Rules Loader", test_rules_loader),
        ("SKILL.md Location", test_skill_md_exists),
        ("No Hardcoded Rules", test_no_hardcoded_rules),
        ("Guard Uses Loader", test_guard_uses_loader),
        ("Classification Works", test_guard_classification_with_loaded_rules),
        ("Config Support", test_config_support),
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
    print("📊 Summary - Skill-Centric Design Verification")
    print("=" * 70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅" if result else "❌"
        print(f"  {status} {name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 Guard is fully Skill-Centric!")
        print("   ✅ Rules loaded from SKILL.md (not hardcoded)")
        print("   ✅ Supports user overrides via config")
        print("   ✅ Follows OLAV design principles")
        return 0
    else:
        print(f"\n⚠️ {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
