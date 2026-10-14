"""用户数据访问层 -- 封装 users 表的 SQL 操作.

统一模式: get_mysql_pool() 拿连接 -> 执行 SQL -> 返回结果 (pool 为 None 时降级返回).
"""

from __future__ import annotations

from typing import Optional

import structlog

from app.core.db import get_mysql_pool

logger = structlog.get_logger()


async def find_user_by_openid(openid: str) -> Optional[dict]:
    """根据 openid 查用户, 不存在返回 None."""
    pool = get_mysql_pool()
    if pool is None:
        return None
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id, openid, nickname, avatar_url, total_xp, created_at, updated_at "
                "FROM users WHERE openid = %s",
                (openid,),
            )
            row = await cur.fetchone()
            if row is None:
                return None
            return {
                "id": row[0],
                "openid": row[1],
                "nickname": row[2],
                "avatar_url": row[3],
                "total_xp": row[4],
                "created_at": row[5],
                "updated_at": row[6],
            }


async def create_user(openid: str) -> dict:
    """新建用户 (首次登录自动注册), 返回新用户信息."""
    pool = get_mysql_pool()
    if pool is None:
        raise RuntimeError("数据库未初始化")
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO users (openid) VALUES (%s)",
                (openid,),
            )
            user_id = cur.lastrowid  # 拿到自增主键 id
            return {
                "id": user_id,
                "openid": openid,
                "nickname": "学习者",  # 默认昵称
                "avatar_url": "",
                "total_xp": 0,
            }


async def update_user_profile(user_id: int, nickname: Optional[str], avatar_url: Optional[str]) -> None:
    """更新用户资料 (昵称/头像). 只更新传入的字段 (动态拼 SQL)."""
    pool = get_mysql_pool()
    if pool is None:
        return
    fields = []   # 要更新的字段列表
    values = []   # 对应的值列表
    if nickname is not None:
        fields.append("nickname = %s")
        values.append(nickname)
    if avatar_url is not None:
        fields.append("avatar_url = %s")
        values.append(avatar_url)
    if not fields:  # 两个都没传, 不用更新
        return
    values.append(user_id)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                f"UPDATE users SET {', '.join(fields)} WHERE id = %s",
                tuple(values),
            )


async def add_user_xp(user_id: int, xp: int) -> None:
    """累加经验值 (total_xp = total_xp + xp)."""
    pool = get_mysql_pool()
    if pool is None:
        return
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE users SET total_xp = total_xp + %s WHERE id = %s",
                (xp, user_id),
            )


async def get_user_by_id(user_id: int) -> Optional[dict]:
    """根据 id 查用户, 不存在返回 None."""
    pool = get_mysql_pool()
    if pool is None:
        return None
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id, openid, nickname, avatar_url, total_xp FROM users WHERE id = %s",
                (user_id,),
            )
            row = await cur.fetchone()
            if row is None:
                return None
            return {
                "id": row[0],
                "openid": row[1],
                "nickname": row[2],
                "avatar_url": row[3],
                "total_xp": row[4],
            }
