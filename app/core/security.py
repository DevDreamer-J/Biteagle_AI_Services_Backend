"""API Key 生成与摘要。"""

from __future__ import annotations

import hashlib
import secrets


def generate_api_key() -> str:
    """生成明文 API Key，仅在注册响应里返回一次。"""
    return f"sk_{secrets.token_urlsafe(32)}"


def hash_api_key(raw_key: str) -> str:
    """与 users.api_key_hash 列长度（64）对齐的 SHA-256 十六进制摘要。"""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
