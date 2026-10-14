"""出题路由 -- 出题相关的 3 个 HTTP 接口.

这是「第 1 层」: 请求进来后的第一站. 路由层很薄, 只做三件事:
接收请求 -> 调 service 干活 -> 包成统一格式返回.

3 个接口 (完整路径 = /api/v1 + /quiz + 下面):
    POST /generate          -> 同步出题 (前端已弃用, 保留兼容)
    POST /generate/async    -> 异步出题, 秒回 task_id (前端主用)
    GET  /task/{task_id}    -> 轮询查询任务状态
"""

from typing import Optional

from fastapi import APIRouter, Depends

from app.core.auth import get_optional_user
from app.models.common import ApiResponse
from app.models.quiz import QuizGenerateRequest
from app.services.quiz_service import (
    handle_quiz_generate,
    create_quiz_task,
    get_quiz_task_status,
)

# 定义路由: prefix="/quiz" 表示本组所有接口都带 /quiz 前缀
# (再叠加上 main.py 里的 /api/v1, 最终是 /api/v1/quiz/xxx)
router = APIRouter(prefix="/quiz", tags=["quiz"])


@router.post("/generate", response_model=ApiResponse)
async def quiz_generate(
    req: QuizGenerateRequest,
    user_id: Optional[int] = Depends(get_optional_user),
):
    """同步出题: 一个请求全程等出题完成再返回 (前端已弃用)."""
    # Depends(get_optional_user) 是「依赖注入」: 从请求头解析 token, 返回 user_id 或 None (未登录)
    result = await handle_quiz_generate(req, user_id=user_id)
    # ApiResponse.success() 把结果包成 {code:0, message:"ok", data:...} 统一格式
    return ApiResponse.success(data=result.model_dump())


@router.post("/generate/async", response_model=ApiResponse)
async def quiz_generate_async(
    req: QuizGenerateRequest,
    user_id: Optional[int] = Depends(get_optional_user),
):
    """异步创建出题任务, 立即返回 task_id (前端主用).

    为什么不直接等出题: 出题 + 联网搜索要几十秒, 同步会超时.
    所以这里只创建任务秒回 task_id, 真正的出题在后台跑, 前端靠轮询拿结果.
    """
    result = await create_quiz_task(req, user_id=user_id)
    return ApiResponse.success(data=result.model_dump())


@router.get("/task/{task_id}", response_model=ApiResponse)
async def quiz_task_status(task_id: str):
    """轮询查询任务状态.

    路径里的 {task_id} 是「路径参数」: 前端把 task_id 拼进 URL,
    FastAPI 自动提取出来传给这个函数.
    """
    result = await get_quiz_task_status(task_id)
    return ApiResponse.success(data=result.model_dump())
