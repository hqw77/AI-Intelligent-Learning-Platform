"""报告相关数据模型 -- 用 Pydantic 定义复盘报告的结构.

复盘报告 = 用户答完题后, AI 生成的「学习总结」, 包含:
正确率, 掌握知识点, 薄弱知识点, 三句总结, 后续建议, 分享金句.
"""

from pydantic import BaseModel, Field
from .quiz import Question, AnswerRecord  # 复用出题模块的题目和答题记录结构


class ReportGenerateRequest(BaseModel):
    """生成报告的请求 -- 前端把整场答题的原始数据都传上来."""
    quiz_id: str
    topic: str                     # 学习主题
    questions: list[Question]      # 这套题目 (含答案和解析)
    answer_records: list[AnswerRecord]  # 用户的答题记录 (选了啥, 对没对, 花了多久)


class ReportOutput(BaseModel):
    """AI 生成报告的结构化输出 Schema -- LLM 按这个结构生成报告."""

    accuracy: int = Field(description="正确率百分比")
    mastered_points: list[str] = Field(description="掌握较好的知识点")
    weak_points: list[str] = Field(description="薄弱知识点")
    three_line_summary: list[str] = Field(description="三句知识总结")
    advice: list[str] = Field(description="后续建议")
    share_quote: str = Field(description="一句可用于分享的学习金句")


class ReportGenerateResponse(BaseModel):
    """报告响应 -- 后端返回给前端的报告数据 (字段和 ReportOutput 一致)."""
    accuracy: int
    mastered_points: list[str]
    weak_points: list[str]
    three_line_summary: list[str]
    advice: list[str]
    share_quote: str
