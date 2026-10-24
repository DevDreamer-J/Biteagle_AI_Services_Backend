"""异步任务接口测试（Celery eager 模式，任务同步执行）。"""

from __future__ import annotations

import httpx

from tests.conftest import auth_headers


async def _create_session(client: httpx.AsyncClient, headers: dict) -> dict:
    response = await client.post("/v1/sessions", headers=headers, json={"title": "T"})
    assert response.status_code == 201
    return response.json()


async def test_session_stats_task_succeeds(client: httpx.AsyncClient):
    headers = await auth_headers(client, email="stats@example.com")
    session = await _create_session(client, headers)
    for role, content in [("user", "hi"), ("assistant", "yo"), ("user", "bye")]:
        await client.post(
            f"/v1/sessions/{session['id']}/messages",
            headers=headers,
            json={"role": role, "content": content},
        )

    response = await client.post(
        "/v1/tasks",
        headers=headers,
        json={"type": "session_stats", "session_id": session["id"]},
    )

    assert response.status_code == 202
    body = response.json()
    # eager 模式下任务已同步执行完毕
    assert body["status"] == "succeeded"
    assert body["attempts"] == 1
    result = body["result"]
    assert result["message_count"] == 3
    assert result["by_role"] == {"user": 2, "assistant": 1}


async def test_session_export_task_returns_markdown(client: httpx.AsyncClient):
    headers = await auth_headers(client, email="export@example.com")
    session = await _create_session(client, headers)
    await client.post(
        f"/v1/sessions/{session['id']}/messages",
        headers=headers,
        json={"role": "user", "content": "hello"},
    )

    response = await client.post(
        "/v1/tasks",
        headers=headers,
        json={"type": "session_export", "session_id": session["id"]},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "succeeded"
    result = body["result"]
    assert result["format"] == "markdown"
    assert result["message_count"] == 1
    assert "hello" in result["content"]


async def test_task_requires_session_id(client: httpx.AsyncClient):
    headers = await auth_headers(client, email="nosid@example.com")

    response = await client.post("/v1/tasks", headers=headers, json={"type": "session_stats"})

    assert response.status_code == 422


async def test_other_user_task_returns_404(client: httpx.AsyncClient):
    owner = await auth_headers(client, email="owner2@example.com")
    other = await auth_headers(client, email="other2@example.com")
    session = await _create_session(client, owner)
    created = await client.post(
        "/v1/tasks",
        headers=owner,
        json={"type": "session_stats", "session_id": session["id"]},
    )
    task_id = created.json()["id"]

    response = await client.get(f"/v1/tasks/{task_id}", headers=other)

    assert response.status_code == 404


async def test_task_idempotency_same_key_returns_same_task(client: httpx.AsyncClient):
    headers = await auth_headers(client, email="idem@example.com")
    session = await _create_session(client, headers)
    body = {"type": "session_stats", "session_id": session["id"]}

    first = await client.post("/v1/tasks", headers={**headers, "Idempotency-Key": "k1"}, json=body)
    second = await client.post("/v1/tasks", headers={**headers, "Idempotency-Key": "k1"}, json=body)

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["id"] == second.json()["id"]


async def test_task_different_keys_create_different_tasks(client: httpx.AsyncClient):
    headers = await auth_headers(client, email="idem2@example.com")
    session = await _create_session(client, headers)
    body = {"type": "session_stats", "session_id": session["id"]}

    first = await client.post("/v1/tasks", headers={**headers, "Idempotency-Key": "a"}, json=body)
    second = await client.post("/v1/tasks", headers={**headers, "Idempotency-Key": "b"}, json=body)

    assert first.json()["id"] != second.json()["id"]


async def test_task_list_filters_by_status(client: httpx.AsyncClient):
    headers = await auth_headers(client, email="list@example.com")
    session = await _create_session(client, headers)
    await client.post(
        "/v1/tasks",
        headers=headers,
        json={"type": "session_stats", "session_id": session["id"]},
    )

    response = await client.get("/v1/tasks?status=succeeded", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["status"] == "succeeded"
