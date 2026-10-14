"""文档解析服务 -- 加载不同格式文档并分块.

这个文件是干什么的:
把用户上传的 PDF / Word / Markdown / 文本文件, 读成「一段段文字」,
再切成适合向量化的小块 (chunk). 这是 RAG 的「数据预处理」第一步.

为什么分块:
1. 向量化是按「段」算的, 一整篇文档太长, 要切成小块才能精确检索
2. 检索时返回的是「最相关的几块」, 而不是整篇文档
"""

from __future__ import annotations

from typing import Optional

import structlog
from langchain_core.documents import Document

from app.core.config import get_settings

logger = structlog.get_logger()

SUPPORTED_FILE_TYPES = {"pdf", "docx", "md", "txt"}  # 支持的文件类型


def _load_documents(file_path: str, file_type: str) -> list[Document]:
    """按文件类型分发到对应的 LangChain Loader, 把文件读成 Document 列表.

    LangChain 提供了现成的文档加载器 (Loader), 每种格式一个:
        PDF -> PyPDFLoader, Word -> Docx2txtLoader, MD/TXT -> TextLoader
    """
    file_type = file_type.lower().lstrip(".")

    if file_type == "pdf":
        from langchain_community.document_loaders import PyPDFLoader

        return PyPDFLoader(file_path).load()

    if file_type == "docx":
        from langchain_community.document_loaders import Docx2txtLoader

        return Docx2txtLoader(file_path).load()

    if file_type in ("md", "txt"):
        from langchain_community.document_loaders import TextLoader

        return TextLoader(file_path, encoding="utf-8").load()

    raise ValueError(f"不支持的文件格式: {file_type}")


def load_and_split(
    file_path: str,
    file_type: str,
    chunk_size: Optional[int] = None,
    chunk_overlap: Optional[int] = None,
) -> list[Document]:
    """加载文档并分块, 返回分块后的 Document 列表.

    参数:
        file_path: 文件路径
        file_type: 文件类型 (pdf/docx/md/txt)
        chunk_size: 每块最大字符数 (默认从配置读, 1000)
        chunk_overlap: 相邻块重叠的字符数 (默认 150, 防止关键信息被切断)
    """
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    settings = get_settings()
    chunk_size = chunk_size or settings.kb_chunk_size
    chunk_overlap = chunk_overlap or settings.kb_chunk_overlap

    # 1) 先把文件读成 Document 列表
    docs = _load_documents(file_path, file_type)

    # 2) 用递归字符分割器切成小块
    # RecursiveCharacterTextSplitter: 按段落 -> 句子 -> 词的优先级递归切分,
    # 尽量在「语义完整」的地方切, 而不是硬切.
    # chunk_overlap 让相邻块之间有重叠, 避免一句话被切成两半导致检索不到.
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    splits = splitter.split_documents(docs)

    logger.info(
        "document_loaded_and_split",
        file_type=file_type,
        raw_doc_count=len(docs),
        chunk_count=len(splits),
    )
    return splits
