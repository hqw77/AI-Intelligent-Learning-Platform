"""FastAPI 应用入口 -- 整个后端的「入口 + 骨架」.

这个文件是干什么的:
它不处理具体业务, 只负责「把各个零件组装起来」:
1. 程序启动时自动建库建表 (lifespan)
2. 把 5 个路由模块注册进应用 (health / quiz / report / user / knowledge)
3. 配置跨域 (CORS) 和全局异常处理

怎么跑起来:
两种方式等效, 都是让 uvicorn 加载这个 app:
    python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
    python app/main.py  (走最下面的 __main__ 分支)

核心组成:
    lifespan       -> 启动时建库, 关闭时释放连接池
    app            -> FastAPI 应用实例 (整个后端的「大厅」)
    include_router -> 注册 5 个路由 (大厅里的 5 个「窗口」)
    exception_handler -> 全局异常处理 (出错时统一返回 JSON 格式)
"""

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.routes import health, knowledge, quiz, report, user
from app.core.config import get_settings
from app.core.db import close_mysql_pool, init_mysql
from app.core.exceptions import (
    AuthenticationError,
    ContentFilterError,
    KnowledgeBaseError,
    QuizGenerationError,
    ReportGenerationError,
)
from app.models.common import ApiResponse

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期: 启动时做的事在 yield 之前, 关闭时做的事在 yield 之后.

    @asynccontextmanager 是 Python 的「上下文管理器」: yield 把函数一分为二.
    """
    settings = get_settings()
    logger.info("app_starting", host=settings.app_host, port=settings.app_port)

    # 启动时: 若配置了自动初始化, 就自动建库 + 建 7 张表 (这就是为什么不用手动建表)
    if settings.mysql_auto_init:
        await init_mysql()

    yield  # 程序运行中...

    # 关闭时: 释放 MySQL 连接池, 避免资源泄漏
    await close_mysql_pool()
    logger.info("app_shutting_down")


# 创建 FastAPI 应用实例, 并把上面的生命周期逻辑挂上去
app = FastAPI(
    title="鱼皮 AI 闯关学习",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS 中间件: 解决「跨域」问题.
# 前端小程序和后端是不同地址, 浏览器/小程序默认会拦跨域请求, 这里放开所有来源.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # 允许所有来源
    allow_credentials=True,
    allow_methods=["*"],      # 允许所有 HTTP 方法
    allow_headers=["*"],      # 允许所有请求头
)

# 注册路由: 把 5 个「窗口」挂到应用上, 统一加 /api/v1 前缀.
# 所以所有接口地址都是 /api/v1/xxx 开头, 如 /api/v1/quiz/generate/async
app.include_router(health.router, prefix="/api/v1")
app.include_router(quiz.router, prefix="/api/v1")
app.include_router(report.router, prefix="/api/v1")
app.include_router(user.router, prefix="/api/v1")
app.include_router(knowledge.router, prefix="/api/v1")


# ===== 全局异常处理 =====
# 下面的每一个 @app.exception_handler 都是「捕获某个异常 -> 转成规范 JSON 返回」.
# 业务代码里 raise 的异常 (如 ContentFilterError), 最终都在这里被统一处理,
# 保证前端拿到的永远是 {code, message, data} 格式, 而不是裸的错误堆栈.


@app.exception_handler(AuthenticationError)
async def auth_error_handler(request: Request, exc: AuthenticationError):
    """鉴权失败 -> 401 + code 4010"""
    return JSONResponse(
        status_code=401,
        content=ApiResponse.error(code=4010, message=str(exc)).model_dump(),
    )


@app.exception_handler(ContentFilterError)
async def content_filter_handler(request: Request, exc: ContentFilterError):
    """内容不合规 (敏感词) -> 400 + code 4000"""
    return JSONResponse(
        status_code=400,
        content=ApiResponse.error(code=4000, message=str(exc)).model_dump(),
    )


@app.exception_handler(QuizGenerationError)
async def quiz_error_handler(request: Request, exc: QuizGenerationError):
    """出题失败 -> 500 + code 5001"""
    return JSONResponse(
        status_code=500,
        content=ApiResponse.error(code=5001, message=str(exc)).model_dump(),
    )


@app.exception_handler(ReportGenerationError)
async def report_error_handler(request: Request, exc: ReportGenerationError):
    """报告生成失败 -> 500 + code 5002"""
    return JSONResponse(
        status_code=500,
        content=ApiResponse.error(code=5002, message=str(exc)).model_dump(),
    )


@app.exception_handler(KnowledgeBaseError)
async def knowledge_base_error_handler(request: Request, exc: KnowledgeBaseError):
    """知识库错误 -> 400 + code 4001"""
    return JSONResponse(
        status_code=400,
        content=ApiResponse.error(code=4001, message=str(exc)).model_dump(),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """兜底异常处理: 捕获所有没预料到的异常.

    避免直接暴露裸的 "Internal Server Error", 并记录完整堆栈便于排查.
    """
    logger.error(
        "unhandled_exception",
        path=request.url.path,
        method=request.method,
        error=str(exc),
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content=ApiResponse.error(code=5000, message="服务器内部错误，请稍后重试").model_dump(),
    )


# 直接运行 python main.py 时, 用 uvicorn 启动服务.
# 等价于命令行: python -m uvicorn app.main:app
if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_debug,  # 调试模式自动重载 (开发时改代码自动重启)
    )
