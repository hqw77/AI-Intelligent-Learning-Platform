"""题库 / 答题 / 报告数据访问层.

这个文件是干什么的:
封装对 quiz_sessions, answer_records, reports 三张表的 SQL 操作.
属于「数据访问层」-- 上层 service 调这里, 这里只跟数据库打交道.

统一模式 (每个函数都一样):
    get_mysql_pool() 拿连接池 -> pool.acquire() 拿连接 -> 执行 SQL -> 返回结果.
    如果 pool 是 None (数据库未初始化), 直接返回空/None (降级, 不报错).
"""

from __future__ import annotations

import json
from typing import Optional

import structlog

from app.core.db import get_mysql_pool

logger = structlog.get_logger()


async def save_quiz_session(
    quiz_id: str,
    user_id: Optional[int],
    title: str,
    summary: str,
    user_input: str,
    questions_json: list,
) -> None:
    """保存一套题目到 quiz_sessions (题目列表序列化成 JSON 存进 questions_json)."""
    pool = get_mysql_pool()
    if pool is None:
        return
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO quiz_sessions (quiz_id, user_id, title, summary, user_input, questions_json) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    quiz_id,
                    user_id,
                    title,
                    summary,
                    user_input,
                    json.dumps(questions_json, ensure_ascii=False),
                ),
            )


async def save_answer_record(
    quiz_id: str,
    user_id: Optional[int],
    records_json: list,
    total_questions: int,
    correct_count: int,
    accuracy: float,
) -> None:
    """保存答题记录到 answer_records (整场答题的 JSON + 统计数字)."""
    pool = get_mysql_pool()
    if pool is None:
        return
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO answer_records (quiz_id, user_id, records_json, total_questions, correct_count, accuracy) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    quiz_id,
                    user_id,
                    json.dumps(records_json, ensure_ascii=False),
                    total_questions,
                    correct_count,
                    accuracy,
                ),
            )


async def save_report(
    quiz_id: str,
    user_id: Optional[int],
    report_json: dict,
) -> None:
    """保存复盘报告到 reports."""
    pool = get_mysql_pool()
    if pool is None:
        return
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO reports (quiz_id, user_id, report_json) VALUES (%s, %s, %s)",
                (
                    quiz_id,
                    user_id,
                    json.dumps(report_json, ensure_ascii=False),
                ),
            )


async def get_user_quiz_count(user_id: int) -> int:
    """统计用户的闯关次数."""
    pool = get_mysql_pool()
    if pool is None:
        return 0
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT COUNT(*) FROM quiz_sessions WHERE user_id = %s",
                (user_id,),
            )
            row = await cur.fetchone()
            return row[0] if row else 0


async def get_user_answer_stats(user_id: int) -> dict:
    """获取用户答题统计: 总答对题数, 平均正确率."""
    pool = get_mysql_pool()
    if pool is None:
        return {"correct_count": 0, "average_accuracy": 0}
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT COALESCE(SUM(correct_count), 0), COALESCE(AVG(accuracy), 0) "
                "FROM answer_records WHERE user_id = %s",
                (user_id,),
            )
            row = await cur.fetchone()
            return {
                "correct_count": int(row[0]) if row else 0,
                "average_accuracy": round(float(row[1])) if row else 0,
            }


async def get_user_quiz_list(user_id: int, page: int, page_size: int) -> tuple[list[dict], int]:
    """分页获取用户闯关历史. 返回 (items, total).

    用 LEFT JOIN 关联 answer_records, 拿到每次闯关的正确率和题数.
    """
    pool = get_mysql_pool()
    if pool is None:
        return [], 0
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # 先查总数 (用于分页)
            await cur.execute(
                "SELECT COUNT(*) FROM quiz_sessions WHERE user_id = %s",
                (user_id,),
            )
            total = (await cur.fetchone())[0]

            # 再查当前页列表 (LIMIT/OFFSET 分页)
            offset = (page - 1) * page_size
            await cur.execute(
                "SELECT qs.quiz_id, qs.title, "
                "COALESCE(ar.accuracy, 0), COALESCE(ar.total_questions, 0), "
                "qs.created_at "
                "FROM quiz_sessions qs "
                "LEFT JOIN answer_records ar ON qs.quiz_id = ar.quiz_id "
                "WHERE qs.user_id = %s "
                "ORDER BY qs.created_at DESC "
                "LIMIT %s OFFSET %s",
                (user_id, page_size, offset),
            )
            rows = await cur.fetchall()
            items = [
                {
                    "quiz_id": r[0],
                    "title": r[1],
                    "accuracy": float(r[2]),
                    "question_count": r[3],
                    "created_at": r[4].strftime("%Y-%m-%d %H:%M:%S") if r[4] else "",
                }
                for r in rows
            ]
            return items, total


async def get_quiz_detail(quiz_id: str, user_id: int) -> Optional[dict]:
    """获取单次闯关完整详情 (题目 + 答题记录 + 报告)."""
    pool = get_mysql_pool()
    if pool is None:
        return None
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # 1) 查 quiz_sessions 拿题目
            await cur.execute(
                "SELECT quiz_id, title, summary, user_input, questions_json, created_at "
                "FROM quiz_sessions WHERE quiz_id = %s AND user_id = %s",
                (quiz_id, user_id),
            )
            qs_row = await cur.fetchone()
            if qs_row is None:
                return None

            result = {
                "quiz_id": qs_row[0],
                "title": qs_row[1],
                "summary": qs_row[2],
                "user_input": qs_row[3],
                "questions": json.loads(qs_row[4]) if isinstance(qs_row[4], str) else qs_row[4],
                "created_at": qs_row[5].strftime("%Y-%m-%d %H:%M:%S") if qs_row[5] else "",
            }

            # 2) 查 answer_records 拿答题记录
            await cur.execute(
                "SELECT records_json FROM answer_records WHERE quiz_id = %s",
                (quiz_id,),
            )
            ar_row = await cur.fetchone()
            if ar_row:
                result["answer_records"] = json.loads(ar_row[0]) if isinstance(ar_row[0], str) else ar_row[0]

            # 3) 查 reports 拿报告
            await cur.execute(
                "SELECT report_json FROM reports WHERE quiz_id = %s",
                (quiz_id,),
            )
            rp_row = await cur.fetchone()
            if rp_row:
                result["report"] = json.loads(rp_row[0]) if isinstance(rp_row[0], str) else rp_row[0]

            return result
