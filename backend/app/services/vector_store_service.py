"""向量存储服务 -- 基于 Chroma 的知识库向量检索.

这个文件是干什么的:
负责「文字 <-> 向量」的转换和存储, 是 RAG 的「检索引擎」.
核心职责:
1. 把文档分块转成向量 (Embedding), 存进 Chroma 向量库
2. 出题时, 把用户问题也转成向量, 在向量库里找最相似的几块 (相似度检索)

关键设计: 每个用户一个独立的 collection (kb_user_{user_id}),
再按 doc_id 过滤, 实现「用户之间数据隔离」.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

import structlog
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from app.core.config import get_settings

logger = structlog.get_logger()


@lru_cache
def get_embeddings() -> Embeddings:
    """获取百炼 text-embedding-v4 Embedding 实例 (OpenAI 兼容模式).

    check_embedding_ctx_length=False 的原因 (重要):
    langchain_openai 默认会把文本先编码成 token id 数组再发送,
    但 DashScope 兼容模式端点无法识别 token id 数组, 会报错,
    所以关掉这个行为, 直接发原始文本.
    """
    from langchain_openai import OpenAIEmbeddings

    settings = get_settings()
    return OpenAIEmbeddings(
        model=settings.dashscope_embedding_model,
        base_url=settings.dashscope_base_url,
        api_key=settings.dashscope_api_key,
        check_embedding_ctx_length=False,
    )


def get_user_vector_store(user_id: int, embeddings: Optional[Embeddings] = None):
    """获取指定用户的 Chroma 向量库实例 (每个用户一个 collection).

    collection_name = kb_user_{user_id} 保证了用户之间数据隔离.
    """
    from langchain_chroma import Chroma

    settings = get_settings()
    return Chroma(
        collection_name=f"kb_user_{user_id}",
        embedding_function=embeddings or get_embeddings(),
        persist_directory=settings.chroma_persist_dir,  # 向量持久化目录
    )


def add_document_chunks(
    user_id: int,
    doc_id: str,
    chunks: list[Document],
    embeddings: Optional[Embeddings] = None,
) -> int:
    """将文档分块写入用户向量库, 返回写入的分块数量.

    每块写入前都会在 metadata 里打上 doc_id 和 user_id 标签,
    这样检索/删除时才能按文档过滤.
    """
    if not chunks:
        return 0

    vector_store = get_user_vector_store(user_id, embeddings=embeddings)

    for chunk in chunks:
        chunk.metadata = {
            **chunk.metadata,
            "doc_id": doc_id,    # 打标签: 这块属于哪个文档
            "user_id": user_id,  # 打标签: 这块属于哪个用户
        }

    ids = vector_store.add_documents(documents=chunks)
    logger.info("document_chunks_added", user_id=user_id, doc_id=doc_id, chunk_count=len(ids))
    return len(ids)


def delete_document_vectors(
    user_id: int,
    doc_id: str,
    embeddings: Optional[Embeddings] = None,
) -> None:
    """从用户向量库中删除指定文档的所有向量 (按 doc_id 过滤删除)."""
    vector_store = get_user_vector_store(user_id, embeddings=embeddings)
    vector_store.delete(where={"doc_id": doc_id})
    logger.info("document_vectors_deleted", user_id=user_id, doc_id=doc_id)


def similarity_search(
    user_id: int,
    doc_id: str,
    query: str,
    k: Optional[int] = None,
    embeddings: Optional[Embeddings] = None,
) -> list[Document]:
    """在用户向量库中检索指定文档的相关分块.

    参数:
        query: 查询文本 (会被转成向量, 和库里的块算相似度)
        k: 返回最相似的前 k 块 (默认从配置读, 4)
    返回:
        最相关的 Document 列表 (相似度从高到低)
    """
    settings = get_settings()
    k = k or settings.kb_retrieve_top_k

    vector_store = get_user_vector_store(user_id, embeddings=embeddings)
    # filter={"doc_id": doc_id} 限定只在这一个文档里检索 (而不是该用户的所有文档)
    return vector_store.similarity_search(query, k=k, filter={"doc_id": doc_id})
