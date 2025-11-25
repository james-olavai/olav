"""Simplified E2E tests for API infrastructure.

Tests basic API functionality without requiring orchestrator initialization.
Useful for validating API server, authentication, and basic endpoints.
"""

import asyncio
import os

import httpx
import pytest

# Set Windows event loop policy
if os.name == "nt":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


# Get server URL from environment variable (for Docker compatibility)
BASE_URL = os.getenv("OLAV_SERVER_URL", "http://localhost:8000")


@pytest.mark.asyncio
async def test_health_check():
    """Test basic health check endpoint."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/health", timeout=10.0)
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "version" in data


@pytest.mark.asyncio
async def test_login_success():
    """Test successful authentication."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_URL}/auth/login",
            json={"username": "admin", "password": "admin123"},
            timeout=10.0,
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_failure():
    """Test failed authentication."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_URL}/auth/login",
            json={"username": "wrong", "password": "wrong"},
            timeout=10.0,
        )
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_endpoint_with_auth():
    """Test /me endpoint with valid token."""
    async with httpx.AsyncClient() as client:
        # Login first
        login_response = await client.post(
            f"{BASE_URL}/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_response.json()["access_token"]
        
        # Test /me
        response = await client.get(
            f"{BASE_URL}/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "admin"
        assert data["role"] == "admin"


@pytest.mark.asyncio
async def test_me_endpoint_without_auth():
    """Test /me endpoint without token."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/me")
        # FastAPI returns 403 Forbidden when credentials are not provided
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_status_endpoint():
    """Test /status endpoint with auth."""
    async with httpx.AsyncClient() as client:
        # Login first
        login_response = await client.post(
            f"{BASE_URL}/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_response.json()["access_token"]
        
        # Test /status
        response = await client.get(
            f"{BASE_URL}/status",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "health" in data
        assert "user" in data
