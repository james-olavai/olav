"""Smoke test for OLAV API Server (LangServe).

Usage:
    python scripts/test_api_server.py
"""

import asyncio
import sys
from pathlib import Path

# Add src and config to path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))
sys.path.insert(0, str(project_root))  # For config module


async def test_server_startup():
    """Test FastAPI server startup and basic endpoints."""
    print("🧪 Testing OLAV API Server startup...")

    from olav.server.app import create_app

    app = create_app()

    # Test health check endpoint
    from fastapi.testclient import TestClient

    client = TestClient(app)

    print("\n1️⃣ Testing /health endpoint (no auth)...")
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    print(f"   Status: {data['status']}")
    print(f"   Version: {data['version']}")
    print(f"   Environment: {data['environment']}")
    print(f"   ✅ Health check passed")

    print("\n2️⃣ Testing /auth/login endpoint...")
    login_response = client.post(
        "/auth/login", json={"username": "admin", "password": "admin123"}
    )
    assert login_response.status_code == 200
    token_data = login_response.json()
    access_token = token_data["access_token"]
    print(f"   Token type: {token_data['token_type']}")
    print(f"   Access token: {access_token[:20]}...")
    print(f"   ✅ Login successful")

    print("\n3️⃣ Testing /me endpoint (requires auth)...")
    me_response = client.get("/me", headers={"Authorization": f"Bearer {access_token}"})
    assert me_response.status_code == 200
    user_data = me_response.json()
    print(f"   Username: {user_data['username']}")
    print(f"   Role: {user_data['role']}")
    print(f"   ✅ Authentication working")

    print("\n4️⃣ Testing unauthorized access...")
    unauth_response = client.get("/status")
    assert unauth_response.status_code == 403  # No auth header
    print(f"   Status: {unauth_response.status_code} (expected 403)")
    print(f"   ✅ Unauthorized access blocked")

    print("\n5️⃣ Testing /status endpoint (with auth)...")
    status_response = client.get("/status", headers={"Authorization": f"Bearer {access_token}"})
    assert status_response.status_code == 200
    status_data = status_response.json()
    print(f"   PostgreSQL: {status_data['health']['postgres_connected']}")
    print(f"   Orchestrator: {status_data['health']['orchestrator_ready']}")
    print(f"   User: {status_data['user']['username']} ({status_data['user']['role']})")
    print(f"   ✅ Status endpoint working")

    print("\n6️⃣ Checking OpenAPI documentation...")
    docs_response = client.get("/docs")
    assert docs_response.status_code == 200
    print(f"   Swagger UI available at /docs")
    redoc_response = client.get("/redoc")
    assert redoc_response.status_code == 200
    print(f"   Redoc available at /redoc")
    print(f"   ✅ API documentation generated")

    print("\n✅ All tests passed! API server is ready.")
    print("\n📖 Next steps:")
    print("   1. Start server: uv run python src/olav/server/app.py")
    print("   2. Visit docs: http://localhost:8000/docs")
    print("   3. Test login: curl -X POST http://localhost:8000/auth/login \\")
    print('      -H "Content-Type: application/json" \\')
    print('      -d \'{"username": "admin", "password": "admin123"}\'')


if __name__ == "__main__":
    asyncio.run(test_server_startup())
