"""用户服务 -- 微信登录, 用户资料管理.

这个文件是干什么的:
处理微信静默登录和用户资料. 核心是「微信登录」:
前端 wx.login 拿到 code -> 后端调微信接口换 openid -> 查/建用户 -> 发 JWT.

什么是「静默登录」:
用户无感, 不需要点授权弹窗. wx.login 拿 code 不需要用户同意,
后端用 code 换到 openid (用户在微信体系里的唯一标识) 就算登录了.
"""

from __future__ import annotations

import httpx
import structlog

from app.core.auth import create_token
from app.core.config import get_settings
from app.core.exceptions import AuthenticationError
from app.models.user import LoginResponse, UserBrief, UserProfile
from app.repositories import user_repository, quiz_repository

logger = structlog.get_logger()

WX_CODE2SESSION_URL = "https://api.weixin.qq.com/sns/jscode2session"  # 微信登录接口地址


async def wx_code_to_openid(code: str) -> str:
    """调微信 jscode2session 接口, 用 code 换 openid.

    code 是前端 wx.login 拿到的临时凭证 (一次性, 5 分钟有效).
    openid 是用户在小程序里的唯一标识 (同一用户在不同小程序 openid 不同).
    """
    settings = get_settings()
    if not settings.wechat_app_id or not settings.wechat_app_secret:
        raise AuthenticationError("微信登录未配置")

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                WX_CODE2SESSION_URL,
                params={
                    "appid": settings.wechat_app_id,
                    "secret": settings.wechat_app_secret,
                    "js_code": code,
                    "grant_type": "authorization_code",
                },
            )
            data = resp.json()
    except httpx.HTTPError as exc:
        logger.error("wx_login_request_failed", error=str(exc), exc_info=True)
        raise AuthenticationError("微信登录服务暂时不可用，请稍后重试") from exc
    except ValueError as exc:  # resp.json() 解析失败
        logger.error("wx_login_invalid_response", error=str(exc), exc_info=True)
        raise AuthenticationError("微信登录失败，请重试") from exc

    if "openid" not in data:
        # 微信返回了错误 (如 code 过期), 记录错误码
        logger.error(
            "wx_login_failed",
            errcode=data.get("errcode"),
            errmsg=data.get("errmsg"),
            appid=settings.wechat_app_id,
        )
        raise AuthenticationError("微信登录失败，请重试")

    return data["openid"]


async def handle_login(code: str) -> LoginResponse:
    """微信登录: code -> openid -> 查/建用户 -> 发 JWT.

    返回: token (JWT) + 用户简要信息.
    """
    # 1) code 换 openid
    openid = await wx_code_to_openid(code)

    # 2) 根据 openid 查用户, 没有就新建 (首次登录自动注册)
    user = await user_repository.find_user_by_openid(openid)
    if user is None:
        user = await user_repository.create_user(openid)

    # 3) 签发 JWT token
    token = create_token(user_id=user["id"], openid=openid)

    return LoginResponse(
        token=token,
        user=UserBrief(
            id=user["id"],
            nickname=user["nickname"],
            avatar_url=user["avatar_url"],
            total_xp=user["total_xp"],
        ),
    )


async def get_profile(user_id: int) -> UserProfile:
    """获取用户档案, 含统计聚合 (闯关数, 答对数, 平均正确率)."""
    user = await user_repository.get_user_by_id(user_id)
    if user is None:
        raise AuthenticationError("用户不存在")

    quiz_count = await quiz_repository.get_user_quiz_count(user_id)
    answer_stats = await quiz_repository.get_user_answer_stats(user_id)

    return UserProfile(
        id=user["id"],
        nickname=user["nickname"],
        avatar_url=user["avatar_url"],
        total_xp=user["total_xp"],
        quiz_count=quiz_count,
        correct_count=answer_stats["correct_count"],
        average_accuracy=answer_stats["average_accuracy"],
    )


async def update_profile(user_id: int, nickname: str | None, avatar_url: str | None) -> None:
    """更新用户档案 (昵称/头像)."""
    await user_repository.update_user_profile(user_id, nickname, avatar_url)
