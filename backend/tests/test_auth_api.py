import pytest
from httpx import AsyncClient

from app.core.config import get_settings


@pytest.fixture
def oidc_only_settings():
    settings = get_settings()
    old = settings.model_dump()
    settings.oidc_enabled = True
    settings.oidc_discovery_url = "https://id.example.com/.well-known/openid-configuration"
    settings.oidc_client_id = "securo"
    settings.local_auth_enabled = False
    yield settings
    for key, value in old.items():
        setattr(settings, key, value)


@pytest.mark.asyncio
async def test_register(client: AsyncClient, clean_db):
    response = await client.post(
        "/api/auth/register",
        json={"email": "new@example.com", "password": "newpass123"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "new@example.com"
    assert "id" in data
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient, test_user):
    response = await client.post(
        "/api/auth/register",
        json={"email": "test@example.com", "password": "otherpass123"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_login(client: AsyncClient, test_user):
    response = await client.post(
        "/api/auth/login",
        data={"username": "test@example.com", "password": "testpass123"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient, test_user):
    response = await client.post(
        "/api/auth/login",
        data={"username": "test@example.com", "password": "wrongpass"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_get_me(client: AsyncClient, auth_headers):
    response = await client.get("/api/users/me", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "test@example.com"
    assert data["preferences"]["language"] == "pt-BR"


@pytest.mark.asyncio
async def test_get_me_unauthenticated(client: AsyncClient, clean_db):
    response = await client.get("/api/users/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_forbidden_when_local_auth_disabled(client: AsyncClient, test_user, oidc_only_settings):
    response = await client.post(
        "/api/auth/login",
        data={"username": "test@example.com", "password": "testpass123"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "LOCAL_AUTH_DISABLED"
