"""用户路由 -- 用户登录, 资料, 闯关历史相关的 5 个接口.

完整路径 = /api/v1/user:
    POST /login              -> 微信登录 (不用鉴权, 因为登录前还没有 token)
    GET  /profile            -> 获取用户资料 (含统计)
    PUT  /profile            -> 更新昵称/头像
    GET  /quizzes            -> 闯关历史列表 (分页)
    GET  /quizzes/{quiz_id}  -> 单次闯关详情 (含报告回看)
"""

from fastapi import APIRouter, Depends, Query

from app.core.auth import get_current_user
from app.models.common import ApiResponse
from app.models.user import LoginRequest, UpdateProfileRequest
from app.services import user_service, history_service

router = APIRouter(prefix="/user", tags=["user"])


@router.post("/login", response_model=ApiResponse)
async def login(req: LoginRequest):
    """微信登录: 前端传 wx.login 的 code, 后端换 openid -> 查/建用户 -> 发 JWT."""
    # 注意: 这个接口没有 Depends(get_current_user), 因为登录前还没有 token
    result = await user_service.handle_login(req.code)
    return ApiResponse.success(data=result.model_dump())


@router.get("/profile", response_model=ApiResponse)
async def get_profile(user_id: int = Depends(get_current_user)):
    """获取用户资料 (含闯关数, 正确率等统计)."""
    result = await user_service.get_profile(user_id)
    return ApiResponse.success(data=result.model_dump())


@router.put("/profile", response_model=ApiResponse)
async def update_profile(
    req: UpdateProfileRequest,
    user_id: int = Depends(get_current_user),
):
    """更新昵称/头像."""
    await user_service.update_profile(user_id, req.nickname, req.avatar_url)
    return ApiResponse.success()


@router.get("/quizzes", response_model=ApiResponse)
async def get_quiz_list(
    page: int = Query(1, ge=1),           # 页码, 从 1 开始
    page_size: int = Query(10, ge=1, le=50),  # 每页条数, 1~50
    user_id: int = Depends(get_current_user),
):
    """闯关历史列表 (分页)."""
    result = await history_service.get_quiz_history(user_id, page, page_size)
    return ApiResponse.success(data=result.model_dump())


@router.get("/quizzes/{quiz_id}", response_model=ApiResponse)
async def get_quiz_detail(
    quiz_id: str,
    user_id: int = Depends(get_current_user),
):
    """单次闯关详情 (含当时的题目, 答题记录, 复盘报告, 用于回看)."""
    result = await history_service.get_quiz_detail(quiz_id, user_id)
    if result is None:
        # 直接在路由层返回错误 (这里没用异常, 是项目里的一处小不一致)
        return ApiResponse.error(code=4004, message="闯关记录不存在")
    return ApiResponse.success(data=result.model_dump())
