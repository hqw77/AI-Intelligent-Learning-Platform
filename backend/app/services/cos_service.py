"""腾讯云 COS 对象存储服务 -- 持久化保存 AI 生成的题目配图.

这个文件是干什么的:
AI 生成的图片是「临时链接」, 会过期. 所以要下载下来, 传到 COS (对象存储),
拿到一个永久的公开 URL, 才能存进数据库长期使用.

为什么用 COS 而不是存本地:
1. 对象存储的 URL 可公开访问, 小程序能直接加载
2. 不占服务器本地磁盘, 且天然支持 CDN 加速
"""

from __future__ import annotations

import asyncio
from functools import lru_cache

import structlog
from qcloud_cos import CosConfig, CosS3Client

from app.core.config import get_settings

logger = structlog.get_logger()


@lru_cache
def _get_cos_client() -> CosS3Client:
    """创建 (并缓存) COS 客户端. lru_cache 避免每次上传都重新初始化."""
    settings = get_settings()
    config = CosConfig(
        Region=settings.cos_region,
        SecretId=settings.cos_secret_id,
        SecretKey=settings.cos_secret_key,
        Scheme="https",
    )
    return CosS3Client(config)


def _build_public_url(key: str) -> str:
    """根据 key 构造可公开访问的 URL.

    优先用自定义域名 (cos_domain, 如 CDN), 否则用 COS 默认域名.
    """
    settings = get_settings()
    if settings.cos_domain:
        return f"https://{settings.cos_domain}/{key}"
    return f"https://{settings.cos_bucket}.cos.{settings.cos_region}.myqcloud.com/{key}"


def _put_object_sync(data: bytes, key: str, content_type: str) -> None:
    """同步上传文件到 COS (阻塞调用, 需在线程中执行)."""
    settings = get_settings()
    client = _get_cos_client()
    client.put_object(
        Bucket=settings.cos_bucket,
        Body=data,
        Key=key,
        ContentType=content_type,
    )


async def upload_image_bytes(data: bytes, key: str, content_type: str = "image/png") -> str:
    """将图片字节流上传到 COS, 返回可公开访问的 URL.

    COS SDK 是同步阻塞的, 通过 asyncio.to_thread 扔到线程池执行,
    避免阻塞事件循环 (否则会卡住其他请求).
    """
    settings = get_settings()
    # 未配置 COS 就直接报错 (调用方会捕获并降级, 不影响出题)
    if not (settings.cos_secret_id and settings.cos_secret_key and settings.cos_bucket and settings.cos_region):
        raise RuntimeError("COS 未配置，无法上传图片")

    await asyncio.to_thread(_put_object_sync, data, key, content_type)
    url = _build_public_url(key)
    logger.info("cos_upload_success", key=key)
    return url
