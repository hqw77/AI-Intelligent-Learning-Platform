"""出题服务 -- 整个「AI 出题」业务的核心编排层.

这个文件是干什么的:
把「用户输入一句话」变成「一套闯关题目」的完整业务流程都在这.
它是路由层 (api/v1/routes/quiz.py) 和 AI 底层 (llm/quiz_chain.py, services/search_service.py) 之间的「大脑」:
接收出题请求 -> 校验 -> 取参考资料 -> 调 AI 生成题目 -> 配图 -> 落库 -> 返回结果.

出题有两种模式:
1. 同步模式 handle_quiz_generate(): 一个请求里全程等出题完成再返回 (前端已弃用, 保留兼容).
2. 异步模式 create_quiz_task() + _run_quiz_task(): 先登记任务秒回 task_id,
   真正出题在后台 asyncio.create_task 跑, 前端轮询 /quiz/task/{task_id} 拿结果.
   主推异步, 因为「联网搜索 + LLM 出题」要几十秒, 同步会让 HTTP 超时.

核心流程总览 (异步模式):
前端输入 -> create_quiz_task (登记任务)
        -> _run_quiz_task (后台执行):
            1) 状态置 running
            2) _fetch_context 取参考资料 (有 doc_id 走 RAG, 否则走联网搜索 Agent)
            3) generate_quiz 调 DeepSeek 生成题目
            4) 可选配图
            5) 登录了才落库
            6) 状态置 completed (结果存 result_json)
        任一步失败 -> 状态置 failed (错误存 error_message)
"""

import asyncio
import uuid
from typing import Optional

import structlog

from app.core.security import check_content
from app.core.exceptions import QuizGenerationError, ContentFilterError, KnowledgeBaseError
from app.llm.quiz_chain import generate_quiz
from app.models.quiz import (
    QuizGenerateRequest,
    QuizGenerateResponse,
    QuizOutput,
    QuizTaskCreateResponse,
    QuizTaskStatusResponse,
)
from app.repositories import quiz_repository
from app.repositories import task_repository
from app.repositories import knowledge_repository
from app.services import rag_service
from app.services import image_service
from app.services.search_service import fetch_knowledge_context

logger = structlog.get_logger()


async def _maybe_generate_images(
    quiz_output: QuizOutput,
    quiz_id: str,
    user_id: Optional[int],
    generate_images: bool,
) -> Optional[str]:
    """按需为题目生成配图, 并把图片 URL 写回每道题的 image_url 字段.

    参数:
        quiz_output: 已生成好的题库 (会原地修改它的 questions[].image_url)
        quiz_id: 本次题库编号, 用于组织 COS 存储路径
        user_id: 用户 id (未登录为 None, 生图需要登录)
        generate_images: 用户是否勾选了「生成配图」
    返回:
        提示信息字符串 (如「未登录 / 额度用完」), 无异常时为 None.
    """
    if not generate_images:  # 用户没开配图开关, 直接跳过
        return None

    try:
        image_map, notice = await image_service.generate_images_for_quiz(
            quiz_output.questions, user_id, quiz_id
        )
        for q in quiz_output.questions:
            if q.id in image_map:  # 只写回成功生成图片的题目
                q.image_url = image_map[q.id]
        return notice
    except Exception as e:
        # 生图失败绝不能影响出题主流程: 吞掉异常, 题目不带图正常返回
        logger.error("quiz_image_generation_failed", quiz_id=quiz_id, error=str(e))
        return None


async def _validate_doc_id(req: QuizGenerateRequest, user_id: Optional[int]) -> None:
    """校验知识库出题的前置条件: 文档存在, 归属正确, 且已解析就绪.

    只有用户指定了 doc_id (基于私有文档出题) 时才真正校验; 否则直接放行.
    """
    if req.doc_id is None:  # 没指定文档, 不涉及知识库, 直接跳过
        return

    if user_id is None:  # 用知识库出题必须登录, 否则无法确认文档归属
        raise KnowledgeBaseError("使用知识库出题需要先登录")

    doc = await knowledge_repository.get_document(req.doc_id, user_id)
    if doc is None:  # 查不到 = 不存在, 或不属于该用户
        raise KnowledgeBaseError("知识库文档不存在")

    if doc["status"] != "ready":  # 文档还在解析/已失败, 不能用来出题
        raise KnowledgeBaseError(f"知识库文档尚未就绪（当前状态：{doc['status']}），请稍后重试")


async def _fetch_context(req: QuizGenerateRequest, user_id: Optional[int]) -> str:
    """获取「参考资料」-- 决定用哪条路给 AI 出题补充最新/私有知识.

    返回: 一段文字资料 (会作为 search_context 喂给 generate_quiz).
    两条路:
        - 指定了 doc_id -> 走知识库 RAG (从用户私有文档检索)
        - 没指定 -> 走联网搜索 Agent (Tavily 联网)
    """
    if req.doc_id is not None:
        return await rag_service.fetch_rag_context(req.user_input, user_id, req.doc_id)
    return await fetch_knowledge_context(req.user_input)


async def handle_quiz_generate(
    req: QuizGenerateRequest,
    user_id: Optional[int] = None,
) -> QuizGenerateResponse:
    """同步出题: 一个请求里从头跑到尾 (校验->取资料->出题->配图->落库).

    参数:
        req: 出题请求 (user_input / question_count / difficulty / doc_id / generate_images)
        user_id: 可选, 登录用户的 id; None 表示未登录
    返回:
        QuizGenerateResponse (含 quiz_id, 标题, 摘要, 题目列表, 配图提示)
    注意: 前端现在主用异步接口, 这个同步版保留兼容.
    """
    # 1) 内容安全检查 (敏感词过滤)
    if not check_content(req.user_input):
        raise ContentFilterError("输入内容包含不当内容，请修改后重试")

    # 2) 校验知识库文档 (仅当指定了 doc_id)
    await _validate_doc_id(req, user_id)

    # 3) 取参考资料 (有 doc_id 走 RAG, 否则走联网搜索)
    search_context = await _fetch_context(req, user_id)

    # 4) 调 DeepSeek 出题
    try:
        quiz_output = await generate_quiz(
            user_input=req.user_input,
            question_count=req.question_count,
            difficulty=req.difficulty,
            search_context=search_context,
        )
    except Exception as e:
        logger.error("quiz_generation_failed", error=str(e))
        raise QuizGenerationError(f"题库生成失败：{e}") from e

    quiz_id = f"quiz_{uuid.uuid4().hex[:12]}"

    # 5) 可选配图 (失败不影响主流程)
    image_notice = await _maybe_generate_images(quiz_output, quiz_id, user_id, req.generate_images)

    # 6) 有登录态才落库 (存库失败只记日志, 不中断 -- 出题已成功, 不能因存库失败丢题)
    if user_id is not None:
        try:
            await quiz_repository.save_quiz_session(
                quiz_id=quiz_id,
                user_id=user_id,
                title=quiz_output.title,
                summary=quiz_output.summary,
                user_input=req.user_input,
                questions_json=[q.model_dump() for q in quiz_output.questions],
            )
        except Exception as e:
            logger.error("quiz_session_save_failed", error=str(e))

    return QuizGenerateResponse(
        quiz_id=quiz_id,
        title=quiz_output.title,
        summary=quiz_output.summary,
        questions=quiz_output.questions,
        image_notice=image_notice,
    )


# ---- 异步任务模式 ----


async def create_quiz_task(
    req: QuizGenerateRequest,
    user_id: Optional[int] = None,
) -> QuizTaskCreateResponse:
    """创建异步出题任务, 立即返回 task_id (真正的出题在后台跑).

    参数:
        req: 出题请求
        user_id: 可选, 登录用户的 id
    返回:
        QuizTaskCreateResponse (只含 task_id)
    为什么异步: 出题 + 联网搜索耗时长 (几十秒), 同步会让 HTTP 超时.
    这里只负责「登记任务 + 秒回编号」, 把重活丢给 _run_quiz_task.
    """
    if not check_content(req.user_input):
        raise ContentFilterError("输入内容包含不当内容，请修改后重试")

    # 若指定了知识库文档, 先校验其归属与状态; 校验失败不进入后台任务
    await _validate_doc_id(req, user_id)

    task_id = f"task_{uuid.uuid4().hex[:12]}"

    # 把任务登记进数据库, 状态默认 pending (待处理)
    await task_repository.create_task(
        task_id=task_id,
        user_id=user_id,
        user_input=req.user_input,
        question_count=req.question_count,
        difficulty=req.difficulty,
    )

    # 关键: 把 _run_quiz_task 丢到后台跑, 不 await 它, 立即往下走
    asyncio.create_task(_run_quiz_task(task_id, req, user_id))

    return QuizTaskCreateResponse(task_id=task_id)


async def _run_quiz_task(
    task_id: str,
    req: QuizGenerateRequest,
    user_id: Optional[int],
) -> None:
    """后台执行出题任务: 真正的重活都在这, 跑完更新任务状态.

    参数:
        task_id: 任务编号 (前端靠它轮询)
        req: 出题请求
        user_id: 可选, 登录用户的 id
    返回: None (结果通过更新任务状态暴露给前端, 不直接返回)
    状态机: running -> completed (成功) / failed (失败), 任何一步出错都能兜住.
    """
    try:
        # 1) 状态置 running, 前端读到就知道「正在生成中」
        await task_repository.update_task_status(task_id, "running")
        logger.info("quiz_task_started", task_id=task_id)

        # 2) 取参考资料 (有 doc_id 走 RAG, 否则走联网搜索 Agent)
        search_context = await _fetch_context(req, user_id)

        # 3) 调 DeepSeek 生成题目
        quiz_output = await generate_quiz(
            user_input=req.user_input,
            question_count=req.question_count,
            difficulty=req.difficulty,
            search_context=search_context,
        )

        quiz_id = f"quiz_{uuid.uuid4().hex[:12]}"

        # 4) 可选配图 (失败不影响主流程)
        image_notice = await _maybe_generate_images(quiz_output, quiz_id, user_id, req.generate_images)

        # 5) 有登录态才落库 (失败只记日志, 不中断)
        if user_id is not None:
            try:
                await quiz_repository.save_quiz_session(
                    quiz_id=quiz_id,
                    user_id=user_id,
                    title=quiz_output.title,
                    summary=quiz_output.summary,
                    user_input=req.user_input,
                    questions_json=[q.model_dump() for q in quiz_output.questions],
                )
            except Exception as e:
                logger.error("quiz_session_save_failed", task_id=task_id, error=str(e))

        # 6) 组装结果
        result = QuizGenerateResponse(
            quiz_id=quiz_id,
            title=quiz_output.title,
            summary=quiz_output.summary,
            questions=quiz_output.questions,
            image_notice=image_notice,
        )

        # 7) 状态置 completed, 并把完整结果存进 result_json (前端轮询从这里拿题目)
        await task_repository.update_task_status(
            task_id, "completed", result_json=result.model_dump()
        )
        logger.info("quiz_task_completed", task_id=task_id, quiz_id=quiz_id)

    except Exception as e:
        # 8) 兜底: 任何一步抛异常 (如 DeepSeek 调用失败) 都跳到这, 标记失败
        logger.error("quiz_task_failed", task_id=task_id, error=str(e))
        await task_repository.update_task_status(
            task_id, "failed", error_message=str(e)[:500]
        )


async def get_quiz_task_status(task_id: str) -> QuizTaskStatusResponse:
    """查询异步出题任务的状态 (前端轮询用).

    参数:
        task_id: 任务编号
    返回:
        QuizTaskStatusResponse: task_id + 状态(pending/running/completed/failed)
        + 结果(completed 时) + 错误信息(failed 时)
    """
    row = await task_repository.get_task(task_id)
    if row is None:
        raise QuizGenerationError("任务不存在")

    result = None
    if row["status"] == "completed" and row.get("result_json"):
        # completed 且存了结果, 才把 JSON 反序列化成 QuizGenerateResponse 返回
        result = QuizGenerateResponse.model_validate(row["result_json"])

    return QuizTaskStatusResponse(
        task_id=row["task_id"],
        status=row["status"],
        result=result,
        error_message=row.get("error_message"),
    )
