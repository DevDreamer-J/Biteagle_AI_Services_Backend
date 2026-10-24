"""用户接口测试。"""

from __future__ import annotations

import httpx
import pytest

from tests.conftest import register_user


async def test_register_returns_api_key_once(client: httpx.AsyncClient):
    response = await client.post(
        "/v1/users",
        json={"email": "alice@example.com", "display_name": "Alice"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "alice@example.com"
    assert body["display_name"] == "Alice"
    assert body["api_key"].startswith("sk_")


async def test_register_duplicate_email_conflicts(client: httpx.AsyncClient):
    await register_user(client, email="bob@example.com")

    response = await client.post(
        "/v1/users",
        json={"email": "bob@example.com", "display_name": "Bob2"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "bad", "display_name": "x"},
        {"email": "ok@example.com"},
        {"email": "ok@example.com", "display_name": ""},
    ],
)
async def test_register_validation(client: httpx.AsyncClient, payload: dict):
    response = await client.post("/v1/users", json=payload)
    assert response.status_code == 422


async def test_get_me_requires_api_key(client: httpx.AsyncClient):
    response = await client.get("/v1/users/me")
    assert response.status_code == 401


async def test_get_me_with_valid_key(client: httpx.AsyncClient):
    user = await register_user(client, email="carol@example.com")

    response = await client.get("/v1/users/me", headers={"X-API-Key": user["api_key"]})

    assert response.status_code == 200
    assert response.json()["email"] == "carol@example.com"
