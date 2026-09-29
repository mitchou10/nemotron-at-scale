"""User endpoint tests."""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_user(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/users/",
        json={
            "email": "test@example.com",
            "full_name": "Test User",
            "password": "supersecret123",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "test@example.com"
    assert data["full_name"] == "Test User"
    assert "id" in data
    assert "hashed_password" not in data


@pytest.mark.asyncio
async def test_create_user_duplicate(client: AsyncClient) -> None:
    payload = {
        "email": "dup@example.com",
        "full_name": "Dup User",
        "password": "supersecret123",
    }
    await client.post("/api/v1/users/", json=payload)
    response = await client.post("/api/v1/users/", json=payload)
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_list_users(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/users/",
        json={
            "email": "list@example.com",
            "full_name": "List User",
            "password": "supersecret123",
        },
    )
    response = await client.get("/api/v1/users/")
    assert response.status_code == 200
    assert len(response.json()) >= 1


@pytest.mark.asyncio
async def test_get_user(client: AsyncClient) -> None:
    create_resp = await client.post(
        "/api/v1/users/",
        json={
            "email": "get@example.com",
            "full_name": "Get User",
            "password": "supersecret123",
        },
    )
    user_id = create_resp.json()["id"]
    response = await client.get(f"/api/v1/users/{user_id}")
    assert response.status_code == 200
    assert response.json()["email"] == "get@example.com"


@pytest.mark.asyncio
async def test_get_user_not_found(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/users/00000000-0000-0000-0000-000000000000"
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_user(client: AsyncClient) -> None:
    create_resp = await client.post(
        "/api/v1/users/",
        json={
            "email": "update@example.com",
            "full_name": "Old Name",
            "password": "supersecret123",
        },
    )
    user_id = create_resp.json()["id"]
    response = await client.patch(
        f"/api/v1/users/{user_id}",
        json={"full_name": "New Name"},
    )
    assert response.status_code == 200
    assert response.json()["full_name"] == "New Name"


@pytest.mark.asyncio
async def test_delete_user(client: AsyncClient) -> None:
    create_resp = await client.post(
        "/api/v1/users/",
        json={
            "email": "delete@example.com",
            "full_name": "Delete User",
            "password": "supersecret123",
        },
    )
    user_id = create_resp.json()["id"]
    response = await client.delete(f"/api/v1/users/{user_id}")
    assert response.status_code == 204
    response = await client.get(f"/api/v1/users/{user_id}")
    assert response.status_code == 404
