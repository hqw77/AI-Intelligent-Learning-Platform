"""知识库文档业务服务 -- 上传, 解析, 状态查询, 删除的编排层.

这个文件是干什么的:
管理用户上传的私有文档, 是知识库 (RAG) 链路的「大脑」.
核心流程:
上传文档 -> 校验 (格式/大小/数量) -> 保存本地文件 -> 建数据库记录
        -> 后台异步解析 (分块 + 向量化) -> 状态置 ready
删除文档 -> 级联清理向量 + 本地文件 + 数据库记录

文档状态机: processing (解析中) -> ready (就绪) / failed (失败)
"""

from __future__ import annotations

import asyncio
import os
import uuid

import structlog

from app.core.config import get_settings
from app.core.exceptions import KnowledgeBaseError
from app.models.knowledge import (
    KnowledgeDocumentItem,
    KnowledgeListResponse,
    KnowledgeStatusResponse,
    KnowledgeUploadResponse,
)
from app.repositories import knowledge_repository
from app.services import document_loader_service, vector_store_service

logger = structlog.get_logger()

SUPPORTED_EXTENSIONS = {"pdf", "docx", "md", "txt"}  # 支持的文档格式白名单


def _get_extension(filename: str) -> str:
    """从文件名里取扩展名 (不含点, 转小写), 如 "a.PDF" -> "pdf"."""
    _, ext = os.path.splitext(filename)
    return ext.lstrip(".").lower()


async def handle_upload(user_id: int, filename: str, content: bytes) -> KnowledgeUploadResponse:
    """上传文档: 校验 -> 保存 -> 建记录 -> 后台解析.

    参数:
        user_id: 用户 id
        filename: 原始文件名
        content: 文件二进制内容
    返回:
        KnowledgeUploadResponse (doc_id + 初始状态 processing)
    """
    settings = get_settings()

    # 1) 校验文件格式 (只允许 pdf/docx/md/txt)
    file_type = _get_extension(filename)
    if file_type not in SUPPORTED_EXTENSIONS:
        raise KnowledgeBaseError(
            f"不支持的文件格式：{file_type or '未知'}，仅支持 PDF/Word/Markdown/文本文件"
        )

    # 2) 校验文件大小
    max_size_bytes = settings.kb_max_file_size_mb * 1024 * 1024
    if len(content) > max_size_bytes:
        raise KnowledgeBaseError(f"文件大小超过限制（最大 {settings.kb_max_file_size_mb}MB）")

    # 3) 校验文档数量 (每个用户有上限)
    existing_count = await knowledge_repository.count_documents(user_id)
    if existing_count >= settings.kb_max_documents_per_user:
        raise KnowledgeBaseError(
            f"知识库文档数量已达上限（最多 {settings.kb_max_documents_per_user} 篇），请先删除部分文档"
        )

    doc_id = f"doc_{uuid.uuid4().hex[:12]}"

    # 4) 保存文件到本地磁盘 (后续解析从这里读)
    os.makedirs(settings.kb_upload_dir, exist_ok=True)
    file_path = os.path.join(settings.kb_upload_dir, f"{doc_id}.{file_type}")
    with open(file_path, "wb") as f:
        f.write(content)

    # 5) 在数据库建一条文档记录 (状态默认 processing)
    await knowledge_repository.create_document(
        doc_id=doc_id,
        user_id=user_id,
        file_name=filename,
        file_type=file_type,
        file_size=len(content),
    )

    # 6) 后台异步解析 (不阻塞上传接口, 立即返回)
    asyncio.create_task(_process_document(doc_id, user_id, file_path, file_type))

    return KnowledgeUploadResponse(doc_id=doc_id, file_name=filename, status="processing")


async def _process_document(doc_id: str, user_id: int, file_path: str, file_type: str) -> None:
    """后台异步解析文档: 加载分块 -> 向量化写入 -> 更新状态.

    这是知识库的核心处理逻辑, 分三步:
        解析分块 (document_loader) -> 向量化存 Chroma (vector_store) -> 状态置 ready
    """
    try:
        logger.info("kb_document_processing_started", doc_id=doc_id, user_id=user_id)

        # 1) 解析文档并分块 (PDF/Word/MD/TXT -> 若干文本块)
        chunks = document_loader_service.load_and_split(file_path, file_type)
        if not chunks:
            raise ValueError("文档解析后未提取到任何内容")

        # 2) 把分块向量化后写入 Chroma
        chunk_count = vector_store_service.add_document_chunks(user_id, doc_id, chunks)

        # 3) 更新状态为 ready, 记录分块数
        await knowledge_repository.update_document_status(
            doc_id, "ready", chunk_count=chunk_count
        )
        logger.info(
            "kb_document_processing_completed", doc_id=doc_id, user_id=user_id, chunk_count=chunk_count
        )
    except Exception as e:
        # 解析失败: 状态置 failed, 记录错误信息 (截断到 500 字)
        logger.error("kb_document_processing_failed", doc_id=doc_id, user_id=user_id, error=str(e))
        await knowledge_repository.update_document_status(
            doc_id, "failed", error_message=str(e)[:500]
        )


async def list_documents(user_id: int) -> KnowledgeListResponse:
    """获取用户的文档列表."""
    rows = await knowledge_repository.list_documents(user_id)
    items = [KnowledgeDocumentItem.model_validate(row) for row in rows]
    return KnowledgeListResponse(items=items)


async def get_document_status(user_id: int, doc_id: str) -> KnowledgeStatusResponse:
    """查询单个文档的处理状态."""
    row = await knowledge_repository.get_document(doc_id, user_id)
    if row is None:
        raise KnowledgeBaseError("文档不存在")
    return KnowledgeStatusResponse(
        doc_id=row["doc_id"],
        file_name=row["file_name"],
        status=row["status"],
        chunk_count=row["chunk_count"],
        error_message=row.get("error_message"),
    )


async def delete_document(user_id: int, doc_id: str) -> None:
    """删除文档: 级联清理向量 + 本地文件 + 数据库记录.

    任一步失败只记日志, 不中断后续清理 (尽量删干净).
    """
    row = await knowledge_repository.get_document(doc_id, user_id)
    if row is None:
        raise KnowledgeBaseError("文档不存在")

    settings = get_settings()

    # 1) 删除向量库里该文档的所有向量
    try:
        vector_store_service.delete_document_vectors(user_id, doc_id)
    except Exception as e:
        logger.warning("kb_document_vector_delete_failed", doc_id=doc_id, error=str(e))

    # 2) 删除本地文件
    try:
        file_path = os.path.join(settings.kb_upload_dir, f"{doc_id}.{row['file_type']}")
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception as e:
        logger.warning("kb_document_file_delete_failed", doc_id=doc_id, error=str(e))

    # 3) 删除数据库记录
    try:
        await knowledge_repository.delete_document(doc_id, user_id)
    except Exception as e:
        logger.warning("kb_document_db_delete_failed", doc_id=doc_id, error=str(e))
