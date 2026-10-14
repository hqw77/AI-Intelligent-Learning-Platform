"""鱼皮 AI 闯关学习小程序 - 后端配置.

这个文件是干什么的:
集中管理所有配置项 (API Key, 数据库, 端口等).
配置值从 .env 文件读取 (model_config 里配了 env_file=".env"),
代码里改配置不需要动代码, 只改 .env 就行.

用法:
    settings = get_settings()        # 拿到配置对象 (全局缓存)
    settings.deepseek_api_key        # 访问某个配置项
"""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """所有配置项的集合. 字段名对应 .env 里的环境变量名 (不区分大小写)."""

    # DeepSeek 配置 (出题/报告/Agent 的大脑)
    deepseek_api_key: str = "sk-xxx"
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    # Tavily 配置 (联网搜索)
    tavily_api_key: str = ""
    enable_web_search: bool = True

    # DashScope (阿里云百炼) 配置 (Embedding, 用于知识库 RAG)
    dashscope_api_key: str = ""
    dashscope_embedding_model: str = "text-embedding-v4"
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    # 知识库 / 向量存储
    chroma_persist_dir: str = "./data/chroma"   # 向量库持久化目录
    kb_upload_dir: str = "./data/uploads"       # 上传文件保存目录
    kb_max_documents_per_user: int = 10         # 每人最多上传几篇文档
    kb_max_file_size_mb: int = 10               # 单文件最大 10MB
    kb_chunk_size: int = 1000                   # 分块大小 (字符)
    kb_chunk_overlap: int = 150                 # 相邻块重叠 (字符)
    kb_retrieve_top_k: int = 4                  # 检索时返回最相关的几块

    # 题目配图 (DashScope 千问-文生图)
    dashscope_image_model: str = "qwen-image-2.0"
    # 生图专用 API Key (留空时回退用 dashscope_api_key)
    dashscope_image_api_key: str = ""
    # 生图用的原生 DashScope API 地址 (与兼容模式的 dashscope_base_url 不同)
    dashscope_image_base_url: str = ""
    image_gen_size: str = "512*512"
    image_gen_daily_limit: int = 20             # 每人每天生图上限 (控成本)
    image_gen_max_concurrency: int = 5          # 生图并发上限 (控成本)

    # 腾讯云 COS (持久化存储 AI 生成的配图)
    cos_secret_id: str = ""
    cos_secret_key: str = ""
    cos_region: str = ""
    cos_bucket: str = ""
    cos_upload_prefix: str = "quiz-images/"
    cos_domain: str = ""  # 可选, 自定义访问域名 (如 CDN)

    # App
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_debug: bool = True

    # JWT
    jwt_secret: str = "change-me-in-production"  # 生产环境必须改!
    jwt_expire_minutes: int = 43200              # 30 天

    # 微信小程序
    wechat_app_id: str = ""
    wechat_app_secret: str = ""

    # MySQL
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = "123456"
    mysql_database: str = "yu_ai_learn"
    mysql_charset: str = "utf8mb4"
    mysql_pool_minsize: int = 1      # 连接池最小连接数
    mysql_pool_maxsize: int = 10     # 连接池最大连接数
    mysql_auto_init: bool = True     # 启动时自动建库建表

    # Log
    log_level: str = "INFO"

    # 关键配置: 从 .env 文件读环境变量, 忽略未识别的字段
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    """获取配置对象 (全局缓存, 只初始化一次).

    @lru_cache 让第一次调用时读取 .env 并创建 Settings,
    之后再调用直接返回同一个实例, 不会重复读文件.
    """
    return Settings()
