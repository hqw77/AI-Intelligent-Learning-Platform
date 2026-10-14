"""健康检查路由 -- 一个最简单的接口.

完整路径: GET /api/v1/health
作用: 返回 {"status": "ok"}, 用于确认服务是否活着 (探活/部署验证).
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check():
    return {"status": "ok"}
