"""Test Authentication Module.

Usage:
    python scripts/test_auth.py
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))


async def test_auth_module():
    """Test authentication module components."""
    from olav.cli.auth import AuthClient, Credentials, CredentialsManager

    print("🧪 Testing OLAV Authentication Module...\n")

    # Test 1: CredentialsManager instantiation
    print("1️⃣ Testing CredentialsManager...")
    try:
        # Use temp path for testing
        test_creds_path = Path.home() / ".olav" / "test_credentials"
        creds_manager = CredentialsManager(credentials_path=test_creds_path)
        print(f"   ✅ CredentialsManager created")
        print(f"   Path: {creds_manager.credentials_path}")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        return False

    # Test 2: Credentials model
    print("\n2️⃣ Testing Credentials model...")
    try:
        from datetime import datetime, timedelta

        expires_at = (datetime.now() + timedelta(hours=1)).isoformat()
        credentials = Credentials(
            server_url="http://localhost:8000",
            access_token="eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.test",
            token_type="bearer",
            expires_at=expires_at,
            username="testuser",
        )
        print("   ✅ Credentials model created")
        print(f"   Username: {credentials.username}")
        print(f"   Server: {credentials.server_url}")
        print(f"   Expires: {credentials.expires_at}")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        return False

    # Test 3: Save/Load credentials
    print("\n3️⃣ Testing save/load credentials...")
    try:
        # Save
        creds_manager.save(credentials)
        print("   ✅ Credentials saved")

        # Load
        loaded_creds = creds_manager.load()
        if loaded_creds is None:
            print("   ❌ Failed to load credentials")
            return False

        print("   ✅ Credentials loaded")
        assert loaded_creds.username == credentials.username
        assert loaded_creds.server_url == credentials.server_url
        print(f"   Loaded username: {loaded_creds.username}")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        return False

    # Test 4: Token expiration check
    print("\n4️⃣ Testing token expiration check...")
    try:
        is_expiring = creds_manager.is_token_expiring_soon(credentials, threshold_minutes=5)
        print(f"   ✅ Token expiring soon: {is_expiring}")
        assert is_expiring is False  # Should have 1 hour left
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        return False

    # Test 5: Delete credentials
    print("\n5️⃣ Testing delete credentials...")
    try:
        creds_manager.delete()
        print("   ✅ Credentials deleted")

        # Verify deleted
        loaded_after_delete = creds_manager.load()
        if loaded_after_delete is not None:
            print("   ❌ Credentials still exist after delete")
            return False
        print("   ✅ Verified deletion")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        return False

    # Test 6: AuthClient instantiation
    print("\n6️⃣ Testing AuthClient...")
    try:
        auth_client = AuthClient(server_url="http://localhost:8000")
        print("   ✅ AuthClient created")
        print(f"   Server: {auth_client.server_url}")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        return False

    # Test 7: Get auth header
    print("\n7️⃣ Testing get_auth_header...")
    try:
        headers = auth_client.get_auth_header(credentials)
        print("   ✅ Auth header generated")
        print(f"   Authorization: {headers.get('Authorization', '')[:50]}...")
        assert "Authorization" in headers
        assert headers["Authorization"].startswith("bearer ")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        return False

    print("\n✅ All authentication module tests passed!")
    return True


if __name__ == "__main__":
    # Windows psycopg async compatibility
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(
            asyncio.WindowsSelectorEventLoopPolicy()  # type: ignore[attr-defined]
        )

    success = asyncio.run(test_auth_module())
    sys.exit(0 if success else 1)
