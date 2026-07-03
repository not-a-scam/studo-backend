import pytest

from conftest import auth_headers, issue_refresh_token


@pytest.mark.asyncio
async def test_register_and_login_success(client):
    register_payload = {
        "email": "auth_user@example.com",
        "password": "password123",
        "full_name": "Auth User",
    }

    register_response = await client.post("/auth/register", json=register_payload)
    assert register_response.status_code == 200

    login_response = await client.post(
        "/auth/token",
        data={"username": register_payload["email"], "password": register_payload["password"]},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert login_response.status_code == 200
    body = login_response.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"
    assert "refresh_token" in body


@pytest.mark.asyncio
async def test_refresh_token_issues_new_access_token(client):
    register_payload = {
        "email": "refresh_user@example.com",
        "password": "password123",
        "full_name": "Refresh User",
    }

    await client.post("/auth/register", json=register_payload)
    refresh_token = await issue_refresh_token(client, register_payload["email"], register_payload["password"])

    response = await client.post("/auth/refresh", json={"refresh_token": refresh_token})

    assert response.status_code == 200
    body = response.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"
    assert body["refresh_token"] == refresh_token


@pytest.mark.asyncio
async def test_refresh_token_cannot_access_protected_routes(client):
    register_payload = {
        "email": "refresh_guard_user@example.com",
        "password": "password123",
        "full_name": "Refresh Guard User",
    }

    await client.post("/auth/register", json=register_payload)
    refresh_token = await issue_refresh_token(client, register_payload["email"], register_payload["password"])

    response = await client.get(
        "/api/groups",
        headers={"Authorization": f"Bearer {refresh_token}"},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_register_duplicate_user_returns_conflict(client):
    payload = {
        "email": "duplicate_user@example.com",
        "password": "password123",
        "full_name": "Duplicate User",
    }

    first = await client.post("/auth/register", json=payload)
    second = await client.post("/auth/register", json=payload)

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"] == "User already exists"


@pytest.mark.asyncio
async def test_login_with_invalid_credentials_returns_401(client):
    response = await client.post(
        "/auth/token",
        data={"username": "missing@example.com", "password": "wrong-password"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect username or password"


@pytest.mark.asyncio
async def test_protected_route_requires_auth(client):
    response = await client.get("/api/groups")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_protected_route_with_auth_success(client, db_session):
    await client.post(
        "/auth/register",
        json={
            "email": "group_user@example.com",
            "password": "password123",
            "full_name": "Group User",
        },
    )

    headers = await auth_headers(client, "group_user@example.com", "password123")
    response = await client.get("/api/groups", headers=headers)
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_cookie_auth_flow(client):
    register_payload = {
        "email": "cookie_user@example.com",
        "password": "password123",
        "full_name": "Cookie User",
    }
    await client.post("/auth/register", json=register_payload)

    login_response = await client.post(
        "/auth/token",
        data={"username": register_payload["email"], "password": register_payload["password"]},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert login_response.status_code == 200
    assert "refresh_token" in login_response.cookies
    refresh_token = login_response.cookies["refresh_token"]
    assert refresh_token is not None

    refresh_response = await client.post("/auth/refresh", json={})
    assert refresh_response.status_code == 200
    body = refresh_response.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"
    assert "refresh_token" in refresh_response.cookies

    logout_response = await client.post("/auth/logout")
    assert logout_response.status_code == 200
    cookie = logout_response.cookies.get("refresh_token")
    assert not cookie or cookie == ""


@pytest.mark.asyncio
async def test_get_me_success(client):
    register_payload = {
        "email": "me_user@example.com",
        "password": "password123",
        "full_name": "Me User",
    }
    await client.post("/auth/register", json=register_payload)

    headers = await auth_headers(client, register_payload["email"], register_payload["password"])
    response = await client.get("/api/users/me", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == register_payload["email"]
    assert body["full_name"] == register_payload["full_name"]
    assert "id" in body

