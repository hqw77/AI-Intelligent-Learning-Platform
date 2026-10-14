"""题库相关数据模型 -- 用 Pydantic 定义出题请求和题库结构.

这个文件是干什么的:
定义所有和「出题」相关的数据结构. Pydantic 的 BaseModel 会自动做两件事:
1. 校验数据: 类型不对 / 字段缺失 / 超出范围, 直接报错 (请求校验)
2. 生成 Schema: 字段的 description 会变成「结构描述」, 用来约束 LLM 输出 (结构化输出的关键)

两类模型的区别:
- 请求/响应模型: QuizGenerateRequest / QuizGenerateResponse 等, 用于 HTTP 接口的数据校验
- 输出 Schema: QuizOutput / Question, 用于「约束 LLM 输出」-- LLM 按这个结构生成题目

Field 里的 description 为什么重要:
比如 Question.stem 的 description="题干", 会随 Schema 一起传给 LLM,
LLM 看到这些描述才知道「该输出什么字段, 每个字段什么意思」.
"""

from typing import Literal
from pydantic import BaseModel, Field


class QuestionOption(BaseModel):
    """一道题的一个选项 (A/B/C/D)"""
    key: str = Field(description="选项标识，如 A、B、C、D")
    text: str = Field(description="选项文本")


class Question(BaseModel):
    """一道题目 -- LLM 要按这个结构生成 (出题输出的核心 Schema)"""
    id: str = Field(description="题目编号，如 q1")
    type: Literal["single", "multiple", "judge"] = Field(description="题型")
    # Literal["single","multiple","judge"] 表示这个字段只能是这三个值之一 (单选/多选/判断)
    stem: str = Field(description="题干")
    options: list[QuestionOption] = Field(description="选项列表")
    answer: list[str] = Field(description="正确答案的 key 列表")
    # 用 list 是因为多选题有多个正确答案, 如 ["A", "C"]
    explanation: str = Field(description="详细讲解")
    knowledge_point: str = Field(description="知识点标签")
    difficulty: Literal["easy", "medium", "hard"] = Field(description="难度")
    image_url: str | None = Field(default=None, description="AI 生成的题目配图 URL（可选）")
    # str | None = 可为空, 配图功能没开或生图失败时就是 None


class QuizOutput(BaseModel):
    """AI 生成题库的结构化输出 Schema -- LLM 输出的「最外层结构」"""

    title: str = Field(description="学习主题")
    summary: str = Field(description="本次题库的主题摘要")
    questions: list[Question] = Field(description="题目列表")


class QuizGenerateRequest(BaseModel):
    """出题请求体 -- 前端传来的数据, Pydantic 自动校验"""
    user_input: str = Field(
        min_length=1,      # 不能为空
        max_length=2000,   # 最长 2000 字
        description="用户输入的学习内容",
    )
    question_count: int = Field(default=5, ge=3, le=10, description="题目数量")
    # ge=3, le=10: 题目数限制在 3~10 之间, 超范围直接拒绝
    difficulty: Literal["easy", "medium", "hard", "mixed"] = Field(
        default="mixed", description="难度"
    )
    doc_id: str | None = Field(
        default=None, description="可选，指定基于某篇知识库文档出题"
    )
    generate_images: bool = Field(
        default=False, description="是否为每道题目生成配图"
    )


class QuizGenerateResponse(BaseModel):
    """出题响应体 -- 后端返回给前端的题库"""
    quiz_id: str
    title: str
    summary: str
    questions: list[Question]
    image_notice: str | None = Field(
        default=None, description="配图相关的提示信息（如未登录/额度已用完/部分题目未配图等），无异常时为 None"
    )


class AnswerRecord(BaseModel):
    """一道题的答题记录 (前端提交, 用于生成报告)"""
    question_id: str
    selected_answers: list[str]  # 用户选了哪些选项
    is_correct: bool             # 是否答对 (前端本地判分后传上来)
    duration_ms: int = Field(ge=0)  # 这题花了多久 (毫秒), ge=0 不能为负


# ---- 异步任务模型 ----


class QuizTaskCreateResponse(BaseModel):
    """创建出题任务的响应 -- 只返回一个 task_id"""
    task_id: str


class QuizTaskStatusResponse(BaseModel):
    """轮询任务状态的响应 -- 前端轮询拿这个"""
    task_id: str
    status: Literal["pending", "running", "completed", "failed"]
    # 任务状态机: 待处理 -> 运行中 -> 完成 / 失败
    result: "QuizGenerateResponse | None" = None  # 完成时才有的题库结果
    error_message: str | None = None  # 失败时才有的错误信息
