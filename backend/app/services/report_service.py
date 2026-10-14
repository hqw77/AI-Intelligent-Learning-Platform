"""报告服务 -- 生成复盘报告的编排层.

这个文件是干什么的:
把「用户的答题记录」变成「一份复盘报告」, 流程:
计分 (scoring_service) -> 调 DeepSeek 生成报告 (report_chain) -> 落库 + 攒经验值.

经验值规则:
    完成闯关 +10, 每答对一题 +2.
"""

from typing import Optional

import structlog

from app.core.exceptions import ReportGenerationError
from app.llm.report_chain import generate_report
from app.models.report import ReportGenerateRequest, ReportGenerateResponse
from app.services.scoring_service import compute_score_summary
from app.repositories import quiz_repository, user_repository

logger = structlog.get_logger()


async def handle_report_generate(
    req: ReportGenerateRequest,
    user_id: Optional[int] = None,
) -> ReportGenerateResponse:
    """生成复盘报告: 计分 -> 生成 -> 落库 -> 经验值.

    参数:
        req: 报告请求 (题目 + 答题记录)
        user_id: 可选, 登录用户的 id; None 表示未登录
    返回:
        ReportGenerateResponse: 结构化报告
    """
    # 1) 先算分 (正确率, 正确题数, 平均耗时)
    score_summary = compute_score_summary(req.answer_records)

    # 2) 调 DeepSeek 生成报告
    try:
        report_output = await generate_report(
            topic=req.topic,
            questions=req.questions,
            answer_records=req.answer_records,
            score_summary=score_summary,
        )
    except Exception as e:
        logger.error("report_generation_failed", error=str(e))
        raise ReportGenerationError(f"报告生成失败：{e}") from e

    # 3) 有登录态才落库 + 攒经验值 (失败只记日志, 不影响返回报告)
    if user_id is not None:
        try:
            # 保存答题记录
            await quiz_repository.save_answer_record(
                quiz_id=req.quiz_id,
                user_id=user_id,
                records_json=[r.model_dump() for r in req.answer_records],
                total_questions=score_summary["total"],
                correct_count=score_summary["correct"],
                accuracy=score_summary["accuracy"],
            )
            # 保存报告
            await quiz_repository.save_report(
                quiz_id=req.quiz_id,
                user_id=user_id,
                report_json=report_output.model_dump(),
            )
            # 累加经验值: 完成闯关 +10, 每答对一题 +2
            xp_gain = 10 + score_summary["correct"] * 2
            await user_repository.add_user_xp(user_id, xp_gain)
        except Exception as e:
            logger.error("report_persist_failed", error=str(e))

    return ReportGenerateResponse(
        accuracy=report_output.accuracy,
        mastered_points=report_output.mastered_points,
        weak_points=report_output.weak_points,
        three_line_summary=report_output.three_line_summary,
        advice=report_output.advice,
        share_quote=report_output.share_quote,
    )
