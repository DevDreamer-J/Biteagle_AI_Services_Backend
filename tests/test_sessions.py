"""会话与消息接口测试。"""

from __future__ import annotations

import httpx

from tests.conftest import auth_headers


async def _create_session(client: httpx.AsyncClient, headers: dict, title: str = "S1") -> dict:
    response = await client.post("/v1/sessions", headers=headers, json={"title": title})
    assert response.status_code == 201
    return response.json()


async def test_create_and_list_sessions(client: httpx.AsyncClient):
    headers = await auth_headers(client, email="s1@example.com")
    await _create_session(client, headers, "S1")
    await _create_session(client, headers, "S2")

    response = await client.get("/v1/sessions", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert {item["title"] for item in body["items"]} == {"S1", "S2"}


async def test_get_session_returns_404_for_other_user(client: httpx.AsyncClient):
    owner = await auth_headers(client, email="owner@example.com")
    other = await auth_headers(client, email="other@example.com")
    session = await _create_session(client, owner)

    response = await client.get(f"/v1/sessions/{session['id']}", headers=other)

    assert response.status_code == 404


async def test_update_and_delete_session(client: httpx.AsyncClient):
    headers = await auth_headers(client, email="ud@example.com")
    session = await _create_session(client, headers)

    patched = await client.patch(
        f"/v1/sessions/{session['id']}",
        headers=headers,
        json={"title": "Renamed", "is_archived": True},
    )
    assert patched.status_code == 200
    assert patched.json()["title"] == "Renamed"
    assert patched.json()["is_archived"] is True

    deleted = await client.delete(f"/v1/sessions/{session['id']}", headers=headers)
    assert deleted.status_code == 204

    gone = await client.get(f"/v1/sessions/{session['id']}", headers=headers)
    assert gone.status_code == 404


async def test_create_message_and_list(client: httpx.AsyncClient):
    headers = await auth_headers(client, email="msg@example.com")
    session = await _create_session(client, headers)

    for role, content in [("user", "hi"), ("assistant", "hello")]:
        response = await client.post(
            f"/v1/sessions/{session['id']}/messages",
            headers=headers,
            json={"role": role, "content": content},
        )
        assert response.status_code == 201

    response = await client.get(f"/v1/sessions/{session['id']}/messages", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["items"][0]["role"] == "user"


async def test_empty_content_rejected(client: httpx.AsyncClient):
    headers = await auth_headers(client, email="empty@example.com")
    session = await _create_session(client, headers)

    response = await client.post(
        f"/v1/sessions/{session['id']}/messages",
        headers=headers,
        json={"role": "user", "content": ""},
    )
    assert response.status_code == 422
