"""Test Authentication CLI Commands (End-to-End).

Tests login, logout, and whoami commands with mock server.

Usage:
    python scripts/test_auth_cli.py
"""

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add src to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))


async def test_auth_cli_flow():
    """Test complete authentication flow."""
    from olav.cli.auth import AuthClient, Credentials, CredentialsManager

    print("🧪 Testing OLAV Authentication CLI Flow...\n")

    # Setup test environment
    test_creds_path = Path.home() / ".olav" / "test_cli_credentials"
    creds_manager = CredentialsManager(credentials_path=test_creds_path)

    # Cleanup previous test data
    if test_creds_path.exists():
        creds_manager.delete()

    # Test 1: Check status before login
    print("1️⃣ Testing whoami (before login)...")
    try:
        loaded_creds = creds_manager.load()
        if loaded_creds is None:
            print("   ✅ Not authenticated (expected)")
        else:
            print(f"   ❌ Unexpected credentials found: {loaded_creds.username}")
            return False
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        return False

    # Test 2: Manual login (simulate successful authentication)
    print("\n2️⃣ Testing login (manual simulation)...")
    try:
        expires_at = (datetime.now() + timedelta(minutes=60)).isoformat()
        test_credentials = Credentials(
            server_url="http://localhost:8000",
            access_token="eyJ0eXAiOiJKV1QiLCJhbGci.simulated.token",
            token_type="bearer",
            expires_at=expires_at,
            username="testadmin",
        )

        creds_manager.save(test_credentials)
        print("   ✅ Login simulated successfully")
        print(f"   Username: {test_credentials.username}")
        print(f"   Server: {test_credentials.server_url}")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        return False

    # Test 3: Check status after login
    print("\n3️⃣ Testing whoami (after login)...")
    try:
        loaded_creds = creds_manager.load()
        if loaded_creds is None:
            print("   ❌ Credentials not found after login")
            return False

        print("   ✅ Authenticated")
        print(f"   Username: {loaded_creds.username}")
        print(f"   Server: {loaded_creds.server_url}")

        # Verify expiration
        expires_at_dt = datetime.fromisoformat(loaded_creds.expires_at)
        time_remaining = (expires_at_dt - datetime.now()).total_seconds() / 60
        print(f"   Expires in: {int(time_remaining)} minutes")

        if time_remaining < 0:
            print("   ❌ Token already expired")
            return False
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        return False

    # Test 4: Test auth header generation
    print("\n4️⃣ Testing auth header generation...")
    try:
        auth_client = AuthClient(
            server_url="http://localhost:8000", credentials_manager=creds_manager
        )
        headers = auth_client.get_auth_header(loaded_creds)

        print("   ✅ Auth header generated")
        print(f"   Authorization: {headers['Authorization'][:40]}...")

        assert headers["Authorization"].startswith("bearer ")
        assert "eyJ0eXAi" in headers["Authorization"]
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        return False

    # Test 5: Test token expiration check
    print("\n5️⃣ Testing token expiration logic...")
    try:
        is_expiring_soon = creds_manager.is_token_expiring_soon(
            loaded_creds, threshold_minutes=5
        )
        print(f"   ✅ Token expiring soon (5min threshold): {is_expiring_soon}")

        # Should be False since we set 60 minutes
        if is_expiring_soon:
            print("   ❌ Token should not be expiring yet (60min remaining)")
            return False

        # Test with high threshold
        is_expiring_soon_high = creds_manager.is_token_expiring_soon(
            loaded_creds, threshold_minutes=120
        )
        print(f"   ✅ Token expiring soon (120min threshold): {is_expiring_soon_high}")

        # Should be True since threshold > remaining time
        if not is_expiring_soon_high:
            print("   ❌ Token should be expiring with 120min threshold")
            return False
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        return False

    # Test 6: Test logout
    print("\n6️⃣ Testing logout...")
    try:
        await auth_client.logout()
        print("   ✅ Logout successful")

        # Verify credentials deleted
        loaded_after_logout = creds_manager.load()
        if loaded_after_logout is not None:
            print("   ❌ Credentials still exist after logout")
            return False

        print("   ✅ Credentials removed")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        return False

    # Test 7: Check status after logout
    print("\n7️⃣ Testing whoami (after logout)...")
    try:
        final_creds = creds_manager.load()
        if final_creds is None:
            print("   ✅ Not authenticated (expected after logout)")
        else:
            print(f"   ❌ Unexpected credentials: {final_creds.username}")
            return False
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        return False

    print("\n✅ All authentication CLI flow tests passed!")
    print("\n📋 Summary:")
    print("   - whoami: before login → NOT authenticated ✅")
    print("   - login: simulate → credentials saved ✅")
    print("   - whoami: after login → authenticated ✅")
    print("   - auth header: generated correctly ✅")
    print("   - token expiration: logic verified ✅")
    print("   - logout: credentials removed ✅")
    print("   - whoami: after logout → NOT authenticated ✅")

    return True


if __name__ == "__main__":
    # Windows psycopg async compatibility
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(
            asyncio.WindowsSelectorEventLoopPolicy()  # type: ignore[attr-defined]
        )

    success = asyncio.run(test_auth_cli_flow())
    sys.exit(0 if success else 1)
