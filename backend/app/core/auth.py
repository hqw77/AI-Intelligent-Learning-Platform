"""JWT 鉴权模块 -- 签发和校验登录凭证.

这个文件是干什么的:
用 JWT (JSON Web Token) 做「无状态鉴权」:
登录时发一个 token 给前端, 前端每次请求带上 token,
后端从 token 里解出 user_id, 就知道是谁了, 不用每次查数据库.

什么是 JWT:
一段签名过的字符串, 里面存了 user_id, openid, 过期时间.
因为带签名, 后端能验证它没被篡改, 所以「无状态」-- 服务器不用存 session.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
import structlog
from fastapi import Depends, Request

from app.core.config import get_settings
from app.core.exceptions import AuthenticationError

logger = structlog.get_logger()

ALGORITHM = "HS256"  # JWT 签名算法


def create_token(user_id: int, openid: str) -> str:
    """签发 JWT token.

    把 user_id 和 openid 打包进 token, 并设过期时间 (默认 30 天).
    """
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {
        "user_id": user_id,
        "openid": openid,
        "exp": expire,  # 过期时间
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """解析 JWT token, 失败时抛出 AuthenticationError.

    用 jwt_secret 验证签名, 签名不对或过期都会抛异常.
    """
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise AuthenticationError("登录已过期，请重新登录")
    except jwt.InvalidTokenError:
        raise AuthenticationError("无效的登录凭证")


def _extract_token(request: Request) -> Optional[str]:
    """从请求头 Authorization: Bearer xxx 里提取 token."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return None


async def get_current_user(request: Request) -> int:
    """必选鉴权依赖: 返回 user_id, 未登录/无效 token 直接抛异常.

    用在「必须登录」的接口 (如知识库, 个人资料).
    """
    token = _extract_token(request)
    if not token:
        raise AuthenticationError()
    payload = decode_token(token)
    return payload["user_id"]


async def get_optional_user(request: Request) -> Optional[int]:
    """可选鉴权依赖: 返回 user_id 或 None, 不抛异常.

    用在「未登录也能用」的接口 (如出题, 报告):
    有 token 就解析出 user_id, 没有就返回 None (未登录也能体验核心流程).
    """
    token = _extract_token(request)
    if not token:
        return None
    try:
        payload = decode_token(token)
        return payload["user_id"]
    except AuthenticationError:
        return None
