#!/usr/bin/env python3
"""
CLI 快速诊断脚本 - OLAV v2.0

Usage:
    python scripts/diagnose_cli.py

This script checks:
1. Interactive mode functionality
2. FileHistory initialization
3. Slash commands registration
4. Session management
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from config.paths import USER_HISTORY_PATH, OLAV_BASE_DIR
from config.settings import settings


def check_tty():
    """Check if running in TTY mode."""
    is_tty = sys.stdin.isatty()
    print(f"✓ TTY Mode: {is_tty}")
    return is_tty


def check_history_file():
    """Check if history file exists and is accessible."""
    if USER_HISTORY_PATH.exists():
        size = USER_HISTORY_PATH.stat().st_size
        print(f"✓ History File: {USER_HISTORY_PATH} ({size} bytes)")
        
        # Show last 5 lines
        try:
            with open(USER_HISTORY_PATH) as f:
                lines = f.readlines()
                if lines:
                    print(f"  Last {min(5, len(lines))} commands:")
                    for line in lines[-5:]:
                        print(f"    {line.strip()}")
                else:
                    print("  (empty)")
        except Exception as e:
            print(f"  ✗ Failed to read: {e}")
    else:
        print(f"⚠️  History File: Not found at {USER_HISTORY_PATH}")
        print(f"  Will be created on first use")
    
    return USER_HISTORY_PATH.exists()


def check_slash_commands():
    """Check if slash commands are registered."""
    try:
        from olav.cli.commands.builtin import SLASH_COMMANDS
        
        print(f"✓ Slash Commands Registered: {len(SLASH_COMMANDS)}")
        print(f"  Available commands:")
        for cmd in sorted(SLASH_COMMANDS.keys()):
            print(f"    /{cmd}")
        
        return True
    except Exception as e:
        print(f"✗ Failed to load slash commands: {e}")
        return False


def check_session():
    """Check if session can be initialized."""
    try:
        from olav.cli.session import OlavPromptSession
        
        session = OlavPromptSession(enable_completion=False)
        print(f"✓ Session Initialized: {session._session is not None}")
        print(f"  Multiline: {session.multiline}")
        print(f"  TTY: {session.is_tty}")
        
        return True
    except Exception as e:
        print(f"✗ Failed to initialize session: {e}")
        import traceback
        traceback.print_exc()
        return False


def check_agent():
    """Check if agent can be created."""
    try:
        from olav.agents.agent import create_olav_agent
        
        agent = create_olav_agent()
        print(f"✓ Agent Created: {agent is not None}")
        
        return True
    except Exception as e:
        print(f"✗ Failed to create agent: {e}")
        return False


def check_entry_point():
    """Check CLI entry points."""
    try:
        import toml
        
        pyproject = project_root / "pyproject.toml"
        with open(pyproject) as f:
            config = toml.load(f)
        
        scripts = config.get("project", {}).get("scripts", {})
        print(f"✓ Entry Points:")
        for name, target in scripts.items():
            print(f"  {name} -> {target}")
        
        return True
    except Exception as e:
        print(f"⚠️  Failed to read pyproject.toml: {e}")
        return False


def test_execute_command():
    """Test execute_command function."""
    try:
        import asyncio
        from olav.cli.commands.builtin import execute_command
        
        print("\n🧪 Testing execute_command:")
        
        # Test /help
        result = asyncio.run(execute_command("/help", agent=None))
        if result and "OLAV" in result:
            print("  ✓ /help works")
        else:
            print(f"  ✗ /help failed: {result}")
        
        # Test /devices
        result = asyncio.run(execute_command("/devices", agent=None))
        if result:
            print("  ✓ /devices works")
        else:
            print(f"  ⚠️  /devices returned empty")
        
        return True
        
    except Exception as e:
        print(f"  ✗ execute_command failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all diagnostic checks."""
    print("=" * 60)
    print("OLAV CLI Diagnostic Tool")
    print("=" * 60)
    print()
    
    results = {}
    
    print("📋 System Checks:")
    print("-" * 60)
    results["tty"] = check_tty()
    results["history"] = check_history_file()
    results["entry_point"] = check_entry_point()
    
    print()
    print("🔧 Component Checks:")
    print("-" * 60)
    results["slash_commands"] = check_slash_commands()
    results["session"] = check_session()
    results["agent"] = check_agent()
    
    print()
    print("🧪 Functional Tests:")
    print("-" * 60)
    results["execute_command"] = test_execute_command()
    
    print()
    print("=" * 60)
    print("📊 Summary:")
    print("=" * 60)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for name, status in results.items():
        icon = "✅" if status else "❌"
        print(f"{icon} {name}")
    
    print()
    print(f"Result: {passed}/{total} checks passed")
    
    if passed == total:
        print("\n✅ All checks passed! CLI should work correctly.")
        print("\nTo test interactively:")
        print("  uv run olav")
        print("  OLAV> /help")
        print("  OLAV> [Press ↑ arrow to test history]")
    else:
        print("\n⚠️  Some checks failed. See details above.")
        print("\nRecommended actions:")
        if not results.get("history"):
            print("  • History will be created on first interactive use")
        if not results.get("slash_commands"):
            print("  • Check builtin.py for import errors")
        if not results.get("session"):
            print("  • Check prompt_toolkit installation: uv pip list | grep prompt")
        if not results.get("agent"):
            print("  • Check agent.py and dependencies")
    
    print()
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
