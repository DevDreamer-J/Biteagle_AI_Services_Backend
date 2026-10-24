"""限流测试。"""

from __future__ import annotations

import httpx

from app.core.config import get_settings
from tests.conftest import auth_headers


async def test_rate_limit_headers_present_on_success(client: httpx.AsyncClient):
    headers = await auth_headers(client, email="rlh@example.com")

    response = await client.post("/v1/sessions", headers=headers, json={"title": "x"})

    assert response.status_code == 201
    assert response.headers["x-ratelimit-limit"] == str(get_settings().rate_limit_per_minute)
    assert "x-ratelimit-remaining" in response.headers
    assert "x-ratelimit-reset" in response.headers


async def test_rate_limit_returns_429_after_limit(client: httpx.AsyncClient, monkeypatch):
    """把限流阈值降到 2，连发 3 次应触发 429。"""
    settings = get_settings()
    monkeypatch.setattr(settings, "rate_limit_per_minute", 2)

    headers = await auth_headers(client, email="rl429@example.com")

    for _ in range(2):
        response = await client.post("/v1/sessions", headers=headers, json={"title": "x"})
        assert response.status_code == 201

    response = await client.post("/v1/sessions", headers=headers, json={"title": "x"})
    assert response.status_code == 429
    assert response.headers.get("retry-after")
    assert response.json()["error"]["code"] == "rate_limited"


async def test_rate_limit_is_per_user(client: httpx.AsyncClient, monkeypatch):
    """A 用户被限流不影响 B 用户。"""
    # 先注册两个用户（此时还是默认阈值，注册不受影响）
    a = await auth_headers(client, email="rla@example.com")
    b = await auth_headers(client, email="rlb@example.com")

    settings = get_settings()
    monkeypatch.setattr(settings, "rate_limit_per_minute", 1)

    assert (await client.post("/v1/sessions", headers=a, json={"title": "x"})).status_code == 201
    assert (await client.post("/v1/sessions", headers=a, json={"title": "x"})).status_code == 429
    # B 用户仍可正常请求
    assert (await client.post("/v1/sessions", headers=b, json={"title": "x"})).status_code == 201


async def test_ip_rate_limit_on_registration(client: httpx.AsyncClient, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "rate_limit_per_minute", 1)

    first = await client.post("/v1/users", json={"email": "ip1@example.com", "display_name": "A"})
    assert first.status_code == 201

    second = await client.post("/v1/users", json={"email": "ip2@example.com", "display_name": "B"})
    assert second.status_code == 429
