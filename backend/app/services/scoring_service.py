"""计分服务 -- 根据答题记录算分数统计.

这个文件是干什么的:
纯计算逻辑, 不调 AI 也不碰数据库, 把答题记录聚合出几个统计数字:
总数, 正确数, 错误数, 正确率, 平均耗时.
这些数字会喂给报告生成 (report_chain), 也会落库保存.
"""

from app.models.quiz import AnswerRecord


def compute_score_summary(answer_records: list[AnswerRecord]) -> dict:
    """根据答题记录计算分数统计.

    参数:
        answer_records: 答题记录列表 (每题的 is_correct 表示答对没有)
    返回:
        dict: total(总题数), correct(答对数), wrong(答错数),
              accuracy(正确率百分比), avg_duration_ms(平均耗时)
    """
    total = len(answer_records)
    correct = sum(1 for r in answer_records if r.is_correct)  # 数有多少题答对
    accuracy = round(correct / total * 100) if total > 0 else 0  # 正确率 = 答对/总数
    avg_duration = (
        round(sum(r.duration_ms for r in answer_records) / total) if total > 0 else 0
    )

    return {
        "total": total,
        "correct": correct,
        "wrong": total - correct,
        "accuracy": accuracy,
        "avg_duration_ms": avg_duration,
    }
