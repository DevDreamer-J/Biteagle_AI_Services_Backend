"""健康检查与统一错误信封的接口测试。"""


async def test_liveness_returns_ok(client):
    response = await client.get("/health/live")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["app"] == "ai-services-backend"
    assert body["version"]


async def test_request_id_is_generated_and_returned(client):
    response = await client.get("/health/live")

    assert response.headers.get("x-request-id")


async def test_request_id_from_client_is_propagated(client):
    response = await client.get("/health/live", headers={"x-request-id": "trace-0001"})

    assert response.headers["x-request-id"] == "trace-0001"


async def test_unknown_route_uses_error_envelope(client):
    response = await client.get("/not-exists")

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "http_error"
    assert body["error"]["request_id"] == response.headers["x-request-id"]
    assert body["error"]["message"]
