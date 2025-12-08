"""Test CLI Client Basic Functionality (No DB Required).

Usage:
    python scripts/test_cli_basic.py
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))


async def test_client_structure():
    """Test client initialization structure."""
    from olav.cli.client import ExecutionResult, OLAVClient, ServerConfig

    print("🧪 Testing OLAV CLI Client Structure...\n")

    # Test 1: Client instantiation
    print("1️⃣ Testing client instantiation...")
    try:
        client = OLAVClient(mode="local")
        print("   ✅ OLAVClient created in local mode")
        assert client.mode == "local"
        assert client.orchestrator is None  # Not connected yet
        print(f"   Mode: {client.mode}")
        print(f"   Connected: {client.orchestrator is not None or client.remote_runnable is not None}")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        return False

    # Test 2: Remote client creation
    print("\n2️⃣ Testing remote client instantiation...")
    try:
        remote_client = OLAVClient(
            mode="remote", server_config=ServerConfig(base_url="http://localhost:8000")
        )
        print("   ✅ Remote client created")
        assert remote_client.mode == "remote"
        print(f"   Server URL: {remote_client.server_config.base_url if remote_client.server_config else 'N/A'}")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        return False

    # Test 3: ExecutionResult model
    print("\n3️⃣ Testing ExecutionResult model...")
    try:
        result = ExecutionResult(
            success=True, messages=[{"type": "ai", "content": "Hello"}], thread_id="test-123"
        )
        print("   ✅ ExecutionResult created")
        assert result.success is True
        assert len(result.messages) == 1
        print(f"   Success: {result.success}")
        print(f"   Messages: {len(result.messages)}")
        print(f"   Thread ID: {result.thread_id}")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        return False

    # Test 4: Display method
    print("\n4️⃣ Testing display_result method...")
    try:
        client.display_result(result)  # Uses client's internal console
        print("   ✅ Display method works")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        return False

    print("\n✅ All basic tests passed!")
    return True


if __name__ == "__main__":
    # Windows psycopg async compatibility
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(
            asyncio.WindowsSelectorEventLoopPolicy()  # type: ignore[attr-defined]
        )

    success = asyncio.run(test_client_structure())
    sys.exit(0 if success else 1)
