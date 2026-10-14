"""异步任务数据访问层 -- 封装 quiz_tasks 表的 SQL 操作.

quiz_tasks 表存「异步出题任务」的状态, 前端轮询就是查这张表.
状态机: pending -> running -> completed / failed.
"""

from __future__ import annotations

import json
from typing import Optional

import structlog

from app.core.db import get_mysql_pool

logger = structlog.get_logger()


async def create_task(
    task_id: str,
    user_id: Optional[int],
    user_input: str,
    question_count: int,
    difficulty: str,
) -> None:
    """创建任务记录 (状态默认 pending)."""
    pool = get_mysql_pool()
    if pool is None:
        return
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO quiz_tasks (task_id, user_id, user_input, question_count, difficulty, status) "
                "VALUES (%s, %s, %s, %s, %s, 'pending')",
                (task_id, user_id, user_input, question_count, difficulty),
            )


async def update_task_status(
    task_id: str,
    status: str,
    result_json: Optional[dict] = None,
    error_message: Optional[str] = None,
) -> None:
    """更新任务状态 (running/completed/failed), 可选带结果或错误信息."""
    pool = get_mysql_pool()
    if pool is None:
        return
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE quiz_tasks SET status = %s, result_json = %s, error_message = %s WHERE task_id = %s",
                (
                    status,
                    json.dumps(result_json, ensure_ascii=False) if result_json else None,
                    error_message,
                    task_id,
                ),
            )


async def get_task(task_id: str) -> Optional[dict]:
    """查询任务, 返回状态 + 结果 + 错误信息 (result_json 自动反序列化)."""
    pool = get_mysql_pool()
    if pool is None:
        return None
    async with pool.acquire() as conn:
        # 用 DictCursor 让查询结果直接是 dict (key 是列名), 不用手动按列号取值
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                "SELECT task_id, status, result_json, error_message FROM quiz_tasks WHERE task_id = %s",
                (task_id,),
            )
            row = await cur.fetchone()
            if row and row.get("result_json"):
                if isinstance(row["result_json"], str):
                    row["result_json"] = json.loads(row["result_json"])
            return row


# 上面的 get_task 用了 aiomysql.DictCursor, 所以需要 import aiomysql
import aiomysql
