"""报告路由 -- 生成复盘报告接口.

完整路径: POST /api/v1/report/generate
用 get_optional_user (可选登录): 未登录也能生成报告, 登录了才落库 + 攒经验值.
"""

from typing import Optional

from fastapi import APIRouter, Depends

from app.core.auth import get_optional_user
from app.models.common import ApiResponse
from app.models.report import ReportGenerateRequest
from app.services.report_service import handle_report_generate

router = APIRouter(prefix="/report", tags=["report"])


@router.post("/generate", response_model=ApiResponse)
async def report_generate(
    req: ReportGenerateRequest,
    user_id: Optional[int] = Depends(get_optional_user),
):
    """生成复盘报告: 接收答题记录, 返回掌握度/薄弱点/总结/建议."""
    result = await handle_report_generate(req, user_id=user_id)
    return ApiResponse.success(data=result.model_dump())
