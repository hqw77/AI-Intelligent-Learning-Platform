"""闯关历史服务 -- 查询用户的闯关记录.

这个文件是干什么的:
个人中心里的「历史闯关列表」和「闯关详情回看」的数据来源.
只做查询, 不写数据 (写数据在 quiz_service/report_service 落库时完成).
"""

from __future__ import annotations

from app.models.user import QuizHistoryItem, QuizHistoryList, QuizDetailResponse
from app.repositories import quiz_repository


async def get_quiz_history(user_id: int, page: int = 1, page_size: int = 10) -> QuizHistoryList:
    """获取用户闯关历史列表 (分页).

    返回: 列表 + 总数 + 页码信息, 用于前端展示「已完成关卡」.
    """
    items, total = await quiz_repository.get_user_quiz_list(user_id, page, page_size)
    return QuizHistoryList(
        items=[QuizHistoryItem(**item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


async def get_quiz_detail(quiz_id: str, user_id: int) -> QuizDetailResponse | None:
    """获取单次闯关详情 (含题目, 答题记录, 报告).

    返回: 详情; 若记录不存在或不属于该用户, 返回 None.
    """
    detail = await quiz_repository.get_quiz_detail(quiz_id, user_id)
    if detail is None:
        return None
    return QuizDetailResponse(**detail)
