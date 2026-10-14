"""知识库文档相关数据模型 -- 用 Pydantic 定义知识库的请求/响应结构.

关键概念: 文档状态机 processing -> ready / failed
    processing: 文档已上传, 正在后台解析 (分块 + 向量化)
    ready:      解析完成, 可以用来出题
    failed:     解析失败 (记录了 error_message)
"""

from typing import Literal, Optional
from pydantic import BaseModel


class KnowledgeUploadResponse(BaseModel):
    """上传文档后的响应 -- 只返回 doc_id 和初始状态 (processing)."""
    doc_id: str
    file_name: str
    status: Literal["processing", "ready", "failed"]


class KnowledgeDocumentItem(BaseModel):
    """知识库文档列表项 -- 列表页展示的一条文档信息."""
    doc_id: str
    file_name: str
    file_type: str    # 文件类型 (pdf/docx/md/txt)
    file_size: int    # 文件大小 (字节)
    status: Literal["processing", "ready", "failed"]
    chunk_count: int  # 切成多少块 (解析完成后才有)
    error_message: Optional[str] = None  # 解析失败时的错误信息
    created_at: str


class KnowledgeListResponse(BaseModel):
    """知识库文档列表响应."""
    items: list[KnowledgeDocumentItem]


class KnowledgeStatusResponse(BaseModel):
    """文档状态查询响应 -- 前端轮询解析进度用."""
    doc_id: str
    file_name: str
    status: Literal["processing", "ready", "failed"]
    chunk_count: int
    error_message: Optional[str] = None
