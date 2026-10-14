"""知识库文档路由 -- 知识库相关的 4 个 HTTP 接口.

这是知识库链路的「第 1 层」: 接收上传/查询/删除文档的请求.
注意: 这里用的是 get_current_user (必选鉴权), 不是出题那边的 get_optional_user (可选鉴权).
原因: 知识库文档必须归属某个用户, 没登录就无法确认归属, 所以强制登录.

4 个接口 (完整路径 = /api/v1/knowledge):
    POST   /documents          -> 上传文档
    GET    /documents          -> 文档列表
    GET    /documents/{doc_id} -> 查询单个文档状态
    DELETE /documents/{doc_id} -> 删除文档
"""

from fastapi import APIRouter, Depends, UploadFile, File

from app.core.auth import get_current_user
from app.models.common import ApiResponse
from app.services import knowledge_service

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.post("/documents", response_model=ApiResponse)
async def upload_document(
    file: UploadFile = File(...),          # 上传的文件 (File(...) 表示必填)
    user_id: int = Depends(get_current_user),  # 必选登录
):
    """上传文档: 先校验, 再保存文件, 后台异步解析 (分块 + 向量化)."""
    content = await file.read()  # 读出文件的二进制内容
    result = await knowledge_service.handle_upload(
        user_id=user_id, filename=file.filename or "unknown", content=content
    )
    return ApiResponse.success(data=result.model_dump())


@router.get("/documents", response_model=ApiResponse)
async def list_documents(user_id: int = Depends(get_current_user)):
    """获取当前用户的文档列表."""
    result = await knowledge_service.list_documents(user_id)
    return ApiResponse.success(data=result.model_dump())


@router.get("/documents/{doc_id}", response_model=ApiResponse)
async def get_document_status(doc_id: str, user_id: int = Depends(get_current_user)):
    """查询单个文档的处理状态 (前端轮询, 判断解析是否完成)."""
    result = await knowledge_service.get_document_status(user_id, doc_id)
    return ApiResponse.success(data=result.model_dump())


@router.delete("/documents/{doc_id}", response_model=ApiResponse)
async def delete_document(doc_id: str, user_id: int = Depends(get_current_user)):
    """删除文档: 级联清理向量 + 本地文件 + 数据库记录."""
    await knowledge_service.delete_document(user_id, doc_id)
    return ApiResponse.success()
