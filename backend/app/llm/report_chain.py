"""报告 Chain -- 用 LangChain 把「答题数据」变成「复盘报告」.

和 quiz_chain 是同一套路: 拼提示词 -> 调 DeepSeek -> 提取 JSON -> Pydantic 校验.
区别只是输入 (答题记录) 和输出 (报告) 不同.
"""

import json
import re

from langchain_core.prompts import ChatPromptTemplate

from app.llm.langchain_factory import get_chat_model
from app.models.quiz import Question, AnswerRecord
from app.models.report import ReportOutput
from app.prompts.report_prompt import REPORT_HUMAN_PROMPT, REPORT_SYSTEM_PROMPT


def _extract_json(text: str) -> dict:
    """从 LLM 输出中提取 JSON, 兼容 markdown 代码块包裹 (和 quiz_chain 一样)."""
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    raw = match.group(1).strip() if match else text.strip()
    return json.loads(raw)


async def generate_report(
    topic: str,
    questions: list[Question],
    answer_records: list[AnswerRecord],
    score_summary: dict,
) -> ReportOutput:
    """调 DeepSeek 生成复盘报告.

    参数:
        topic: 学习主题
        questions: 这套题目
        answer_records: 用户的答题记录
        score_summary: 计分结果 (正确率等, 由 scoring_service 算好)
    返回:
        ReportOutput: 结构化报告 (掌握点/薄弱点/总结/建议/金句)
    """
    llm = get_chat_model(temperature=0.5)  # 报告用稍高温度, 文字更自然

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", REPORT_SYSTEM_PROMPT),
            ("human", REPORT_HUMAN_PROMPT),
        ]
    )

    chain = prompt | llm

    # 把题目, 答题记录, 计分结果都序列化成 JSON 字符串, 一起喂给 LLM
    result = await chain.ainvoke(
        {
            "topic": topic,
            "quiz_json": json.dumps(
                [q.model_dump() for q in questions], ensure_ascii=False
            ),
            "answer_records": json.dumps(
                [r.model_dump() for r in answer_records], ensure_ascii=False
            ),
            "score_summary": json.dumps(score_summary, ensure_ascii=False),
        }
    )

    # 提取 JSON -> Pydantic 校验成 ReportOutput (和 quiz_chain 同一套「三层保险」)
    data = _extract_json(result.content)
    return ReportOutput.model_validate(data)
